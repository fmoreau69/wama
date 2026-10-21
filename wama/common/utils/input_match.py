"""Appariement card d'entrée ↔ modèles — côté SERVEUR de la brique commune.

Pendant Python de `static/common/js/wama-input-match.js` (doctrine INPUT_MODEL_MATCHING.md) :
fournit aux vues d'index le contexte `input_match_meta` / `input_labels` que le template passe
à `WamaInputMatch.init()`. SOURCE UNIQUE = le catalogue `AIModel.capabilities`
(`inputs_required` / `inputs_optional`, vocabulaire canonique de `model_capabilities.py`) ;
les libellés viennent d'`INPUT_TYPES` (`app_modes.py`). Zéro hardcode par app.

Historique : logique née dans le composer (1er adopteur, `views._input_match_meta`) puis
recopiée dans l'imager (inline depuis le registry) — extraite ici (2026-08-17) au moment de
l'adoption ×7 (règle /brique : le copier-coller imminent est LE signal d'extraction).

Les politiques d'app restent dans l'app : les pseudo-modèles « auto-* » du composer (union des
entrées de leur groupe) se déclarent en POST-TRAITEMENT du dict rendu, pas ici.
"""
from __future__ import annotations

from typing import Any, Callable, Dict, Optional


def input_match_meta(source: Optional[str] = None,
                     key: Optional[Callable[[str], str]] = None,
                     extra_caps: tuple = (),
                     task: Optional[str] = None,
                     query: Optional[Dict[str, Any]] = None) -> Dict[str, Dict[str, Any]]:
    """{model_id: {label, inputs_required, inputs_optional}} depuis le CATALOGUE — fail-safe {}.

    `source` = valeur d'`AIModel.source` (le lien app↔modèles, cf. feedback_find_accessor).
    `key` = mapping model_key → id d'option du <select> de l'app ; défaut = retrait du
    préfixe `source:` (``model_key.split(':', 1)[-1]``) — surcharger si le select de l'app
    emploie un autre identifiant (ex. anonymizer : clés `anonymizer:yolo:<poids>`).
    `extra_caps` = clés de capacités supplémentaires à joindre à chaque entrée (ex. `('task',)`
    pour le post-traitement auto-* du composer) — à retirer du payload avant sérialisation
    si elles ne servent qu'au serveur.

    `task` (2026-09-01, route F4b) : borne le domaine par CAPACITÉ au lieu d'`AIModel.source`,
    et les clés rendues sont alors les clés catalogue ENTIÈRES — donc identiques aux valeurs
    d'option servies par `api/models/options/?task=…`. À employer dès qu'un select est peuplé
    par `options_source="catalog"` : ancrer la meta sur `source` pendant que les options
    viennent d'une requête par capacité produirait un appariement MUET sur tout modèle d'une
    autre source (mesuré : 3 des 7 moteurs TTS). Les deux modes doivent nommer les mêmes
    choses, sinon `WamaInputMatch` n'apparie rien et ne le dit pas.

    `query` (2026-10-13) : le DOMAINE ENTIER d'un select (`options_query` : tâche, catégorie,
    modalité…), lu comme l'endpoint de ses options — `task` seul ne bornait pas le select de
    vision du describer (`captioning,text-generation` + `modality: image`).
    """
    if task and not query:
        query = {'task': task}
    strip = key or (lambda mk: mk.split(':', 1)[-1])
    if query:
        strip = key or (lambda mk: mk)      # les options portent la clé entière
    try:
        from wama.model_manager.models import AIModel
        meta: Dict[str, Dict[str, Any]] = {}
        if query:
            from wama.model_manager.services import get_registry_models
            # Les clés de DOMAINE que l'endpoint des options lit (`api_model_options`) — et elles
            # seules : la meta nomme exactement ce que le select propose.
            domain = {k: query[k] for k in ('task', 'model_type', 'modality') if query.get(k)}
            _choices, _info = get_registry_models(query.get('source') or None, **domain)
            cibles = AIModel.objects.filter(model_key__in=[c[0] for c in _choices])
        else:
            from wama.common.sandbox import declaring_app   # une jumelle : modèles de sa source
            # Même lot que `get_registry_models` sans compte : système et publics (ROADMAP §29).
            cibles = AIModel.objects.catalogue_visible_to(None).filter(
                source=declaring_app(source), is_proposed=False)
        for m in cibles:
            caps = m.capabilities or {}
            entry: Dict[str, Any] = {
                'label': m.name or strip(m.model_key),
                'inputs_required': caps.get('inputs_required') or [],
                'inputs_optional': caps.get('inputs_optional') or [],
            }
            for k in extra_caps:
                entry[k] = caps.get(k)
            meta[strip(m.model_key)] = entry
        return meta
    except Exception:
        return {}


