"""Bac à sable d'apps — jumelles EXÉCUTABLES (route §10.3, marche S, actée Fabien 2026-08-18).

  python manage.py app_sandbox create converter        # → jumelle TÉMOIN `converter_01`
  python manage.py app_sandbox drop converter_01       # migrate zero + retrait complet
  python manage.py app_sandbox list

Étape S1 (jumelle TÉMOIN) : COPIE du code réel sous un label suffixé `_NN` — prouve la
plomberie de coexistence (INSTALLED_APPS/urls/gating/catalogue injectés depuis
`wama/sandbox_apps.json`, tables Django séparées par app_label) et livre le banc de
comparaison (Playwright côte à côte + diff dé-suffixé). L'étape S2 substituera un à un les
fichiers copiés par les fichiers GÉNÉRÉS (gabarits codegen/) — le diff copie↔généré devient
le détecteur des trous.

Renommages MÉCANIQUES appliqués aux fichiers texte du package (py/html/js/css) :
  1. `wama.converter`   → `wama.converter_01`   (modules, noms de tâches Celery)
  2. `'converter'`      → `'converter_01'`      (app id QUOTÉ EXACT : app_access, registres
                                                 preview/detail, app_name, cache keys)
  3. `'converter:`      → `'converter_01:`      (reverse()/{% url %} namespacés)
  4. `'converter/`      → `'converter_01/`      (chemins templates/static de l'app)
  + renommage des dossiers templates/<app>/ et static/<app>/.
La jumelle RÉFÉRENCE le monde (briques common, catalogue, workers) — les références des
AUTRES modules vers l'app source ne sont jamais touchées (hors package).

Migrations : les migrations de la source ne sont PAS copiées (leurs dépendances internes
portent l'ancien app_label) — `makemigrations <label>` FRAIS en sous-process (le process
courant ne connaît pas encore la jumelle), puis `migrate <label>` → tables `<label>_*`
vierges. Drop symétrique : `migrate <label> zero` AVANT le retrait du registre/package.

⚠ Après create/drop : REDÉMARRER gunicorn/workers (INSTALLED_APPS est lu au boot).
"""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from wama.common.sandbox import (
    LABEL_RE, REGISTRY_PATH, load_registry, save_registry,
)

WAMA_DIR = Path(__file__).resolve().parents[3]          # …/wama
BASE_DIR = WAMA_DIR.parent
TEXT_EXT = {'.py', '.html', '.js', '.css', '.md', '.txt', '.json'}
SKIP_DIRS = {'__pycache__', 'migrations', '.pytest_cache'}

#: Cibles substituables (étape S2) : fichier ← gabarit codegen (render_*(manifest) → (src, raison)).
#: L'ordre du dict = l'ordre RECOMMANDÉ de substitution (du plus conventionnel au plus spécifique).
_SUBSTITUTABLE = {
    'apps':   ('apps.py',   'wama.common.manifests.codegen.apps_gen',   'render_apps'),
    'urls':   ('urls.py',   'wama.common.manifests.codegen.urls_gen',   'render_urls'),
    'models': ('models.py', 'wama.common.manifests.codegen.models_gen', 'render_models'),
    'tasks':  ('tasks.py',  'wama.common.manifests.codegen.tasks_gen',  'render_tasks'),
}


def _next_label(base: str) -> str:
    taken = {e['label'] for e in load_registry()}
    for n in range(1, 100):
        label = f'{base}_{n:02d}'
        if label not in taken and not (WAMA_DIR / label).exists():
            return label
    raise CommandError(f"Plus d'indice libre pour {base} (01..99 pris ?)")


_FIELD_CALL_RE = re.compile(
    r'(ForeignKey|OneToOneField|ManyToManyField)\(\s*(?:to\s*=\s*)?'
    r'(?P<target>[A-Za-z_][\w.]*|\'[^\']+\'|"[^"]+")', re.S)


def _patch_related_names(text: str, label: str) -> str:
    """models.py de la jumelle : suffixe les `related_name` des relations vers des modèles
    EXTERNES au package (User…) — ce sont eux qui portent la collision d'accesseur inverse
    (E304/E305 mesurés au pilote converter). Les relations INTERNES gardent leur nom : le
    code de l'app consomme ses propres accesseurs (`batch.items` — vérifié au pilote)."""
    internal = set(re.findall(r'^class\s+(\w+)\(', text, re.M))

    def _is_internal(target: str) -> bool:
        t = target.strip('\'"').split('.')[-1]
        return t == 'self' or t in internal

    out, pos = [], 0
    for m in re.finditer(r"related_name\s*=\s*(['\"])(\w+)\1", text):
        # Le champ propriétaire = le dernier appel de relation AVANT ce related_name.
        calls = list(_FIELD_CALL_RE.finditer(text, 0, m.start()))
        external = bool(calls) and not _is_internal(calls[-1].group('target'))
        out.append(text[pos:m.start()])
        if external:
            q, name = m.group(1), m.group(2)
            out.append(f'related_name={q}{name}_{label}{q}')
        else:
            out.append(m.group(0))
        pos = m.end()
    out.append(text[pos:])
    return ''.join(out)


