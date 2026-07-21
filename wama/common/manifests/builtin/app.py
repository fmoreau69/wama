"""
Kind `app` — le plus riche (8 facettes, cf. WAMA_MANIFEST_SPEC §3).

`extract_app(app_id)` LIT l'état courant des registres épars et produit UN manifeste consolidé
(enveloppe + body). C'est la 1re moitié du ROUND-TRIP : réinjecter ce manifeste et le régénérer en
sandbox, puis diffe contre l'app réelle → les écarts révèlent trous du schéma ET mécanismes non
généralisés (spec §4).

Posture prudente : `project`/`un_project` (write-back dans les registres) NE sont PAS implémentés ici
(chantier ultérieur — écrire dans APP_CATALOG = code-gen, pas une écriture DB). Le kind est donc
« extract + verify only » pour l'instant : on stocke, on diffe, on ne réécrit pas les briques.
"""

from __future__ import annotations

from typing import Any, Optional

from ..kinds import ManifestKind, register_kind

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

# Endpoints standard (convention §3) — cible, générés par projection à terme.
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
    if 'params' in body and not isinstance(body['params'], list):
        errs.append("params doit être une liste")
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
    body['capabilities'] = _capabilities(cat)

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
    body['processing'] = _processing(cat)

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
        'body': body,
    }


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
    if isinstance(raw, dict) and ('inputs' in raw or 'outputs' in raw):
        return {'inputs': list(raw.get('inputs', [])), 'outputs': list(raw.get('outputs', []))}
    # certains renvoient une liste plate → séparer par présence d'un flag 'side'/'kind'
    if isinstance(raw, (list, tuple)):
        ins, outs = [], []
        for p in raw:
            (outs if isinstance(p, dict) and p.get('side') == 'output' else ins).append(p)
        return {'inputs': ins, 'outputs': outs}
    return {'inputs': [], 'outputs': []}


def _capabilities(cat: dict) -> dict:
    caps = {
        'has_batch': bool(cat.get('has_batch')),
        'batch_type': cat.get('batch_type'),
        'has_url_import': bool(cat.get('has_url_import')),
        'has_youtube': bool(cat.get('has_youtube')),
    }
    conv = cat.get('conventions')
    if conv is not None:
        d = _to_dict(conv)
        # drapeaux de capacité utiles (spec F2) — présents seulement s'ils existent dans conventions
        for k in ('settings_modal_item', 'settings_modal_batch', 'inspector', 'realtime',
                  'edit_page', 'instant_preview', 'multi_format_download', 'layout', 'anti_race'):
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
    # 1) via GENERIC_APPS (pointe params_module + params_attr = source de vérité studio)
    try:
        from wama.studio.services.generic_runner import GENERIC_APPS
        g = GENERIC_APPS.get(app_id)
        if g and g.get('params_module') and g.get('params_attr'):
            import importlib
            mod = importlib.import_module(g['params_module'])
            val = getattr(mod, g['params_attr'], None)
            if val is not None:
                return val
    except Exception:
        pass
    # 2) fallback : wama.<app>.params.PARAMS_JSON
    try:
        import importlib
        mod = importlib.import_module(f'wama.{app_id}.params')
        return getattr(mod, 'PARAMS_JSON', None)
    except Exception:
        return None


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
    """Best-effort : catalogue <APP>_MODELS dans wama.<app>.utils.model_config."""
    try:
        import importlib
        mod = importlib.import_module(f'wama.{app_id}.utils.model_config')
    except Exception:
        return None
    for attr in (f'{app_id.upper()}_MODELS', 'MODELS', 'MODEL_CATALOG'):
        val = getattr(mod, attr, None)
        if isinstance(val, dict) and val:
            return {'catalog_keys': sorted(val.keys()), 'source_attr': attr}
    return None


def _processing(cat: dict) -> dict:
    conv = _to_dict(cat.get('conventions')) if cat.get('conventions') is not None else {}
    return {
        'statuses': STATUS_VOCAB if conv.get('status_vocab') else None,
        'processing_time': bool(conv.get('processing_time')),
        'anti_race': conv.get('anti_race'),
        'endpoints': STANDARD_ENDPOINTS,   # cible conventionnelle
    }


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
    try:
        from wama.tool_api import TOOL_REGISTRY, TOOL_DESCRIPTIONS
    except Exception:
        return None
    names = {'add': f'add_to_{app_id}', 'start': f'start_{app_id}', 'status': f'get_{app_id}_status'}
    present = {role: n for role, n in names.items() if n in TOOL_REGISTRY}
    if not present:
        return None
    present['descriptions'] = {n: TOOL_DESCRIPTIONS.get(n) for n in present.values() if isinstance(n, str)}
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
    try:
        from wama.studio.services.generic_runner import GENERIC_APPS
        g = GENERIC_APPS.get(app_id)
        if not g:
            return None
        return {
            'runnable': True,
            'primary_input': g.get('primary_input'),
            'input_kinds': list(g.get('input_kinds', ())) or None,
            'input_kwarg': g.get('input_kwarg'),
            'fixed_kwargs': g.get('fixed_kwargs'),
            'auto_start': g.get('auto_start'),
            'output_type': g.get('output_type'),
        }
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


register_kind(ManifestKind(
    kind='app',
    validate=validate_app_body,
    extract=extract_app,
    description="Application généraliste WAMA (8 facettes : identité/ports/UI/modèles/traitement/"
                "prompts/permissions/studio). Extract-only pour l'instant (write-back = chantier).",
))
