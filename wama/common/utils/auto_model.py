"""
Auto-sélection de modèle — brique COMMUNE (valeur « auto » d'un select de modèle).

Généralise ce que `composer/utils/auto_model.py` (1er adopteur, 2026-07-21) et
`imager/utils/auto_model.py` (2026-08-06) portaient chacun en propre — structurellement
identiques, constat du handoff 2026-09-01 : (1) une valeur explicite se respecte telle
quelle ; (2) « auto » se résout par CAPACITÉ via `select_model_id()` (model_manager) ;
(3) un repli déclaré si le catalogue ne propose rien ; (4) ne lève jamais — refuser un
traitement pour un problème de tirage serait pire que le faire avec un modèle correct
mais non optimal.

Ce que la brique ajoute aux deux jumelles : le DOMAINE du tirage n'est plus écrit dans
l'app — c'est CELUI que le schéma déclare déjà pour ses OPTIONS (`options_query` du
paramètre `options_source='catalog'`, route F4b). Un seul domaine, deux usages : ce que
le select PROPOSE et ce que « auto » TIRE parlent du même inventaire, ils ne peuvent pas
diverger. Une app qui a porté ses options au catalogue a donc l'auto-sélection GRATUITE.

⚠ MOMENT DE LA RÉSOLUTION (règle des deux jumelles, conservée) : AU LANCEMENT de la
tâche, jamais à la création de l'item — la VRAM libre du moment fait foi ; un batch
résout chaque élément avec l'état GPU de son tour. La PRÉVISION affichée sous le select
(`predict_model_choice`) est une photo au moment du rendu, réévaluée au lancement.

⚠ SPEC DE RÉSOLUTION ≠ DOMAINE D'OPTIONS. `options_query` ne borne que le DOMAINE
(task / model_type / modality / source — lister n'est pas pouvoir choisir,
`INPUT_MODEL_MATCHING §2`). La RÉSOLUTION, elle, peut affiner par `consumes` /
`available_inputs` (surcharges au point d'appel — ex. imager img2vid) : sélectionner
n'est pas lister, le grisage expliqué ne s'applique qu'à l'UI.
"""

import logging

logger = logging.getLogger(__name__)

AUTO = 'auto'
#: Libellé de l'option « auto » servie en 1ʳᵉ position par le catalogue (décision
#: Fabien, handoff 2026-09-01). Un seul domicile — l'endpoint et les tests le citent.
AUTO_LABEL = 'Automatique — choisi au lancement'


def is_auto(value) -> bool:
    """Cette valeur demande-t-elle le tirage automatique ? (vide compris)."""
    return not value or str(value).strip().lower() == AUTO


def catalog_domain(app_id: str):
    """DOMAINE déclaré au schéma de l'app pour son select de modèle, ou None.

    Lit le paramètre `options_source='catalog'` de `params.py` (le premier — une app
    n'a qu'un select de modèle) et rend son `options_query` tel quel. C'est la même
    déclaration qui peuple le select : zéro second lieu de vérité.
    """
    from wama.common.utils.param_schema import schema_for_app
    for field in schema_for_app(app_id):
        if field.get('options_source') == 'catalog':
            return dict(field.get('options_query') or {})
    return None


def resolve_model_choice(requested, *, app_id=None, spec=None, fallback=None, **overrides):
    """Valeur finale du modèle pour un lancement : `requested` explicite, sinon tirage.

    Args:
        requested: valeur portée par l'item ('' / 'auto' → tirage ; sinon telle quelle,
                   même si elle impose un offload — choix assumé de l'utilisateur).
        app_id:    app dont le schéma déclare le domaine (`catalog_domain`).
        spec:      domaine EXPLICITE (dict) — prime sur `app_id` ; pour les apps dont la
                   correspondance item→domaine est une spécificité déclarée chez elles
                   (imager `_BY_MODE`, composer musique/ambiance).
        fallback:  rendu si le catalogue ne propose rien (première install, catalogue
                   injoignable) — typiquement le défaut du champ de modèle.
        overrides: affinages de RÉSOLUTION (`consumes`, `available_inputs`…), permis ici
                   et interdits dans `options_query` (cf. docstring de module).

    L'espace de clés du retour suit celui de la requête (règle `select_model_id`) :
    domaine avec `source` → id nu ; sans → clé catalogue entière. Ne lève jamais.
    """
    if requested and not is_auto(requested):
        return requested
    domain = dict(spec) if spec is not None else (catalog_domain(app_id) or {})
    domain.update(overrides)
    source = domain.pop('source', None)
    from wama.model_manager.services import select_model_id
    return select_model_id(source, requested=AUTO, fallback=fallback, **domain)


def predict_model_choice(spec):
    """PRÉVISION : le modèle qui serait retenu MAINTENANT pour ce domaine, ou None.

    Sert l'affichage sous le select (décision Fabien, handoff 2026-09-01) : même chemin
    que le tirage réel — VRAM libre, résidence, classement — pour que la prévision dise
    la vérité du lancement. Photo du moment : le lancement réévalue.

    Retour : {'id', 'name', 'vram_gb'} — `id` dans l'espace de clés du domaine.
    """
    key = resolve_model_choice(AUTO, spec=dict(spec or {}))
    if not key:
        return None
    source = (spec or {}).get('source')
    model_key = f'{source}:{key}' if source and ':' not in str(key) else key
    from wama.model_manager.models import AIModel
    m = AIModel.objects.filter(model_key=model_key).first()
    return {
        'id': key,
        'name': (m.name if m else str(key)),
        'vram_gb': (m.vram_gb if m else None),
    }