def _rename_text(text: str, src: str, dst: str) -> str:
    """Les 4 familles de renommage — quotes simples ET doubles, ordre du plus spécifique
    au plus général (le `wama.` d'abord, sinon le quoté exact le casserait)."""
    text = text.replace(f'wama.{src}', f'wama.{dst}')
    for q in ("'", '"'):
        text = text.replace(f'{q}{src}:', f'{q}{dst}:')      # namespaces d'URL
        text = text.replace(f'{q}{src}/', f'{q}{dst}/')      # chemins templates/static
        text = re.sub(rf'{q}{re.escape(src)}{q}', f'{q}{dst}{q}', text)  # app id exact
    return text


def _copy_package(src: str, dst: str) -> list:
    """Copie wama/<src> → wama/<dst> avec renommages ; retourne la liste des fichiers écrits."""
    src_dir, dst_dir = WAMA_DIR / src, WAMA_DIR / dst
    written = []
    for path in sorted(src_dir.rglob('*')):
        rel = path.relative_to(src_dir)
        if any(part in SKIP_DIRS for part in rel.parts):
            continue
        # Dossiers d'app dans templates/ et static/ : renommés vers le label jumeau.
        parts = list(rel.parts)
        for i in range(len(parts) - 1):
            if parts[i] in ('templates', 'static') and parts[i + 1] == src:
                parts[i + 1] = dst
        target = dst_dir / Path(*parts)
        if path.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        if path.suffix.lower() in TEXT_EXT:
            try:
                out = _rename_text(path.read_text(encoding='utf-8'), src, dst)
                if rel.name == 'models.py':
                    out = _patch_related_names(out, dst)
                target.write_text(out, encoding='utf-8')
            except UnicodeDecodeError:
                shutil.copy2(path, target)
        else:
            shutil.copy2(path, target)
        written.append(target)
    # Dossier migrations FRAIS (package sans migrations = app non migrable).
    mig = dst_dir / 'migrations'
    mig.mkdir(exist_ok=True)
    (mig / '__init__.py').write_text('', encoding='utf-8')
    return written


def _manage(args: list) -> subprocess.CompletedProcess:
    """manage.py en SOUS-PROCESS FRAIS : le boot relit sandbox_apps.json — le process
    courant, lui, ne connaît pas (encore/plus) la jumelle (même principe que app_regen_check)."""
    return subprocess.run([sys.executable, str(BASE_DIR / 'manage.py'), *args],
                          capture_output=True, text=True, cwd=str(BASE_DIR))


