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
    """Cette valeur demande-t-elle le tirage automatique ? (vide compris, et l'« auto » borné à
    une tâche — `auto:text-to-music`, l'« auto » d'un groupe de select)."""
    from wama.common.utils.model_keys import auto_task
    return not value or str(value).strip().lower() == AUTO or bool(auto_task(str(value)))


def candidates_with(capability: str, value, q=None, **filters) -> list:
    """Clés catalogue des modèles du domaine `filters` (champs d'`AIModel` ou `capabilities__…`,
    ou un `Q` — celui d'un domaine déclaré, `model_selector.domain_q`) dont la capacité
    `capability` vaut `value` — [] si la valeur est vide ou le catalogue muet.

    C'est le BESOIN qui filtre avant le classement : ×2 et ×4 ne sont pas deux qualités, ce
    sont deux résultats (`scale`). Remonté de l'enhancer (`media_candidates`, 2026-09-21) au
    2ᵉ consommateur — le post-traitement de sortie commun (`output_formats`, 2026-09-30).
    Les nombres se comparent en nombres (`2` == `2.0` == `'2'`), le reste en texte."""
    if value in (None, ''):
        return []

    def _same(a, b):
        try:
            return float(a) == float(b)
        except (TypeError, ValueError):
            return str(a) == str(b)

    try:
        from wama.model_manager.models import AIModel
        rows = AIModel.objects.filter(*([q] if q is not None else []), **filters)
        rows = rows.only('model_key', 'capabilities')
        return [m.model_key for m in rows
                if _same((m.capabilities or {}).get(capability), value)]
    except Exception as exc:                          # catalogue absent : on ne filtre pas
        logger.debug('[auto_model] candidats %s=%s indisponibles : %s', capability, value, exc)
        return []


def catalog_domain(app_id: str):
    """DOMAINE déclaré au schéma de l'app pour son select de modèle, ou None.

    Lit le paramètre `options_source='catalog'` de `params.py` (le premier — une app
    n'a qu'un select de modèle) et rend son `options_query` tel quel. C'est la même
    déclaration qui peuple le select : zéro second lieu de vérité.
    """
    field = catalog_field(app_id)
    return dict(field.get('options_query') or {}) if field is not None else None


def catalog_field(app_id: str):
    """Le paramètre `options_source='catalog'` du schéma de l'app (le premier), ou None — le
    domaine ET ses drapeaux d'UI (`options_cloud`…), lus au même endroit."""
    from wama.common.utils.param_schema import schema_for_app
    for field in schema_for_app(app_id) or []:
        if field.get('options_source') == 'catalog':
            return field
    return None


def catalog_fields(app_id: str) -> list:
    """TOUS les paramètres `options_source='catalog'` de l'app — ceux de chacun de ses schémas
    (`declared_param_schemas` : l'imager IMAGE+VIDÉO, l'enhancer MÉDIA+AUDIO), le principal à défaut.
    Pour qui doit savoir quels réglages CHOISISSENT un modèle, pas seulement le premier (2026-10-28 :
    comparer deux lignes d'exécution « le modèle seul changé », `model_quality.defect_evidence`)."""
    from wama.common.utils.param_schema import declared_param_schemas, schema_for_app
    declared = declared_param_schemas(app_id)
    schemas = list((declared or {}).get('schemas', {}).values()) or [schema_for_app(app_id) or []]
    seen, fields = set(), []
    for schema in schemas:
        for field in schema or []:
            if (isinstance(field, dict) and field.get('options_source') == 'catalog'
                    and field.get('name') not in seen):
                seen.add(field.get('name'))
                fields.append(field)
    return fields


def declared_cloud_keys(app_id: str, user):
    """Les modèles DISTANTS que le tirage AUTOMATIQUE de `app_id` peut retenir pour `user`, ou
    None (aucun : le tirage reste local, comme avant le 2026-09-30).

    Le schéma DÉCLARE l'ouverture (`options_cloud`, le drapeau qui ajoute déjà les distants aux
    OPTIONS du select) : un seul lieu de vérité pour « ce que le select propose » et « ce que
    auto tire ». Le PROFIL borne (`allowed_cloud_keys(automatic=True)`) : « cloud autorisé » ouvre
    le tirage automatique, « cloud si saturé » seulement le choix manuel (tant que le signal de
    saturation n'existe pas), « 100 % local » rien — décision de Fabien du 15/09, portée au commun
    le 30/09 (jusque-là seul l'assistant passait `cloud_keys`, à la main)."""
    field = catalog_field(app_id) if app_id else None
    if not field or not field.get('options_cloud') or user is None:
        return None
    try:
        from wama.model_manager.services.cloud_models import allowed_cloud_keys
        return allowed_cloud_keys(user, automatic=True) or None
    except Exception:
        logger.debug('[auto_model] modèles distants autorisés illisibles', exc_info=True)
        return None


