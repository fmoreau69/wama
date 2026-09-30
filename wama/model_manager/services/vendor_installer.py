"""
Route VENDOR de la route `library` — une librairie que pip ne sait pas installer (ROADMAP D-a,
décision de Fabien le 2026-09-30 : « uniformiser, universaliser au passage »).

La norme reste pip (`model_installer.install_library`). Cette voie ne sert qu'aux dépôts qui ne
sont PAS des paquets — MuseTalk, CodeFormer, TripoSR : pas de `setup.py`, le backend les lance
par chemin dans un sous-processus. Avant elle, chacun avait son script shell, qui clonait `main`
SANS épingle (`git pull --ff-only`) et réappliquait ses correctifs à la main, ou jamais.

Contrat — le même que la voie pip, verrou pour verrou :
  • la déclaration passe `vendor_spec_error` (dépôt « owner/name », commit EXACT, correctif
    sous `patches/`) — l'adresse se dérive de la source déclarée `github`, jamais d'une URL libre ;
  • `apply=False` (défaut) = PLAN sans aucun effet, lisible sans allowlist ;
  • `is_allowed` (décision humaine) obligatoire pour exécuter, kill switch commun ;
  • 🔴 une modification LOCALE que la déclaration n'explique pas (ni le correctif, ni un chemin
    `ignore`) n'est JAMAIS écrasée : l'installation s'arrête et la nomme. Un clone vendorisé a
    déjà porté des correctifs que personne n'avait exportés (MuseTalk, 7 fichiers, 07/09) ;
  • état CONSTATÉ après coup (`vendor_state`) — un « git ok » ne suffit pas ;
  • journal daté (`install_history`), cache des moteurs invalidé.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from django.conf import settings

from wama.common.manifests.builtin.library import vendor_spec_error

#: Délai d'une opération git réseau (clone / fetch).
GIT_TIMEOUT = 900


def repo_root() -> Path:
    """Racine du dépôt WAMA — les correctifs déclarés sont relatifs à elle."""
    return Path(settings.BASE_DIR)


def vendor_dir(engine: str) -> Path:
    """Dossier du moteur vendorisé : racine DÉCLARÉE + nom du moteur (`vendor/README.md`)."""
    return Path(settings.BACKEND_VENDOR_DIR) / engine


def repo_url(repo: str) -> str:
    """Adresse de clonage, dérivée de la source déclarée `github` (jamais écrite en dur)."""
    from wama.common.external_sources import base_url
    return f"{base_url('github')}/{repo}.git"


def _git(args, cwd=None, timeout=120):
    # `core.fileMode=false` : le clone vit sur /mnt/d, où chaque fichier paraît exécutable —
    # sans lui, `status` annonce tout le dépôt modifié (mesuré le 2026-09-30 sur MuseTalk).
    return subprocess.run(['git', '-c', 'core.fileMode=false', *args], cwd=cwd,
                          capture_output=True, text=True, timeout=timeout)


def _ignored(path: str, ignore) -> bool:
    return any(path == p.rstrip('/') or path.startswith(p.rstrip('/') + '/')
               for p in (ignore or []))


def _patch_files(patch_path: Path) -> set:
    """Chemins touchés par un correctif (lignes `diff --git a/X b/X`)."""
    files = set()
    try:
        for line in patch_path.read_text(encoding='utf-8', errors='replace').splitlines():
            if line.startswith('diff --git a/'):
                files.add(line.split(' b/', 1)[-1].strip())
    except OSError:
        pass
    return files


def vendor_state(vendor: dict, root: Path | None = None) -> dict:
    """État MESURÉ du clone d'un moteur vendorisé, confronté à sa déclaration.

    `verdict` :
      • 'absent'        — pas de clone ;
      • 'conform'       — au commit déclaré, correctif appliqué (s'il y en a un), rien d'autre ;
      • 'patch_missing' — au commit, propre, mais le correctif déclaré n'est pas appliqué ;
      • 'other_commit'  — le clone est à un autre commit ;
      • 'local_changes' — des fichiers suivis diffèrent SANS que la déclaration l'explique.
    Les fins de ligne (CR) ne comptent pas : un clone passé par Windows les convertit, sans
    que le contenu change.
    """
    root = Path(root) if root else vendor_dir(vendor['engine'])
    state = {'dir': str(root), 'commit': vendor.get('commit'), 'head': None,
             'patch_applied': None, 'local_changes': [], 'untracked': []}
    if not (root / '.git').exists():
        state['verdict'] = 'absent'
        return state

    head = _git(['rev-parse', 'HEAD'], cwd=root)
    state['head'] = head.stdout.strip() if head.returncode == 0 else None

    ignore = vendor.get('ignore') or []
    # `--numstat`, pas `--name-only` : ce dernier liste tout fichier dont l'empreinte a bougé
    # SANS calculer le contenu, donc ignore `--ignore-cr-at-eol` — mesuré le 2026-09-30, il
    # annonçait « modifiés » tous les fichiers d'un clone passé par Windows. Une ligne « 0 0 »
    # est un fichier qui ne diffère que par ses fins de ligne.
    changed = []
    for line in _git(['diff', '--ignore-cr-at-eol', '--numstat'], cwd=root).stdout.splitlines():
        added, deleted, path = (line.split('\t', 2) + ['', ''])[:3]
        if path and (added, deleted) != ('0', '0'):
            changed.append(path)
    patch = vendor.get('patch')
    explained = set()
    if patch:
        patch_path = repo_root() / patch
        rev = _git(['apply', '--reverse', '--check', '--ignore-whitespace', str(patch_path)],
                   cwd=root)
        state['patch_applied'] = rev.returncode == 0
        if state['patch_applied']:
            explained = _patch_files(patch_path)
    state['local_changes'] = sorted(p for p in changed
                                    if p not in explained and not _ignored(p, ignore))
    porcelain = _git(['status', '--porcelain', '--untracked-files=all'], cwd=root).stdout
    state['untracked'] = sorted(line[3:] for line in porcelain.splitlines()
                                if line.startswith('??') and not _ignored(line[3:], ignore))

    if state['local_changes']:
        state['verdict'] = 'local_changes'
    elif state['head'] != vendor.get('commit'):
        state['verdict'] = 'other_commit'
    elif patch and not state['patch_applied']:
        state['verdict'] = 'patch_missing'
    else:
        state['verdict'] = 'conform'
    return state


def _actions_for(state: dict, vendor: dict) -> list:
    """Gestes que l'installation ferait, dans l'ordre — lisibles dans le PLAN."""
    verdict = state['verdict']
    if verdict == 'conform':
        return []
    if verdict == 'absent':
        actions = ['clone']
    elif verdict == 'other_commit':
        actions = ['fetch', 'checkout']
    else:
        actions = []
    if vendor.get('patch') and verdict != 'local_changes':
        actions.append('apply_patch')
    return actions


def _clone(vendor: dict, target: Path) -> None:
    """Clone au commit EXACT dans un dossier temporaire, renommé seulement au succès : un
    clone interrompu ne laisse jamais un moteur à moitié présent à sa place."""
    tmp = target.with_name(f'.{target.name}.partial-{os.getpid()}')
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    try:
        for args, timeout in ((['init', '--quiet'], 60),
                              (['remote', 'add', 'origin', repo_url(vendor['repo'])], 60),
                              # Récupérer LE commit, pas une branche : GitHub sert un SHA atteignable.
                              (['fetch', '--quiet', '--depth', '1', 'origin', vendor['commit']],
                               GIT_TIMEOUT),
                              (['checkout', '--quiet', '--detach', 'FETCH_HEAD'], 120)):
            proc = _git(args, cwd=tmp, timeout=timeout)
            if proc.returncode != 0:
                raise RuntimeError(f"git {args[0]} : {(proc.stderr or proc.stdout).strip()[-500:]}")
        os.replace(tmp, target)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _checkout(vendor: dict, target: Path) -> None:
    has = _git(['cat-file', '-e', f"{vendor['commit']}^{{commit}}"], cwd=target)
    if has.returncode != 0:
        proc = _git(['fetch', '--quiet', 'origin', vendor['commit']], cwd=target,
                    timeout=GIT_TIMEOUT)
        if proc.returncode != 0:
            raise RuntimeError(f"git fetch : {(proc.stderr or proc.stdout).strip()[-500:]}")
    proc = _git(['checkout', '--quiet', '--detach', vendor['commit']], cwd=target)
    if proc.returncode != 0:
        raise RuntimeError(f"git checkout : {(proc.stderr or proc.stdout).strip()[-500:]}")


def _apply_patch(vendor: dict, target: Path) -> None:
    proc = _git(['apply', '--whitespace=nowarn', str(repo_root() / vendor['patch'])], cwd=target)
    if proc.returncode != 0:
        raise RuntimeError(f"git apply : {(proc.stderr or proc.stdout).strip()[-500:]}")


def install_vendor(lib, apply: bool = False, via: str = '') -> dict:
    """Installe (plan/apply) une librairie VENDORISÉE du registre — appelé par
    `model_installer.install_library` quand `Library.vendor` est renseigné."""
    from .model_installer import PIP_KILL_SWITCH_ENV

    key, vendor = lib.key, dict(lib.vendor or {})
    err = vendor_spec_error(vendor)
    if err:
        return {'ok': False, 'library': key, 'error': f"install.vendor : {err}"}
    if vendor.get('patch') and not (repo_root() / vendor['patch']).is_file():
        return {'ok': False, 'library': key,
                'error': f"correctif déclaré introuvable : {vendor['patch']}"}

    target = vendor_dir(vendor['engine'])
    state = vendor_state(vendor, target)
    plan = {'library': key, 'route': 'vendor', 'repo': vendor['repo'],
            'url': repo_url(vendor['repo']), 'commit': vendor['commit'],
            'patch': vendor.get('patch'), 'dir': str(target), 'state': state,
            'actions': _actions_for(state, vendor), 'allowed': lib.is_allowed}
    if state['verdict'] == 'local_changes':
        plan['blocked'] = ("modifications locales NON déclarées — jamais écrasées : les exporter "
                           "en correctif (`patches/`) et le déclarer, ou les retirer à la main")

    if not apply:
        return {'ok': True, 'plan': plan, 'would_install': bool(plan['actions'])}

    if os.environ.get(PIP_KILL_SWITCH_ENV):
        return {'ok': False, 'library': key, 'plan': plan,
                'error': f"installations désactivées ({PIP_KILL_SWITCH_ENV} posé)"}
    if not lib.is_allowed:
        return {'ok': False, 'library': key, 'plan': plan,
                'error': "is_allowed=False — l'installation exige une décision humaine "
                         "explicite (allowlist, ROADMAP §16.7) : manage.py install_library "
                         f"{key} --allow --apply"}
    if plan.get('blocked'):
        return {'ok': False, 'library': key, 'plan': plan,
                'error': plan['blocked'] + f" : {', '.join(state['local_changes'][:10])}"}
    if state['verdict'] == 'other_commit' and state['patch_applied']:
        # Changer de commit sous un correctif appliqué le ferait porter par un code qu'il ne
        # vise pas : on ne devine pas l'ordre des gestes, on le demande.
        return {'ok': False, 'library': key, 'plan': plan,
                'error': "le clone est à un autre commit AVEC le correctif appliqué — retirer le "
                         "correctif à la main (git apply --reverse) avant de changer de commit"}

    if plan['actions']:
        from .install_history import opened
        with opened('library', key, name=lib.name or key, via=via) as outcome:
            try:
                if 'clone' in plan['actions']:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    _clone(vendor, target)
                elif 'checkout' in plan['actions']:
                    _checkout(vendor, target)
                if 'apply_patch' in plan['actions']:
                    _apply_patch(vendor, target)
            except (RuntimeError, OSError, subprocess.SubprocessError) as exc:
                outcome.update({'ok': False, 'error': str(exc)})
                return {'ok': False, 'library': key, 'plan': plan, 'error': str(exc)}
            final = vendor_state(vendor, target)
            if final['verdict'] != 'conform':
                error = f"état constaté après installation : {final['verdict']}"
                outcome.update({'ok': False, 'error': error})
                return {'ok': False, 'library': key, 'plan': plan, 'state': final,
                        'error': error}
            outcome.update({'ok': True, 'version': vendor['commit'][:12]})
        try:
            from wama.common.backends.manager import invalidate_engine_cache
            invalidate_engine_cache()
        except Exception:
            pass

    lib.is_installed = True
    lib.installed_version = vendor['commit']
    lib.save(update_fields=['is_installed', 'installed_version'])
    return {'ok': True, 'library': key, 'installed': bool(plan['actions']),
            'version': vendor['commit'][:12], 'plan': plan}
