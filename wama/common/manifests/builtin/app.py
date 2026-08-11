"""
Kind `app` — le plus riche (8 facettes, cf. WAMA_MANIFEST_SPEC §3).

`extract_app(app_id)` LIT l'état courant des registres épars et produit UN manifeste consolidé
(enveloppe + body). C'est la 1re moitié du ROUND-TRIP : réinjecter ce manifeste et le régénérer en
sandbox, puis diffe contre l'app réelle → les écarts révèlent trous du schéma ET mécanismes non
généralisés (spec §4).

`write_back_app`/`un_write_back_app` SONT implémentés (voir bas de fichier). Facettes ÉCRITES
aujourd'hui (`PROJECTED_FACETS`) : `access` (DB → `AppAccessPolicy`, runtime) et `identity`
(CODE → entrée `APP_CATALOG` d'app_registry.py, §10.3 pilote converter 2026-08-11) — idempotent,
réversible (marqueur sur les blocs générés), dry-run par défaut. Les facettes `backend=code`
restantes sont rapportées dans `codegen_required` (tri = `projection.FACET_TARGETS`, source
unique) : leur write-back = générer la couche MINCE déclarative de l'app (registres en code,
params.py, gabarit), chantier route §10 — PAS un mécanisme d'UI à bâtir, l'UI est générée au
runtime par les briques communes une fois les registres alimentés.

⚠ 2026-08-11 : l'ancienne version de ce docstring (« write_back NE sont PAS implémentés ici »)
a survécu ~6 semaines à l'implémentation et a fait conclure À TORT que la chaîne n'existait pas.
Ce docstring est un CONTRAT : le tenir à jour au même commit que le code qu'il décrit.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional

from django.db import transaction

from ..kinds import ManifestKind, register_kind

logger = logging.getLogger(__name__)

# APP_GROUP (permissions) → world (spec §1.1 : le monde classe la FINALITÉ).
GROUP_TO_WORLD = {
    'Production': 'media',
    'Recherche / Analyse': 'data',
    'Utilitaires': 'transverse',
    'Orchestration': 'transverse',
    'Technique': 'transverse',
    'WAMA Lab': 'lab',
    'Autres': 'transverse',
}

# Facettes attendues d'un manifeste `app` complet (pour signaler les trous par app).
APP_FACETS = ('identity', 'ports', 'capabilities', 'modes', 'params', 'inspector',
              'models', 'processing', 'prompts', 'tool_api', 'access', 'studio')

# Endpoints standard (convention §3) — CIBLE documentaire. N'est PLUS extraite comme réalité :
# depuis A1 (2026-08-11), `processing.endpoints` porte les routes RÉELLES lues de l'URLconf
# (codegen/urls_gen.app_routes) — la vraie convention mesurée vit dans ROUTE_TABLE.
STANDARD_ENDPOINTS = ['index', 'upload', 'start', 'status', 'download', 'delete', 'duplicate',
                      'update', 'start_all', 'clear_all', 'download_all', 'global_progress']
STATUS_VOCAB = ['PENDING', 'RUNNING', 'SUCCESS', 'FAILURE']


# ── Validation du body ──────────────────────────────────────────────────────────
def validate_app_body(body: dict) -> list[str]:
    errs: list[str] = []
    if not isinstance(body, dict):
        return ["body 'app' doit être un dict"]
    ports = body.get('ports') or {}
    if not isinstance(ports, dict):
        errs.append("ports doit être un dict {inputs, outputs}")
    else:
        for side in ('inputs', 'outputs'):
            plist = ports.get(side, [])
            if not isinstance(plist, list):
                errs.append(f"ports.{side} doit être une liste")
                continue
            for p in plist:
                if not isinstance(p, dict) or 'id' not in p:
                    errs.append(f"ports.{side} : chaque port exige au moins un 'id' ({p!r})")
            if side == 'inputs':
                for p in plist:
                    g = isinstance(p, dict) and p.get('group')
                    if g and g not in ('travail', 'prompt', 'reference'):
                        errs.append(f"ports.inputs group '{g}' invalide (travail|prompt|reference)")
    if 'params' in body:
        p = body['params']
        if isinstance(p, list):
            pass                        # forme historique (schéma unique) — acceptée à l'ingest
        elif isinstance(p, dict):
            sch = p.get('schemas')
            if not isinstance(sch, dict) or not sch:
                errs.append("params.schemas doit être un dict {attr: liste} non vide")
            elif any(not isinstance(v, list) for v in sch.values()):
                errs.append("params.schemas : chaque schéma doit être une liste")
            elif p.get('primary') not in sch:
                errs.append("params.primary doit désigner une clé de params.schemas")
        else:
            errs.append("params doit être une liste (héritage) ou un dict {primary, schemas}")
    proc = body.get('processing') or {}
    if proc and isinstance(proc, dict):
        st = proc.get('statuses')
        if st and any(s not in STATUS_VOCAB for s in st):
            errs.append(f"processing.statuses hors vocabulaire canonique {STATUS_VOCAB} : {st}")
    return errs


# ── Extraction (registres → manifeste) ──────────────────────────────────────────
def extract_app(app_id: str) -> Optional[dict]:
    from wama.common.app_registry import APP_CATALOG, studio_node_ports

    cat = APP_CATALOG.get(app_id)
    if cat is None:
        return None

    world = GROUP_TO_WORLD.get(_app_group(app_id), 'transverse')

    body: dict[str, Any] = {}

    # F1 IDENTITÉ (le reste — name/description/world — va dans l'enveloppe)
    body['identity'] = {
        'icon': cat.get('icon'),
        'color': cat.get('color'),
        'category': cat.get('category'),
        'url_name': cat.get('url_name'),
        'input_extensions': list(cat.get('input_extensions', ())),
    }

    # F2 CAPACITÉS & PORTS
    try:
        body['ports'] = _ports(studio_node_ports(app_id))
    except Exception as e:
        body['ports'] = {'inputs': [], 'outputs': [], '_error': repr(e)}
    body['capabilities'] = _capabilities(cat, app_id)

    # F2bis MODES
    modes = _modes(app_id)
    if modes is not None:
        body['modes'] = modes

    # F3 UI (params + inspecteur)
    params = _params(app_id)
    if params is not None:
        body['params'] = params
    body['inspector'] = _inspector(app_id)

    # F4 MODÈLES
    models = _models(app_id)
    if models:
        body['models'] = models

    # F5 TRAITEMENT
    body['processing'] = _processing(cat, app_id)

    # F6 PROMPTS / IA
    prompts = _prompts(app_id)
    if prompts:
        body['prompts'] = prompts
    tool_api = _tool_api(app_id)
    if tool_api:
        body['tool_api'] = tool_api

    # F7 PERMISSIONS
    body['access'] = _access(app_id)

    # F8 STUDIO
    studio = _studio(app_id)
    if studio is not None:
        body['studio'] = studio

    # Diagnostic : facettes vides (réalité de conformité, spec §4)
    body['_missing_facets'] = [f for f in APP_FACETS if not body.get(f)]

    return {
        'manifest_kind': 'app',
        'key': app_id,
        'schema_version': '1.0',
        'name': cat.get('label', app_id),
        'description': cat.get('description', ''),
        'world': world,
        'visibility': 'public',        # les apps builtin sont publiques
        'projects': [],
        'source': {'type': 'extract', 'ref': f'APP_CATALOG:{app_id}'},
        # Composition (SPEC §7.3) : les références de la facette models, RECOPIÉES dans
        # l'enveloppe sous forme kind-agnostique. Même source (le catalogue), deux projections —
        # `resolve_requires()` ne lit que l'enveloppe, sans connaître les facettes.
        # Jambe `library` : deux conditions CUMULATIVES — l'app importe réellement la
        # distribution (mesuré par AST, cf. `library_index`) ET celle-ci est SEMÉE au corpus
        # (décision humaine, SPEC §7.4-3). La 2e n'est pas cosmétique : `valider()` traite une
        # référence `requires` pendante comme une ERREUR, donc citer une lib non semée
        # invaliderait les 10 manifestes d'apps d'un coup.
        'requires': [{'kind': 'model', 'key': k}
                     for k in ((body.get('models') or {}).get('catalog_keys') or [])]
                    + [{'kind': 'library', 'key': k} for k in _librairies(app_id)],
        'body': body,
    }


def _librairies(app_id: str) -> list:
    """Librairies semées ET réellement importées par l'app (best-effort : jamais bloquant —
    un inventaire indisponible ne doit pas empêcher d'extraire un manifeste)."""
    try:
        from wama.common.services.library_index import librairies_de
        return librairies_de(app_id)
    except Exception:
        logger.debug("[manifest:app] inventaire des librairies indisponible", exc_info=True)
        return []


