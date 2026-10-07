"""Bac à sable d'apps — jumelles EXÉCUTABLES (route §10.3, marche S, actée Fabien 2026-08-18).

  python manage.py app_sandbox create converter        # → jumelle TÉMOIN `converter_01`
  python manage.py app_sandbox remove converter_01     # migrate zero + retrait complet
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

⚠ Après create/remove : REDÉMARRER gunicorn/workers (INSTALLED_APPS est lu au boot).
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from wama.common.sandbox import (
    LABEL_RE, REGISTRY_PATH, is_test_module, load_registry, save_registry,
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
    # Le PIPELINE d'une app à plusieurs process (2026-10-05, patron composer) — rendu seulement
    # quand l'app en déclare un (`pipeline_decl`) ; sinon la cible n'a rien à générer.
    'function_specs': ('function_specs.py', 'wama.common.manifests.codegen.function_specs_gen',
                       'render_function_specs'),
    'views':  ('views.py',  'wama.common.manifests.codegen.views_gen',  'render_views'),
    # Multi-fichiers (le gabarit rend un DICT nom→contenu) : écrits sous templates/<label>/.
    'templates': ('templates/', 'wama.common.manifests.codegen.templates_gen', 'render_index'),
    # `base.html` d'app (2026-09-30) : d'office à la création DE ZÉRO ; pour une jumelle, cible
    # OPT-IN — son base.html COPIÉ porte encore du propre à l'app (cf. `render_base`).
    'base':   ('templates/', 'wama.common.manifests.codegen.templates_gen', 'render_base'),
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
    # `related_query_name` porte la même collision que `related_name` (E305 : nom de requête
    # inverse) — enhancer.UserSettings déclare les deux ; seul le premier était suffixé, et la
    # jumelle enhancer_01 échouait au check dès sa création (2026-10-07).
    for m in re.finditer(r"(related_(?:query_)?name)\s*=\s*(['\"])(\w+)\2", text):
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
            kw, q, name = m.group(1), m.group(2), m.group(3)
            out.append(f'{kw}={q}{name}_{label}{q}')
        else:
            out.append(m.group(0))
        pos = m.end()
    out.append(text[pos:])
    return ''.join(out)


#: Ce qui ressemble à un namespace d'URL mais désigne un MODÈLE DU CATALOGUE — et ne se
#: substitue donc JAMAIS. ⚠ Défaut MESURÉ le 2026-09-19, révélé par le stage `suite` : la règle
#: « namespaces d'URL » (`'composer:`) attrapait aussi les clés de catalogue, et les jumelles
#: cherchaient leur modèle sous une clé FANTÔME (`composer_01:minimax-music3`, jamais catalogué)
#: tout en enregistrant leurs statistiques de runtime dessous. Les deux tests rouges de
#: `composer_01` n'étaient pas faux : ils étaient le MESSAGER.
#:
#: ⭐ LE PRINCIPE : **une jumelle partage les MODÈLES de sa source.** Elle a ses propres tables
#: (`app_label`, `related_name`, ses URL, ses gabarits), mais pas ses propres poids — il n'y a
#: qu'un jeu de fichiers sur le disque, catalogué sous la clé de l'app SOURCE. Substituer la clé
#: fabriquait un second modèle qui n'existe pas.
#:
#: Le motif DISCRIMINANT est mesuré, pas supposé : une clé de catalogue est construite par
#: f-string (`f'composer:{self.model}'` — 5 occurrences dans 2 jumelles) ou écrite en
#: `model_key='composer:…'` (les tests) ; un namespace d'URL est une chaîne CLOSE sans `f`
#: (`'composer:generate'`, `{% url "composer:batch_preview" %}`).
_CATALOG_KEY_PATTERNS = (
    r'f{q}{src}:',            # f-string : `f'composer:{...}'`, `f'imager:img:{...}'`
    r'model_key={q}{src}:',   # clé littérale : `model_key='composer:minimax-music3'`
)


def _rename_text(text: str, src: str, dst: str) -> str:
    """Les 4 familles de renommage — quotes simples ET doubles, ordre du plus spécifique
    au plus général (le `wama.` d'abord, sinon le quoté exact le casserait).

    ⚠ Les clés de CATALOGUE DE MODÈLES sont MASQUÉES avant substitution et rendues après :
    voir `_CATALOG_KEY_PATTERNS` — une jumelle partage les modèles de sa source.
    """
    # Masquage : chaque clé de catalogue devient un jeton que les `replace` ne peuvent pas voir.
    frozen, tokens = text, {}
    for i, raw in enumerate(_CATALOG_KEY_PATTERNS):
        for q in ("'", '"'):
            pattern = raw.format(q=re.escape(q), src=re.escape(src))
            for found in set(re.findall(pattern, frozen)):
                token = f'\x00CATALOGKEY{i}_{len(tokens)}\x00'
                tokens[token] = found
                frozen = frozen.replace(found, token)

    frozen = frozen.replace(f'wama.{src}', f'wama.{dst}')
    for q in ("'", '"'):
        frozen = frozen.replace(f'{q}{src}:', f'{q}{dst}:')    # namespaces d'URL
        frozen = frozen.replace(f'{q}{src}/', f'{q}{dst}/')    # chemins templates/static
        frozen = frozen.replace(f'{q}{src}.', f'{q}{dst}.')    # réfs par app_label ('converter.Model'
                                                               #  des FK sérialisées — facette data S2)
        frozen = re.sub(rf'{q}{re.escape(src)}{q}', f'{q}{dst}{q}', frozen)  # app id exact

    for token, original in tokens.items():                     # démasquage à l'identique
        frozen = frozen.replace(token, original)
    return frozen


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


#: Les fichiers qu'une jumelle doit avoir GÉNÉRÉS pour être convergée (`converge`).
CONVERGENCE_TARGETS = ('params', 'apps', 'urls', 'views', 'templates', 'tasks', 'models')


def parse_test_run(output: str) -> dict:
    """{ran, failures, errors, skipped} lus dans la sortie de `manage.py test`. `ran` vaut None
    quand rien n'a tourné : le code de sortie de `manage.py test` ne le dit pas (il sort à 0
    sans rien lancer), seule la ligne « Ran N tests » le dit."""
    m = re.search(r'^Ran (\d+) tests? in ', output or '', re.M)
    out = {'ran': int(m.group(1)) if m else None, 'failures': 0, 'errors': 0, 'skipped': 0}
    status = re.search(r'^(?:OK|FAILED)(?: \((.*?)\))?\s*$', output or '', re.M)
    if status and status.group(1):
        for key, n in re.findall(r'(failures|errors|skipped)=(\d+)', status.group(1)):
            out[key] = int(n)
    return out


def _module_level_statements(body):
    """Les instructions exécutées AU NIVEAU DU MODULE, blocs compris : un nom posé dans un
    `try:`/`if`/`with` de tête est exposé comme un autre (`MODELS_ROOT` de l'anonymizer, posé
    dans un `try/except ImportError` — faux « absent » mesuré le 2026-10-07). On ne descend
    jamais dans une fonction ni une classe : leurs noms sont locaux."""
    import ast
    for n in body:
        yield n
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        for champ in ('body', 'orelse', 'finalbody'):
            yield from _module_level_statements(getattr(n, champ, None) or [])
        for h in getattr(n, 'handlers', None) or []:
            yield from _module_level_statements(h.body)


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
        for n in _module_level_statements(arbre.body):
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
        # Les tests COPIÉS de l'original ne sont pas du code d'exécution : ils visent la glu par
        # ses noms privés, et ils mesurent la convergence (`converge`), pas une substitution.
        if is_test_module(p.relative_to(base).parts):
            continue
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
            parent = '' if mod in ('__init__', '') else f'{mod}.'
            for a in n.names:
                # `from wama.<jumelle> import tasks` importe un SOUS-MODULE, pas un symbole
                # de `__init__` (faux positif mesuré sur anonymizer_01, 2026-10-07).
                sous_module = f'{parent}{a.name}'
                if sous_module in exposes or f'{sous_module}.__init__' in exposes:
                    continue
                if a.name != '*' and a.name not in exposes[cle]:
                    manquants.append(
                        f"{p.relative_to(base).as_posix()} : "
                        f"from {'.' * n.level}{n.module or ''} import {a.name} — absent de {cle}")
    return manquants


def _class_members(class_node) -> set:
    """Noms qu'une classe de modèle DÉFINIT dans son corps : méthodes, properties, attributs
    de classe et champs. `Meta` et les dunders n'en sont pas (aucun lecteur ne les cite)."""
    import ast
    names = set()
    for n in class_node.body:
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            names.add(n.name)
        elif isinstance(n, ast.Assign):
            names.update(t.id for t in n.targets if isinstance(t, ast.Name))
        elif isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name):
            names.add(n.target.id)
    return {x for x in names if not (x.startswith('__') and x.endswith('__'))}


