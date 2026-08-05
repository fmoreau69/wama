"""
Kind `app` — le plus riche (8 facettes, cf. WAMA_MANIFEST_SPEC §3).

`extract_app(app_id)` LIT l'état courant des registres épars et produit UN manifeste consolidé
(enveloppe + body). C'est la 1re moitié du ROUND-TRIP : réinjecter ce manifeste et le régénérer en
sandbox, puis diffe contre l'app réelle → les écarts révèlent trous du schéma ET mécanismes non
généralisés (spec §4).

Posture prudente : `write_back`/`un_write_back` (write-back dans les registres) NE sont PAS implémentés ici
(chantier ultérieur — écrire dans APP_CATALOG = code-gen, pas une écriture DB). Le kind est donc
« extract + verify only » pour l'instant : on stocke, on diffe, on ne réécrit pas les briques.
"""

from __future__ import annotations

import logging
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
    """Schéma de params de l'app — via l'accesseur COMMUN, pas une résolution recopiée.

    `schema_for_app()` (`common/utils/param_schema.py`) applique la même règle qu'avant
    (pointeur déclaratif `GENERIC_APPS.params_module/params_attr`, repli sur la convention
    `wama.<app>.params.PARAMS_JSON`) mais en un seul endroit, partagé avec le runner studio
    et la surface outils. Retour `None` (et pas `[]`) quand l'app n'en déclare pas, pour que
    la facette reste ABSENTE du manifeste plutôt que présente et vide.
    """
    from wama.common.utils.param_schema import schema_for_app
    return schema_for_app(app_id) or None


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
    return {
        'statuses': STATUS_VOCAB if conv.get('status_vocab') else None,
        'processing_time': bool(conv.get('processing_time')),
        'anti_race': conv.get('anti_race'),
        'endpoints': STANDARD_ENDPOINTS,   # cible conventionnelle
        'ingest': _ingest(app_id),         # F5/trou #14 : projette vers WAMA_INGEST (source_ingest.py)
    }


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


# ── PROJECTION (write-back) ──────────────────────────────────────────────────────
# Propriété de sûreté (SPEC §2.1) : rien ne lit le manifeste en direct ; la projection est un geste
# EXPLICITE, jamais automatique. AUJOURD'HUI, une SEULE facette est projetable au RUNTIME : `access`
# → `AppAccessPolicy` (DB). Les autres facettes = CODE-GEN (non écrites, rapportées dans `codegen_required`).
def write_back_app(manifest: dict, *, apply: bool = False) -> dict:
    """Projette le manifeste `app` vers l'état committé. `apply=False` = DRY-RUN (retourne le plan) ;
    `apply=True` = écrit (idempotent, transactionnel, réversible). Seule `access` écrit au runtime."""
    key = manifest.get('key')
    body = manifest.get('body', {}) or {}
    return {
        'app': key,
        'access': _project_access(key, body.get('access') or {}, apply=apply),
        'codegen_required': [f for f in ('identity', 'ports', 'params', 'inspector', 'models',
                                         'processing', 'prompts', 'tool_api', 'studio') if body.get(f)],
    }


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


@transaction.atomic
def un_write_back_app(manifest: dict, *, apply: bool = False) -> dict:
    """
    Réversibilité : retire la politique DB projetée → retombe sur le seed `DEFAULT_APP_ACCESS`.

    Signature ALIGNÉE sur les autres kinds le 2026-08-05 (`(manifest, *, apply=False) -> dict`).
    Elle appliquait auparavant sans dry-run et rendait un `bool` : un appelant générique itérant
    sur les kinds obtenait donc un essai à blanc pour `library` et une suppression immédiate ici.
    """
    from wama.accounts.models import AppAccessPolicy

    qs = AppAccessPolicy.objects.filter(app_id=manifest.get('key'))
    n = qs.count()
    if not apply:
        return {'app': manifest.get('key'), 'would_remove': n}
    qs.delete()
    return {'app': manifest.get('key'), 'removed': n}


register_kind(ManifestKind(
    kind='app',
    validate=validate_app_body,
    extract=extract_app,
    write_back=write_back_app,
    un_write_back=un_write_back_app,
    description="Application généraliste WAMA (8 facettes). Extract complet ; PROJECTION partielle : "
                "seule `access`→AppAccessPolicy écrit au runtime (idempotent/réversible), le reste = code-gen.",
))
