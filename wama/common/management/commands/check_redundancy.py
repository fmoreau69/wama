"""
check_redundancy — détecte MÉCANIQUEMENT les implémentations locales qui vivent à côté
d'un domicile unique déclaré (ROADMAP §16.9 ②).

La maladie visée n'est pas le code mort : c'est la RECOPIE d'un vocabulaire ou d'une
mécanique dont la source unique existe (schéma d'app, TOOL_REGISTRY, brique commune).
Une recopie diverge toujours en silence — les 6 résidus soldés le 2026-08-02 en sont le
corpus d'acceptation : ce détecteur doit TOUS les retrouver sur le code d'avant correctif
(`--root` sur un arbre reconstruit par `git show <commit>^:<fichier>`).

Classes de détection :
  A — vocabulaire recopié : collection littérale (list/tuple/set/clés de dict « données »)
      recouvrant les noms de params d'une app (`schema_for_app`), les choices d'un param,
      ou les noms d'outils (`TOOL_REGISTRY`).
      → résidus TOOL_DESCRIPTIONS, options converter (views.py), styles describer.
  B — bornes divergentes : clamp `max(a, min(b, x))` (ou miroir) sur une variable homonyme
      d'un param à bornes déclarées, avec (a, b) ≠ (min, max) du schéma.
      → résidu clamp 1–30 de batch_parsers (schéma composer : 10–600).
  C — brique doublée : (i) def privé hors `wama/common/` dont le premier token du nom
      coïncide avec celui d'une brique publique de `common/utils|services` ;
      (ii) fonction hors `param_schema.py` qui recharge elle-même le schéma d'app
      (`import_module` + params_module/params_attr/PARAMS_JSON).
      → résidus `_coerce` et `_params_json` du generic_runner.

Le détecteur est un CONSOMMATEUR des registres (schema_for_app, APP_CATALOG,
TOOL_REGISTRY) : aucun vocabulaire n'est recopié ici — sinon il se signalerait lui-même.

Triage humain : un site LÉGITIME (mapping keyé par le vocabulaire qui porte une info
NOUVELLE, politique d'acceptation volontairement étroite) s'assume par le pragma
`# wama:redondance-ok — <raison>` sur la ligne du littéral/def. Jamais sans raison.

Usage :
    python manage.py check_redundancy                 # arbre courant
    python manage.py check_redundancy --root DIR      # arbre d'acceptation (code pré-fix)
    python manage.py check_redundancy --strict        # code sortie 1 si trouvaille
"""
import ast
import re
from pathlib import Path

from django.core.management.base import BaseCommand

# Dossiers jamais scannés (mêmes exclusions d'esprit que check_docs).
DOSSIERS_EXCLUS = {
    'venv_win', 'venv_linux', 'node_modules', '.git', 'migrations', 'staticfiles',
    'static', 'media', 'logs', 'AI-models', 'docs', 'archive', '__pycache__',
    'wama-dev-ai', 'patches', 'tests',
    'musetalk',   # code vendored (upstream) — ses redondances ne nous appartiennent pas
    'codeformer',  # idem : repo CodeFormer embarqué dans avatarizer (upstream)
}
# Domiciles du vocabulaire : les recopies y sont LÉGITIMES (c'est la source).
# model_config.py / model_registry.py / quality_presets.py : le schéma DÉRIVE ses
# choices de ces catalogues (options_source) — le sens de la copie s'inverse.
# tests.py : un test qui énumère les params exerce le schéma, il ne le double pas.
# admin.py : un list_display énumère les champs du modèle par nature.
# check_redundancy.py : ses motifs de détection contiennent le vocabulaire cherché.
FICHIERS_SOURCE = {'params.py', 'param_schema.py', 'output_formats.py',
                   'model_config.py', 'model_registry.py', 'quality_presets.py',
                   'app_registry.py',   # MEDIA_CATEGORIES/EXTENSIONS : LE domicile des vocabulaires média
                   'app_modes.py',      # les MODES déclarent leurs sous-ensembles de params par nom
                   'tests.py', 'admin.py', 'check_redundancy.py'}
# Assignations autorisées à énumérer les outils (l'infrastructure du registre).
NOMS_REGISTRE_OUTILS = {'TOOL_REGISTRY', 'TOOL_APP_OVERRIDE'}

