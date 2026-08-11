"""
Harnais de régénération d'app (route §10.3, marche C) — la « passe intégrée » érigée en commande.

  python manage.py app_regen_check converter            # bac à sable git requis (arbre propre)
  python manage.py app_regen_check converter --keep     # laisser l'état régénéré en place
  python manage.py app_regen_check converter --json     # rapport machine

Protocole (celui du pilote converter, 2026-08-11) :
  0. GARDES    : fichiers cibles PROPRES (git), branche ≠ dev/main (sauf --force), corpus fidèle
                 à l'extraction courante — sinon on jugerait la régénération d'un manifeste périmé.
  1. BASELINE  : mesure en SOUS-PROCESS frais = manifeste extrait + grille (run_checks) + smoke.
  2. STRIP     : retrait des déclarations régénérables (`strip_app_declarations` — APP_CATALOG,
                 GENERIC_APPS, APP_MODES, PROMPT_TARGETS, params.py).
  3. APPLY     : `write_back_app(corpus, apply=True, skip=('access',))` en SOUS-PROCESS FRAIS —
                 dans le process courant, les modules importés (params, registres) sont périmés
                 dès le strip. `access` (DB) est exclu : le harnais ne touche JAMAIS la base.
  4. APRÈS     : même mesure, autre sous-process frais.
  5. VERDICT   : 3 axes — ① manifeste ré-extrait identique (écarts de la famille MESURÉE tolérés,
                 trou #16) ; ② grille identique (mêmes états critère par critère) ; ③ smoke
                 identique et page en 200. JAMAIS un diff textuel byte à byte : le jugement
                 porte sur des artefacts NORMALISÉS.
  6. RESTORE   : `git checkout` des fichiers touchés (sauf --keep).

Sert de JUGE aux marches suivantes de la route : gabarit `processing` (A) et rôle LLM `codegen` (B).
"""
import json
import os
import subprocess
import sys
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

# Écarts TOLÉRÉS entre manifeste baseline et manifeste ré-extrait : la famille MESURÉE
# (trou #16, route §11) — drapeaux fusionnés par `app_capabilities` (grille par-dessus les
# défauts `_conv(...)` de l'entrée) et champs de `processing` dérivés de `conventions`.
# L'entrée régénérée ne porte que le DÉCLARATIF, donc ces drapeaux bougent sans qu'aucun
# comportement mesurable ne change (vérifié à la passe intégrée : grille et smoke identiques).
_MESURE_CAP_FLAGS = ('settings_modal_item', 'settings_modal_batch', 'inspector', 'realtime',
                     'edit_page', 'instant_preview', 'during_preview', 'streaming',
                     'multi_format_download', 'layout', 'anti_race')
_MESURE_PATHS = tuple(f'body.capabilities.{f}' for f in _MESURE_CAP_FLAGS) + (
    'body.processing.anti_race', 'body.processing.processing_time', 'body.processing.statuses')


def _famille_mesuree(path: str) -> bool:
    return path in _MESURE_PATHS