# ── Helpers d'extraction (best-effort, jamais bloquants) ────────────────────────
def _app_group(app_id):
    try:
        from wama.accounts.permissions import app_group
        return app_group(app_id)
    except Exception:
        return 'Autres'


def _ports(raw) -> dict:
    """studio_node_ports() renvoie déjà des ports {id,label,group,types,multi}. On les répartit
    entrées/sorties et on NE régresse PAS la preview (group=travail|prompt = entrée de travail)."""
    if isinstance(raw, dict) and ('inputs' in raw or 'outputs' in raw or 'output' in raw):
        # `studio_node_ports()` nomme la sortie `output` (SINGULIER, un dict) — la lecture de
        # `outputs` seule rendait une liste VIDE pour les 10 apps : la facette perdait le type
        # de sortie, et `studio_redundancy()` signalait à juste titre 10/10 désaccords sur
        # `output_type`. Les deux formes sont acceptées, la sortie du manifeste reste une liste.
        outs = list(raw.get('outputs') or [])
        if not outs and raw.get('output'):
            outs = [raw['output']]
        return {'inputs': list(raw.get('inputs', [])), 'outputs': outs}
    # certains renvoient une liste plate → séparer par présence d'un flag 'side'/'kind'
    if isinstance(raw, (list, tuple)):
        ins, outs = [], []
        for p in raw:
            (outs if isinstance(p, dict) and p.get('side') == 'output' else ins).append(p)
        return {'inputs': ins, 'outputs': outs}
    return {'inputs': [], 'outputs': []}


def _capabilities(cat: dict, app_id: str) -> dict:
    caps = {
        'has_batch': bool(cat.get('has_batch')),
        'batch_type': cat.get('batch_type'),
        'has_url_import': bool(cat.get('has_url_import')),
        'has_youtube': bool(cat.get('has_youtube')),
        # accepts_url (F2, trou #14) : capacité déclarative → génère la card d'import URL (vs show_url manuel).
        # Vrai si l'app importe depuis une URL OU déclare un ingest WAMA_INGEST.
        'accepts_url': bool(cat.get('has_url_import')) or _ingest(app_id) is not None,
    }
    # Accesseur PARTAGÉ app_capabilities(app_id) = point de bascule UNIQUE (contrat multi-instances,
    # REPRISE_2026-07-22) — plus de lecture directe de `conventions`. Repli défensif si indisponible.
    try:
        from wama.common.app_registry import app_capabilities
        d = app_capabilities(app_id) or {}
    except Exception:
        d = _to_dict(cat.get('conventions'))
    # drapeaux de capacité utiles (spec F2) — présents seulement s'ils existent
    for k in ('settings_modal_item', 'settings_modal_batch', 'inspector', 'realtime',
              'edit_page', 'instant_preview', 'during_preview', 'streaming',
              'multi_format_download', 'layout', 'anti_race'):
        if k in d:
            caps[k] = d[k]
    return caps


def _modes(app_id):
    try:
        from wama.common.utils.app_modes import APP_MODES
        return APP_MODES.get(app_id)
    except Exception:
        return None


def _params(app_id):
    """Schémas de params de l'app — TOUS les attributs `*PARAMS_JSON` du module, pas seulement
    celui pointé par le studio (trou #10 résorbé 2026-08-11 : imager IMAGE+VIDEO, enhancer
    MEDIA+AUDIO étaient invisibles au manifeste). Forme : {'primary': <attr du nœud studio>,
    'schemas': {attr: [param, …]}} ; None quand l'app n'en déclare pas (facette ABSENTE).
    La résolution du module reste celle de l'accesseur commun (`schema_for_app`) : pointeur
    déclaratif GENERIC_APPS.params_module, repli convention `wama.<app>.params`."""
    import importlib
    module_name, primary = f'wama.{app_id}.params', 'PARAMS_JSON'
    try:
        from wama.studio.services.generic_runner import GENERIC_APPS
        conf = GENERIC_APPS.get(app_id) or {}
        module_name = conf.get('params_module') or module_name
        primary = conf.get('params_attr') or primary
    except Exception:
        pass
    try:
        mod = importlib.import_module(module_name)
    except Exception:
        return None
    schemas = {}
    for attr in sorted(dir(mod)):
        if attr.endswith('PARAMS_JSON') and not attr.startswith('_'):
            val = getattr(mod, attr)
            if isinstance(val, list) and val:
                schemas[attr] = list(val)
    if not schemas:
        return None
    return {'primary': primary if primary in schemas else sorted(schemas)[0],
            'schemas': schemas}


def _inspector(app_id):
    """Introspecte l'enregistrement Detail/Preview COMMUN (présence, pas contenu). Ces deux briques
    sont largement adoptées : une app 'registered' tire son volet droit / sa preview du commun (source
    unique), pas d'un HTML hand-built. `preview_registered` = la preview d'ENTRÉE/résultat vient du
    commun (PreviewRegistry bind sur le fichier de TRAVAIL, jamais la référence — cf. spec F2)."""
    info = {}
    try:
        from wama.common.utils.detail_registry import DetailRegistry
        info['detail_registered'] = DetailRegistry.is_registered(app_id)
    except Exception:
        info['detail_registered'] = None
    try:
        from wama.common.utils.preview_registry import PreviewRegistry
        info['preview_registered'] = PreviewRegistry.is_registered(app_id)
    except Exception:
        info['preview_registered'] = None
    return info


def _models(app_id):
    """
    Modèles de l'app, RÉFÉRENCÉS depuis le catalogue `AIModel` — la source unique.

    Le lien app↔modèles existe déjà et n'est pas à réinventer : `AIModel.source` porte l'app,
    et `model_key` vaut `{source}:{id}` (convention documentée dans
    `model_manager/services/model_registry.py`). Les clés rendues ici sont donc **canoniques**,
    directement résolvables vers un manifeste de kind `model` (composition, SPEC §7).

    La version précédente lisait `wama/<app>/utils/model_config.py`, une source PARALLÈLE et
    incomplète : elle déclarait 42 modèles là où le catalogue en lie 91 aux apps, et **0 pour
    l'anonymizer alors qu'il en a 48** — le manifeste affirmait donc qu'il n'utilise aucun modèle.

    `model_config` reste cité comme provenance (`source_attr`) : il porte le câblage runtime
    par app, que le catalogue n'a pas. Ce n'est pas une redondance, c'est une autre facette.
    """
    try:
        from wama.model_manager.models import AIModel
        cles = sorted(AIModel.objects.filter(source=app_id)
                      .values_list('model_key', flat=True))
    except Exception:
        cles = []

    provenance = None
    try:
        import importlib
        mod = importlib.import_module(f'wama.{app_id}.utils.model_config')
        for attr in (f'{app_id.upper()}_MODELS', 'MODELS', 'MODEL_CATALOG'):
            if isinstance(getattr(mod, attr, None), dict) and getattr(mod, attr):
                provenance = attr
                break
    except Exception:
        pass

    if not cles and not provenance:
        return None
    out = {'catalog_keys': cles}
    if provenance:
        out['source_attr'] = provenance
    return out


def _processing(cat: dict, app_id: str) -> dict:
    conv = _to_dict(cat.get('conventions')) if cat.get('conventions') is not None else {}
    out = {
        'statuses': STATUS_VOCAB if conv.get('status_vocab') else None,
        'processing_time': bool(conv.get('processing_time')),
        'anti_race': conv.get('anti_race'),
        'ingest': _ingest(app_id),         # F5/trou #14 : projette vers WAMA_INGEST (source_ingest.py)
    }
    # Routes RÉELLES lues de l'URLconf (A1) — remplace l'ancienne affirmation STANDARD_ENDPOINTS
    # (une CIBLE présentée comme réalité pour les 10 apps, cadrage A0). Compression : un nom
    # conforme à ROUTE_TABLE suffit ; toute déviation (motif, vue) est déclarée in extenso.
    try:
        from ..codegen.urls_gen import app_routes
        noms, extras = app_routes(app_id)
        out['endpoints'] = noms
        if extras:
            out['extra_routes'] = extras
    except Exception as e:
        out['endpoints'] = []
        out['_routes_error'] = repr(e)
    return out