# Pragma de triage HUMAIN : posé sur la ligne du littéral/def, il assume explicitement
# un câblage déclaratif (mapping keyé par le vocabulaire qui porte une info NOUVELLE,
# politique d'acceptation volontairement plus étroite…). Toujours avec une raison.
PRAGMA = 'wama:redondance-ok'

SEUIL_INTERSECTION = 3      # moins de 3 éléments communs = coïncidence probable
SEUIL_RATIO = 0.5           # la moitié de la collection doit venir du vocabulaire
SEUIL_OUTILS = 5            # les noms d'outils sont plus génériques → seuil plus haut
LONGUEUR_TOKEN_BRIQUE = 5   # 'coerce' oui, 'get'/'run' non


# Kwargs dont la LISTE est de la mécanique Django (champs à sauver/afficher), pas une
# redéfinition de vocabulaire : `item.save(update_fields=[...])` cite les champs par nature.
KWARGS_MECANIQUE = {'update_fields', 'fields', 'list_display', 'list_filter', 'search_fields'}


def _collections_litterales(tree):
    """(node, valeurs, nom_assigné, est_dict_données) pour chaque collection littérale."""
    assignations, mecanique = {}, set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and len(node.targets) == 1 \
                and isinstance(node.targets[0], ast.Name):
            assignations[id(node.value)] = node.targets[0].id
        elif isinstance(node, ast.Call):
            for kw in node.keywords:
                if kw.arg in KWARGS_MECANIQUE:
                    mecanique.add(id(kw.value))
    for node in ast.walk(tree):
        if id(node) in mecanique:
            continue
        if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
            vals = [e.value for e in node.elts
                    if isinstance(e, ast.Constant) and isinstance(e.value, str)]
            if len(vals) >= SEUIL_INTERSECTION:
                yield node, set(vals), assignations.get(id(node)), False
        elif isinstance(node, ast.Dict):
            keys = [k.value for k in node.keys
                    if isinstance(k, ast.Constant) and isinstance(k.value, str)]
            if len(keys) < SEUIL_INTERSECTION:
                continue
            # Dict « données » : les valeurs sont elles-mêmes des littéraux. Un dict de
            # sérialisation (valeurs = attributs d'objet) est un usage, pas une recopie.
            litteraux = sum(1 for v in node.values
                            if isinstance(v, (ast.Constant, ast.Dict, ast.List, ast.Tuple)))
            if node.values and litteraux / len(node.values) >= 0.6:
                yield node, set(keys), assignations.get(id(node)), True


def _clamps(tree):
    """(node, borne_basse, borne_haute, nom_de_variable) pour max(a, min(b, x)) et miroir."""
    def _num(n):
        return n.value if isinstance(n, ast.Constant) and isinstance(n.value, (int, float)) \
            else None

    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id in ('min', 'max') and len(node.args) == 2):
            continue
        exterieur = node.func.id
        for a, b in ((node.args[0], node.args[1]), (node.args[1], node.args[0])):
            if not (isinstance(b, ast.Call) and isinstance(b.func, ast.Name)
                    and b.func.id in ('min', 'max') and b.func.id != exterieur
                    and len(b.args) == 2):
                continue
            cste_ext = _num(a)
            if cste_ext is None:
                continue
            for c, d in ((b.args[0], b.args[1]), (b.args[1], b.args[0])):
                cste_int = _num(c)
                if cste_int is None or not isinstance(d, ast.Name):
                    continue
                basse, haute = ((cste_ext, cste_int) if exterieur == 'max'
                                else (cste_int, cste_ext))
                yield node, basse, haute, d.id