#: Affinages du tirage qu'un schéma peut déclarer (`options_resolution`) — les autres clés sont
#: ignorées : une borne de DOMAINE n'a rien à faire là (elle vit dans `options_query`).
#: `needs` (2026-10-14) : le BESOIN de l'élément, `{capacité: champ}` — le modèle tiré doit porter
#: la capacité à la valeur du champ (enhancer : `scale` = `upscale_factor`). Les deux autres sont
#: des constantes du schéma ; celui-ci se LIT sur l'élément au lancement, dans le formulaire pour
#: la prévision (le navigateur transmet `needs=<capacité>:<valeur>,…`).
#: `voice` (2026-10-28) : le CHAMP de voix de l'élément — la voix choisie borne le tirage aux
#: modèles qui savent la dire (`voice_refs.voice_draw_constraint`), au lancement comme pour la
#: prévision (le navigateur transmet `voice=<valeur>`).
RESOLUTION_KEYS = ('priority', 'available_inputs', 'needs', 'voice')
#: Les affinages qui nomment un CHAMP de l'élément : leur valeur se lit sur lui, jamais au schéma.
FIELD_RESOLUTION_KEYS = ('needs', 'voice')


def declared_resolution(app_id: str) -> dict:
    """Les affinages du tirage « auto » DÉCLARÉS au schéma de `app_id` (`options_resolution`),
    {} sinon. Le lancement les lit ici ; la prévision les reçoit du navigateur, qui les tient du
    même schéma — c'est ce qui fait dire la même chose aux deux (2026-10-01). `needs` garde sa
    forme `{capacité: champ}`."""
    field = catalog_field(app_id) if app_id else None
    declared = (field or {}).get('options_resolution') or {}
    return {k: (dict(v) if isinstance(v, dict) else v if isinstance(v, str) else list(v))
            for k, v in declared.items() if k in RESOLUTION_KEYS and v}


def read_needs(text: str) -> dict:
    """`needs` tel que le navigateur le transmet (`scale:4,autre:x`) → `{capacité: valeur}`."""
    pairs = (part.split(':', 1) for part in str(text or '').split(',') if ':' in part)
    return {cap.strip(): value.strip() for cap, value in pairs if cap.strip() and value.strip()}


def read_refinement(key: str, text: str):
    """Un affinage du tirage tel que le navigateur le transmet à la prévision : `needs` en paires,
    `voice` en valeur, les autres en liste (`a,b`)."""
    if key == 'needs':
        return read_needs(text)
    if key == 'voice':
        return str(text or '').strip()
    return [v for v in str(text or '').split(',') if v]


def narrow_by_voice(domain: dict, voice: str, fallback=None):
    """Applique au domaine du tirage ce que la voix choisie impose (`voice_draw_constraint`) et rend
    le repli à employer. Les capacités s'AJOUTENT, les candidats se CROISENT avec ceux de l'appelant
    (l'assistant borne au temps réel) — un croisement vide garde ceux de la voix : la voix choisie
    l'emporte sur la vitesse. Clés dans l'espace du domaine (id nu quand une source le borne)."""
    if not voice:
        return fallback
    from wama.common.tts.voice_refs import voice_draw_constraint
    constraint = voice_draw_constraint(voice)
    if constraint.get('requires'):
        domain['requires'] = list(dict.fromkeys(list(domain.get('requires') or [])
                                                + constraint['requires']))
    keys = constraint.get('candidates')
    if keys:
        prefix = f"{domain['source']}:" if domain.get('source') else ''
        keys = [k[len(prefix):] if prefix and k.startswith(prefix) else k for k in keys]
        mine = domain.get('candidates')
        domain['candidates'] = ([k for k in mine if k in keys] or keys) if mine else keys
        # Repli : un modèle qui DIT la voix. Si aucun ne tient au budget ou n'est installé, la tâche
        # le prend quand même et la route l'installe (`ensure_model`), au lieu de tirer un moteur
        # qui dirait une autre voix sans le dire.
        fallback = keys[0]
    return fallback