def _ingest(app_id: str):
    """Facette INGEST (trou #14) : lit la déclaration `WAMA_INGEST` du modèle d'item de l'app
    (mécanisme commun `common/utils/source_ingest.py::ensure_local_input`). C'est l'état committé vers
    lequel la projection F5 écrira ; ici extract-only. None si l'app ne fait pas d'ingest source→fichier."""
    model = None
    try:
        from wama.common.utils.detail_registry import DetailRegistry
        entry = DetailRegistry.get(app_id) if DetailRegistry.is_registered(app_id) else None
        model = (entry or {}).get('model')
    except Exception:
        return None
    if model is None:
        return None
    spec = getattr(model, 'WAMA_INGEST', None)
    if not spec:
        return None
    # normalise en dict sérialisable (spec = {source, target, mode, ...})
    try:
        return dict(spec)
    except Exception:
        return {'_raw': repr(spec)}


def _prompts(app_id):
    out = {}
    try:
        from wama.common.utils.app_metadata import PROMPT_TARGETS
        t = PROMPT_TARGETS.get(app_id)
        if t:
            out['targets'] = t
    except Exception:
        pass
    skills = _skill_files(app_id)
    if skills:
        out['skills'] = skills
    return out or None


def _skill_files(app_id):
    try:
        import os
        from django.conf import settings
        base = os.path.join(settings.BASE_DIR, 'wama', 'common', 'prompt_skills')
        if not os.path.isdir(base):
            return []
        pref = app_id.replace('_', '-')
        return sorted(f for f in os.listdir(base)
                      if f.endswith('.md') and (f.startswith(app_id) or f.startswith(pref)))
    except Exception:
        return []


def _tool_api(app_id):
    """Triade d'outils de l'app + leurs descriptions.

    Les descriptions viennent de `tool_descriptions()`, qui les DÉRIVE (APP_CATALOG + docstring
    + schéma + signature réelle). Avant : le dict manuel `TOOL_DESCRIPTIONS`, qui datait de
    mars 2026 et avait dérivé — 21 params décrits sur 71, 3 outils sans entrée. La facette F3
    de ce même fichier était déjà alignée sur `params.py` ; F6 ne l'était pas.
    """
    try:
        from wama.tool_api import TOOL_REGISTRY, tool_descriptions
    except Exception:
        return None
    names = {'add': f'add_to_{app_id}', 'start': f'start_{app_id}', 'status': f'get_{app_id}_status'}
    present = {role: n for role, n in names.items() if n in TOOL_REGISTRY}
    if not present:
        return None
    described = tool_descriptions()
    present['descriptions'] = {n: described.get(n) for n in present.values() if isinstance(n, str)}
    return present


def _access(app_id):
    try:
        from wama.accounts.permissions import _policy_for
        p = _policy_for(app_id)
        return {'roles': sorted(p.get('roles', [])), 'public': bool(p.get('public')),
                'min_tier': p.get('min_tier')}
    except Exception:
        return {}


def _studio(app_id):
    """Facette studio = le DÉCLARATIF de l'entrée GENERIC_APPS : pointeur params
    (params_module/params_attr), auto_start, signatures historiques (input_kwarg,
    fixed_kwargs, extra_params_spec) et RÉTRÉCISSEMENT d'E/S (io_scope + les champs E/S
    déclarés). Les E/S DÉRIVÉES des ports (§10.1, tracées `_io_derived`) sont EXCLUES :
    elles se reconstruisent à l'import — même règle que la couleur d'APP_CATALOG, le
    manifeste ne porte que ce qui se déclare. (Jusqu'au 2026-08-11 la facette recopiait
    les E/S effectives sans distinguer dérivé/déclaré, et perdait le pointeur params et
    io_scope — trou d'extract corrigé avec le write-back.)"""
    try:
        from wama.studio.services.generic_runner import GENERIC_APPS
        g = GENERIC_APPS.get(app_id)
        if not g:
            return None
        derived = set(g.get('_io_derived') or ())
        out = {'runnable': True}
        for c in ('params_module', 'params_attr', 'auto_start', 'input_kwarg',
                  'fixed_kwargs', 'io_scope', 'extra_params_spec'):
            if g.get(c) is not None:
                out[c] = g.get(c)
        for c in ('input_kinds', 'primary_input', 'output_type'):
            if c in g and c not in derived and g.get(c) is not None:
                v = g.get(c)
                out[c] = list(v) if isinstance(v, (list, tuple)) else v
        return out
    except Exception:
        return None


def _to_dict(obj) -> dict:
    """Convertit un objet conventions (dataclass/namedtuple/obj) en dict plat, best-effort."""
    if obj is None:
        return {}
    if isinstance(obj, dict):
        return obj
    try:
        from dataclasses import asdict, is_dataclass
        if is_dataclass(obj):
            return asdict(obj)
    except Exception:
        pass
    if hasattr(obj, '_asdict'):
        try:
            return dict(obj._asdict())
        except Exception:
            pass
    if hasattr(obj, '__dict__'):
        return {k: v for k, v in vars(obj).items() if not k.startswith('_')}
    return {}


# ── PROJECTION (write-back) ──────────────────────────────────────────────────────
# Propriété de sûreté (SPEC §2.1) : rien ne lit le manifeste en direct ; la projection est un geste
# EXPLICITE, jamais automatique. Facettes que `write_back_app` SAIT écrire (une entrée ici = un
# projecteur en bas de fichier) :
#   - `access`       → AppAccessPolicy (DB, runtime)
#   - `identity`     → entrée APP_CATALOG (app_registry.py, CODE — §10.3, pilote converter)
#   - `ports`        → input_types/output_types de la même entrée (inversion studio_node_ports)
#   - `capabilities` → has_batch/batch_type/has_url_import/has_youtube (le déclaratif seul)
#   - `studio`       → entrée GENERIC_APPS (generic_runner.py — déclaratif seul, E/S dérivées exclues)
#   - `modes`        → entrée APP_MODES (app_modes.py — littéral profond, égalité profonde)
#   - `prompts`      → entrée PROMPT_TARGETS (app_metadata.py — `targets` seul, entrée-valeur)
# Le reste des facettes `backend=code` part dans `codegen_required`. Le tri code/db vient de
# `projection.FACET_TARGETS` (source unique) — l'ancienne liste locale codée en dur avait divergé
# (elle omettait capabilities/modes et citait models/prompts), corrigé 2026-08-11.
PROJECTED_FACETS = ('access', 'identity', 'ports', 'capabilities', 'studio', 'modes', 'prompts',
                    'params')


def write_back_app(manifest: dict, *, apply: bool = False, skip: tuple = ()) -> dict:
    """Projette le manifeste `app` vers l'état committé. `apply=False` = DRY-RUN (retourne le plan) ;
    `apply=True` = écrit (idempotent, réversible ; transactionnel pour la DB, garde `compile()`
    pour le code). Facettes écrites : `access` (DB) + `identity`/`ports`/`capabilities`
    (code, entrée APP_CATALOG — moteur commun, champs disjoints par facette).
    `skip` : facettes à NE PAS projeter — le harnais `app_regen_check` passe `('access',)`
    (il juge le CODE régénéré et ne touche jamais la DB)."""
    from ..projection import FACET_TARGETS   # import tardif : source unique du tri code/db
    key = manifest.get('key')
    body = manifest.get('body', {}) or {}
    out = {'app': key}
    if 'access' not in skip:
        out['access'] = _project_access(key, body.get('access') or {}, apply=apply)
    projecteurs = (('identity', _project_identity), ('ports', _project_ports),
                   ('capabilities', _project_capabilities), ('studio', _project_studio),
                   ('modes', _project_modes), ('prompts', _project_prompts),
                   ('params', _project_params),
                   # processing = projection PARTIELLE (urls.py seul, gabarit A1) : la facette
                   # reste dans codegen_required tant que models.py/tasks.py ne se génèrent pas.
                   ('processing', _project_processing))
    for facette, projecteur in projecteurs:
        if body.get(facette) and facette not in skip:
            out[facette] = projecteur(manifest, apply=apply)
    out['codegen_required'] = [f for f, (_cible, backend) in FACET_TARGETS.items()
                               if backend == 'code' and body.get(f) and f not in PROJECTED_FACETS]
    return out


@transaction.atomic
def _project_access(app_id: str, access: dict, *, apply: bool) -> dict:
    from wama.accounts.models import AppAccessPolicy
    from django.contrib.auth.models import Group
    from wama.accounts.permissions import GROUP_PREFIX

    roles = sorted(access.get('roles') or [])
    public = bool(access.get('public'))
    min_tier = access.get('min_tier') or ''
    target = {'roles': roles, 'public': public, 'min_tier': min_tier}

    cur = AppAccessPolicy.objects.filter(app_id=app_id).first()
    cur_state = None
    if cur:
        cur_state = {
            'roles': sorted(g.name[len(GROUP_PREFIX):] for g in cur.roles.all()
                            if g.name.startswith(GROUP_PREFIX)),
            'public': cur.public, 'min_tier': cur.min_tier or '',
        }
    if not apply:
        return {'target': target, 'current': cur_state, 'would_change': cur_state != target}

    pol, _created = AppAccessPolicy.objects.get_or_create(app_id=app_id)
    pol.public = public
    pol.min_tier = min_tier
    pol.save()
    pol.roles.set([Group.objects.get_or_create(name=GROUP_PREFIX + r)[0] for r in roles])
    return {'applied': target, 'previous': cur_state, 'changed': cur_state != target,
            '_manifest_key': f'app:{app_id}'}


