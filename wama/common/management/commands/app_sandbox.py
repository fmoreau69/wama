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
    # `params` AVANT views/templates dans l'ordre recommandé : les deux consomment PARAMS_JSON,
    # et une jumelle qui garde sa COPIE de params.py mesure un schéma périmé (converter_01 :
    # copie d'avant le 18/08, sans le contexte 'panel' → volet PARAMÈTRES vide, 31/08).
    'params': ('params.py', 'wama.common.manifests.codegen.params_gen', 'render_params'),
    'tasks':  ('tasks.py',  'wama.common.manifests.codegen.tasks_gen',  'render_tasks'),
    'views':  ('views.py',  'wama.common.manifests.codegen.views_gen',  'render_views'),
    # Multi-fichiers (le gabarit rend un DICT nom→contenu) : écrits sous templates/<label>/.
    'templates': ('templates/', 'wama.common.manifests.codegen.templates_gen', 'render_index'),
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
    internal_lower = {c.lower() for c in internal}

    def _is_internal(target: str) -> bool:
        t = target.strip('\'"').split('.')[-1]
        return t == 'self' or t in internal or t.lower() in internal_lower

    out, pos = [], 0
    for m in re.finditer(r"related_name\s*=\s*(['\"])(\w+)\1", text):
        # Le champ propriétaire = le dernier appel de relation AVANT ce related_name.
        calls = list(_FIELD_CALL_RE.finditer(text, 0, m.start()))
        # Cible RÉELLE : le `to=` DANS l'appel COMPLET prime (code généré = kwargs
        # alphabétiques : `to=` vient APRÈS related_name — une fenêtre arrêtée au
        # related_name le manquait, sur-suffixage mesuré ×2 au pilote S2) ; repli sur le
        # token positionnel (code réel copié : classe en 1er argument).
        target = ''
        if calls:
            debut = calls[-1].end()
            prof, fin = 1, debut
            while fin < len(text) and prof:
                if text[fin] == '(':
                    prof += 1
                elif text[fin] == ')':
                    prof -= 1
                fin += 1
            m_to = re.search(r"to\s*=\s*['\"]([\w.]+)['\"]", text[calls[-1].start():fin])
            target = m_to.group(1) if m_to else calls[-1].group('target')
        external = bool(target) and not _is_internal(target)
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
        text = text.replace(f'{q}{src}.', f'{q}{dst}.')      # réfs par app_label ('converter.Model'
                                                             #  des FK sérialisées — facette data S2)
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


def _imports_intra_paquet_non_resolus(label: str) -> list:
    """Juge GÉNÉRIQUE de cohérence du paquet jumeau (2026-09-03, demande Fabien : « qu'une
    nouvelle génération ne redécouvre pas les mêmes problèmes »).

    La CLASSE du défaut `PARAMS` (params généré n'exposant plus un symbole que le models
    COPIÉ importait — ImportError au rendu de chaque card, invisible du smoke à file vide) :
    un fichier substitué doit continuer d'exposer TOUT ce que les fichiers copiés lui
    importent. Vérifié par AST sur tout le paquet, y compris les imports PARESSEUX dans les
    fonctions/properties (c'est là que vivait le défaut — un simple import de module ne
    l'aurait jamais levé). Rend la liste des `from .x import Y` sans `Y` chez la cible.
    """
    import ast
    base = WAMA_DIR / label
    prefixe = f'wama.{label}'

    exposes = {}
    arbres = {}
    for p in base.rglob('*.py'):
        if 'migrations' in p.parts:
            continue
        try:
            arbre = ast.parse(p.read_text(encoding='utf-8'))
        except SyntaxError:
            continue    # un fichier insyntaxique est le problème d'un AUTRE juge (compile)
        arbres[p] = arbre
        mod = '.'.join(p.relative_to(base).with_suffix('').parts)
        noms = set()
        for n in arbre.body:
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                noms.add(n.name)
            elif isinstance(n, ast.Assign):
                noms.update(t.id for t in n.targets if isinstance(t, ast.Name))
            elif isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name):
                noms.add(n.target.id)
            elif isinstance(n, (ast.Import, ast.ImportFrom)):
                noms.update((a.asname or a.name.split('.')[0]) for a in n.names)
        exposes[mod] = noms

    manquants = []
    for p, arbre in arbres.items():
        for n in ast.walk(arbre):
            if not isinstance(n, ast.ImportFrom):
                continue
            if n.level:                                   # from .params / from ..utils
                pkg = list(p.relative_to(base).parent.parts)
                pkg = pkg[:len(pkg) - (n.level - 1)] if n.level > 1 else pkg
                if len(pkg) < 0:
                    continue
                mod = '.'.join(pkg + (n.module.split('.') if n.module else []))
            elif n.module and n.module.startswith(prefixe + '.'):
                mod = n.module[len(prefixe) + 1:]
            elif n.module == prefixe:
                mod = '__init__'
            else:
                continue                                  # import EXTERNE au paquet
            cle = mod if mod in exposes else f'{mod}.__init__'
            if cle not in exposes:
                continue                                  # module absent → vu par check/compile
            for a in n.names:
                if a.name != '*' and a.name not in exposes[cle]:
                    manquants.append(
                        f"{p.relative_to(base).as_posix()} : "
                        f"from {'.' * n.level}{n.module or ''} import {a.name} — absent de {cle}")
    return manquants