def _inherited_members(tree) -> set:
    """Ce que les classes d'un `models.py` HÉRITENT : `models.Model` et chaque base importée
    (les mixins de `wama.common.models`), résolues par leur import réel — un membre que le
    généré tient de son mixin n'est pas perdu."""
    import ast
    import importlib
    from django.db import models as dj_models
    inherited = set(dir(dj_models.Model))
    imported = {}
    for n in tree.body:
        if isinstance(n, ast.ImportFrom) and n.module and not n.level:
            for a in n.names:
                imported[a.asname or a.name] = (n.module, a.name)
    for n in tree.body:
        if not isinstance(n, ast.ClassDef):
            continue
        for b in n.bases:
            if isinstance(b, ast.Name) and b.id in imported:
                mod, name = imported[b.id]
                try:
                    inherited.update(dir(getattr(importlib.import_module(mod), name)))
                except Exception:
                    continue
    return inherited


def _lost_model_members_read(label: str) -> list:
    """Juge GÉNÉRIQUE : un membre de modèle que le `models.py` COPIÉ portait, que le GÉNÉRÉ
    n'a plus, et qu'un autre fichier de la jumelle LIT encore (2026-10-07).

    Classe du défaut : la glu d'un modèle (properties, méthodes, constantes de classe) n'est
    pas dans la facette `data` — le générateur ne l'émet pas, c'est le trou de la marche B.
    Mesuré sur `converter_02` : `models` généré « tenait » (check, smokes de page et de card
    verts) pendant que le `tasks.py` et le `utils/cross_app.py` copiés lisaient
    `job.options`, `job.cross_app_options` et `job.CHAMPS_CROSS_APP` — AttributeError au
    premier lancement, invisible de tout juge qui ne lance pas de tâche. Le juge des imports
    ne le voit pas : un membre de modèle se LIT, il ne s'importe pas.

    Le receveur d'un attribut n'est pas typé : on ne retient comme perdu qu'un nom absent de
    TOUTES les classes générées, de leurs bases, et des attributs que les vues posent par
    leur nom (`_set_unless_property(item, 'gear_data', …)`, `setattr`) — un nom encore
    porté ailleurs ne lève pas. Les gabarits sont lus dans leurs balises `{{ }}`/`{% %}`
    seulement (le JS inline a ses propres `.options`). Rend `fichier:ligne .nom`.
    """
    import ast
    import re
    base = WAMA_DIR / label
    current, temoin = base / 'models.py', base / 'models.py.temoin'
    if not (current.is_file() and temoin.is_file()):
        return []
    try:
        gen_tree = ast.parse(current.read_text(encoding='utf-8'))
        old_tree = ast.parse(temoin.read_text(encoding='utf-8'))
    except SyntaxError:
        return []                                         # un autre juge (compile) le dit
    gen_classes = {n.name: _class_members(n) for n in gen_tree.body if isinstance(n, ast.ClassDef)}
    still_held = set().union(*gen_classes.values()) if gen_classes else set()
    still_held |= _inherited_members(gen_tree)
    lost = set()
    for n in old_tree.body:
        if isinstance(n, ast.ClassDef) and n.name in gen_classes:
            lost |= _class_members(n) - gen_classes[n.name]
    lost -= still_held
    if not lost:
        return []

    readers = [p for p in base.rglob('*.py')
               if 'migrations' not in p.parts and p.name != 'models.py'
               and not is_test_module(p.relative_to(base).parts)]   # cf. `converge`
    trees = {}
    for p in readers:
        try:
            trees[p] = ast.parse(p.read_text(encoding='utf-8'))
        except SyntaxError:
            continue
    # Attributs posés PAR LEUR NOM sur l'élément (vues générées : `_set_unless_property`).
    for tree in trees.values():
        for n in ast.walk(tree):
            if (isinstance(n, ast.Call) and len(n.args) >= 2
                    and isinstance(n.args[1], ast.Constant) and isinstance(n.args[1].value, str)
                    and getattr(n.func, 'id', getattr(n.func, 'attr', '')) in
                    ('setattr', '_set_unless_property')):
                lost.discard(n.args[1].value)
    if not lost:
        return []

    found = []
    for p, tree in trees.items():
        for n in ast.walk(tree):
            if isinstance(n, ast.Attribute) and n.attr in lost:
                found.append(f'{p.relative_to(base).as_posix()}:{n.lineno} .{n.attr}')
    tag = re.compile(r'\{\{(.*?)\}\}|\{%(.*?)%\}', re.S)
    attr = re.compile(r'\.(' + '|'.join(sorted(map(re.escape, lost))) + r')\b')
    templates = (sorted((base / 'templates').rglob('*.html'))
                 if (base / 'templates').is_dir() else [])
    # Un gabarit COPIÉ que plus rien ne rend (vues et index générés en citent d'autres) n'est
    # pas un lecteur : on ne lit que ceux qu'un fichier VIVANT cite par `<label>/<nom>`.
    living = '\n'.join(p.read_text(encoding='utf-8', errors='replace')
                       for p in list(trees) + templates)
    for p in templates:
        if f'{label}/{p.name}' not in living:
            continue
        text = p.read_text(encoding='utf-8', errors='replace')
        for m in tag.finditer(text):
            for a in attr.finditer(m.group(1) or m.group(2) or ''):
                line = text.count('\n', 0, m.start()) + 1
                found.append(f'{p.relative_to(base).as_posix()}:{line} .{a.group(1)}')
    return sorted(set(found))