class Command(BaseCommand):
    help = "Bac à sable d'apps : create <app> / drop <app_NN> / list (route §10.3 marche S)"

    def add_arguments(self, parser):
        parser.add_argument('action', choices=['create', 'drop', 'list', 'substitute'])
        parser.add_argument('app', nargs='?', help='app source (create) ou label jumeau (drop/substitute)')
        parser.add_argument('cible', nargs='?',
                            help=f"substitute : {sorted(_SUBSTITUTABLE)} — fichier à passer en GÉNÉRÉ")

    def handle(self, *args, **opts):
        action = opts['action']
        if action == 'list':
            entries = load_registry()
            if not entries:
                self.stdout.write('Aucune jumelle (registre vide ou absent : '
                                  f'{REGISTRY_PATH}).')
            for e in entries:
                subs = ', '.join(f"{k}:{v.get('verdict')}" for k, v in
                                 (e.get('substituted') or {}).items()) or '—'
                self.stdout.write(f"  {e['label']}  ← {e.get('generated_from')}  "
                                  f"({e.get('created', '?')})  substitués : {subs}")
            return

        app = opts.get('app')
        if not app:
            raise CommandError(f"app_sandbox {action} exige un nom d'app.")

        if action == 'create':
            self._create(app)
        elif action == 'substitute':
            self._substitute(app, opts.get('cible'))
        else:
            self._drop(app)

    # ── create ───────────────────────────────────────────────────────────────
    def _create(self, src: str):
        from wama.common.app_registry import APP_CATALOG
        if src not in APP_CATALOG:
            raise CommandError(f"App inconnue au catalogue : {src}")
        if (APP_CATALOG[src] or {}).get('sandbox'):
            raise CommandError('On ne clone pas une jumelle.')
        if not (WAMA_DIR / src / 'apps.py').exists():
            raise CommandError(f'Package wama/{src} introuvable.')

        label = _next_label(src)
        self.stdout.write(f'Jumelle TÉMOIN : wama/{src} → wama/{label}')
        written = _copy_package(src, label)
        self.stdout.write(f'  {len(written)} fichiers copiés/renommés.')

        entries = load_registry()
        entries.append({'label': label, 'generated_from': src,
                        'created': datetime.now(timezone.utc).isoformat(timespec='seconds'),
                        'stage': 'S1-temoin'})
        save_registry(entries)

        # Migrations FRAÎCHES en sous-process (boot avec la jumelle enregistrée).
        for step in (['makemigrations', label], ['migrate', label]):
            r = _manage(step)
            tail = (r.stdout or r.stderr).strip().splitlines()[-3:]
            self.stdout.write(f"  manage.py {' '.join(step)} → rc={r.returncode}")
            for line in tail:
                self.stdout.write(f'    {line}')
            if r.returncode != 0:
                self.stderr.write(self.style.ERROR(
                    '  ÉCHEC — la jumelle reste enregistrée pour diagnostic ; '
                    f'`app_sandbox drop {label}` pour tout retirer.'))
                return

        self.stdout.write(self.style.SUCCESS(
            f'Jumelle {label} prête : /{label}/ (dev-only). '
            '⚠ Redémarrer gunicorn/workers pour la servir.'))

    # ── substitute (étape S2) ────────────────────────────────────────────────
    def _substitute(self, label: str, cible: str):
        """Remplace UN fichier copié de la jumelle par sa version GÉNÉRÉE (gabarit codegen
        sur le manifeste extrait LIVE de la SOURCE), puis re-mesure. Le fichier copié est
        préservé en `.temoin` (= la référence du diff copie↔généré). ÉCHEC → auto-revert :
        jamais une jumelle morte. Verdicts journalisés au registre (stage S2)."""
        import importlib

        if cible not in _SUBSTITUTABLE:
            raise CommandError(f'Cible inconnue : {cible} (attendu {sorted(_SUBSTITUTABLE)}).')
        entries = load_registry()
        entry = next((e for e in entries if e['label'] == label), None)
        if not entry:
            raise CommandError(f'{label} absent du registre.')
        src = entry['generated_from']

        # 1. GÉNÉRATION depuis le manifeste LIVE de la source (l'app d'origine n'est que LUE).
        from wama.common.manifests.ingest import extract
        manifest = extract('app', src)
        if not manifest:
            raise CommandError(f"Extraction du manifeste de {src} impossible.")
        fname, mod_path, fn_name = _SUBSTITUTABLE[cible]
        rendered, raison = getattr(importlib.import_module(mod_path), fn_name)(manifest)
        if rendered is None:
            raise CommandError(f'Gabarit {cible} : rien à générer — {raison}')

        # 2. SUFFIXAGE identique à la copie (la génération vise `converter`, la jumelle
        #    parle `converter_01`) + patch related_name pour models.
        text = _rename_text(rendered, src, label)
        if cible == 'models':
            text = _patch_related_names(text, label)

        target = WAMA_DIR / label / fname
        temoin = target.with_name(fname + '.temoin')
        if target.exists() and not temoin.exists():
            shutil.copy2(target, temoin)      # référence du diff, préservée UNE fois
        target.write_text(text, encoding='utf-8')
        self.stdout.write(f'{fname} ← GÉNÉRÉ ({len(text.splitlines())} lignes ; '
                          f'témoin : {temoin.name})')

        # 3. RE-MESURE : check + (models → makemigrations) + smoke page en sous-process frais.
        verdict, details = 'ok', []
        r = _manage(['check'])
        if r.returncode != 0:
            verdict = 'revert'
            details.append('manage.py check KO')
        mig_dir = WAMA_DIR / label / 'migrations'
        mig_avant = {p.name for p in mig_dir.glob('0*.py')}
        if verdict == 'ok' and cible == 'models':
            r = _manage(['makemigrations', label])
            if r.returncode != 0:
                verdict, details = 'revert', ['makemigrations KO']
            elif 'No changes detected' not in (r.stdout or ''):
                details.append('schéma DIVERGENT (migration créée — champs en écart)')
                r2 = _manage(['migrate', label])
                if r2.returncode != 0:
                    verdict, details = 'revert', ['migrate de l’écart KO']
        if verdict == 'ok':
            smoke = subprocess.run(
                [sys.executable, '-c',
                 "import os,django;os.environ.setdefault('DJANGO_SETTINGS_MODULE','wama.settings');"
                 "django.setup();from django.test import Client;"
                 f"r=Client().get('/{label}/',follow=True);print(r.status_code);"
                 "raise SystemExit(0 if r.status_code==200 else 1)"],
                capture_output=True, text=True, cwd=str(BASE_DIR))
            if smoke.returncode != 0:
                verdict = 'revert'
                details.append(f"smoke /{label}/ KO ({(smoke.stdout or smoke.stderr).strip()[:120]})")

        # 4. Diff compact copie↔généré (le DÉTECTEUR : chaque écart est un fait).
        if temoin.exists():
            a = temoin.read_text(encoding='utf-8').splitlines()
            b = text.splitlines()
            import difflib
            delta = [l for l in difflib.unified_diff(a, b, lineterm='') if l[:1] in '+-'
                     and not l.startswith(('+++', '---'))]
            details.append(f'diff copie↔généré : {len(delta)} lignes')

        # 5. Échec → RETOUR AU TÉMOIN (jamais une jumelle morte) ; sinon journal.
        if verdict == 'revert':
            shutil.copy2(temoin, target)
            # Revert COMPLET côté schéma (défaut mesuré au 1er run : la migration divergente
            # restait APPLIQUÉE avec le modèle revenu au témoin) : désappliquer puis retirer
            # les fichiers de migration créés par CETTE substitution.
            nouvelles = sorted({p.name for p in mig_dir.glob('0*.py')} - mig_avant)
            if nouvelles:
                derniere_saine = sorted(mig_avant)[-1].split('_', 1)[0] if mig_avant else 'zero'
                _manage(['migrate', label, derniere_saine, '--skip-checks'])
                for n in nouvelles:
                    (mig_dir / n).unlink(missing_ok=True)
                details.append(f'migrations divergentes désappliquées/retirées : {nouvelles}')
            self.stderr.write(self.style.ERROR(
                f'ÉCHEC — {fname} REVENU au témoin. TROU documenté : ' + ' ; '.join(details)))
        else:
            self.stdout.write(self.style.SUCCESS(
                f'{cible} : GÉNÉRÉ tient ({" ; ".join(details) or "aucun écart"})'))
        entry.setdefault('substituted', {})[cible] = {
            'verdict': verdict, 'details': details,
            'at': datetime.now(timezone.utc).isoformat(timespec='seconds')}
        entry['stage'] = ('S2-partiel'
                          if any(v.get('verdict') == 'ok'
                                 for v in entry['substituted'].values()) else entry['stage'])
        save_registry(entries)

    # ── drop ─────────────────────────────────────────────────────────────────
    def _drop(self, label: str):
        if not LABEL_RE.match(label):
            raise CommandError(f'Label jumeau invalide : {label} (attendu <app>_NN).')
        entries = load_registry()
        if label not in {e['label'] for e in entries}:
            raise CommandError(f'{label} absent du registre {REGISTRY_PATH}.')

        # 1. Tables : migrate zero PENDANT que la jumelle est encore enregistrée.
        # --skip-checks : une jumelle CASSÉE (clash de modèles, import raté) bloquerait le
        # system check du sous-process — le drop doit toujours pouvoir nettoyer (œuf/poule
        # mesuré au pilote : le premier essai raté était indéboulonnable sans ça).
        r = _manage(['migrate', label, 'zero', '--skip-checks'])
        self.stdout.write(f'  manage.py migrate {label} zero → rc={r.returncode}')
        if r.returncode != 0:
            for line in (r.stderr or r.stdout).strip().splitlines()[-5:]:
                self.stdout.write(f'    {line}')
            raise CommandError('migrate zero a échoué — rien retiré (relancer après correction).')

        # 2. Registre puis package (l'ordre inverse laisserait une entrée orpheline,
        #    inoffensive grâce à la garde sandbox_labels(), mais sale).
        save_registry([e for e in entries if e['label'] != label])
        target = WAMA_DIR / label
        if target.exists():
            shutil.rmtree(target)
        self.stdout.write(self.style.SUCCESS(
            f'Jumelle {label} retirée (tables, registre, package). '
            '⚠ Redémarrer gunicorn/workers.'))