def need_candidates(needs: dict, domain: dict):
    """Les clés du DOMAINE qui satisfont TOUS les besoins `{capacité: valeur}` — None quand aucun
    besoin n'est posé, ou qu'aucun modèle du domaine n'y répond : le domaine entier reste alors au
    tirage (facteur inconnu, catalogue muet — la règle de l'enhancer depuis le 2026-09-21)."""
    wanted = {cap: v for cap, v in (needs or {}).items() if v not in (None, '')}
    if not wanted:
        return None
    from wama.model_manager.services.model_selector import domain_q
    q = domain_q(domain)
    keys = None
    for cap, value in wanted.items():
        found = set(candidates_with(cap, value, q=q))
        keys = found if keys is None else keys & found
    # L'espace de clés du DOMAINE (règle `select_model_id`) : id nu quand une source le borne.
    prefix = f"{domain['source']}:" if domain.get('source') else ''
    return sorted(k[len(prefix):] if prefix and k.startswith(prefix) else k
                  for k in keys) or None


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
    # « auto » d'un GROUPE (`auto:<tâche>`) : il borne le tirage à SA tâche — le domaine du select
    # en réunit plusieurs (composer : musique / ambiances, 2026-10-01).
    from wama.common.utils.model_keys import auto_task
    if auto_task(requested):
        domain['task'] = auto_task(requested)
    if 'quality_intent' not in overrides and (item is not None or user is not None):
        overrides['quality_intent'] = quality_intent_of(item, app_id, user)
    # Affinages DÉCLARÉS au schéma (`options_resolution`) ; un appelant qui en passe garde la main
    # (l'imager pose `available_inputs` selon l'élément).
    if spec is None:
        for key, value in declared_resolution(app_id).items():
            if key == 'needs':
                # Le besoin déclaré nomme des CHAMPS : au lancement, leurs valeurs sont l'élément.
                value = ({cap: getattr(item, field, None) for cap, field in value.items()}
                         if item is not None else {})
            elif key == 'voice':
                # La voix aussi : le champ déclaré, lu sur l'élément.
                value = getattr(item, value, None) if item is not None else None
            overrides.setdefault(key, value)
    # Distants DÉCLARÉS au schéma et autorisés par le profil (`declared_cloud_keys`) ; un
    # appelant qui passe lui-même `cloud_keys` (l'assistant) garde la main.
    owner = user if user is not None else getattr(item, 'user', None)
    if 'cloud_keys' not in overrides and spec is None:
        cloud = declared_cloud_keys(app_id, owner)
        if cloud:
            overrides['cloud_keys'] = cloud
    # Le tirage se fait POUR ce compte : ses modèles privés y entrent, ceux d'autrui jamais
    # (`ROADMAP §29` étape 3). Sans compte, le système seul.
    if owner is not None:
        overrides.setdefault('user', owner)
    domain.update(overrides)
    # Besoins de l'élément (`needs`) : le lot se restreint aux modèles qui y répondent, AVANT le
    # classement — le même geste au lancement et pour la prévision.
    narrowed = need_candidates(domain.pop('needs', None), domain)
    if narrowed:
        domain['candidates'] = ([k for k in domain['candidates'] if k in narrowed]
                                if domain.get('candidates') else narrowed)
    # La VOIX choisie (2026-10-28) : un moteur qui clone pour un enregistrement, un modèle qui la
    # nomme pour une voix propre — même geste au lancement et pour la prévision.
    fallback = narrow_by_voice(domain, domain.pop('voice', None), fallback)
    source = domain.pop('source', None)
    from wama.model_manager.services import select_model_id
    return select_model_id(source, requested=AUTO, fallback=fallback, **domain)


def predict_model_choice(spec):
    """PRÉVISION : le modèle qui serait retenu MAINTENANT pour ce domaine, ou None.

    Sert l'affichage sous le select (décision Fabien, handoff 2026-09-01) : même chemin
    que le tirage réel — VRAM libre, résidence, classement — pour que la prévision dise
    la vérité du lancement. Photo du moment : le lancement réévalue.

    Retour : {'id', 'name', 'vram_gb', 'origin'} — `id` dans l'espace de clés du domaine ;
    `origin` dit OÙ le modèle tourne (`AIModel.origin_label`, la phrase des intitulés de groupe
    du menu). Fabien, 2026-10-13 : « Prévu : qwen-3.8-27b » ne disait pas que c'était ILaaS.
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
        'origin': (m.origin_label if m else ''),
    }


def vram_needed_gb(model_key: str, *, offload: bool = False):
    """Besoin VRAM du modèle RÉSOLU, pour la garde du squelette de tâche
    (`run_item_task(vram_needed=…)`) : LA cascade commune `memory_manager.model_footprint_gb`
    (mesurée → source → déclarée → preset), lue sur la ligne de catalogue. None si la ligne
    manque ou si personne ne sait — pas de garde, jamais un chiffre recopié dans une app.

    `offload=False` (défaut) : le pic SANS déchargement, la borne prudente pour décider
    d'attendre. Écrite dans l'enhancer le 2026-09-21, remontée ici le 2026-10-02 avec son 2ᵉ
    consommateur : le composer, dont la 1ʳᵉ génération YuE2 réelle est partie sans rien
    déclarer sur une carte pleine — elle a échoué faute de mémoire au lieu d'attendre.
    """
    try:
        from wama.model_manager.models import AIModel
        from wama.model_manager.services.memory_manager import model_footprint_gb
        row = AIModel.objects.filter(model_key=model_key).first()
        if row is None:
            return None
        gb, _provenance = model_footprint_gb(row, offload=offload)
        return float(gb) if gb else None
    except Exception as exc:
        logger.debug('besoin VRAM de %s illisible : %s', model_key, exc)
        return None