def _superseded_task_modules(manifest: dict, fname: str = 'tasks.py') -> list:
    """Modules de tâches COPIÉS que le `tasks.py` GÉNÉRÉ remplace.

    Le manifeste déclare où vit chaque tâche de l'app (`processing.tasks[].file`) : quatre apps
    la logent dans `workers.py`, et `wama/celery.py` autodécouvre LES DEUX noms (`tasks` et
    `workers`). Une jumelle qui garde sa copie de `workers.py` à côté du `tasks.py` généré
    enregistre donc la MÊME tâche deux fois — et sa copie importe des symboles des vues
    COPIÉES (`detect_type_from_extension`) que les vues GÉNÉRÉES n'exposent pas. Mesuré le
    2026-09-22 sur `describer_01` : la substitution de `views` était refusée pour un import
    d'un module que plus rien n'appelait. Porter, c'est REMPLACER : le généré retire la copie.
    """
    proc = (manifest.get('body') or {}).get('processing') or {}
    seen, out = set(), []
    for t in (proc.get('tasks') or []):
        f = str((t or {}).get('file') or '').strip()
        if f and f != fname and f.endswith('.py') and f not in seen:
            seen.add(f)
            out.append(f)
    return out


def _withdraw_modules(label: str, files: list) -> list:
    """Retire de la jumelle les modules `files` (copies remplacées), témoin `.temoin`
    préservé une fois — le geste inverse est `_restore_retired_modules`. Rend les retirés."""
    withdrawn = []
    for f in files:
        p = WAMA_DIR / label / f
        if not p.is_file():
            continue
        t = p.with_name(p.name + '.temoin')
        if not t.exists():
            shutil.copy2(p, t)
        p.unlink()
        withdrawn.append(f)
    return withdrawn


def _restore_retired_modules(label: str, files: list) -> list:
    """Ramène les modules retirés par `_retire_modules` depuis leur témoin. Rend les restaurés."""
    restaures = []
    for f in files:
        p = WAMA_DIR / label / f
        t = p.with_name(p.name + '.temoin')
        if t.exists() and not p.exists():
            shutil.copy2(t, p)
            restaures.append(f)
    return restaures


def _last_cause(stdout: str, stderr: str, width: int = 200) -> str:
    """La CAUSE d'un sous-process en échec : sa dernière ligne utile, avertissements de
    bibliothèques écartés — jamais les premiers caractères du flux."""
    lines = [l.strip() for l in ((stdout or '') + '\n' + (stderr or '')).splitlines()
             if l.strip() and 'Warning' not in l and 'import pynvml' not in l]
    return (lines[-1] if lines else '')[-width:]


def _save_entry(entry: dict) -> None:
    """Réécrit le registre en ne portant que L'ENTRÉE de cette jumelle, relue à l'instant.

    Une substitution dure plusieurs minutes (check + smokes en sous-process) et tenait la
    liste ENTIÈRE chargée à son début : deux chaînes lancées en parallèle sur deux jumelles
    se sont écrasées (2026-09-22 — le `views: ok` de `describer_01` remplacé par la copie
    périmée que la chaîne `composer_01` avait relue avant lui ; disque généré, registre
    « revert »). Le registre est partagé par le DÉPÔT, pas par la chaîne : on n'y écrit que
    ce qu'on a mesuré.
    """
    current = load_registry()
    label = entry.get('label')
    if any(e.get('label') == label for e in current):
        out = [entry if e.get('label') == label else e for e in current]
    else:
        out = current + [entry]
    save_registry(out)


def _drop_entry(label: str) -> None:
    """Retire L'ENTRÉE `label` du registre RELU à l'instant — le pendant de `_save_entry`.

    `remove` chargeait la liste à son début, passait des minutes dans `migrate zero`, puis la
    réécrivait entière : les jumelles créées entre-temps par une autre chaîne disparaissaient
    du registre, paquet et tables restant sur disque (2026-10-07 : `anonymizer_01` et
    `reader_01`, effacées par le retrait concurrent de `describer_01`).
    """
    save_registry([e for e in load_registry() if e.get('label') != label])


def _manage(args: list, env: dict = None) -> subprocess.CompletedProcess:
    """manage.py en SOUS-PROCESS FRAIS : le boot relit sandbox_apps.json — le process
    courant, lui, ne connaît pas (encore/plus) la jumelle (même principe que app_regen_check).
    `env` : variables AJOUTÉES à l'environnement du sous-process (la base de test, au retrait)."""
    return subprocess.run([sys.executable, str(BASE_DIR / 'manage.py'), *args],
                          capture_output=True, text=True, cwd=str(BASE_DIR),
                          env={**os.environ, **env} if env else None)


def _test_database_name() -> str:
    """Le nom de la base de TEST (celle que `manage.py test --keepdb` conserve d'un run à l'autre)
    — celui que Django calcule lui-même (`TEST.NAME`, sinon `test_<NAME>`)."""
    from django.db import connection
    return connection.creation._get_test_db_name()


def replace_glue_hole(source: str, function: str, code: str) -> str:
    """`source` où la fonction `function` — encore un TROU DE GLU — est remplacée par `code`.
    Lève `ValueError` si la fonction est absente, si elle n'est plus un trou (on n'écrase JAMAIS
    une glu écrite), ou si le résultat ne compile pas. Pure : aucun fichier touché."""
    import ast
    target = next((n for n in ast.parse(source).body
                   if isinstance(n, ast.FunctionDef) and n.name == function), None)
    if target is None:
        raise ValueError(f'{function} absente du fichier.')
    lines = source.splitlines(keepends=True)
    if 'TROU DE GLU' not in ''.join(lines[target.lineno - 1:target.end_lineno]):
        raise ValueError(f"{function} n'est plus un trou de glu : rien n'est écrasé.")
    new_source = (''.join(lines[:target.lineno - 1]) + code.rstrip('\n') + '\n'
                  + ''.join(lines[target.end_lineno:]))
    try:
        compile(new_source, 'tasks.py', 'exec')
    except SyntaxError as exc:
        raise ValueError(f'Le fichier résultant ne compile pas : {exc}')
    return new_source


def _smoke_page(label: str) -> subprocess.CompletedProcess:
    """La page de la jumelle répond-elle 200 ? Sous-process frais (le boot relit le registre).
    rc 0 = 200, rc 1 = autre statut ou exception."""
    return subprocess.run(
        [sys.executable, '-c',
         "import os,django;os.environ.setdefault('DJANGO_SETTINGS_MODULE','wama.settings');"
         "django.setup();from django.test import Client;"
         f"r=Client().get('/{label}/',follow=True);print(r.status_code);"
         "raise SystemExit(0 if r.status_code==200 else 1)"],
        capture_output=True, text=True, cwd=str(BASE_DIR))