def select_match_meta(app_id: str, field: str, extra_caps: tuple = (),
                      inputs: bool = True) -> Dict[str, Dict[str, Any]]:
    """Meta d'appariement d'un select de modèle DÉCLARÉ au schéma de l'app — son domaine est
    celui de son `options_query`, lu là où il est déclaré, jamais recopié dans la vue.

    Extraite le 2026-10-13 au 3ᵉ consommateur : le transcriber (`task='transcription'`) et le
    reader (`OCR_SPEC`) portaient la même fonction, domaine écrit en dur dans la vue À CÔTÉ de
    celui du schéma ; le describer en aurait été la troisième copie, pour trois selects.
    « auto » reçoit l'entrée commune (`auto_entry`) quand le select sert le tirage commun
    (`options_auto=True`) ; un « auto » `silent` est la règle propre de l'app (la cascade vision
    du describer) qu'une intersection ne décrirait pas — pas d'entrée. Fail-safe {}.

    `inputs=False` : la card ne fournit PAS les entrées des modèles de ce select, son pipeline
    les compose (le describer : la consigne d'un modèle de vision, la piste son d'une vidéo).
    Les `inputs_*` du catalogue feraient alors annoncer « ⚠ Ce modèle requiert : Consigne » sous
    chaque modèle de conversation — la meta ne garde que le libellé et `extra_caps` (ses
    `modalities`, jugées par `WamaInputMatch.modalitySlot`), et pas d'« auto » d'intersection."""
    from wama.common.utils.param_schema import declared_param_schemas
    try:
        declared = declared_param_schemas(app_id) or {}
    except Exception:
        return {}
    param = next((p for params in (declared.get('schemas') or {}).values() for p in params
                  if isinstance(p, dict) and p.get('name') == field), None)
    if not param or param.get('options_source') != 'catalog' or not param.get('options_query'):
        return {}
    meta = input_match_meta(query=param['options_query'], extra_caps=extra_caps)
    if not inputs:
        return {mid: {k: v for k, v in entry.items()
                      if k not in ('inputs_required', 'inputs_optional')}
                for mid, entry in meta.items()}
    if meta and param.get('options_auto') is True:
        meta['auto'] = auto_entry(meta)
    return meta


def card_match(app_id: str, ports) -> Dict[str, Any]:
    """L'appariement de la CARD d'une app rendue À CÔTÉ de son volet généré — `{field, meta,
    labels, ports}`, ou `{}` s'il n'y a rien à apparier (2026-10-21, modale d'une card d'entrée du
    Studio : `STUDIO_VISION §Entrées du Studio`).

    `field` : le select de modèle du schéma (`auto_model.catalog_field`, celui que le tirage lit) ;
    `meta` : son domaine (`select_match_meta`) ; `ports` : les ports FICHIER de la card que ce
    select JUGE — ceux qu'au moins un de ses modèles nomme. Un port qu'aucun de ses modèles ne
    nomme alimente un autre moteur ou une autre étape (l'audio de l'enhancer et son moteur audio,
    le fichier du describer et sa cascade) : le juger ici griserait TOUS les modèles du select
    (mesuré le 2026-10-21). Les entrées de la meta sont bornées à ces ports — la ligne d'état ne
    parle que de ce que la card fournit.
    `ports` (argument) : la forme de `studio_node_ports()['inputs']`. Fail-safe {}."""
    from wama.common.utils.auto_model import catalog_field
    try:
        field = catalog_field(app_id)
    except Exception:
        return {}
    if not field:
        return {}
    meta = select_match_meta(app_id, field.get('name'))
    named = {t for entry in meta.values()
             for t in (entry.get('inputs_required') or []) + (entry.get('inputs_optional') or [])}
    judged = [p.get('id') for p in ports or []
              if p.get('group') != 'prompt' and p.get('id') in named]
    if not judged:
        return {}
    bounded = {mid: {**entry,
                     'inputs_required': [t for t in entry.get('inputs_required') or [] if t in judged],
                     'inputs_optional': [t for t in entry.get('inputs_optional') or [] if t in judged]}
               for mid, entry in meta.items()}
    return {'field': field.get('name'), 'meta': bounded, 'labels': input_labels(), 'ports': judged}


