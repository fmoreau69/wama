"""Tirage « auto » de l'enhancer — la brique COMMUNE `auto_model` appliquée aux DEUX branches
(curseur C, 2026-09-21 ; levée de la décision « l'utilisateur désigne son moteur »).

Ce que l'app DÉCLARE, et rien d'autre :
  • le DOMAINE de chaque branche (le même que ses selects : upscalers / moteurs audio) ;
  • le BESOIN qui filtre AVANT le classement — le facteur d'agrandissement (`upscale_factor` =
    capacité `scale` du catalogue) : ×2 et ×4 ne sont pas deux qualités, ce sont deux résultats ;
  • la DÉCLINAISON locale du curseur quand le moteur est auto : le NFE de Resemble.
Le classement (score qualité/coût au poids du curseur, budget VRAM, résidence) est celui du
sélecteur commun — aucune règle de choix ici.

⚠ MOMENT : au LANCEMENT (glu de tâche), jamais au dépôt — la VRAM libre du moment fait foi ;
l'item GARDE « auto » (une relance ré-arbitre), le modèle retenu vit dans la ligne d'exécution.
"""
import logging

from wama.common.utils.auto_model import AUTO, is_auto, quality_intent_of, resolve_model_choice

logger = logging.getLogger(__name__)

APP_ID = 'enhancer'

#: Domaines = ceux des selects (`params.py`, `options_query`) : une seule déclaration par branche.
MEDIA_SPEC = {'source': 'enhancer', 'model_type': 'upscaling'}
AUDIO_SPEC = {'source': 'enhancer', 'task': 'audio-enhance'}

#: Replis si le catalogue ne propose rien (première install, base injoignable) — le défaut
#: historique de l'app (une seule déclaration, `model_config.DEFAULT_MODEL`).
from wama.enhancer.utils.model_config import DEFAULT_MODEL as MEDIA_FALLBACK  # noqa: E402
AUDIO_FALLBACK = 'resemble'

#: NFE de Resemble par POSITION nommée du curseur — positions lues chez le sélecteur commun
#: (`QUALITY_PRESETS`), jamais recopiées ; le NFE est la déclinaison locale.
NFE_BY_PRESET = {'fast': 32, 'balanced': 64, 'quality': 128}


def media_candidates(factor) -> list:
    """Clés catalogue des upscalers qui RENDENT le facteur demandé (capacité `scale`), ou []
    (facteur inconnu / catalogue muet → le domaine entier reste au tirage)."""
    try:
        factor = int(factor or 0)
    except (TypeError, ValueError):
        return []
    if factor <= 0:
        return []
    try:
        from wama.model_manager.models import AIModel
        rows = AIModel.objects.filter(source='enhancer', model_type='upscaling')
        return [m.model_key for m in rows
                if int((m.capabilities or {}).get('scale') or 0) == factor]
    except Exception as exc:                          # catalogue absent : on ne filtre pas
        logger.debug('[enhancer] candidats par facteur indisponibles : %s', exc)
        return []


def resolve_media_model(enhancement) -> str:
    """Modèle d'upscaling pour CE lancement : le choix explicite tel quel, sinon tirage dans
    le domaine des upscalers, restreint au facteur demandé, au poids du curseur de l'item."""
    requested = (enhancement.ai_model or '').strip()
    if requested and not is_auto(requested):
        return requested
    overrides = {}
    candidates = media_candidates(getattr(enhancement, 'upscale_factor', None))
    if candidates:
        overrides['candidates'] = candidates
    chosen = resolve_model_choice(AUTO, app_id=APP_ID, spec=MEDIA_SPEC,
                                  fallback=MEDIA_FALLBACK, item=enhancement, **overrides)
    return chosen or MEDIA_FALLBACK


def resolve_audio_engine(ae) -> str:
    """Moteur audio pour CE lancement : explicite tel quel, sinon tirage entre les moteurs de
    restauration au poids du curseur (DeepFilterNet léger ↔ Resemble qualité)."""
    requested = (ae.engine or '').strip()
    if requested and not is_auto(requested):
        return requested
    chosen = resolve_model_choice(AUTO, app_id=APP_ID, spec=AUDIO_SPEC,
                                  fallback=AUDIO_FALLBACK, item=ae)
    return chosen or AUDIO_FALLBACK


def nfe_for_intent(intent) -> int:
    """NFE de Resemble décliné du curseur : la position nommée la plus proche (Rapide 32 /
    Équilibré 64 / Qualité 128) — la règle de proximité est celle du commun
    (`auto_model.preset_key_for_intent`), la table NFE est la déclinaison de l'app."""
    from wama.common.utils.auto_model import preset_key_for_intent
    return NFE_BY_PRESET.get(preset_key_for_intent(intent), 64)


def audio_nfe(ae, engine: str) -> int:
    """Le NFE effectif : la colonne quand le moteur a été DÉSIGNÉ (le select NFE est alors
    visible et posé), la déclinaison du curseur quand il a été résolu par « auto »."""
    if is_auto(ae.engine) and engine == 'resemble':
        return nfe_for_intent(quality_intent_of(ae, APP_ID))
    return int(ae.quality or 64)


def vram_needed_gb(model_key: str):
    """Besoin VRAM du modèle RÉSOLU, pour la garde du squelette (`vram_needed`) : LA cascade
    commune `memory_manager.model_footprint_gb` (mesurée → source → déclarée → preset), lue sur
    la ligne de catalogue ; None si la ligne manque ou si personne ne sait (pas de garde —
    jamais un chiffre recopié ici). `offload=False` : un moteur ONNX ne décharge rien.
    ⚠ Mesuré le 21/09 : les 7 upscalers n'ont qu'une VRAM heuristique de taille (0,0-0,1 Go)
    — leur `vram_usage` déclaré dans `model_config` attend d'être PROJETÉ par la découverte
    (`model_registry`, fichier de la session sœur) ; la garde suivra sans une ligne ici."""
    try:
        from wama.model_manager.models import AIModel
        from wama.model_manager.services.memory_manager import model_footprint_gb
        row = AIModel.objects.filter(model_key=model_key).first()
        if row is None:
            return None
        gb, _provenance = model_footprint_gb(row, offload=False)
        return float(gb) if gb else None
    except Exception as exc:
        logger.debug('[enhancer] besoin VRAM de %s illisible : %s', model_key, exc)
        return None
