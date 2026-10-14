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

#: Domaines des selects — UNE déclaration par branche, que `params.py` reprend (`options_query`).
#: MÉDIA par TÂCHE depuis la route F4b étape ⑤ (2026-10-06), jamais par source : `source='enhancer'`
#: écartait tout agrandisseur installé depuis le model manager (Swin2SR, `huggingface:…`), et les
#: valeurs deviennent des clés de catalogue ENTIÈRES. Mesuré avant de basculer : ce domaine rend
#: les 7 modèles d'avant plus Swin2SR, tous lançables. AUDIO par TÂCHE aussi depuis le
#: 2026-10-07 : le domaine rend les deux mêmes moteurs, en clés — après que l'appariement a
#: cessé de laisser entrer un modèle SANS tâche déclarée (`matches_inputs`, un diariseur
#: `pyannote` y figurait).
MEDIA_SPEC = {'task': 'upscale,denoise'}
AUDIO_SPEC = {'task': 'audio-enhance'}

#: Replis si le catalogue ne propose rien (première install, base injoignable) — le défaut
#: historique de l'app (une seule déclaration, `model_config.DEFAULT_MODEL`), en CLÉ de catalogue.
from wama.enhancer.utils.model_config import DEFAULT_MODEL  # noqa: E402
MEDIA_FALLBACK = f'{APP_ID}:{DEFAULT_MODEL}'
AUDIO_FALLBACK = f'{APP_ID}:resemble'

#: NFE de Resemble par POSITION nommée du curseur — positions lues chez le sélecteur commun
#: (`QUALITY_PRESETS`), jamais recopiées ; le NFE est la déclinaison locale.
NFE_BY_PRESET = {'fast': 32, 'balanced': 64, 'quality': 128}


def resolve_media_model(enhancement) -> str:
    """Modèle d'upscaling pour CE lancement : le choix explicite tel quel, sinon tirage dans
    le domaine des upscalers, restreint au facteur demandé, au poids du curseur de l'item.

    Domaine ET besoin (le facteur, capacité `scale`) sont lus au SCHÉMA du select (`params.py`,
    `options_query` + `options_resolution.needs`) — la déclaration que la prévision lit aussi.
    Jusqu'au 2026-10-14 le filtre par facteur vivait ici seul (`media_candidates`) : la prévision
    ne pouvait pas le connaître, et se taisait."""
    from wama.common.utils.model_keys import catalog_key
    requested = catalog_key(enhancement.ai_model or '', APP_ID)
    if requested and not is_auto(requested):
        return requested
    chosen = resolve_model_choice(AUTO, app_id=APP_ID, fallback=MEDIA_FALLBACK, item=enhancement)
    return chosen or MEDIA_FALLBACK


def resolve_audio_engine(ae) -> str:
    """Moteur audio pour CE lancement : explicite tel quel, sinon tirage entre les moteurs de
    restauration au poids du curseur (DeepFilterNet léger ↔ Resemble qualité). Rend une CLÉ de
    catalogue ; un identifiant nu d'avant se lit dans l'espace de l'enhancer."""
    from wama.common.utils.model_keys import catalog_key
    requested = catalog_key(ae.engine or '', APP_ID)
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
    visible et posé), la déclinaison du curseur quand il a été résolu par « auto ». `engine` :
    clé ou identifiant, c'est l'identifiant qui dit le moteur."""
    from wama.common.utils.model_keys import model_id
    if is_auto(ae.engine) and model_id(engine) == 'resemble':
        return nfe_for_intent(quality_intent_of(ae, APP_ID))
    return int(ae.quality or 64)