# ── Facettes → APP_CATALOG (app_registry.py) — moteur COMMUN d'écriture code (§10.3) ─
# TROIS facettes écrivent dans la MÊME entrée APP_CATALOG, chacune possédant des champs
# DISJOINTS (moteur commun, un champ n'appartient qu'à une facette) :
#   identity     → label/category/icon/url_name/description/input_extensions
#   ports        → input_types/output_types (inversion de `studio_node_ports` : le port
#                  travail rend les médias DANS L'ORDRE (= priorité, §10.1), le port prompt
#                  redevient un 'text' en QUEUE ; les ports `reference` sont IGNORÉS ici —
#                  ils dérivent d'APP_MODES, donc appartiennent à la facette modes)
#   capabilities → has_batch/batch_type/has_url_import/has_youtube — le DÉCLARATIF seul :
#                  `accepts_url` est DÉRIVÉ (has_url_import OU ingest), et les drapeaux
#                  (inspector, layout, during_preview…) sont MESURÉS par la grille
#                  (`app_capabilities` fusionne conformity_report par-dessus l'entrée) —
#                  les écrire depuis le manifeste projetterait une mesure comme déclaration.
# `color` est EXCLUE : dérivée à l'import par `_assign_derived_colors()` (teinte de catégorie
# + rang alphabétique) — l'écrire la figerait en override.
CATALOG_FIELD_ORDER = ('label', 'category', 'icon', 'url_name', 'description',
                       'input_extensions', 'input_types', 'batch_type', 'has_batch',
                       'has_url_import', 'has_youtube', 'output_types')
IDENTITY_FIELDS = ('label', 'category', 'icon', 'url_name', 'description', 'input_extensions')
PORTS_FIELDS = ('input_types', 'output_types')
CAPABILITY_FIELDS = ('has_batch', 'batch_type', 'has_url_import', 'has_youtube')
_GEN_MARK = '[manifest-gen app:{app_id}]'


class _NonLiteral:
    """Sentinelle : champ présent dans le fichier mais porté par une EXPRESSION (constantes,
    appel `_conv(...)`) — comparable via le runtime, jamais éditable par le moteur."""
    def __repr__(self):
        return '⟨expression⟩'


_NONLITERAL = _NonLiteral()


def _identity_target(manifest: dict) -> dict:
    ident = (manifest.get('body') or {}).get('identity') or {}
    return {
        'label': manifest.get('name') or manifest.get('key'),
        'category': ident.get('category'),
        'icon': ident.get('icon'),
        'url_name': ident.get('url_name'),
        'description': manifest.get('description') or '',
        'input_extensions': list(ident.get('input_extensions') or []),
    }


def _ports_target(manifest: dict) -> dict:
    ports = (manifest.get('body') or {}).get('ports') or {}
    ins = ports.get('inputs') or []
    work = next((p for p in ins if isinstance(p, dict) and p.get('group') == 'travail'), None)
    types = [t for t in ((work or {}).get('types') or []) if t]
    if any(isinstance(p, dict) and p.get('group') == 'prompt' for p in ins):
        types = types + ['text']
    outs = ports.get('outputs') or []
    out_types = [t for t in (((outs[0] or {}).get('types') if outs else None) or []) if t]
    return {'input_types': types, 'output_types': out_types}


def _capabilities_target(manifest: dict) -> dict:
    caps = (manifest.get('body') or {}).get('capabilities') or {}
    return {
        'has_batch': bool(caps.get('has_batch')),
        'batch_type': caps.get('batch_type'),
        'has_url_import': bool(caps.get('has_url_import')),
        'has_youtube': bool(caps.get('has_youtube')),
    }


# Champs DÉCLARATIFS d'une entrée GENERIC_APPS (facette studio) — les E/S dérivées des ports
# (§10.1) n'y figurent JAMAIS : elles se reconstruisent à l'import (`_fill_io_from_ports`).
STUDIO_FIELDS = ('params_module', 'params_attr', 'auto_start', 'input_kwarg', 'fixed_kwargs',
                 'input_kinds', 'primary_input', 'output_type', 'io_scope', 'extra_params_spec')


def _studio_target(manifest: dict) -> dict:
    st = (manifest.get('body') or {}).get('studio') or {}
    return {c: (list(st[c]) if isinstance(st.get(c), (list, tuple)) else st.get(c))
            for c in STUDIO_FIELDS if st.get(c) is not None}


def _io_sig(fields: dict) -> dict:
    """Signature E/S pour comparer en ESPACE DE FACETTE : la position du 'text' dans le tuple
    écrit main est une variation d'écriture sans effet (la dérivation des ports sépare médias
    et prompt) — comparer les tuples bruts fabriquerait de fausses dérives."""
    from wama.common.app_registry import normalize_types
    ins = normalize_types(list(fields.get('input_types') or []))
    return {'media': [t for t in ins if t != 'text'], 'text': 'text' in ins,
            'out': normalize_types(list(fields.get('output_types') or []))}


def _norm_v(v):
    if isinstance(v, tuple):
        return list(v)
    return v


def _project_identity(manifest: dict, *, apply: bool) -> dict:
    target = _identity_target(manifest)
    def deltas(cur):
        out = []
        for c in IDENTITY_FIELDS:
            cv = cur.get(c)
            if c == 'description' and cv is None:
                cv = ''
            if c == 'input_extensions':
                cv = list(cv or [])
            if _norm_v(target[c]) != _norm_v(cv):
                out.append(c)
        return out
    return _project_catalog_facet(manifest.get('key'), target, deltas, apply=apply)


def _project_ports(manifest: dict, *, apply: bool) -> dict:
    target = _ports_target(manifest)
    def deltas(cur):
        sig_t, sig_c = _io_sig(target), _io_sig(cur)
        out = []
        if (sig_t['media'], sig_t['text']) != (sig_c['media'], sig_c['text']):
            out.append('input_types')
        if sig_t['out'] != sig_c['out']:
            out.append('output_types')
        return out
    return _project_catalog_facet(manifest.get('key'), target, deltas, apply=apply)


def _project_capabilities(manifest: dict, *, apply: bool) -> dict:
    target = _capabilities_target(manifest)
    def deltas(cur):
        out = []
        for c in CAPABILITY_FIELDS:
            tv, cv = target[c], cur.get(c)
            if isinstance(tv, bool):
                cv = bool(cv)
            if _norm_v(tv) != _norm_v(cv):
                out.append(c)
        return out
    return _project_catalog_facet(manifest.get('key'), target, deltas, apply=apply)


def _project_studio(manifest: dict, *, apply: bool) -> dict:
    """Facette studio → entrée GENERIC_APPS. Compare et écrit le DÉCLARATIF seul (STUDIO_FIELDS) ;
    un champ déclaré dans le fichier mais absent du manifeste est un delta (retrait) — appliqué
    par régénération si l'entrée est marquée, REFUSÉ en chirurgie sur une entrée main."""
    target = _studio_target(manifest)
    def deltas(cur):
        return [c for c in STUDIO_FIELDS if _norm_v(target.get(c)) != _norm_v(cur.get(c))]
    return _project_dict_facet(manifest.get('key'), target, deltas, apply=apply,
                               current_fn=_runner_current, write_fn=_write_runner_fields,
                               champs=STUDIO_FIELDS)


def _project_prompts(manifest: dict, *, apply: bool) -> dict:
    """Facette prompts → entrée PROMPT_TARGETS (app_metadata.py). Seule la clé `targets` se
    projette : l'entrée du registre EST cette liste (déclarative). `skills` ne liste que des
    NOMS de fichiers `.md` — rapport de présence, pas régénérable (trou #17). Une entrée
    écrite main n'est jamais régénérée (les listes du registre portent des commentaires
    d'intention — seule une entrée marquée se réécrit)."""
    app_id = manifest.get('key')
    facet = (manifest.get('body') or {}).get('prompts') or {}
    target = facet.get('targets')
    if target is None:
        return {'op': 'skip', 'reason': "facette sans `targets` (skills seuls) — rien à projeter"}
    path = _metadata_path()
    found, cur = _value_entry_from_file(path, 'PROMPT_TARGETS', app_id)
    delta = (not found) or (cur is _NONLITERAL) or (cur != target)
    op = 'create' if not found else ('update' if delta else 'noop')
    if not apply:
        return {'op': op, 'target': target, 'current': None if not found else cur,
                'would_change': ['targets'] if delta else []}
    if op == 'noop':
        return {'op': op, 'changed': [], '_manifest_key': f'app:{app_id}'}
    res = _write_value_entry(path, 'PROMPT_TARGETS', app_id, target,
                             facette='prompts', create=(op == 'create'))
    res.update({'op': op, 'previous': None if not found else cur,
                '_manifest_key': f'app:{app_id}', 'reload_required': True})
    return res


