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
# Le reste des facettes `backend=code` part dans `codegen_required`. Le tri code/db vient de
# `projection.FACET_TARGETS` (source unique) — l'ancienne liste locale codée en dur avait divergé
# (elle omettait capabilities/modes et citait models/prompts), corrigé 2026-08-11.
PROJECTED_FACETS = ('access', 'identity', 'ports', 'capabilities', 'studio')


def write_back_app(manifest: dict, *, apply: bool = False) -> dict:
    """Projette le manifeste `app` vers l'état committé. `apply=False` = DRY-RUN (retourne le plan) ;
    `apply=True` = écrit (idempotent, réversible ; transactionnel pour la DB, garde `compile()`
    pour le code). Facettes écrites : `access` (DB) + `identity`/`ports`/`capabilities`
    (code, entrée APP_CATALOG — moteur commun, champs disjoints par facette)."""
    from ..projection import FACET_TARGETS   # import tardif : source unique du tri code/db
    key = manifest.get('key')
    body = manifest.get('body', {}) or {}
    out = {
        'app': key,
        'access': _project_access(key, body.get('access') or {}, apply=apply),
    }
    if body.get('identity'):
        out['identity'] = _project_identity(manifest, apply=apply)
    if body.get('ports'):
        out['ports'] = _project_ports(manifest, apply=apply)
    if body.get('capabilities'):
        out['capabilities'] = _project_capabilities(manifest, apply=apply)
    if body.get('studio'):
        out['studio'] = _project_studio(manifest, apply=apply)
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
                  if c in field_order and v is not _NONLITERAL}
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

    cibles = (('catalog_entry', _registry_path(), 'APP_CATALOG', True),
              ('runner_entry', _runner_path(), 'GENERIC_APPS', False))
    generes = {}
    for nom, path, var, _sep in cibles:
        lines = path.read_text(encoding='utf-8').split('\n')
        span = _entry_span(lines, app_id, *_dict_bounds(lines, var))
        generes[nom] = span is not None and _GEN_MARK.format(app_id=app_id) in lines[span[0]]

    if not apply:
        return {'app': app_id, 'would_remove': n,
                **{f'would_remove_{nom}': g for nom, g in generes.items()}}
    qs.delete()
    out = {'app': app_id, 'removed': n}
    for nom, path, var, blank_sep in cibles:
        out[f'{nom}_removed'] = False
        if not generes[nom]:
            continue
        lines = path.read_text(encoding='utf-8').split('\n')
        span = _entry_span(lines, app_id, *_dict_bounds(lines, var))
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