def _smoke_populated_queue(label: str, item_model: str, check_card: bool) \
        -> subprocess.CompletedProcess:
    """Smoke « file HABITÉE » : un élément témoin créé, la page rendue (et la card seule si
    `check_card`), le témoin supprimé. rc 0 = rendu 200, rc 1 = un rendu lève ou n'est pas 200,
    rc 2 = témoin INCRÉABLE (contraintes propres à l'app — non mesuré, jamais bloquant)."""
    return subprocess.run(
        [sys.executable, '-c',
         "import os,django;os.environ.setdefault('DJANGO_SETTINGS_MODULE','wama.settings');"
         "django.setup();from django.apps import apps;from django.test import Client;"
         "from wama.common.services.nightly_tests import get_test_dev_user;"
         f"M=apps.get_model('{label}','{item_model}');u=get_test_dev_user();\n"
         "try:\n    it=M.objects.create(user=u)\n"
         "except Exception as e:\n    print('temoin increable:',e);raise SystemExit(2)\n"
         "try:\n    c=Client();c.force_login(u);r=c.get('" + f'/{label}/' + "',follow=True)\n"
         "    print(r.status_code)\n"
         # La card SEULE aussi (`card_html`) : des vues GÉNÉRÉES rendent le partial généré
         # `_generic_card.html`, que des templates COPIÉS n'ont pas — page 200, mais 🗑/⚙/↻
         # (qui redemandent la card) en 500. Mesuré sur composer_01 le 2026-09-22 par le
         # contrat générique de suppression, invisible du smoke de page. Route absente
         # (app sans card_html) → non mesuré, jamais bloquant.
         + ("    from django.urls import reverse, NoReverseMatch\n"
            "    try:\n        url=reverse('" + label + ":card_html', args=[it.id])\n"
            "    except NoReverseMatch:\n        url=None\n"
            "    if url:\n        r2=c.get(url)\n        print('card_html', r2.status_code)\n"
            "        r=r2 if r2.status_code!=200 else r\n" if check_card else '') +
         "finally:\n    it.delete()\n"
         "raise SystemExit(0 if r.status_code==200 else 1)"],
        capture_output=True, text=True, cwd=str(BASE_DIR))


