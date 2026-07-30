"""
Résolution du modèle « auto » de l'Imager — AU LANCEMENT de la tâche.

⚠️ **Le moment compte autant que la règle.** Le tirage lit la VRAM libre ; or entre le dépôt
dans la file et l'exécution réelle il peut s'écouler plusieurs minutes, pendant lesquelles une
autre app charge ou libère un modèle. Résoudre « auto » dans la VUE (au clic) donnerait donc un
choix fondé sur un état périmé. C'est pour cette raison que `composer/utils/auto_model.py` le
fait dans `tasks.py` — « capacités + VRAM libre au lancement » — et non dans la vue. Même
pattern ici, volontairement.

Aucune règle de sélection n'est écrite ici : tout vient de la brique commune
`model_manager.services.select_model_id()`, à qui l'on ne fait que NOMMER la capacité voulue,
en vocabulaire canonique (`INPUT_MODEL_MATCHING.md`).
"""

import logging

from wama.model_manager.services import select_model_id

from .model_config import DEFAULT_I2V_MODEL, DEFAULT_IMAGE_MODEL, DEFAULT_VIDEO_MODEL

logger = logging.getLogger(__name__)

AUTO = 'auto'

# Mode de génération → ce dont on dispose et ce qu'on veut voir consommé.
# Déclaratif : ajouter un mode ne demande aucune logique, juste une ligne.
_BY_MODE = {
    'txt2vid': dict(modality='video', available_inputs=['prompt'],
                    fallback=DEFAULT_VIDEO_MODEL),
    'img2vid': dict(modality='video', available_inputs=['prompt', 'work_image'],
                    consumes=['work_image'], fallback=DEFAULT_I2V_MODEL),
}
_DEFAULT_IMAGE = dict(modality='image', fallback=DEFAULT_IMAGE_MODEL)


def resolve_auto_model(generation) -> str:
    """
    Modèle à utiliser pour cette génération. Renvoie le modèle demandé s'il est explicite.

    Ne lève jamais : en cas d'échec, on retombe sur le défaut de la modalité (qui tient sur la
    carte), car refuser une génération pour un problème de tirage serait pire que la faire avec
    un modèle correct mais non optimal.
    """
    requested = (generation.model or '').strip()
    if requested and requested != AUTO:
        return requested

    spec = _BY_MODE.get(generation.generation_mode, _DEFAULT_IMAGE)
    try:
        chosen = select_model_id('imager', **spec)
    except Exception as exc:
        chosen = spec['fallback']
        logger.warning("[Imager] tirage auto indisponible (%s) → %s", exc, chosen)
    return chosen or spec['fallback']
