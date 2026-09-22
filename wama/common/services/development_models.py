"""
Modèles de NIVEAU DÉVELOPPEMENT — le bridage « qualité max » du travail sur le code (2026-09-22).

DEMANDE DE FABIEN, le jour même, après un test réel : l'assistant, en domaine dev sur le curseur
par défaut (55 → sans réflexion), avait tiré `qwen3.5:4b` et INVENTÉ trois jumelles sur un résultat
d'outil vide. « Il faut le brider en qualité max pour éviter de retomber sur un modèle peu
performant, donc limiter les modèles possibles pour le dev — de façon GLOBALE à wama-dev-ai, pas
seulement l'assistant ; et peut-être autoriser Albert avec le plus gros modèle, gpt-oss. »

UN SEUL DOMICILE pour « qu'est-ce qu'un modèle de niveau développement ? », lu par :
  • l'assistant (`assistant_engine.resolve_turn_model`, domaine `dev` — et la BASCULE en cours de
    tour dès que la compétence dev ou un outil `dev_*` est appelé) ;
  • les rôles wama-dev-ai (`role_utils.resolve_model`) — les chaînes de repli de `config.py`
    finissaient sur `fast`/`ultra_fast`, c'est-à-dire précisément sur un petit modèle quand la
    VRAM manque.

LA RÈGLE, SUR UNE MESURE ET PAS AU GOÛT : le sous-indice **coding** du banc tiers
(`AIModel.benchmark_meta['family_scores']['coding']`, `sync_benchmarks`) doit atteindre
`DEV_CODING_FLOOR`. Relevé le 22/09 sur le parc : qwen3.8 58,2 · albert gemma-4-31b 43,4 ·
qwen3.6:35b 41,9 · gemma4:12b 31 · qwen3.5:4b 22,6 · gemma4:e4b 9,4 — le plancher 40 sépare
exactement ce que le banc du 13/08 a confirmé (codegen 8/8, zéro import inventé) de ce qui
fabule. Un modèle SANS score coding est exclu, sauf déclaration explicite
(`DEV_UNSCORED_ALLOWED` : `albert:gpt-oss-120b`, décision de Fabien — à retirer le jour où le
banc lui donne un score, la mesure primant alors la déclaration).

CE QUE LE BRIDAGE CHANGE, ET RIEN D'AUTRE :
  1. le curseur vaut 100 (« Qualité ») : réflexion demandée (`assistant_engine.thinking_wanted`),
     et le budget VRAM cesse de borner le tirage — l'attente ou l'offload est le prix assumé ;
  2. le lot est RESTREINT aux modèles de niveau dev ; un choix MANUEL sous le plancher est
     remplacé (et l'étiquette du tour le dit : « · dev ») ;
  3. les distants SOUVERAINS (`external_sources.hosting == 'sovereign'`, Albert) entrent dans le
     tirage AUTOMATIQUE dès le niveau de profil « cloud si WAMA est saturé » — un travail sur le
     code n'est pas une tâche sensible et Albert est l'hébergement de l'État ; « 100 % local »
     reste 100 % local, et les hébergeurs TIERS gardent la règle commune (`allowed_cloud_keys`) ;
  4. aucun repli : sans modèle de niveau dev, on REFUSE avec la raison (`development_refusal`),
     jamais un petit modèle en silence — c'est le défaut vécu.

Ne touche PAS aux autres domaines de l'assistant ni aux apps : `resolve_model_choice` et le
curseur commun restent ce qu'ils sont.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

#: Score coding minimal au banc tiers (`family_scores['coding']`) pour compter comme modèle de dev.
DEV_CODING_FLOOR = 40.0
#: Modèles SANS score coding admis par DÉCLARATION (Fabien, 22/09). Vide dès qu'ils sont mesurés.
DEV_UNSCORED_ALLOWED = ('albert:gpt-oss-120b',)
#: Curseur imposé au travail sur le code : « Qualité », réflexion comprise.
DEV_QUALITY_INTENT = 100
#: Les distants SOUVERAINS entrent au tirage automatique dès « cloud si WAMA est saturé ».
DEV_SOVEREIGN_AUTOMATIC = True
#: Préfixe des outils de la surface de développement (`mcp_client.DEV_TOOL_PREFIX`, redit ici pour
#: ne pas faire dépendre le store de conversation du client MCP).
DEV_TOOL_PREFIX = 'dev_'


def coding_score(model) -> float | None:
    """Sous-indice coding du banc tiers, ou None s'il n'est pas mesuré."""
    meta = getattr(model, 'benchmark_meta', None) or {}
    value = (meta.get('family_scores') or {}).get('coding')
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def is_development_grade(model) -> bool:
    """Ce modèle a-t-il le niveau développement ? Mesure d'abord, déclaration ensuite."""
    score = coding_score(model)
    if score is not None:
        return score >= DEV_CODING_FLOOR
    return getattr(model, 'model_key', '') in DEV_UNSCORED_ALLOWED