def _write_value_entry(path: Path, var: str, app_id: str, value, *, facette: str,
                       create: bool) -> dict:
    """Écrit une entrée-VALEUR (littéral rendu pprint) : create, ou régénération si l'entrée
    porte le marqueur ; une entrée main est REFUSÉE. Garde `compile()` comme partout."""
    import pprint
    lines = path.read_text(encoding='utf-8').split('\n')
    lo, hi = _dict_bounds(lines, var)
    span = _value_entry_span(lines, app_id, lo, hi)
    mark = _GEN_MARK.format(app_id=app_id)

    rendu = pprint.pformat(value, width=96, sort_dicts=False).split('\n')
    commentaire = f"  # {mark} entrée GÉNÉRÉE par write_back_app (facette {facette})"
    if len(rendu) == 1:
        bloc = [f"    '{app_id}': {rendu[0]},{commentaire}"]
    else:
        bloc = [f"    '{app_id}': {rendu[0]}{commentaire}"]
        pad = ' ' * len(f"    '{app_id}': ")
        bloc += [pad + l for l in rendu[1:]]
        bloc[-1] += ','

    if create:
        if span is not None:
            return {'error': "entrée déjà présente — l'état a changé depuis le plan, relancer"}
        lines[hi:hi] = bloc
    else:
        if span is None:
            return {'error': "entrée absente — l'état a changé depuis le plan, relancer"}
        if mark not in lines[span[0]]:
            return {'changed': [], 'skipped': [{'field': 'targets',
                    'reason': "entrée écrite main (commentaires d'intention) — régénération refusée"}]}
        lines[span[0]:span[1] + 1] = bloc

    nouveau = '\n'.join(lines)
    compile(nouveau, str(path), 'exec')
    path.write_text(nouveau, encoding='utf-8')
    return {'applied': {'targets': value}, 'changed': ['targets'], 'file': str(path)}


def _params_facet(manifest: dict) -> Optional[dict]:
    """Facette params NORMALISÉE : {'primary': attr, 'schemas': {attr: [...]}} — accepte la
    forme historique (liste = schéma unique PARAMS_JSON)."""
    facet = (manifest.get('body') or {}).get('params')
    if not facet:
        return None
    if isinstance(facet, list):
        return {'primary': 'PARAMS_JSON', 'schemas': {'PARAMS_JSON': facet}}
    return facet


def _params_module_name(manifest: dict) -> str:
    st = (manifest.get('body') or {}).get('studio') or {}
    return st.get('params_module') or f"wama.{manifest.get('key')}.params"


def _params_file_path(module_name: str) -> Path:
    import wama
    return Path(wama.__file__).parent.joinpath(*module_name.split('.')[1:]).with_suffix('.py')


def _project_params(manifest: dict, *, apply: bool) -> dict:
    """Facette params → fichier `<params_module>.py`. Un params.py écrit MAIN est du code
    DÉRIVANT (derive_from_model + sources dynamiques — modèle Django, catalogues, formats
    converter) : le moteur COMPARE (égalité sémantique des schémas évalués) et ne le touche
    JAMAIS — figer le résultat évalué projetterait du dérivé, comme pour la couleur. Un module
    ABSENT est GÉNÉRÉ (littéral marqué = couche de démarrage, à raffiner vers derive_from_model
    quand la facette processing génèrera le modèle) ; un fichier marqué se régénère."""
    import importlib
    app_id = manifest.get('key')
    facet = _params_facet(manifest)
    if not facet:
        return {'op': 'skip', 'reason': 'facette params absente'}
    module_name = _params_module_name(manifest)
    target = facet['schemas']
    try:
        mod = importlib.import_module(module_name)
    except ImportError:
        mod = None
    if mod is None:
        op, deltas, marked = 'create', sorted(target), False
        path = _params_file_path(module_name)
    else:
        # Comparaison en CANONIQUE JSON : le manifeste a déjà traversé json (tuples → listes,
        # à TOUTE profondeur — option_groups niche des tuples au 2e niveau) ; on fait subir le
        # même aller-retour au schéma évalué plutôt que d'inventer un comparateur.
        import json as _json
        canon = lambda x: _json.loads(_json.dumps(x, ensure_ascii=False))
        path = Path(mod.__file__)
        marked = _GEN_MARK.format(app_id=app_id) in path.read_text(encoding='utf-8')[:600]
        current = {a: list(getattr(mod, a, []) or []) for a in target}
        deltas = sorted(a for a in target if canon(target[a]) != canon(current.get(a) or []))
        op = 'update' if deltas else 'noop'
    if not apply:
        return {'op': op, 'module': module_name, 'generated_file': marked,
                'would_change': deltas}
    if op == 'noop':
        return {'op': op, 'changed': [], '_manifest_key': f'app:{app_id}'}
    if op == 'update' and not marked:
        return {'op': op, 'changed': [], 'skipped': [
            {'field': a, 'reason': "params.py écrit main (code dérivant : derive_from_model, "
                                   "sources dynamiques) — régénération refusée ; écart à "
                                   "traiter côté manifeste ou côté code"} for a in deltas]}
    res = _write_params_file(path, app_id, facet)
    res.update({'op': op, '_manifest_key': f'app:{app_id}', 'reload_required': True})
    return res


def _write_params_file(path: Path, app_id: str, facet: dict) -> dict:
    import pprint
    if not path.parent.is_dir():
        return {'error': f"paquet {path.parent} absent — la facette processing (squelette "
                         f"d'app) doit passer d'abord", 'changed': []}
    mark = _GEN_MARK.format(app_id=app_id)
    lignes = [
        '"""',
        f"{mark} — params.py GÉNÉRÉ par write_back_app (facette params).",
        '',
        'Couche de DÉMARRAGE : schémas au LITTÉRAL (résultat évalué du manifeste). À raffiner',
        'vers derive_from_model(...) + sources dynamiques quand la facette processing génèrera',
        'le modèle Django — les valeurs dérivées redeviendront alors dérivées. Ne pas éditer à',
        'la main : rejouer write_back après modification du manifeste.',
        '"""',
        '',
    ]
    for attr in sorted(facet['schemas']):
        rendu = pprint.pformat(facet['schemas'][attr], width=96, sort_dicts=False).split('\n')
        lignes.append(f"{attr} = {rendu[0]}")
        pad = ' ' * (len(attr) + 3)
        lignes += [pad + l for l in rendu[1:]]
        lignes.append('')
    src = '\n'.join(lignes)
    compile(src, str(path), 'exec')
    path.write_text(src, encoding='utf-8')
    return {'changed': sorted(facet['schemas']), 'file': str(path)}


def _project_modes(manifest: dict, *, apply: bool) -> dict:
    """Facette modes → entrée APP_MODES (app_modes.py). La facette EST l'entrée (littéral
    profond : domains → modes → inputs/settings) : comparaison en égalité PROFONDE (l'ordre
    des clés de dict est indifférent, l'ordre des LISTES — domaines, modes, settings — est
    significatif et préservé). Sur entrée main, `domains` est multi-ligne → la chirurgie est
    refusée par construction : seule une entrée marquée se régénère."""
    facet = (manifest.get('body') or {}).get('modes') or {}
    target = {k: v for k, v in facet.items() if not k.startswith('_')}
    def deltas(cur):
        return [k for k in target if target[k] != cur.get(k)]
    def current_fn(app_id, champs):
        fichier = _entry_fields_from_file(_modes_path(), 'APP_MODES', app_id)
        if fichier is None:
            return None
        return {c: fichier.get(c) for c in champs}
    def write_fn(app_id, tgt, dlt, *, create):
        return _write_dict_fields(_modes_path(), 'APP_MODES', app_id, tgt, dlt,
                                  create=create, render_fn=_render_modes_entry_lines,
                                  field_order=None, alphabetical=False, blank_sep=True)
    return _project_dict_facet(manifest.get('key'), target, deltas, apply=apply,
                               current_fn=current_fn, write_fn=write_fn)


