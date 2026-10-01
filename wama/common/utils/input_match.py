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
                     task: Optional[str] = None) -> Dict[str, Dict[str, Any]]:
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
    """
    strip = key or (lambda mk: mk.split(':', 1)[-1])
    if task:
        strip = key or (lambda mk: mk)      # les options portent la clé entière
    try:
        from wama.model_manager.models import AIModel
        meta: Dict[str, Dict[str, Any]] = {}
        if task:
            from wama.model_manager.services import get_registry_models
            _choices, _info = get_registry_models(None, task=task)
            cibles = AIModel.objects.filter(model_key__in=[c[0] for c in _choices])
        else:
            cibles = AIModel.objects.filter(source=source, is_proposed=False)
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
