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

#: Curseur de QUALITÉ — échelle CONTINUE 0-100 (décision Fabien 02/09 : « l'intention
#: n'est pas un branchement, c'est un poids dans le score » — les 3 politiques discrètes
#: de la 1ʳᵉ implémentation ne savaient désigner que 3 candidats sur N). Le barème, les
#: positions nommées (Rapide/Équilibré/Qualité) et le seuil d'offload vivent chez le
#: sélecteur (`QUALITY_PRESETS`, `QUALITY_OFFLOAD_THRESHOLD`) ; les libellés rendus et le
#: tricolore vivent dans le renderer commun `type='intent'` (wama-params.js) et le partial
#: `common/_intent_slider.html` — MÊME contrat de classes, un seul listener délégué.
#: La MÊME forme utilisateur partout ; chaque usage DÉCLINE la valeur selon ses capacités
#: (ici : choix de modèle ; converter : presets de lot ↔ slider unitaire ; anonymizer :
#: sa règle locale de floutage) — la couche d'adaptation reste locale et déclarée.
INTENT_DEFAULT = 50


def read_quality_intent(value) -> int:
    """Valeur 0-100 SÛRE depuis un POST/JSON : bornée, défaut équilibré, ne lève jamais.

    Le helper des VUES adoptantes (synthesizer, avatarizer, demain converter…) — sans lui
    chaque app réécrivait le même try/int/clamp, et un POST malformé faisait un 500.
    """
    try:
        return max(0, min(100, int(float(value))))
    except (TypeError, ValueError):
        return INTENT_DEFAULT


def posted_quality_intent(source):
    """Curseur POSTÉ (POST ou dict JSON) → entier borné, ou **None** s'il n'est pas posté ou
    posté vide — la colonne de l'item reste vide et la cascade `quality_intent_of` retombe sur
    le réglage d'app de l'utilisateur, puis 50. Différent de `read_quality_intent`, qui rend 50
    quand la valeur manque : ici « absent » et « équilibré » ne se confondent pas.

    Revérification du 2026-09-21 : imager, composer et enhancer portaient chacun cette même
    fonction sous le nom `_intent_posted` — trois copies d'un helper de vue, remontées ici.
    """
    raw = source.get('quality_intent') if hasattr(source, 'get') else None
    if raw is None or str(raw).strip() == '':
        return None
    return read_quality_intent(raw)


def preset_key_for_intent(intent) -> str:
    """La POSITION NOMMÉE la plus proche d'une valeur de curseur (`QUALITY_PRESETS` du sélecteur :
    fast 15 / balanced 50 / quality 85) — à égalité, la position la plus haute. C'est la règle
    de toute DÉCLINAISON locale à paliers (converter : preset d'encodage ; enhancer : NFE de
    Resemble) ; elle vivait chez le converter seul jusqu'au 2026-09-21."""
    from wama.model_manager.services.model_selector import QUALITY_PRESETS
    v = read_quality_intent(intent)
    return min(QUALITY_PRESETS, key=lambda p: (abs(p[2] - v), -p[2]))[0]


def intent_param(**overrides) -> dict:
    """Surcouche STANDARD du curseur de qualité pour un schéma d'app (`derive_from_model`).

    L'app déclare le champ modèle (`quality_intent`, IntegerField défaut 50) et passe
    `intent_param(dom_id=…, show_if=…)` en override. Le rendu, la liaison, le tricolore
    et les graduations de presets sont le renderer commun — rien à écrire par app.
    """
    base = dict(
        type='intent', label='Rapide ↔ Qualité', icon='fa-gauge-high',
        default=INTENT_DEFAULT, min=0, max=100, step=1,
        help="Guide le choix automatique : à gauche un modèle léger et rapide, à droite "
             "le meilleur modèle même s'il faut attendre des ressources.",
    )
    base.update(overrides)
    return base


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


def intent_field_for(app_id: str):
    """Nom du champ « curseur » déclaré au schéma de l'app (`type='intent'`), ou None.

    Le nom n'est pas imposé : `quality_intent` chez synthesizer/avatarizer/assistant,
    `precision_level` chez l'anonymizer (frontière des DONNÉES — tasks et sélecteur d'app le
    lisent). C'est le schéma qui dit lequel, comme il dit le domaine (`catalog_domain`)."""
    if not app_id:
        return None
    from wama.common.utils.param_schema import schema_for_app
    for field in schema_for_app(app_id) or []:
        if field.get('type') == 'intent':
            return field.get('name')
    return None


def quality_intent_of(item=None, app_id=None, user=None) -> int:
    """La valeur du curseur qui vaut pour CE lancement, en UN endroit (chantier C, 2026-09-20).

    Cascade : le champ de l'item déclaré au schéma (`intent_field_for`) → le réglage d'app
    de l'utilisateur (brique durable `user_settings`, même nom : une app SANS choix par item —
    reader, transcriber — porte le curseur là) → `INTENT_DEFAULT`. Bornée, ne lève jamais.
    """
    name = intent_field_for(app_id) or 'quality_intent'
    if item is not None:
        value = getattr(item, name, None)
        if value is not None and str(value).strip() != '':
            return read_quality_intent(value)
    if user is None and item is not None:
        user = getattr(item, 'user', None)
    if user is not None and getattr(user, 'pk', None) and app_id:
        try:
            from wama.common.utils.user_settings import get_user_app_setting
            value = get_user_app_setting(user, app_id, name)
            if value is not None and str(value).strip() != '':
                return read_quality_intent(value)
        except Exception:
            pass
    return INTENT_DEFAULT


def resolve_model_choice(requested, *, app_id=None, spec=None, fallback=None, item=None,
                         user=None, **overrides):
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
        item, user: (chantier C) d'où lire le CURSEUR quand l'appelant ne passe pas
                   `quality_intent` lui-même — `quality_intent_of(item, app_id, user)` ; sans
                   eux ni `quality_intent`, le tirage reste équilibré (50), comme avant.
        overrides: affinages de RÉSOLUTION (`consumes`, `available_inputs`…), permis ici
                   et interdits dans `options_query` (cf. docstring de module).

    L'espace de clés du retour suit celui de la requête (règle `select_model_id`) :
    domaine avec `source` → id nu ; sans → clé catalogue entière. Ne lève jamais.
    """
    if requested and not is_auto(requested):
        return requested
    domain = dict(spec) if spec is not None else (catalog_domain(app_id) or {})
    if 'quality_intent' not in overrides and (item is not None or user is not None):
        overrides['quality_intent'] = quality_intent_of(item, app_id, user)
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