def _manage(args: list) -> subprocess.CompletedProcess:
    """manage.py en SOUS-PROCESS FRAIS : le boot relit sandbox_apps.json — le process
    courant, lui, ne connaît pas (encore/plus) la jumelle (même principe que app_regen_check)."""
    return subprocess.run([sys.executable, str(BASE_DIR / 'manage.py'), *args],
                          capture_output=True, text=True, cwd=str(BASE_DIR))


class Command(BaseCommand):
    help = "Bac à sable d'apps : create <app> / drop <app_NN> / list (route §10.3 marche S)"

    def add_arguments(self, parser):
        parser.add_argument('action', choices=['create', 'drop', 'list', 'substitute', 'revert'])
        parser.add_argument('app', nargs='?', help='app source (create) ou label jumeau (drop/substitute)')
        parser.add_argument('cible', nargs='?',
                            help=f"substitute : {sorted(_SUBSTITUTABLE)} — fichier à passer en GÉNÉRÉ")
        parser.add_argument('--proprietaire', default='',
                            help="create : username du CRÉATEUR de la jumelle (visibilité "
                                 "« créateur + dev + admin », demande Fabien 03/09) ; "
                                 "vide = jumelle d'opérateur, dev/admin seuls")

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
            self._create(app, owner=opts.get('proprietaire') or '')
        elif action == 'substitute':
            self._substitute(app, opts.get('cible'))
        elif action == 'revert':
            self._revert(app, opts.get('cible'))
        else:
            self._drop(app)

    # ── create ───────────────────────────────────────────────────────────────
    def _create(self, src: str, owner: str = ''):
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
                        'created_by': owner,
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

        # ⚠ COUPLE views↔templates (mesuré par Fabien sur describer_01, 2026-09-03) : l'index
        # GÉNÉRÉ inclut la card générique et attend le contexte des vues GÉNÉRÉES ; des vues
        # COPIÉES rendent l'autre partial au refresh et un autre contexte → page qui s'affiche,
        # boutons de card MORTS. Le smoke de l'étape 3 (HTTP 200) ne voit rien : la paire
        # incohérente REND. On refuse donc templates sans views:ok — l'inverse (views générées,
        # templates copiés) est refusé par l'ORDRE recommandé et le même argument.
        if cible == 'templates':
            v = ((entry.get('substituted') or {}).get('views') or {}).get('verdict')
            if v != 'ok':
                raise CommandError(
                    "templates et views se substituent en COUPLE : substituer `views` d'abord "
                    f"(état actuel : {v or 'jamais substitué'}). Une app dont views_gen refuse "
                    "(ex. file à modèle de liaison) garde SES templates copiés — cohérents.")

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
        #    parle `converter_01`) + patch related_name pour models. Un gabarit peut rendre
        #    un DICT nom→contenu (multi-fichiers, ex. templates : index + card générique).
        fichiers = rendered if isinstance(rendered, dict) else {fname: rendered}
        temoin = None
        ecrits = []
        for nom, contenu in fichiers.items():
            texte = _rename_text(contenu, src, label)
            if cible == 'models':
                texte = _patch_related_names(texte, label)
            if isinstance(rendered, dict):
                cible_path = WAMA_DIR / label / 'templates' / label / nom
            else:
                cible_path = WAMA_DIR / label / nom
            cible_path.parent.mkdir(parents=True, exist_ok=True)
            t = cible_path.with_name(cible_path.name + '.temoin')
            if cible_path.exists() and not t.exists():
                shutil.copy2(cible_path, t)   # référence du diff, préservée UNE fois
            if temoin is None and t.exists():
                temoin, target, text = t, cible_path, texte   # diff/revert = 1er fichier témoin
            cible_path.write_text(texte, encoding='utf-8')
            ecrits.append((cible_path, t))
            self.stdout.write(f'{cible_path.relative_to(WAMA_DIR / label)} ← GÉNÉRÉ '
                              f'({len(texte.splitlines())} lignes)')
        if temoin is None:                     # aucun fichier préexistant (tout est neuf)
            target, text = ecrits[0][0], ecrits[0][0].read_text(encoding='utf-8')

        # 3. RE-MESURE : cohérence de paquet + check + (models → makemigrations) + smoke page.
        verdict, details = 'ok', []
        # Juge GÉNÉRIQUE avant tout sous-process : chaque symbole intra-paquet importé par
        # les fichiers copiés doit exister chez sa cible (classe du défaut PARAMS, 03/09).
        _non_resolus = _imports_intra_paquet_non_resolus(label)
        if _non_resolus:
            verdict = 'revert'
            details.append('symboles intra-paquet NON RÉSOLUS : '
                           + ' ; '.join(_non_resolus[:4]))
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
        # ── Smoke « file HABITÉE » (mesuré le 2026-09-03, describer_01/params) : une page à
        # file VIDE ne rend AUCUNE card — un symbole de schéma disparu (`PARAMS`) ne levait
        # qu'au rendu d'une card réelle : 200 au juge, ImportError chez l'utilisateur. On
        # crée donc un témoin minimal, on rend la page, on le supprime. Témoin incréable
        # (contraintes NOT NULL propres à l'app) → NON MESURÉ, dit tel quel — jamais bloquant
        # sur l'incréabilité, toujours bloquant sur un rendu qui lève.
        item_model = ((manifest.get('body') or {}).get('processing') or {}).get('item_model')
        if verdict == 'ok' and item_model:
            habite = subprocess.run(
                [sys.executable, '-c',
                 "import os,django;os.environ.setdefault('DJANGO_SETTINGS_MODULE','wama.settings');"
                 "django.setup();from django.apps import apps;from django.test import Client;"
                 "from wama.common.services.nightly_tests import get_test_dev_user;"
                 f"M=apps.get_model('{label}','{item_model}');u=get_test_dev_user();\n"
                 "try:\n    it=M.objects.create(user=u)\n"
                 "except Exception as e:\n    print('temoin increable:',e);raise SystemExit(2)\n"
                 "try:\n    c=Client();c.force_login(u);r=c.get('" + f'/{label}/' + "',follow=True)\n"
                 "    print(r.status_code)\nfinally:\n    it.delete()\n"
                 "raise SystemExit(0 if r.status_code==200 else 1)"],
                capture_output=True, text=True, cwd=str(BASE_DIR))
            if habite.returncode == 1:
                verdict = 'revert'
                details.append('smoke file HABITÉE KO — le rendu de card lève '
                               f"({(habite.stdout or habite.stderr).strip()[:160]})")
            elif habite.returncode == 2:
                details.append('file habitée NON MESURÉE (témoin incréable — contraintes app)')

        # 4. Diff compact copie↔généré (le DÉTECTEUR : chaque écart est un fait).
        if temoin.exists():
            a = temoin.read_text(encoding='utf-8').splitlines()
            b = text.splitlines()
            import difflib
            delta = [l for l in difflib.unified_diff(a, b, lineterm='') if l[:1] in '+-'
                     and not l.startswith(('+++', '---'))]
            details.append(f'diff copie↔généré : {len(delta)} lignes')

        # 5. Échec → RETOUR AU TÉMOIN (jamais une jumelle morte) ; sinon journal.
        # Multi-fichiers : chaque fichier revient à SON témoin ; un fichier NEUF (sans
        # témoin) est retiré.
        if verdict == 'revert':
            for _cible_path, _t in ecrits:
                if _t.exists():
                    shutil.copy2(_t, _cible_path)
                else:
                    _cible_path.unlink(missing_ok=True)
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

    # ── revert (retour MANUEL au témoin) ─────────────────────────────────────
    def _revert(self, label: str, cible: str):
        """Ramène UNE cible substituée à sa copie témoin (`.temoin`) — le geste qu'aucun
        outil n'offrait quand la substitution avait « tenu » au smoke mais cassait à
        l'usage (describer_01, 2026-09-03 : templates générés × views copiées — page 200,
        boutons morts). Fichier GÉNÉRÉ sans témoin (neuf, marqué manifest-gen) → retiré."""
        if cible not in _SUBSTITUTABLE:
            raise CommandError(f'Cible inconnue : {cible} (attendu {sorted(_SUBSTITUTABLE)}).')
        entries = load_registry()
        entry = next((e for e in entries if e['label'] == label), None)
        if not entry:
            raise CommandError(f'{label} absent du registre.')

        fname = _SUBSTITUTABLE[cible][0]
        if cible == 'templates':
            candidats = sorted((WAMA_DIR / label / 'templates' / label).glob('*.html'))
        else:
            candidats = [WAMA_DIR / label / fname]
        restaures, retires = [], []
        for p in candidats:
            if not p.is_file():
                continue
            t = p.with_name(p.name + '.temoin')
            if t.exists():
                shutil.copy2(t, p)
                restaures.append(p.name)
            elif 'manifest-gen' in p.read_text(encoding='utf-8', errors='replace')[:600]:
                p.unlink()
                retires.append(p.name)
        if not restaures and not retires:
            raise CommandError(f'{cible} : aucun témoin ni fichier généré — rien à ramener.')

        # Smoke : la jumelle revenue doit RENDRE (même juge que la substitution).
        smoke = subprocess.run(
            [sys.executable, '-c',
             "import os,django;os.environ.setdefault('DJANGO_SETTINGS_MODULE','wama.settings');"
             "django.setup();from django.test import Client;"
             f"r=Client().get('/{label}/',follow=True);print(r.status_code);"
             "raise SystemExit(0 if r.status_code==200 else 1)"],
            capture_output=True, text=True, cwd=str(BASE_DIR))
        etat = 'OK' if smoke.returncode == 0 else f'KO ({(smoke.stdout or smoke.stderr).strip()[:80]})'

        entry.setdefault('substituted', {})[cible] = {
            'verdict': 'reverted-manuel',
            'details': [f'restaurés : {restaures}', f'retirés : {retires}', f'smoke {etat}'],
            'at': datetime.now(timezone.utc).isoformat(timespec='seconds')}
        save_registry(entries)
        style = self.style.SUCCESS if smoke.returncode == 0 else self.style.ERROR
        self.stdout.write(style(
            f'{cible} REVENU au témoin — restaurés {restaures}, retirés {retires}, '
            f'smoke /{label}/ {etat}. ⚠ Recharger gunicorn pour servir la copie.'))

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
        # Écho collectstatic de la jumelle (staticfiles/<label>/ — ramassé par le restart) :
        # retiré aussi, sinon il traîne orphelin (constat Fabien 18/08 ; gitignoré par ailleurs).
        echo = BASE_DIR / 'staticfiles' / label
        if echo.exists():
            shutil.rmtree(echo, ignore_errors=True)
        self.stdout.write(self.style.SUCCESS(
            f'Jumelle {label} retirée (tables, registre, package). '
            '⚠ Redémarrer gunicorn/workers.'))