class Command(BaseCommand):
    help = "Détecte les recopies locales d'un vocabulaire/mécanique à domicile unique (§16.9 ②)."

    def add_arguments(self, parser):
        parser.add_argument('--root', default=None,
                            help="Arbre à scanner (défaut : le repo). Sert aux runs "
                                 "d'acceptation sur du code reconstruit pré-correctif.")
        parser.add_argument('--strict', action='store_true',
                            help="Code de sortie 1 s'il reste au moins une trouvaille.")

    # ── Vocabulaires de référence (toujours les registres LIVE, jamais l'arbre scanné) ──
    def _vocabulaires(self):
        from wama.common.app_registry import APP_CATALOG
        from wama.common.utils.param_schema import schema_for_app
        from wama.tool_api import TOOL_REGISTRY

        noms_params, choices, bornes = {}, [], []
        for app_id in sorted(APP_CATALOG):
            schema = schema_for_app(app_id) or []
            noms = {p.get('name') for p in schema if p.get('name')}
            if noms:
                noms_params[app_id] = noms
            for p in schema:
                vals = {c[0] for c in (p.get('choices') or []) if c and c[0]}
                if len(vals) >= SEUIL_INTERSECTION:
                    choices.append((app_id, p['name'], vals))
                if p.get('min') is not None or p.get('max') is not None:
                    bornes.append((app_id, p['name'], p.get('min'), p.get('max')))
        return noms_params, choices, bornes, set(TOOL_REGISTRY)

    def _briques_communes(self, racine_repo):
        """Premier token → briques publiques de common/utils + common/services."""
        briques = {}
        for sousdir in ('wama/common/utils', 'wama/common/services'):
            for f in sorted((racine_repo / sousdir).glob('*.py')):
                try:
                    tree = ast.parse(f.read_text(encoding='utf-8', errors='replace'))
                except SyntaxError:
                    continue
                for node in tree.body:
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                            and not node.name.startswith('_') \
                            and len(node.name.split('_')[0]) >= LONGUEUR_TOKEN_BRIQUE:
                        briques.setdefault(node.name, (f.stem, []))[1].append(
                            f"{sousdir}/{f.name}::{node.name}")
        return briques

    def _fichiers(self, racine):
        import os
        # os.walk AVEC élagage : rglob descendrait dans venvs/AI-models/media avant de
        # filtrer — plusieurs minutes de pur I/O sur /mnt/d (même leçon que check_docs).
        for dirpath, dirs, files in os.walk(racine):
            dirs[:] = sorted(d for d in dirs if d not in DOSSIERS_EXCLUS)
            for name in sorted(files):
                if name.endswith('.py') and name not in FICHIERS_SOURCE:
                    yield Path(dirpath) / name

    def handle(self, *args, **o):
        from django.conf import settings
        racine_repo = Path(settings.BASE_DIR)
        racine = Path(o['root']).resolve() if o['root'] else racine_repo

        noms_params, choices, bornes, noms_outils = self._vocabulaires()
        briques = self._briques_communes(racine_repo)
        trouvailles = []   # (classe, fichier_relatif, ligne, message)

        for f in self._fichiers(racine):
            rel = f.relative_to(racine)
            source = f.read_text(encoding='utf-8', errors='replace')
            try:
                tree = ast.parse(source)
            except SyntaxError:
                continue
            lignes = source.splitlines()

            def _assume(node):
                """Pragma de triage sur la ligne du nœud (ou la précédente) → assumé."""
                for i in (node.lineno - 1, node.lineno - 2):
                    if 0 <= i < len(lignes) and PRAGMA in lignes[i]:
                        return True
                return False

            # ── Classe A : vocabulaire recopié ─────────────────────────────────
            for node, vals, nom, _dict in _collections_litterales(tree):
                if nom in NOMS_REGISTRE_OUTILS or _assume(node):
                    continue
                inter_outils = vals & noms_outils
                if len(inter_outils) >= SEUIL_OUTILS:
                    trouvailles.append(('A', rel, node.lineno,
                                        f"{len(inter_outils)} noms d'outils du TOOL_REGISTRY "
                                        f"recopiés (ex. {sorted(inter_outils)[:3]}…)"
                                        + (f" — assigné à {nom}" if nom else "")))
                    continue
                meilleur = None
                for app_id, noms in noms_params.items():
                    inter = vals & noms
                    if len(inter) >= SEUIL_INTERSECTION and len(inter) / len(vals) >= SEUIL_RATIO:
                        if meilleur is None or len(inter) > meilleur[1]:
                            meilleur = (f"noms de params du schéma « {app_id} »", len(inter), inter)
                for app_id, param, vals_choices in choices:
                    inter = vals & vals_choices
                    if len(inter) >= SEUIL_INTERSECTION and len(inter) / len(vals) >= SEUIL_RATIO:
                        if meilleur is None or len(inter) > meilleur[1]:
                            meilleur = (f"choices de {app_id}.{param}", len(inter), inter)
                if meilleur:
                    quoi, n, inter = meilleur
                    trouvailles.append(('A', rel, node.lineno,
                                        f"{n} valeurs recopiées des {quoi} "
                                        f"(ex. {sorted(inter)[:4]}…)"
                                        + (f" — assigné à {nom}" if nom else "")))

            # ── Classe B : bornes divergentes ──────────────────────────────────
            for node, basse, haute, var in _clamps(tree):
                if _assume(node):
                    continue
                for app_id, param, pmin, pmax in bornes:
                    if var != param:
                        continue
                    div_min = pmin is not None and float(basse) != float(pmin)
                    div_max = pmax is not None and float(haute) != float(pmax)
                    if div_min or div_max:
                        trouvailles.append(('B', rel, node.lineno,
                                            f"clamp {basse}–{haute} sur « {var} » ; le schéma "
                                            f"{app_id} déclare {pmin}–{pmax}"))

            # ── Classe C : brique doublée ──────────────────────────────────────
            est_common = str(rel).replace('\\', '/').startswith('wama/common/')
            # (i) def privé de NIVEAU MODULE homonyme d'une brique commune (hors common/).
            # Garde-fous contre les coïncidences (200+ faux positifs sinon) :
            #   - niveau module seulement : une closure imbriquée est un helper local — les
            #     briques doublées vécues (`_coerce`, `_params_json`) étaient top-level, et
            #     les faux positifs étaient des CALLBACKS (`derive=_derive`, `_probe`) ;
            #   - relation de PRÉFIXE entre les noms complets, avec COUVERTURE ≥ ½ des
            #     tokens du plus long (« _analyze » vs analyze_segments_coherence : 1/3, out) ;
            #   - un module qui référence la brique OU son module l'a adoptée (wrapper
            #     `_console` → push_console_line, `_chips` → card_chips) : pas un doublon.
            if not est_common:
                for node in tree.body:
                    if not (isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                            and node.name.startswith('_')) or _assume(node):
                        continue
                    tl = node.name.lstrip('_').split('_')
                    for bnom, (stem, cibles) in briques.items():
                        tb = bnom.split('_')
                        court = min(len(tl), len(tb))
                        if not court or tl[:court] != tb[:court]:
                            continue
                        if court / max(len(tl), len(tb)) < 0.5:
                            continue
                        if bnom in source or stem in source:
                            continue
                        trouvailles.append(('C', rel, node.lineno,
                                            f"def {node.name}() double une brique commune "
                                            f"({', '.join(cibles[:2])})"))
                        break
            # (ii) rechargement local du schéma d'app (même imbriqué)
            for node in ast.walk(tree):
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                        or _assume(node):
                    continue
                segment = ast.get_source_segment(source, node) or ''
                if 'import_module' in segment \
                        and re.search(r"params_module|params_attr|PARAMS_JSON", segment):
                    trouvailles.append(('C', rel, node.lineno,
                                        f"def {node.name}() recharge lui-même le schéma d'app "
                                        f"(import_module + params_module/PARAMS_JSON) — "
                                        f"domicile : param_schema.schema_for_app"))

        # ── Rapport ────────────────────────────────────────────────────────────
        w = self.stdout.write
        w(f"\nREDONDANCES CODE ↔ DOMICILE UNIQUE  (racine : {racine})")
        w("=" * 78)
        if not trouvailles:
            w(self.style.SUCCESS("Aucune recopie détectée."))
            return
        libelles = {'A': 'A — vocabulaire recopié', 'B': 'B — bornes divergentes',
                    'C': 'C — brique doublée'}
        for classe in ('A', 'B', 'C'):
            lot = [t for t in trouvailles if t[0] == classe]
            if not lot:
                continue
            w(f"\n{libelles[classe]} ({len(lot)}) :")
            for _, rel, ligne, msg in lot:
                w(f"  {rel}:{ligne}  {msg}")
        w(f"\nBilan : {len(trouvailles)} trouvaille(s). Chaque recopie diverge en silence — "
          "brancher le consommateur sur le domicile unique, puis relancer.")
        if o['strict']:
            raise SystemExit(1)