class Command(BaseCommand):
    help = "Harnais de régénération d'app : strip → write_back → jugement 3 axes (route §10.3)."

    def add_arguments(self, parser):
        parser.add_argument('app_id', help="App à régénérer (ex. converter).")
        parser.add_argument('--keep', action='store_true',
                            help="Laisser l'état régénéré en place (pas de git restore).")
        parser.add_argument('--json', action='store_true', help="Rapport JSON.")
        parser.add_argument('--force', action='store_true',
                            help="Autoriser l'exécution sur dev/main (déconseillé : bac à sable).")
        parser.add_argument('--phase', choices=['measure', 'apply'], help=(
            "INTERNE — phases exécutées en sous-process frais par l'orchestrateur."))

    # ── Phases internes (sous-process frais : imports non périmés) ───────────
    def _corpus(self, app_id: str) -> dict:
        from django.conf import settings
        chemin = Path(settings.BASE_DIR) / 'manifests' / 'apps' / f'{app_id}.json'
        if not chemin.is_file():
            raise CommandError(f"corpus absent : {chemin} — lancer `manage.py manifest_export`.")
        return json.loads(chemin.read_text(encoding='utf-8'))

    def _measure(self, app_id: str) -> dict:
        from wama.common.manifests.ingest import extract
        from wama.common.services.conformity_checker import run_checks

        grille = (run_checks([app_id]).get('apps') or {}).get(app_id) or {}
        return {
            'manifest': extract('app', app_id),
            # `conv` seul : `evidence` porte des numéros de ligne, qui bougent à la régénération.
            'conv': grille.get('conv') or {},
            'score': grille.get('score'), 'total': grille.get('total'), 'pct': grille.get('pct'),
            'smoke': self._smoke(app_id),
        }

    def _smoke(self, app_id: str) -> dict:
        out = {}
        try:
            from django.test import Client
            from django.urls import reverse
            from wama.common.app_registry import APP_CATALOG
            url_name = (APP_CATALOG.get(app_id) or {}).get('url_name')
            out['http_status'] = (Client().get(reverse(url_name), HTTP_HOST='localhost').status_code
                                  if url_name else "ERREUR: url_name absent d'APP_CATALOG")
        except Exception as e:
            out['http_status'] = f'ERREUR: {e!r}'
        try:
            from wama.common.utils.param_schema import schema_for_app
            out['params_count'] = len(schema_for_app(app_id) or [])
        except Exception as e:
            out['params_count'] = f'ERREUR: {e!r}'
        try:
            # Runtime voulu ici : les E/S DÉRIVÉES des ports (injectées à l'import) font partie
            # du comportement jugé, contrairement au write-back qui ne compare que le déclaratif.
            from wama.studio.services.generic_runner import GENERIC_APPS
            conf = GENERIC_APPS.get(app_id)
            out['studio_node'] = None if conf is None else {
                'input_kinds': conf.get('input_kinds'), 'primary_input': conf.get('primary_input'),
                'output_type': conf.get('output_type'), 'io_derived': conf.get('_io_derived'),
                'auto_start': bool(conf.get('auto_start')),
                'params_module': conf.get('params_module'),
            }
        except Exception as e:
            out['studio_node'] = f'ERREUR: {e!r}'
        try:
            from wama.common.utils.app_modes import APP_MODES
            entree = APP_MODES.get(app_id)
            out['modes_domains'] = ([d.get('id') for d in (entree.get('domains') or [])]
                                    if entree else None)
        except Exception as e:
            out['modes_domains'] = f'ERREUR: {e!r}'
        return out

    def _apply(self, app_id: str) -> dict:
        from wama.common.manifests.builtin.app import write_back_app
        return write_back_app(self._corpus(app_id), apply=True, skip=('access',))

    # ── Orchestration ────────────────────────────────────────────────────────
    # Tout est ancré sur BASE_DIR (l'arbre dont le code est réellement importé) : lancé via
    # `python <worktree>/manage.py`, le harnais doit mesurer et restaurer CE worktree-là,
    # jamais l'arbre du cwd de l'appelant.
    @staticmethod
    def _root() -> Path:
        from django.conf import settings
        return Path(settings.BASE_DIR)

    def _run_phase(self, app_id: str, phase: str) -> dict:
        env = {**os.environ, 'PYTHONIOENCODING': 'utf-8'}
        r = subprocess.run([sys.executable, str(self._root() / 'manage.py'),
                            'app_regen_check', app_id, '--phase', phase],
                           capture_output=True, text=True, encoding='utf-8', env=env,
                           cwd=str(self._root()))
        if r.returncode != 0:
            raise CommandError(f"phase {phase} : échec (code {r.returncode})\n{r.stderr[-2000:]}")
        for ligne in reversed((r.stdout or '').strip().splitlines()):
            if ligne.strip().startswith('{'):
                return json.loads(ligne)
        raise CommandError(f"phase {phase} : aucune sortie JSON\n{(r.stdout or '')[-2000:]}")

    def _git(self, *args) -> tuple:
        r = subprocess.run(['git', '-C', str(self._root()), *args],
                           capture_output=True, text=True, encoding='utf-8')
        return r.returncode, (r.stdout or '').strip()

    def _gardes(self, force: bool, candidats: list):
        code, branche = self._git('rev-parse', '--abbrev-ref', 'HEAD')
        if code != 0:
            raise CommandError("pas un dépôt git — le harnais exige un bac à sable restaurable.")
        if branche in ('dev', 'main', 'master') and not force:
            raise CommandError(f"branche '{branche}' : le harnais STRIPPE du code committé — "
                               f"l'exécuter dans un worktree dédié (ou --force en connaissance).")
        # Propreté exigée sur les FICHIERS CIBLES seuls (ceux que strip/write_back/restore
        # touchent) : le restore doit être exact là, le reste de l'arbre ne le concerne pas.
        _, sale = self._git('status', '--porcelain', '-uno', '--',
                            *[self._rel(p) for p in candidats])
        if sale:
            raise CommandError("fichier(s) cible(s) non propre(s) — le restore doit pouvoir "
                               "être exact :\n" + sale[:1500])
        return branche

    def _rel(self, p) -> str:
        return os.path.relpath(str(p), str(self._root()))

    def _restore(self, chemins: list):
        for p in chemins:
            rel = self._rel(p)
            code, _ = self._git('ls-files', '--error-unmatch', rel)
            if code == 0:
                self._git('checkout', '--', rel)
            else:
                Path(p).unlink(missing_ok=True)   # fichier créé par le write-back, non suivi

    @staticmethod
    def _sans_diagnostic(manifest: dict) -> dict:
        """Le corpus est exporté SANS les clés diagnostiques (`_missing_facets`…, cf.
        manifest_export) : la garde corpus compare donc hors clés `_` des deux côtés."""
        body = {k: v for k, v in (manifest.get('body') or {}).items()
                if not k.startswith('_')}
        return {**manifest, 'body': body}

    @staticmethod
    def _diff_manifeste(base: dict, apres: dict) -> tuple:
        from wama.common.manifests.ingest import diff_dicts
        ecarts = diff_dicts(base or {}, apres or {})
        toleres = [e for e in ecarts if _famille_mesuree(e.get('path', ''))]
        reels = [e for e in ecarts if not _famille_mesuree(e.get('path', ''))]
        return reels, toleres

    @staticmethod
    def _diff_grille(base: dict, apres: dict) -> list:
        b, a = base.get('conv') or {}, apres.get('conv') or {}
        return [{'critere': k, 'avant': b.get(k), 'apres': a.get(k)}
                for k in sorted(set(b) | set(a)) if b.get(k) != a.get(k)]

    def handle(self, *args, **o):
        app_id = o['app_id']
        if o.get('phase'):
            resultat = self._measure(app_id) if o['phase'] == 'measure' else self._apply(app_id)
            self.stdout.write(json.dumps(resultat, ensure_ascii=False, default=str))
            return

        from wama.common.manifests.builtin.app import (
            strip_app_declarations, _metadata_path, _modes_path, _params_file_path,
            _params_module_name, _registry_path, _runner_path)

        corpus = self._corpus(app_id)
        candidats = [str(_registry_path()), str(_runner_path()), str(_modes_path()),
                     str(_metadata_path()), str(_params_file_path(_params_module_name(corpus)))]
        branche = self._gardes(o['force'], candidats)

        rapport = {'app': app_id, 'branche': branche}
        try:
            baseline = self._run_phase(app_id, 'measure')
            # Garde corpus : juger la régénération d'un manifeste périmé n'aurait pas de sens.
            perimes, _ = self._diff_manifeste(self._sans_diagnostic(corpus),
                                              self._sans_diagnostic(baseline['manifest']))
            if perimes:
                raise CommandError(
                    "corpus PÉRIMÉ vs extraction courante — lancer `manage.py manifest_export` "
                    "puis relancer :\n" + '\n'.join(f"  - {e['path']}" for e in perimes[:10]))

            rapport['strip'] = strip_app_declarations(corpus, apply=True)
            rapport['write_back'] = self._run_phase(app_id, 'apply')
            erreurs = [f"{f}: {r['error']}" for f, r in rapport['write_back'].items()
                       if isinstance(r, dict) and r.get('error')]
            if erreurs:
                raise CommandError("write_back en erreur :\n" + '\n'.join(erreurs))

            apres = self._run_phase(app_id, 'measure')

            reels, toleres = self._diff_manifeste(baseline['manifest'], apres['manifest'])
            rapport['axe1_manifeste'] = {'ok': not reels, 'ecarts_reels': reels,
                                         'ecarts_mesures_toleres': toleres}
            dg = self._diff_grille(baseline, apres)
            rapport['axe2_grille'] = {'ok': not dg, 'avant_pct': baseline.get('pct'),
                                      'apres_pct': apres.get('pct'), 'ecarts': dg}
            smoke_ok = (baseline['smoke'] == apres['smoke']
                        and apres['smoke'].get('http_status') == 200)
            rapport['axe3_smoke'] = {'ok': smoke_ok, 'avant': baseline['smoke'],
                                     'apres': apres['smoke']}
            rapport['verdict'] = all(rapport[a]['ok'] for a in
                                     ('axe1_manifeste', 'axe2_grille', 'axe3_smoke'))
        finally:
            if not o['keep']:
                self._restore(candidats)
                rapport['restore'] = 'worktree restauré (git checkout)'
            else:
                rapport['restore'] = 'état régénéré CONSERVÉ (--keep)'

        if o['json']:
            self.stdout.write(json.dumps(rapport, ensure_ascii=False, indent=1, default=str))
        else:
            self._afficher(rapport)
        if not rapport.get('verdict'):
            raise CommandError("régénération NON conforme — détail ci-dessus.")

    def _afficher(self, r):
        w, s, e = self.stdout.write, self.style.SUCCESS, self.style.ERROR
        warn = self.style.WARNING
        w(f"\n{'=' * 78}\nHARNAIS DE RÉGÉNÉRATION — {r['app']} (branche {r['branche']})\n{'=' * 78}")

        strip = r.get('strip') or {}
        faits = [k for k, v in strip.items() if v == 'retiré']
        w(f"\n  Strip      : {', '.join(faits) or 'rien à retirer'}"
          + (f"  ({len(strip.get('files') or [])} fichier(s))" if faits else ''))

        wb = r.get('write_back') or {}
        ops = {f: v.get('op', 'écrit') for f, v in wb.items()
               if isinstance(v, dict) and f not in ('app', 'codegen_required')}
        w(f"  Write-back : {', '.join(f'{f}={op}' for f, op in ops.items()) or '—'}")
        if wb.get('codegen_required'):
            w(f"               (hors périmètre, code-gen : {', '.join(wb['codegen_required'])})")

        a1 = r.get('axe1_manifeste') or {}
        if a1.get('ok'):
            n = len(a1.get('ecarts_mesures_toleres') or [])
            w(s(f"  ① Manifeste : IDENTIQUE ({n} écart(s) famille mesurée toléré(s), trou #16)"))
        else:
            w(e(f"  ① Manifeste : DIVERGENT — {len(a1.get('ecarts_reels') or [])} écart(s) réel(s)"))
            for d in (a1.get('ecarts_reels') or [])[:10]:
                w(e(f"      - {d.get('path')}: baseline={d.get('manifest')!r} "
                    f"régénéré={d.get('current')!r}"))

        a2 = r.get('axe2_grille') or {}
        if a2.get('ok'):
            w(s(f"  ② Grille    : IDENTIQUE ({a2.get('apres_pct')} %)"))
        else:
            w(e(f"  ② Grille    : DIVERGENTE ({a2.get('avant_pct')} % → {a2.get('apres_pct')} %)"))
            for d in (a2.get('ecarts') or [])[:15]:
                w(e(f"      - {d['critere']}: {d['avant']!r} → {d['apres']!r}"))

        a3 = r.get('axe3_smoke') or {}
        if a3.get('ok'):
            sm = a3.get('apres') or {}
            w(s(f"  ③ Smoke     : identique (HTTP {sm.get('http_status')}, "
                f"{sm.get('params_count')} params, studio "
                f"{'✓' if sm.get('studio_node') else '—'}, "
                f"domaines {len(sm.get('modes_domains') or [])})"))
        else:
            w(e("  ③ Smoke     : DIVERGENT"))
            w(e(f"      avant : {a3.get('avant')!r}"))
            w(e(f"      après : {a3.get('apres')!r}"))

        w(f"\n  Restore    : {r.get('restore')}")
        if r.get('verdict'):
            w(s("\n  VERDICT    : RÉGÉNÉRATION CONFORME — l'app régénérée est indistinguable "
                "sur les 3 axes."))
        else:
            w(e("\n  VERDICT    : NON CONFORME — chaque écart part dans un des 3 bacs "
                "(déclarer / porter / trou de route, §10.3)."))