def auto_entry(meta: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """Entrée du pseudo-modèle « auto » d'un select : intersection des requis, union du
    reste en optionnel (l'auto accepte ce qu'au moins UN candidat accepte). Extrait au 2ᵉ
    consommateur (transcriber puis reader, 2026-08-17) ; les politiques par GROUPE
    (auto-music/auto-sfx du composer) restent dans l'app."""
    if not meta:
        return {'inputs_required': [], 'inputs_optional': []}
    reqs = [set(e.get('inputs_required') or []) for e in meta.values()]
    alls = [set(e.get('inputs_required') or []) | set(e.get('inputs_optional') or [])
            for e in meta.values()]
    req = set.intersection(*reqs)
    return {'inputs_required': sorted(req),
            'inputs_optional': sorted(set().union(*alls) - req)}


def work_token_for(path: str) -> Optional[str]:
    """Le jeton de TRAVAIL qu'un fichier fournit, d'après sa NATURE (2026-09-30) — ou None.

    Lu dans `INPUT_TYPES` : le jeton de groupe `travail` dont l'`accept` est la catégorie du
    fichier (`work_image` pour une photo, `work_object3d` pour un GLB, `work_audio` pour un son).
    C'est ce qui traduit « ce qu'on a » en `available_inputs` pour le tirage commun
    (`resolve_model_choice`) — plutôt qu'un aiguillage par extension écrit dans chaque app.
    Un fichier sans jeton dédié à sa nature rend None (`work_file`, générique, ne tranche rien)."""
    from wama.common.app_registry import category_of_path
    from wama.common.utils.app_modes import INPUT_TYPES
    category = category_of_path(path)
    for token, spec in INPUT_TYPES.items():
        if spec.get('port') == 'travail' and spec.get('accept') == category:
            return token
    return None


def input_attribute_verdict(capabilities: Optional[dict], token: str, path: str):
    """`(état, raison)` : ce FICHIER satisfait-il ce que le modèle exige des ATTRIBUTS de l'entrée
    `token` ? — capacité `input_attributes` (2026-09-30), jugée par `natures.asset_accepts`.

    Le rôle ne suffit pas toujours : un maillage TripoSR est bien un `work_object3d`, mais sans
    squelette ni visage TalkingHead n'en fera jamais parler personne. Les attributs sont MESURÉS
    dans le fichier (`media_probe`) : le verdict ne dépend pas de ce que l'utilisateur a saisi.
    États : `compatible` / `warning` (souhaité manquant) / `incompatible` (requis manquant) —
    la raison NOMME ce qui manque, pour être affichée telle quelle. Sans exigence déclarée :
    `('compatible', '')`, on ne juge jamais ce que le modèle ne demande pas.
    """
    from wama.media_library.natures import COMPATIBLE, AssetSpec, asset_accepts, resolve_asset_type

    wanted = ((capabilities or {}).get('input_attributes') or {}).get(token) or {}
    if not wanted:
        return COMPATIBLE, ''
    from wama.common.app_registry import category_of_path
    from wama.common.utils.media_probe import probe_media
    try:
        nature = resolve_asset_type(category_of_path(path), filename=str(path))
    except ValueError as exc:
        from wama.media_library.natures import INCOMPATIBLE
        return INCOMPATIBLE, str(exc)
    attributes = (probe_media(str(path)) or {}).get('attributes') or {}
    spec = AssetSpec(require=dict(wanted.get('require') or {}),
                     prefer=dict(wanted.get('prefer') or {}))
    return asset_accepts(spec, nature, attributes)


def app_attribute_verdict(source: str, token: str, path: str):
    """`(état, raison)` pour une APP : ce fichier convient-il à AU MOINS UN de ses modèles qui
    consomment `token` ? (2026-09-30) — le jugement à poser DÈS L'AJOUT d'un élément, avant que
    le tirage ne choisisse le modèle au lancement.

    Le meilleur état l'emporte (compatible > avertissement > refus) ; la raison est celle du
    meilleur. Aucun modèle de l'app ne consomme ce jeton, ou aucun n'exige d'attribut : rien à
    juger, `('compatible', '')`. Les étapes internes (`pipeline_stage`) ne comptent pas."""
    from wama.common.app_registry import app_model_capabilities
    from wama.media_library.natures import COMPATIBLE, INCOMPATIBLE, WARNING
    # L'inventaire des modèles de l'app est CELUI de ses ports (`app_model_capabilities`,
    # 2026-10-01) : un modèle que le select propose sans être de la source est jugé aussi.
    rows = app_model_capabilities(source)
    rank = {COMPATIBLE: 0, WARNING: 1, INCOMPATIBLE: 2}
    best = None
    for caps in rows:
        caps = caps or {}
        if caps.get('pipeline_stage'):
            continue
        if token not in set(caps.get('inputs_required') or []) | set(caps.get('inputs_optional') or []):
            continue
        verdict = input_attribute_verdict(caps, token, path)
        if best is None or rank[verdict[0]] < rank[best[0]]:
            best = verdict
    return best or (COMPATIBLE, '')


def input_labels() -> Dict[str, str]:
    """{input_id: libellé} depuis INPUT_TYPES (source déclarée commune) — fail-safe {}."""
    try:
        from wama.common.utils.app_modes import INPUT_TYPES
        return {k: v.get('label', k) for k, v in INPUT_TYPES.items()}
    except Exception:
        return {}