def _project_processing(manifest: dict, *, apply: bool) -> dict:
    """Facette processing → cible `urls.py` SEULE pour l'instant (gabarit A1) ; `models.py` et
    `tasks.py` restent en code-gen (paliers A2/A5) — la facette reste donc HORS
    PROJECTED_FACETS (projection partielle assumée, rapportée dans le retour). Contrats du
    moteur : fichier absent → GÉNÉRÉ marqué ; marqué → régénéré ; écrit main → comparaison
    SÉMANTIQUE (table name→(motif, vue) relue du fichier par ast) et JAMAIS réécrit."""
    from ..codegen.urls_gen import (current_routes_from_file, namespace_of, render_urls,
                                    routes_target, urls_file_path)
    app_id = manifest.get('key')
    restants = {'models.py': 'codegen (palier A5)', 'tasks.py': 'codegen (palier A2)'}
    cible, manquantes = routes_target(manifest)
    if not cible:
        return {'op': 'skip', 'reason': 'facette processing sans endpoints', **restants}
    if manquantes:
        return {'op': 'skip', 'reason': f"routes non couvertes (ni table ni extra_routes) : "
                                        f"{', '.join(manquantes[:8])}", **restants}
    path = urls_file_path(app_id)
    if not path.is_file():
        op, deltas, marked = 'create', sorted(cible), False
    else:
        marked = _GEN_MARK.format(app_id=app_id) in path.read_text(encoding='utf-8')[:600]
        courant, app_name = current_routes_from_file(path)
        deltas = sorted(set(n for n in set(cible) | set(courant)
                            if cible.get(n) != courant.get(n)))
        if app_name != namespace_of(manifest):
            deltas.append(f'app_name ({app_name!r} → {namespace_of(manifest)!r})')
        op = 'update' if deltas else 'noop'
    if not apply:
        return {'op': op, 'file': str(path), 'generated_file': marked,
                'would_change': deltas, **restants}
    if op == 'noop':
        return {'op': op, 'changed': [], '_manifest_key': f'app:{app_id}', **restants}
    if op == 'update' and not marked:
        return {'op': op, 'changed': [], **restants, 'skipped': [
            {'field': d, 'reason': "urls.py écrit main — régénération refusée ; écart à "
                                   "trancher (déclarer / porter / trou de route)"}
            for d in deltas]}
    src, _ = render_urls(manifest)
    compile(src, str(path), 'exec')
    path.write_text(src, encoding='utf-8')
    return {'op': op, 'changed': deltas, 'file': str(path),
            '_manifest_key': f'app:{app_id}', 'reload_required': True, **restants}


def _project_dict_facet(app_id: str, target: dict, deltas_fn, *, apply: bool,
                        current_fn, write_fn, champs: Optional[tuple] = None) -> dict:
    """Moteur commun des facettes → registre dict en code : create (entrée générée marquée) /
    update (régénération si marquée, chirurgie champ par champ si écrite main) / noop. La
    vérité d'EXISTENCE et de valeur se lit dans le FICHIER (`ast`), pas dans le module
    importé — dans un apply multi-facettes du même process, le module importé est périmé dès
    la première écriture."""
    current = current_fn(app_id, champs or tuple(target))
    deltas = deltas_fn(current) if current is not None else list(target)
    op = 'create' if current is None else ('update' if deltas else 'noop')
    if not apply:
        return {'op': op, 'target': target, 'current': current, 'would_change': deltas}
    if op == 'noop':
        return {'op': op, 'changed': [], '_manifest_key': f'app:{app_id}'}
    res = write_fn(app_id, target, deltas, create=(op == 'create'))
    res.update({'op': op, 'previous': current, '_manifest_key': f'app:{app_id}',
                'reload_required': True})
    return res


def _project_catalog_facet(app_id: str, target: dict, deltas_fn, *, apply: bool) -> dict:
    return _project_dict_facet(app_id, target, deltas_fn, apply=apply,
                               current_fn=_catalog_current, write_fn=_write_catalog_fields)


# ── Helpers d'écriture CODE (mécanique de fichier, jamais d'écriture insyntaxique) ─
# Paramétrés par (chemin, nom d'assignation) : le MÊME moteur écrit APP_CATALOG
# (app_registry.py) et GENERIC_APPS (generic_runner.py) — registres dict au même idiome
# (entrées à indentation 4, fermeture `    },`).
def _registry_path() -> Path:
    from wama.common import app_registry
    return Path(app_registry.__file__)


def _runner_path() -> Path:
    from wama.studio.services import generic_runner
    return Path(generic_runner.__file__)


def _modes_path() -> Path:
    from wama.common.utils import app_modes
    return Path(app_modes.__file__)


def _metadata_path() -> Path:
    from wama.common.utils import app_metadata
    return Path(app_metadata.__file__)


def _dict_bounds(lines: list, var: str) -> tuple:
    """(1re ligne APRÈS `<var> = {`, ligne du `}` fermant à indentation 0)."""
    debut = next(i for i, l in enumerate(lines) if l.startswith(f'{var} = {{'))
    fin = next(i for i in range(debut + 1, len(lines)) if lines[i].rstrip() == '}')
    return debut + 1, fin


def _catalog_bounds(lines: list) -> tuple:
    return _dict_bounds(lines, 'APP_CATALOG')


def _entry_span(lines: list, app_id: str, lo: int, hi: int) -> Optional[tuple]:
    """Bornes (debut, fin) du bloc `    'app_id': {` … `    },` — indentation 4 STRICTE :
    les fermetures imbriquées (conventions, tuples) sont plus profondes, donc sans ambiguïté."""
    for i in range(lo, hi):
        if lines[i].startswith(f"    '{app_id}': {{"):
            fin = next(j for j in range(i + 1, hi + 1) if lines[j].rstrip() == '    },')
            return i, fin
    return None


def _entry_fields_from_file(path: Path, var: str, app_id: str) -> Optional[dict]:
    """Champs d'une entrée du dict `<var>` lus dans le FICHIER (la vérité d'écriture) :
    littéraux évalués par `ast.literal_eval`, expressions (constantes, `_conv(...)`) →
    `_NONLITERAL`. None si l'entrée est absente. C'est CE lecteur qui rend le moteur sûr en
    apply multi-facettes : le module importé, lui, fige l'état d'avant la première écriture
    (et GENERIC_APPS est en plus MUTÉ à l'import par `_fill_io_from_ports`)."""
    import ast
    src = path.read_text(encoding='utf-8')
    for node in ast.walk(ast.parse(src)):
        if (isinstance(node, ast.Assign)
                and any(getattr(t, 'id', None) == var for t in node.targets)
                and isinstance(node.value, ast.Dict)):
            for k, v in zip(node.value.keys, node.value.values):
                if isinstance(k, ast.Constant) and k.value == app_id:
                    fields = {}
                    if isinstance(v, ast.Dict):
                        for kk, vv in zip(v.keys, v.values):
                            if isinstance(kk, ast.Constant):
                                try:
                                    fields[kk.value] = ast.literal_eval(vv)
                                except (ValueError, SyntaxError):
                                    fields[kk.value] = _NONLITERAL
                    return fields
            return None
    return None


def _value_entry_from_file(path: Path, var: str, app_id: str) -> tuple:
    """(présente?, valeur) d'une entrée du dict `<var>` dont la valeur est UN littéral
    (liste, scalaire) et non un dict de champs — ex. PROMPT_TARGETS. `_NONLITERAL` si
    l'entrée est une expression."""
    import ast
    for node in ast.walk(ast.parse(path.read_text(encoding='utf-8'))):
        if (isinstance(node, ast.Assign)
                and any(getattr(t, 'id', None) == var for t in node.targets)
                and isinstance(node.value, ast.Dict)):
            for k, v in zip(node.value.keys, node.value.values):
                if isinstance(k, ast.Constant) and k.value == app_id:
                    try:
                        return True, ast.literal_eval(v)
                    except (ValueError, SyntaxError):
                        return True, _NONLITERAL
            return False, None
    return False, None


def _value_entry_span(lines: list, app_id: str, lo: int, hi: int) -> Optional[tuple]:
    """Bornes (debut, fin) d'une entrée-VALEUR `    'app_id': [...]` — via AST
    (lineno/end_lineno), robuste aux trois idiomes : mono-ligne, fermeture `    ],` écrite
    main, continuation pprint alignée d'une entrée générée. `lo` = 1re ligne APRÈS
    `<var> = {` (contrat de `_dict_bounds`) ⇒ l'Assign du registre a lineno == lo."""
    import ast
    for node in ast.walk(ast.parse('\n'.join(lines))):
        if isinstance(node, ast.Assign) and node.lineno == lo and isinstance(node.value, ast.Dict):
            for k, v in zip(node.value.keys, node.value.values):
                if isinstance(k, ast.Constant) and k.value == app_id:
                    return k.lineno - 1, v.end_lineno - 1
            return None
    return None