class Command(BaseCommand):
    help = "Bac à sable d'apps : create <app> / remove <app_NN> / list (route §10.3 marche S)"
    # PAS de check système au démarrage : une jumelle CASSÉE (enregistrée, modèle refusé)
    # bloquait la commande entière — `remove` compris, donc plus aucun moyen de la retirer (vécu le
    # 2026-09-30 sur la 1ʳᵉ app de zéro). Les juges de la commande lancent leur propre
    # `manage.py check` en sous-processus, là où il mesure quelque chose.
    requires_system_checks = []

    def add_arguments(self, parser):
        parser.add_argument('action', choices=['create', 'remove', 'list', 'substitute', 'revert',
                                               'glue', 'converge'])
        parser.add_argument('app', nargs='?', help='app source (create) ou label jumeau (remove/substitute)')
        # Options et arguments en ANGLAIS (AGENTS.md, décision du 2026-09-14 : une option de ligne
        # de commande est du code). Renommés le 2026-10-01 : `cible` → `target`, `--proprietaire`
        # → `--owner` (relevé par Fabien sur la page du Writer).
        parser.add_argument('target', nargs='?',
                            help=f"substitute/revert : {sorted(_SUBSTITUTABLE)} — fichier à passer "
                                 "en GÉNÉRÉ ; glue : sortie du rôle codegen à appliquer")
        parser.add_argument('--from-manifest', default='',
                            help="create : crée l'app DE ZÉRO depuis un manifeste `app` FICHIER "
                                 "(ex. manifests/app_drafts/writer.json) — sans app source "
                                 "(route « app de zéro », WAMA_APP_GENERATION_ROUTE §10.5)")
        parser.add_argument('--owner', default='',
                            help="create : username du CRÉATEUR de la jumelle (visibilité "
                                 "« créateur + dev + admin », demande Fabien 03/09) ; "
                                 "vide = jumelle d'opérateur, dev/admin seuls ; glue : qui applique")

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

        if action == 'create' and opts.get('from_manifest'):
            self._create_from_manifest(opts['from_manifest'],
                                       owner=opts.get('owner') or '')
            return

        app = opts.get('app')
        if not app:
            raise CommandError(f"app_sandbox {action} exige un nom d'app.")

        if action == 'glue':
            self._apply_glue(app, opts.get('target'), applied_by=opts.get('owner') or '')
        elif action == 'create':
            self._create(app, owner=opts.get('owner') or '')
        elif action == 'substitute':
            self._substitute(app, opts.get('target'))
        elif action == 'revert':
            self._revert(app, opts.get('target'))
        elif action == 'converge':
            self._converge(app)
        else:
            self._remove(app)

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

        _save_entry({'label': label, 'generated_from': src,
                     'created': datetime.now(timezone.utc).isoformat(timespec='seconds'),
                     'created_by': owner,
                     'stage': 'S1-temoin'})

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
                    f'`app_sandbox remove {label}` pour tout retirer.'))
                return

        self.stdout.write(self.style.SUCCESS(
            f'Jumelle {label} prête : /{label}/ (dev-only). '
            '⚠ Redémarrer gunicorn/workers pour la servir.'))

    # ── create DE ZÉRO depuis un manifeste fichier (route §10.5) ──────────────
    def _create_from_manifest(self, path: str, owner: str = ''):
        """Crée une app DE ZÉRO, sans app source : tout le code vient des gabarits appliqués au
        manifeste. Deux temps, parce que les vues se génèrent depuis les MODÈLES :
          1. apps / models / params / tasks → makemigrations + migrate ;
          2. les modèles ainsi créés sont INTROSPECTÉS (`_data`, le même extracteur que pour
             une app existante) → la facette `data` que `views_gen` exige → urls / views /
             templates, puis check et smokes.
        L'app naît dans le BAC À SABLE (dev seulement) sous le label `<clé>_NN` ; ce qui reste
        à écrire est marqué `TROU DE GLU` — le terrain du rôle `codegen`, jamais rempli ici.
        Un échec laisse l'app enregistrée pour diagnostic (`app_sandbox remove <label>`)."""
        import importlib
        import json

        from wama.common.app_registry import APP_CATALOG
        from wama.common.manifests.builtin.app import (_capabilities_target, _identity_target,
                                                       _ports_target)
        from wama.common.manifests.kinds import MANIFEST_KINDS

        manifest_path = Path(path) if Path(path).is_absolute() else BASE_DIR / path
        try:
            manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
        except (OSError, ValueError) as exc:
            raise CommandError(f'Manifeste illisible : {manifest_path} ({exc})')
        if manifest.get('manifest_kind') != 'app':
            raise CommandError("Seul un manifeste de kind `app` crée une app.")
        errors = MANIFEST_KINDS['app'].validate(manifest.get('body') or {})
        if errors:
            raise CommandError('Manifeste invalide : ' + ' ; '.join(errors[:5]))
        key = manifest.get('key') or ''
        if not re.fullmatch(r'[a-z_]+', key):
            raise CommandError(f'Clé d\'app invalide : {key!r} (underscore_case, AGENTS.md).')
        if key in APP_CATALOG or (WAMA_DIR / key).exists():
            raise CommandError(f'{key} existe déjà : on ne crée DE ZÉRO qu\'une app nouvelle '
                               f'(pour une app existante : `app_sandbox create {key}`).')

        label = _next_label(key)
        pkg = WAMA_DIR / label
        self.stdout.write(f'App DE ZÉRO : {manifest_path.name} → wama/{label}')

        def render(targets, payload):
            """Rend les cibles ; un refus arrête tout AVANT d'écrire."""
            out = []
            for c in targets:
                fname_c, mod_path, fn_name = _SUBSTITUTABLE[c]
                rendered, raison = getattr(importlib.import_module(mod_path), fn_name)(payload)
                if rendered is None:
                    raise CommandError(f'Gabarit {c} : rien à générer — {raison}')
                out.append((c, fname_c, rendered))
            return out

        holes = {}

        def write(rendered_list):
            for c, fname_c, rendered in rendered_list:
                files = rendered if isinstance(rendered, dict) else {fname_c: rendered}
                for name, content in files.items():
                    text = _rename_text(content, key, label)
                    if c == 'models':
                        text = _patch_related_names(text, label)
                    dest = (pkg / 'templates' / label / name if isinstance(rendered, dict)
                            else pkg / name)
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    dest.write_text(text, encoding='utf-8')
                    holes[str(dest.relative_to(pkg))] = text.count('TROU DE GLU')
                    self.stdout.write(f'  {dest.relative_to(pkg)} ← GÉNÉRÉ '
                                      f'({len(text.splitlines())} lignes, '
                                      f'{holes[str(dest.relative_to(pkg))]} trou(s) de glu)')

        # 1. Premier temps : ce qui ne dépend que du manifeste. Le pipeline (une app à plusieurs
        # process) se lit par la CLÉ, comme au corpus (`pipeline_decl`) : `function_specs.py`
        # n'est rendu que s'il est déclaré — sans lui, une app à un process, le cas normal.
        from wama.common.manifests.codegen.pipeline_decl import declared_pipeline
        targets = ['apps', 'models', 'params', 'tasks']
        if declared_pipeline(key)[0]:
            targets.append('function_specs')
        first = render(targets, manifest)
        (pkg / 'migrations').mkdir(parents=True, exist_ok=True)
        (pkg / '__init__.py').write_text('', encoding='utf-8')
        (pkg / 'migrations' / '__init__.py').write_text('', encoding='utf-8')
        write(first)

        # L'entrée de catalogue est calculée ICI (Django chargé) et STOCKÉE au registre :
        # `inject_sandbox_catalog` la relit au boot sans rien importer (sandbox.py reste pur).
        catalog = {**_identity_target(manifest), **_ports_target(manifest),
                   **_capabilities_target(manifest)}
        catalog['url_name'] = f"{label}:{(catalog.get('url_name') or 'x:index').split(':', 1)[-1]}"
        try:
            rel_manifest = manifest_path.relative_to(BASE_DIR).as_posix()
        except ValueError:
            rel_manifest = str(manifest_path)
        # Les DÉCLARATIONS que les accesseurs des registres indexés par nom d'app relisent pour une
        # app sans source (`sandbox.born_declaration`) : modes (→ ports dérivés, card d'entrée v4)
        # et cibles de prompts (→ pipeline de prompts, fichiers de référence).
        declarations = {f: (manifest.get('body') or {}).get(f)
                        for f in ('modes', 'prompts') if (manifest.get('body') or {}).get(f)}
        entry = {'label': label, 'generated_from': '', 'from_manifest': rel_manifest,
                 'catalog': catalog, 'declarations': declarations,
                 'created': datetime.now(timezone.utc).isoformat(timespec='seconds'),
                 'created_by': owner, 'stage': 'S0-de-zero'}
        _save_entry(entry)

        def fail(message):
            entry['stage'] = 'S0-de-zero-echec'
            entry['failure'] = message
            _save_entry(entry)
            self.stderr.write(self.style.ERROR(
                f'  ÉCHEC — {message}. L\'app reste enregistrée pour diagnostic ; '
                f'`app_sandbox remove {label}` pour tout retirer.'))

        for step in (['makemigrations', label], ['migrate', label]):
            r = _manage(step)
            self.stdout.write(f"  manage.py {' '.join(step)} → rc={r.returncode}")
            if r.returncode != 0:
                return fail(f"{' '.join(step)} : {_last_cause(r.stdout, r.stderr)}")

        # 2. Deuxième temps : introspection des modèles créés → facette `data` → vues.
        r = _manage(['shell', '-c',
                     'import json;from wama.common.manifests.builtin.app import _data;'
                     f"print('DATA=' + json.dumps(_data('{label}')))"])
        line = next((ln for ln in (r.stdout or '').splitlines() if ln.startswith('DATA=')), '')
        data = json.loads(line[5:]) if line else None
        if not (data or {}).get('models'):
            return fail(f'introspection des modèles de {label} vide '
                        f'({_last_cause(r.stdout, r.stderr)})')
        second_manifest = json.loads(json.dumps(manifest))
        second_manifest['body']['data'] = data
        try:
            second = render(['urls', 'views', 'templates', 'base'], second_manifest)
        except CommandError as exc:
            return fail(str(exc))
        write(second)

        # 3. Juges : cohérence de paquet, check, page, file habitée (+ card seule).
        unresolved = _imports_intra_paquet_non_resolus(label)
        if unresolved:
            return fail('symboles intra-paquet NON RÉSOLUS : ' + ' ; '.join(unresolved[:4]))
        r = _manage(['check'])
        if r.returncode != 0:
            return fail(f'manage.py check KO ({_last_cause(r.stdout, r.stderr)})')
        smoke = _smoke_page(label)
        if smoke.returncode != 0:
            return fail(f'smoke /{label}/ KO ({_last_cause(smoke.stdout, smoke.stderr)})')
        item_model = ((manifest.get('body') or {}).get('processing') or {}).get('item_model')
        details = []
        if item_model:
            populated = _smoke_populated_queue(label, item_model, check_card=True)
            if populated.returncode == 1:
                return fail('smoke file HABITÉE KO — le rendu de card lève '
                            f'({_last_cause(populated.stdout, populated.stderr)})')
            if populated.returncode == 2:
                details.append('file habitée NON MESURÉE (témoin incréable)')

        entry['stage'] = 'S2-de-zero'
        entry['glue_holes'] = holes
        _save_entry(entry)
        total = sum(holes.values())
        self.stdout.write(self.style.SUCCESS(
            f'App {label} créée DE ZÉRO : /{label}/ (dev-only) — {total} trou(s) de glu à '
            f'confier au rôle codegen{" ; " + " ; ".join(details) if details else ""}. '
            '⚠ Redémarrer gunicorn/workers pour la servir.'))

    # ── glue : APPLIQUER une glu validée (sortie du rôle `codegen`) ────────────
    def _apply_glue(self, label: str, output_path: str, applied_by: str = ''):
        """Remplace le TROU DE GLU d'une fonction de `tasks.py` d'une app du BAC À SABLE par la
        glu qu'un rôle `codegen` a proposée (`wama-dev-ai/outputs/codegen_*.json`).

        Le geste « Valider → appliquer » existait pour les modèles et les backends
        (`backend_proposals.apply`), pas pour une glu d'app : la chaîne « app de zéro » s'arrêtait
        à une sortie qu'il fallait coller à la main (2026-10-01). Gardes : app du bac à sable
        SEULEMENT (jamais une app réelle) ; sortie encore `PENDING_HUMAN_VALIDATION` ; fonction
        visée encore marquée TROU DE GLU (jamais écraser une glu déjà écrite) ; mêmes renommages
        que la génération (`<clé>` → `<label>`) ; le fichier résultant doit COMPILER. La sortie
        passe `APPLIED` (qui, quand, où) — convention de `backend_proposals`.
        Appliquer est une DÉCISION HUMAINE : la commande la sert, elle ne la prend pas."""
        import json

        entry = next((e for e in load_registry() if e.get('label') == label), None)
        if not entry:
            raise CommandError(f'{label} n\'est pas une app du bac à sable.')
        if not output_path:
            raise CommandError('app_sandbox glue <label> <sortie codegen .json>')
        out_file = Path(output_path) if Path(output_path).is_absolute() else BASE_DIR / output_path
        data = json.loads(out_file.read_text(encoding='utf-8'))
        if data.get('role') != 'codegen':
            raise CommandError('Sortie qui n\'est pas celle du rôle codegen.')
        # APPLIED est admis : RÉ-appliquer une glu déjà validée sur une app RÉGÉNÉRÉE (ses trous
        # sont revenus) ne redemande pas la décision — elle a eu lieu ; chaque application est tracée.
        if data.get('status') not in ('PENDING_HUMAN_VALIDATION', 'APPLIED'):
            raise CommandError(f"Sortie {data.get('status')} : elle ne s'applique pas.")
        if data.get('app') != label:
            raise CommandError(f"Glu écrite pour {data.get('app')}, pas pour {label}.")
        function = data.get('function') or ''
        key = LABEL_RE.match(label).group('base')
        code = _rename_text(data.get('code') or '', key, label)

        tasks_path = WAMA_DIR / label / 'tasks.py'
        try:
            new_source = replace_glue_hole(tasks_path.read_text(encoding='utf-8'), function, code)
        except ValueError as exc:
            raise CommandError(str(exc))
        tasks_path.write_text(new_source, encoding='utf-8')
        now = datetime.now(timezone.utc).isoformat(timespec='seconds')
        data.setdefault('applications', []).append({'by': applied_by or None, 'at': now})
        data.update(status='APPLIED', applied_by=applied_by or None, applied_at=now,
                    written=f'wama/{label}/tasks.py::{function}')
        out_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
        self.stdout.write(self.style.SUCCESS(
            f'{function} ← glu {data.get("model")} appliquée dans wama/{label}/tasks.py. '
            '⚠ Redémarrer les workers pour qu\'ils la chargent.'))

    # ── substitute (étape S2) ────────────────────────────────────────────────
    def _substitute(self, label: str, requested: str):
        """Remplace UN fichier copié de la jumelle par sa version GÉNÉRÉE (gabarit codegen
        sur le manifeste extrait LIVE de la SOURCE), puis re-mesure. Le fichier copié est
        préservé en `.temoin` (= la référence du diff copie↔généré). ÉCHEC → auto-revert :
        jamais une jumelle morte. Verdicts journalisés au registre (stage S2)."""
        import importlib

        # PLUSIEURS cibles d'un coup (`urls+views`, 2026-09-24) : quand la SOURCE renomme une
        # route, `urls` généré importe une vue que les vues de la jumelle n'ont pas encore, et
        # `views` généré retire le nom que ses urls importent — chacune seule est revertée
        # (vécu sur converter_01 : `update_job` → `update_settings`, smoke 404 dans les deux
        # ordres, l'include de la jumelle tombant à l'import). Ensemble : générées, mesurées et
        # revertées comme UNE substitution.
        targets = [c for c in (requested or '').split('+') if c]
        unknown = [c for c in targets if c not in _SUBSTITUTABLE]
        if not targets or unknown:
            raise CommandError(f'Cible inconnue : {requested} (attendu {sorted(_SUBSTITUTABLE)}, '
                               'ou plusieurs jointes par « + »).')
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
        if 'templates' in targets and 'views' not in targets:
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
        renders = []
        for c in targets:            # tout RENDRE avant d'écrire : un refus n'écrit rien
            fname_c, mod_path, fn_name = _SUBSTITUTABLE[c]
            rendered, raison = getattr(importlib.import_module(mod_path), fn_name)(manifest)
            if rendered is None:
                raise CommandError(f'Gabarit {c} : rien à générer — {raison}')
            renders.append((c, fname_c, rendered))
        fname = '+'.join(f for _c, f, _r in renders)

        # 2. SUFFIXAGE identique à la copie (la génération vise `converter`, la jumelle
        #    parle `converter_01`) + patch related_name pour models. Un gabarit peut rendre
        #    un DICT nom→contenu (multi-fichiers, ex. templates : index + card générique).
        temoin = None
        ecrits = []
        for c, fname_c, rendered in renders:
            fichiers = rendered if isinstance(rendered, dict) else {fname_c: rendered}
            for nom, contenu in fichiers.items():
                texte = _rename_text(contenu, src, label)
                if c == 'models':
                    texte = _patch_related_names(texte, label)
                if isinstance(rendered, dict):
                    dest_path = WAMA_DIR / label / 'templates' / label / nom
                else:
                    dest_path = WAMA_DIR / label / nom
                dest_path.parent.mkdir(parents=True, exist_ok=True)
                t = dest_path.with_name(dest_path.name + '.temoin')
                if dest_path.exists() and not t.exists():
                    shutil.copy2(dest_path, t)   # référence du diff, préservée UNE fois
                if temoin is None and t.exists():
                    temoin, target, text = t, dest_path, texte   # diff/revert = 1er fichier témoin
                dest_path.write_text(texte, encoding='utf-8')
                ecrits.append((dest_path, t))
                self.stdout.write(f'{dest_path.relative_to(WAMA_DIR / label)} ← GÉNÉRÉ '
                                  f'({len(texte.splitlines())} lignes)')
        if temoin is None:                     # aucun fichier préexistant (tout est neuf)
            target, text = ecrits[0][0], ecrits[0][0].read_text(encoding='utf-8')

        # 3. RE-MESURE : cohérence de paquet + check + (models → makemigrations) + smoke page.
        verdict, details = 'ok', []
        # `tasks` généré REMPLACE le module de tâches copié que le manifeste déclare sous un
        # autre nom (`workers.py`) — sinon deux enregistrements Celery de la même tâche, et un
        # import mort vers les vues copiées (cf. `_superseded_task_modules`). Restauré au revert.
        withdrawn = (_withdraw_modules(label, _superseded_task_modules(
                         manifest, _SUBSTITUTABLE['tasks'][0]))
                     if 'tasks' in targets else [])
        if withdrawn:
            details.append(f'module de tâches COPIÉ remplacé par le généré, retiré : {withdrawn}')
        # Juge GÉNÉRIQUE avant tout sous-process : chaque symbole intra-paquet importé par
        # les fichiers copiés doit exister chez sa cible (classe du défaut PARAMS, 03/09).
        _non_resolus = _imports_intra_paquet_non_resolus(label)
        if _non_resolus:
            verdict = 'revert'
            details.append('symboles intra-paquet NON RÉSOLUS : '
                           + ' ; '.join(_non_resolus[:4]))
        # Même juge pour la glu d'un modèle : un membre perdu par le `models` généré et encore
        # LU ailleurs — AttributeError au premier lancement, sinon. Posé sur la substitution
        # qui PERD le membre : il juge tout le paquet tel qu'il restera.
        _perdus = _lost_model_members_read(label) if 'models' in targets else []
        if _perdus:
            verdict = 'revert'
            details.append('membres de modèle PERDUS encore lus : ' + ' ; '.join(_perdus[:6]))
        r = _manage(['check'])
        if r.returncode != 0:
            verdict = 'revert'
            details.append('manage.py check KO')
        mig_dir = WAMA_DIR / label / 'migrations'
        mig_avant = {p.name for p in mig_dir.glob('0*.py')}
        if verdict == 'ok' and 'models' in targets:
            r = _manage(['makemigrations', label])
            if r.returncode != 0:
                verdict, details = 'revert', ['makemigrations KO']
            elif 'No changes detected' not in (r.stdout or ''):
                details.append('schéma DIVERGENT (migration créée — champs en écart)')
                r2 = _manage(['migrate', label])
                if r2.returncode != 0:
                    verdict, details = 'revert', ['migrate de l’écart KO']
        if verdict == 'ok':
            smoke = _smoke_page(label)
            if smoke.returncode != 0:
                verdict = 'revert'
                details.append(f"smoke /{label}/ KO ({_last_cause(smoke.stdout, smoke.stderr)})")
        # ── Smoke « file HABITÉE » (mesuré le 2026-09-03, describer_01/params) : une page à
        # file VIDE ne rend AUCUNE card — un symbole de schéma disparu (`PARAMS`) ne levait
        # qu'au rendu d'une card réelle : 200 au juge, ImportError chez l'utilisateur. On
        # crée donc un témoin minimal, on rend la page, on le supprime. Témoin incréable
        # (contraintes NOT NULL propres à l'app) → NON MESURÉ, dit tel quel — jamais bloquant
        # sur l'incréabilité, toujours bloquant sur un rendu qui lève.
        item_model = ((manifest.get('body') or {}).get('processing') or {}).get('item_model')
        # La card SEULE (`card_html`) ne se mesure que quand le COUPLE views↔templates est
        # complet : des vues GÉNÉRÉES rendent le partial généré `_generic_card.html`, que des
        # templates COPIÉS n'ont pas. Au pas `views` (templates encore copiés, ordre
        # recommandé) le juge s'en abstient ; au pas `templates` — ou à un `views` rejoué après
        # — il l'exige. Sans cette règle le couple était un ordre à respecter de mémoire.
        templates_ok = ((entry.get('substituted') or {}).get('templates') or {}).get('verdict') == 'ok'
        check_card = 'templates' in targets or templates_ok
        if verdict == 'ok' and item_model:
            habite = _smoke_populated_queue(label, item_model, check_card)
            if habite.returncode == 1:
                verdict = 'revert'
                # La CAUSE est la dernière ligne de la trace, jamais la première du flux :
                # les 160 premiers caractères de stderr étaient un FutureWarning de torch
                # (mesuré le 2026-09-22 sur describer_01 — verdict illisible).
                details.append('smoke file HABITÉE KO — le rendu de card lève '
                               f"({_last_cause(habite.stdout, habite.stderr)})")
            elif habite.returncode == 2:
                details.append('file habitée NON MESURÉE (témoin incréable — contraintes app)')

        # 4. Diff compact copie↔généré (le DÉTECTEUR : chaque écart est un fait).
        # Un fichier NEUF n'a pas de témoin (`tasks.py` d'une app qui loge ses tâches dans
        # `workers.py` — describer_01, 2026-10-07) : rien à comparer, mais le verdict et le
        # registre doivent suivre. `temoin.exists()` sur None levait APRÈS l'écriture : fichier
        # généré en place, module copié retiré, aucun verdict ni retour au témoin.
        if temoin is not None and temoin.exists():
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
            for _dest_path, _t in ecrits:
                if _t.exists():
                    shutil.copy2(_t, _dest_path)
                else:
                    _dest_path.unlink(missing_ok=True)
            if withdrawn:
                _restore_retired_modules(label, withdrawn)
            # Le COUPLE se défait ensemble : des templates qui échouent laissaient des vues
            # GÉNÉRÉES servir des templates COPIÉS — card_html en 500 (composer_01, 22/09).
            if 'templates' in targets and 'views' not in targets:
                v_path = WAMA_DIR / label / 'views.py'
                v_temoin = v_path.with_name('views.py.temoin')
                if v_temoin.exists() and 'manifest-gen' in v_path.read_text(
                        encoding='utf-8', errors='replace')[:600]:
                    shutil.copy2(v_temoin, v_path)
                    entry.setdefault('substituted', {})['views'] = {
                        'verdict': 'reverted-couple', 'details': ['templates revenus au témoin'],
                        'at': datetime.now(timezone.utc).isoformat(timespec='seconds')}
                    details.append('views.py REVENU au témoin avec les templates (couple)')
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
                f'{requested} : GÉNÉRÉ tient ({" ; ".join(details) or "aucun écart"})'))
        for c in targets:
            entry.setdefault('substituted', {})[c] = {
                'verdict': verdict, 'details': details,
                'at': datetime.now(timezone.utc).isoformat(timespec='seconds')}
        entry['stage'] = ('S2-partiel'
                          if any(v.get('verdict') == 'ok'
                                 for v in entry['substituted'].values()) else entry['stage'])
        _save_entry(entry)

    # ── converge : MESURER la distance jumelle ↔ original ──────────────────────
    def _converge(self, label: str):
        """La jumelle fait-elle ce que fait l'ORIGINAL ? (décision de Fabien, 2026-10-07)

        Deux mesures, rien d'autre : (1) chaque fichier substituable est GÉNÉRÉ et tient (les
        verdicts de `substitute`, relus au registre) ; (2) les tests PROPRES de l'original,
        copiés dans la jumelle, passent CONTRE elle — l'oracle de son comportement spécifique
        (sa glu), que les contrats génériques ne connaissent pas. Convergée = les deux.

        Ces tests ne jugent PAS une substitution (ils visent la glu par ses noms privés) et la
        suite complète les écarte (`runners`) : ils ne servent qu'ici. Une app NOUVELLE, sans
        original, n'a pas cette mesure — elle a les contrats génériques, la batterie nocturne et
        les tests d'usage écrits à sa génération.
        """
        entry = next((e for e in load_registry() if e.get('label') == label), None)
        if not entry:
            raise CommandError(f'{label} absent du registre.')
        subs = entry.get('substituted') or {}
        pending = [t for t in CONVERGENCE_TARGETS if (subs.get(t) or {}).get('verdict') != 'ok']
        self.stdout.write(f'{label} ← {entry.get("generated_from") or "manifeste"} : '
                          f'fichiers encore COPIÉS {pending or "aucun"}')
        r = _manage(['test', f'wama.{label}', '--keepdb'])
        run = parse_test_run((r.stdout or '') + '\n' + (r.stderr or ''))
        if run['ran'] is None:
            self.stdout.write(f'  tests de l\'original : NON MESURÉ ({_last_cause(r.stdout, r.stderr)})')
        else:
            self.stdout.write(f"  tests de l'original contre la jumelle : {run['ran']} lancés, "
                              f"{run['failures']} échec(s), {run['errors']} erreur(s), "
                              f"{run['skipped']} sauté(s)")
        converged = (not pending and bool(run['ran'])
                     and run['failures'] == 0 and run['errors'] == 0)
        entry = next((e for e in load_registry() if e.get('label') == label), entry)
        entry['convergence'] = {
            'copied_targets': pending, 'tests': run, 'converged': converged,
            'at': datetime.now(timezone.utc).isoformat(timespec='seconds')}
        _save_entry(entry)
        style = self.style.SUCCESS if converged else self.style.WARNING
        self.stdout.write(style(f'{label} : {"CONVERGÉE" if converged else "pas encore convergée"}'))

    # ── revert (retour MANUEL au témoin) ─────────────────────────────────────
    def _revert(self, label: str, target: str):
        """Ramène UNE cible substituée à sa copie témoin (`.temoin`) — le geste qu'aucun
        outil n'offrait quand la substitution avait « tenu » au smoke mais cassait à
        l'usage (describer_01, 2026-09-03 : templates générés × views copiées — page 200,
        boutons morts). Fichier GÉNÉRÉ sans témoin (neuf, marqué manifest-gen) → retiré."""
        if target not in _SUBSTITUTABLE:
            raise CommandError(f'Cible inconnue : {target} (attendu {sorted(_SUBSTITUTABLE)}).')
        entries = load_registry()
        entry = next((e for e in entries if e['label'] == label), None)
        if not entry:
            raise CommandError(f'{label} absent du registre.')

        fname = _SUBSTITUTABLE[target][0]
        if target == 'templates':
            candidates = sorted((WAMA_DIR / label / 'templates' / label).glob('*.html'))
        else:
            candidates = [WAMA_DIR / label / fname]
        restored, removed = [], []
        for p in candidates:
            if not p.is_file():
                continue
            t = p.with_name(p.name + '.temoin')
            if t.exists():
                shutil.copy2(t, p)
                restored.append(p.name)
            elif 'manifest-gen' in p.read_text(encoding='utf-8', errors='replace')[:600]:
                p.unlink()
                removed.append(p.name)
        if target == 'tasks':
            # Les modules de tâches COPIÉS que la substitution avait retirés (`workers.py`)
            # reviennent avec elle : leur témoin est le seul `.py.temoin` sans `.py` en face.
            for t in sorted((WAMA_DIR / label).glob('*.py.temoin')):
                p = t.with_name(t.name[:-len('.temoin')])
                if p.name != fname and not p.exists():
                    shutil.copy2(t, p)
                    restored.append(p.name)
        if not restored and not removed:
            raise CommandError(f'{target} : aucun témoin ni fichier généré — rien à ramener.')

        # Smoke : la jumelle revenue doit RENDRE (même juge que la substitution).
        smoke = subprocess.run(
            [sys.executable, '-c',
             "import os,django;os.environ.setdefault('DJANGO_SETTINGS_MODULE','wama.settings');"
             "django.setup();from django.test import Client;"
             f"r=Client().get('/{label}/',follow=True);print(r.status_code);"
             "raise SystemExit(0 if r.status_code==200 else 1)"],
            capture_output=True, text=True, cwd=str(BASE_DIR))
        state = 'OK' if smoke.returncode == 0 else f'KO ({(smoke.stdout or smoke.stderr).strip()[:80]})'

        entry.setdefault('substituted', {})[target] = {
            'verdict': 'reverted-manuel',
            'details': [f'restaurés : {restored}', f'retirés : {removed}', f'smoke {state}'],
            'at': datetime.now(timezone.utc).isoformat(timespec='seconds')}
        _save_entry(entry)
        style = self.style.SUCCESS if smoke.returncode == 0 else self.style.ERROR
        self.stdout.write(style(
            f'{target} REVENU au témoin — restaurés {restored}, retirés {removed}, '
            f'smoke /{label}/ {state}. ⚠ Recharger gunicorn pour servir la copie.'))

    # ── remove ─────────────────────────────────────────────────────────────────
    def _remove(self, label: str):
        if not LABEL_RE.match(label):
            raise CommandError(f'Label jumeau invalide : {label} (attendu <app>_NN).')
        entries = load_registry()
        if label not in {e['label'] for e in entries}:
            raise CommandError(f'{label} absent du registre {REGISTRY_PATH}.')

        # 1. Tables : migrate zero PENDANT que la jumelle est encore enregistrée.
        # --skip-checks : une jumelle CASSÉE (clash de modèles, import raté) bloquerait le
        # system check du sous-process — le retrait doit toujours pouvoir nettoyer (œuf/poule
        # mesuré au pilote : le premier essai raté était indéboulonnable sans ça).
        # Aucune migration écrite (une création qui a échoué AVANT le premier makemigrations —
        # vécu le 2026-09-30 sur la 1ʳᵉ app de zéro, modèle refusé par le check) : aucune table
        # à retirer, et `migrate zero` buterait sur le même check système. Rien à désappliquer.
        has_migrations = any((WAMA_DIR / label / 'migrations').glob('0*.py'))
        r = (_manage(['migrate', label, 'zero', '--skip-checks']) if has_migrations
             else subprocess.CompletedProcess([], 0, '', ''))
        self.stdout.write(f'  manage.py migrate {label} zero → '
                          f'{"rc=%d" % r.returncode if has_migrations else "sans objet (aucune migration)"}')
        if r.returncode != 0:
            for line in (r.stderr or r.stdout).strip().splitlines()[-5:]:
                self.stdout.write(f'    {line}')
            raise CommandError('migrate zero a échoué — rien retiré (relancer après correction).')
        # 1 ter. La base de TEST conservée (`--keepdb`) porte aussi les tables de la jumelle, et
        # sa migration `0001` y reste marquée appliquée : une jumelle RECRÉÉE sous le même label
        # y garderait l'ANCIEN schéma. Mesuré le 2026-10-05 (writer_01 recréé avec `draft_file`) :
        # `file_references` interroge toutes les tables à champ fichier, la colonne manquait, et
        # les tests d'AUTRES apps tombaient en ERROR. Non bloquant : sans base de test, rien à faire.
        if has_migrations:
            # `WAMA_DB_NAME` est la variable que `settings.py` lit pour le nom de la base.
            rt = _manage(['migrate', label, 'zero', '--skip-checks'],
                         env={'WAMA_DB_NAME': _test_database_name()})
            self.stdout.write(f'  base de test ({_test_database_name()}) : migrate {label} zero → '
                              f'{"rc=0" if rt.returncode == 0 else "ignoré (base absente ou refus)"}')

        # 1 bis. Révisions de ses éléments (`common.ItemRevision`, désignées par app + type +
        # numéro) : sans cette purge, la jumelle RECRÉÉE sous le même label repart à l'élément
        # n°1 et hérite de l'historique des anciens — mesuré le 2026-10-01 sur writer_01, un
        # élément neuf portait une « révision 1 » qu'il n'avait jamais produite.
        from wama.common.models import ItemRevision
        purged, _ = ItemRevision.objects.filter(app=label).delete()
        self.stdout.write(f'  révisions de {label} purgées : {purged}')

        # 2. Registre puis package (l'ordre inverse laisserait une entrée orpheline,
        #    inoffensive grâce à la garde sandbox_labels(), mais sale).
        _drop_entry(label)
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