def dev_cloud_keys(user) -> set:
    """Modèles distants admis au tirage de DÉVELOPPEMENT pour `user` : la règle commune
    (`allowed_cloud_keys`, automatique), plus les SOUVERAINS ouverts par ses clés dès le niveau
    « cloud si WAMA est saturé ». Sans utilisateur (rôle en ligne de commande) : aucun."""
    if user is None or not getattr(user, 'is_authenticated', False):
        return set()
    from wama.model_manager.services.cloud_models import allowed_cloud_keys
    keys = set(allowed_cloud_keys(user, automatic=True))
    if not DEV_SOVEREIGN_AUTOMATIC:
        return keys
    from wama.common import external_sources
    sovereign = {s.key for s in external_sources.SOURCES if getattr(s, 'hosting', '') == 'sovereign'}
    for key in allowed_cloud_keys(user, automatic=False):
        if key.partition(':')[0] in sovereign:
            keys.add(key)
    return keys


def development_candidates(user) -> list:
    """`model_key` des modèles de conversation de niveau dev que `user` peut lancer : locaux
    installés, distants qu'il autorise (`dev_cloud_keys`)."""
    from django.db.models import Q
    from wama.model_manager.models import AIModel, EXECUTION_CLOUD, EXECUTION_LOCAL

    cloud = dev_cloud_keys(user)
    qs = AIModel.objects.filter(is_available=True, is_proposed=False, model_type='llm')
    qs = qs.filter(Q(execution=EXECUTION_LOCAL, is_downloaded=True) | Q(model_key__in=list(cloud)))
    return [m.model_key for m in qs if m.execution != EXECUTION_CLOUD or m.model_key in cloud
            if is_development_grade(m)]


def development_model(user, requested: str = None) -> str | None:
    """Le modèle de niveau dev pour ce travail — `model_key` complet (`ollama:…`, `albert:…`), ou
    None s'il n'y en a aucun (l'appelant REFUSE, cf. `development_refusal`).

    `requested` : un choix explicite (réglage durable, ligne de commande) est respecté s'il a
    le niveau ; sinon il est REMPLACÉ par le tirage — c'est le bridage."""
    from wama.common.utils.auto_model import is_auto

    candidates = development_candidates(user)
    if not candidates:
        return None
    if requested and not is_auto(requested):
        if requested in candidates:
            return requested
        logger.info("[development_models] %r sous le niveau développement — remplacé par le tirage",
                    requested)
    try:
        from wama.model_manager.services.model_selector import select_model
        chosen = select_model(None, model_type='llm', requires=['completion'],
                              candidates=candidates, quality_intent=DEV_QUALITY_INTENT,
                              benchmark_family='coding', prefer_loaded=False,
                              cloud_keys=dev_cloud_keys(user) or None)
        if chosen is not None:
            return chosen.model_key
    except Exception:
        logger.debug("[development_models] tirage indisponible", exc_info=True)
    # Sélecteur muet (VRAM inconnue, catalogue partiel) : le premier candidat par score, jamais
    # un modèle hors lot.
    return candidates[0]


def development_refusal(user=None) -> str:
    """La raison, lisible, quand aucun modèle de niveau dev n'est disponible."""
    unscored = ', '.join(DEV_UNSCORED_ALLOWED)
    return (f"Aucun modèle de niveau développement disponible (score coding ≥ {DEV_CODING_FLOOR:g} "
            f"au banc, ou {unscored}) : installez un modèle local qui l'atteint, ou ouvrez Albert "
            "dans votre profil (le niveau « cloud si WAMA est saturé » suffit pour le "
            "développement).")


def is_development_step(step: dict) -> bool:
    """Une étape d'outil qui fait ENTRER la conversation dans le travail sur le code : la
    compétence d'un domaine de développement chargée, ou un outil de la surface dev appelé."""
    tool = str((step or {}).get('tool') or '')
    if tool.startswith(DEV_TOOL_PREFIX):
        return True
    if tool == 'charger_competence':
        from wama.common.utils.assistant_skills import resolve_domain
        return resolve_domain(((step or {}).get('args') or {}).get('domaine')).development
    return False