def _catalog_current(app_id: str, champs: tuple) -> Optional[dict]:
    """Valeurs courantes des champs demandés : littéral du fichier d'abord, repli RUNTIME pour
    les expressions (leur valeur évaluée à l'import — sémantiquement juste, jamais éditable)."""
    fichier = _entry_fields_from_file(_registry_path(), 'APP_CATALOG', app_id)
    if fichier is None:
        return None
    from wama.common.app_registry import APP_CATALOG
    runtime = APP_CATALOG.get(app_id) or {}
    cur = {}
    for c in champs:
        v = fichier.get(c)
        if v is _NONLITERAL:
            v = runtime.get(c)
        cur[c] = list(v) if isinstance(v, (list, tuple)) else v
    return cur


def _runner_current(app_id: str, champs: tuple) -> Optional[dict]:
    """Valeurs courantes d'une entrée GENERIC_APPS — FICHIER SEUL : le runtime est mué à
    l'import (E/S dérivées injectées), il ne reflète pas la déclaration."""
    fichier = _entry_fields_from_file(_runner_path(), 'GENERIC_APPS', app_id)
    if fichier is None:
        return None
    return {c: (list(v) if isinstance(v, (list, tuple)) else v)
            for c, v in ((c, fichier.get(c)) for c in champs)}


def _render_entry_lines(app_id: str, fields: dict) -> list:
    """Entrée APP_CATALOG générée (champs connus seuls, ordre canonique), dans l'idiome du
    fichier. Le marqueur = la trace `_manifest_key` version code — il borne ce que
    `un_write_back_app` a le droit de supprimer et ce que le moteur a le droit de régénérer."""
    mark = _GEN_MARK.format(app_id=app_id)
    out = [f"    '{app_id}': {{  # {mark} entrée GÉNÉRÉE par write_back_app ;",
           "        # la compléter par les write-backs des autres facettes, pas à la main."]
    for champ in CATALOG_FIELD_ORDER:
        if champ not in fields or fields[champ] is None:
            continue
        val = fields[champ]
        if champ == 'input_extensions' and isinstance(val, (list, tuple)) and val:
            out.append("        'input_extensions': (")
            ligne = "            "
            for e in val:
                tok = f"{e!r}, "
                if len(ligne) + len(tok) > 98:
                    out.append(ligne.rstrip())
                    ligne = "            "
                ligne += tok
            out.append(ligne.rstrip())
            out.append("        ),")
            continue
        if isinstance(val, list):
            val = tuple(val)
        out.append(f"        '{champ}': {val!r},")
    out += ["    },", ""]
    return out


def _render_modes_entry_lines(app_id: str, fields: dict) -> list:
    """Entrée APP_MODES générée : littéral profond rendu par pprint (ordre d'insertion
    préservé), continuation alignée sous la clé."""
    import pprint
    mark = _GEN_MARK.format(app_id=app_id)
    out = [f"    '{app_id}': {{  # {mark} entrée GÉNÉRÉE par write_back_app (facette modes) ;",
           "        # régénérée depuis le manifeste — ne pas éditer à la main."]
    for k, v in fields.items():
        prefix = f"        '{k}': "
        rendu = pprint.pformat(v, width=96, sort_dicts=False).split('\n')
        out.append(prefix + rendu[0])
        pad = ' ' * len(prefix)
        out += [pad + l for l in rendu[1:]]
        out[-1] += ','
    out.append("    },")
    return out


def _render_runner_entry_lines(app_id: str, fields: dict) -> list:
    """Entrée GENERIC_APPS générée (déclaratif seul, idiome du fichier — pas de ligne vide
    entre entrées). Les E/S dérivées n'y sont jamais rendues."""
    mark = _GEN_MARK.format(app_id=app_id)
    out = [f"    '{app_id}': {{  # {mark} entrée GÉNÉRÉE par write_back_app (facette studio) ;",
           "        # E/S dérivées des ports à l'import (§10.1) — ne déclarer ici que le rétrécissement."]
    for champ in STUDIO_FIELDS:
        if champ not in fields or fields[champ] is None:
            continue
        val = fields[champ]
        if isinstance(val, list) and champ == 'input_kinds':
            val = tuple(val)
        out.append(f"        '{champ}': {val!r},")
    out.append("    },")
    return out


def _write_dict_fields(path: Path, var: str, app_id: str, target: dict, deltas: list, *,
                       create: bool, render_fn, field_order: tuple,
                       alphabetical: bool, blank_sep: bool) -> dict:
    """Moteur d'écriture COMMUN des registres dict (APP_CATALOG, GENERIC_APPS) :
    create (entrée générée marquée) / régénération entière si entrée marquée (union des
    littéraux relus du fichier + facette en cours) / chirurgie champ par champ si entrée
    écrite main (expression et multi-ligne REFUSÉES). Garde `compile()` avant écriture."""
    import re
    lines = path.read_text(encoding='utf-8').split('\n')
    lo, hi = _dict_bounds(lines, var)
    span = _entry_span(lines, app_id, lo, hi)
    changed, skipped = [], []

    if create:
        if span is not None:
            return {'error': "entrée déjà présente — l'état a changé depuis le plan, relancer"}
        pos = hi
        if alphabetical:
            # APP_CATALOG est alphabétique — et la couleur dérivée dépend du rang, donc
            # l'ordre n'est pas cosmétique.
            for i in range(lo, hi):
                m = re.match(r"    '([a-z0-9_]+)': \{", lines[i])
                if m and m.group(1) > app_id:
                    pos = i
                    break
        lines[pos:pos] = render_fn(app_id, target)
        changed = [c for c in target if target.get(c) not in (None, '', [])]
    elif _GEN_MARK.format(app_id=app_id) in lines[span[0]]:
        # entrée à nous : régénération entière — UNION des champs littéraux déjà écrits
        # (toutes facettes confondues, relus du FICHIER) et des champs de la facette en cours.
        merged = {c: v for c, v in (_entry_fields_from_file(path, var, app_id) or {}).items()
                  if (field_order is None or c in field_order) and v is not _NONLITERAL}
        merged.update(target)
        fin = span[1]
        vide = 1 if blank_sep and fin + 1 < len(lines) and lines[fin + 1].strip() == '' else 0
        lines[span[0]:fin + 1 + vide] = render_fn(app_id, merged)
        changed = list(deltas)
    else:
        # entrée écrite MAIN : chirurgie champ par champ, jamais de réécriture du bloc
        # (il porte les champs des autres facettes et leurs commentaires d'audit)
        fichier = _entry_fields_from_file(path, var, app_id) or {}
        for champ in deltas:
            span = _entry_span(lines, app_id, *_dict_bounds(lines, var))  # re-borne à chaque édition
            existant = fichier.get(champ, None)
            if existant is _NONLITERAL:
                # valeur écrite main = expression (IMAGE_EXTENSIONS + …) : la remplacer par un
                # littéral détruirait l'intention — écart à trancher (déclarer / porter / trou
                # de route), pas à écraser.
                skipped.append({'field': champ,
                                'reason': "expression non littérale — édition refusée"})
                continue
            if target.get(champ) is None:
                # suppression d'une déclaration sur entrée main : geste humain, pas moteur
                skipped.append({'field': champ,
                                'reason': "retrait d'un champ déclaré main — refusé"})
                continue
            val = tuple(target[champ]) if isinstance(target[champ], list) else target[champ]
            pat = re.compile(rf"^(\s{{8}}'{champ}':\s+)(.*)$")
            for i in range(span[0] + 1, span[1]):
                m = pat.match(lines[i])
                if m:
                    mm = re.match(r"(.*?,)(\s*#.*)?$", m.group(2))
                    comment = (mm.group(2) or '') if mm else ''
                    lines[i] = f"{m.group(1)}{val!r},{comment}"
                    changed.append(champ)
                    break
            else:
                if champ in fichier:
                    # présent mais pas sur UNE ligne éditable (littéral multi-ligne) : on
                    # n'insère pas un doublon de clé, on refuse.
                    skipped.append({'field': champ,
                                    'reason': "valeur multi-ligne — édition refusée"})
                    continue
                lines.insert(span[0] + 1, f"        '{champ}': {val!r},")
                changed.append(champ)

    nouveau = '\n'.join(lines)
    compile(nouveau, str(path), 'exec')     # garde-fou : ne JAMAIS écrire un registre insyntaxique
    path.write_text(nouveau, encoding='utf-8')
    out = {'applied': {c: target.get(c) for c in changed}, 'changed': sorted(set(changed)),
           'file': str(path)}
    if skipped:
        out['skipped'] = skipped
    return out


def _write_catalog_fields(app_id: str, target: dict, deltas: list, *, create: bool) -> dict:
    return _write_dict_fields(_registry_path(), 'APP_CATALOG', app_id, target, deltas,
                              create=create, render_fn=_render_entry_lines,
                              field_order=CATALOG_FIELD_ORDER, alphabetical=True, blank_sep=True)


def _write_runner_fields(app_id: str, target: dict, deltas: list, *, create: bool) -> dict:
    return _write_dict_fields(_runner_path(), 'GENERIC_APPS', app_id, target, deltas,
                              create=create, render_fn=_render_runner_entry_lines,
                              field_order=STUDIO_FIELDS, alphabetical=False, blank_sep=False)


@transaction.atomic
def un_write_back_app(manifest: dict, *, apply: bool = False) -> dict:
    """
    Réversibilité : retire la politique DB projetée (→ retombe sur le seed `DEFAULT_APP_ACCESS`)
    et, si l'entrée APP_CATALOG a été GÉNÉRÉE par write_back (marqueur `_GEN_MARK` en tête de
    bloc), la retire aussi. Une entrée écrite main n'est JAMAIS supprimée — même contrat que
    `un_write_back_library` qui refuse de retirer une librairie installée.

    Signature ALIGNÉE sur les autres kinds le 2026-08-05 (`(manifest, *, apply=False) -> dict`).
    Elle appliquait auparavant sans dry-run et rendait un `bool` : un appelant générique itérant
    sur les kinds obtenait donc un essai à blanc pour `library` et une suppression immédiate ici.
    """
    from wama.accounts.models import AppAccessPolicy

    app_id = manifest.get('key')
    qs = AppAccessPolicy.objects.filter(app_id=app_id)
    n = qs.count()

    cibles = (('catalog_entry', _registry_path(), 'APP_CATALOG', True, _entry_span),
              ('runner_entry', _runner_path(), 'GENERIC_APPS', False, _entry_span),
              ('modes_entry', _modes_path(), 'APP_MODES', True, _entry_span),
              ('prompts_entry', _metadata_path(), 'PROMPT_TARGETS', False, _value_entry_span))
    generes = {}
    for nom, path, var, _sep, span_fn in cibles:
        lines = path.read_text(encoding='utf-8').split('\n')
        span = span_fn(lines, app_id, *_dict_bounds(lines, var))
        generes[nom] = span is not None and _GEN_MARK.format(app_id=app_id) in lines[span[0]]

    # params.py / urls.py générés = des FICHIERS (pas des entrées de dict) : retirables s'ils
    # portent le marqueur.
    from ..codegen.urls_gen import urls_file_path
    fichiers = {}
    for nom_f, p in (('params_file', _params_file_path(_params_module_name(manifest))),
                     ('urls_file', urls_file_path(app_id))):
        fichiers[nom_f] = (p, p.is_file()
                           and _GEN_MARK.format(app_id=app_id)
                           in p.read_text(encoding='utf-8')[:600])

    if not apply:
        return {'app': app_id, 'would_remove': n,
                **{f'would_remove_{nom}': g for nom, g in generes.items()},
                **{f'would_remove_{nom_f}': g for nom_f, (_p, g) in fichiers.items()}}
    qs.delete()
    out = {'app': app_id, 'removed': n}
    for nom_f, (p, genere) in fichiers.items():
        out[f'{nom_f}_removed'] = False
        if genere:
            p.unlink()
            out[f'{nom_f}_removed'] = True
    for nom, path, var, blank_sep, span_fn in cibles:
        out[f'{nom}_removed'] = False
        if not generes[nom]:
            continue
        lines = path.read_text(encoding='utf-8').split('\n')
        span = span_fn(lines, app_id, *_dict_bounds(lines, var))
        if span is None:
            continue
        fin = span[1]
        vide = 1 if blank_sep and fin + 1 < len(lines) and lines[fin + 1].strip() == '' else 0
        del lines[span[0]:fin + 1 + vide]
        nouveau = '\n'.join(lines)
        compile(nouveau, str(path), 'exec')
        path.write_text(nouveau, encoding='utf-8')
        out[f'{nom}_removed'] = True
    return out


def strip_app_declarations(manifest: dict, *, apply: bool = False) -> dict:
    """Geste de HARNAIS (`app_regen_check`, route §10.3) — bac à sable git SEULEMENT.

    Retire du CODE les déclarations que `write_back_app` sait régénérer (entrée APP_CATALOG,
    GENERIC_APPS, APP_MODES, PROMPT_TARGETS, fichier params.py), qu'elles soient écrites main
    ou générées : c'est l'inverse ASSUMÉ du contrat du moteur (qui ne touche jamais une entrée
    main) — on supprime l'existant POUR le régénérer et juger l'app régénérée sur pièces
    (protocole de la « passe intégrée » du pilote converter, 2026-08-11). Ne touche JAMAIS la
    DB (`access` reste). Ne retire que ce que le manifeste fourni sait reconstruire (facettes
    présentes dans le body). Garde `compile()` comme partout ; la restauration est l'affaire
    de l'appelant (git restore)."""
    app_id = manifest.get('key')
    body = manifest.get('body') or {}
    cibles = (
        ('catalog_entry', _registry_path(), 'APP_CATALOG', True, _entry_span,
         bool(body.get('identity') or body.get('ports') or body.get('capabilities'))),
        ('runner_entry', _runner_path(), 'GENERIC_APPS', False, _entry_span,
         bool(body.get('studio'))),
        ('modes_entry', _modes_path(), 'APP_MODES', True, _entry_span,
         bool(body.get('modes'))),
        ('prompts_entry', _metadata_path(), 'PROMPT_TARGETS', False, _value_entry_span,
         bool((body.get('prompts') or {}).get('targets'))),
    )
    out = {'app': app_id, 'files': []}
    for nom, path, var, blank_sep, span_fn, regenerable in cibles:
        if not regenerable:
            out[nom] = 'hors périmètre (facette absente du manifeste)'
            continue
        lines = path.read_text(encoding='utf-8').split('\n')
        span = span_fn(lines, app_id, *_dict_bounds(lines, var))
        if span is None:
            out[nom] = 'déjà absent'
            continue
        out['files'].append(str(path))
        if not apply:
            out[nom] = f'à retirer (lignes {span[0] + 1}-{span[1] + 1})'
            continue
        fin = span[1]
        vide = 1 if blank_sep and fin + 1 < len(lines) and lines[fin + 1].strip() == '' else 0
        del lines[span[0]:fin + 1 + vide]
        nouveau = '\n'.join(lines)
        compile(nouveau, str(path), 'exec')
        path.write_text(nouveau, encoding='utf-8')
        out[nom] = 'retiré'
    if _params_facet(manifest):
        p = _params_file_path(_params_module_name(manifest))
        if not p.is_file():
            out['params_file'] = 'déjà absent'
        else:
            out['files'].append(str(p))
            if apply:
                p.unlink()
                out['params_file'] = 'retiré'
            else:
                out['params_file'] = 'à retirer'
    else:
        out['params_file'] = 'hors périmètre (facette absente du manifeste)'

    # urls.py (gabarit A1) : strippé SEULEMENT si la facette sait le régénérer en entier
    # (toutes les routes couvertes par ROUTE_TABLE ∪ extra_routes) — jamais de strip partiel.
    from ..codegen.urls_gen import routes_target, urls_file_path
    cible, manquantes = routes_target(manifest)
    p = urls_file_path(app_id)
    if not cible or manquantes:
        out['urls_file'] = ('hors périmètre (routes non couvertes : '
                            + ', '.join(manquantes[:8]) + ')') if manquantes else \
                           'hors périmètre (facette processing sans endpoints)'
    elif not p.is_file():
        out['urls_file'] = 'déjà absent'
    else:
        out['files'].append(str(p))
        if apply:
            p.unlink()
            out['urls_file'] = 'retiré'
        else:
            out['urls_file'] = 'à retirer'
    return out


register_kind(ManifestKind(
    kind='app',
    validate=validate_app_body,
    extract=extract_app,
    write_back=write_back_app,
    un_write_back=un_write_back_app,
    description="Application généraliste WAMA (8 facettes). Extract complet ; PROJECTION partielle "
                "(PROJECTED_FACETS) : `access`→AppAccessPolicy (DB) + `identity`→APP_CATALOG (code, "
                "blocs marqués réversibles), le reste = code-gen.",
))
