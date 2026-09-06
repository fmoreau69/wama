"""Backend DeepFace — analyse d'émotions (+ âge/genre optionnels) sur une image.

Il n'ENVELOPPE pas une nouvelle logique : `emotions.EmotionRecognizer` porte déjà le lissage
temporel, le choix de détecteur et la normalisation des résultats. Ce backend l'expose au
CONTRAT COMMUN (`load`/`unload`/`process`/`is_loaded`) — ce qui apporte trois choses que
l'app n'avait pas :

  • le **lien modèle↔moteur** se referme (`ENGINE = 'deepface'` répond aux 3 poids catalogués
    qui déclarent `runtime.engine = 'deepface'`) — préalable au retrait de `backend_ref` ;
  • le **gouverneur de ressources** voit enfin la VRAM prise : `BaseModelBackend.__init_subclass__`
    enveloppe `load`/`unload` et publie la réservation, à n'importe quelle profondeur d'héritage ;
  • le **grisage** devient mesurable (`REQUIRED_PACKAGES` → `missing_packages()`), au lieu d'être
    supposé.

⚠ FER n'a PAS de backend ici, et c'est délibéré : `ENGINE` nomme le moteur qu'on pilote, or
aucun modèle catalogué ne déclare `engine='fer'` — les poids de FER sont embarqués dans sa roue
pip, donc ils ne sont pas au catalogue (cf. `utils/model_config.py`). Déclarer un moteur que
personne n'exige gonflerait l'inventaire sans fermer aucun lien.
"""
import logging
from typing import Optional

from wama.common.backends.base import BaseModelBackend

logger = logging.getLogger(__name__)


class DeepFaceBackend(BaseModelBackend):
    """Émotions, âge et genre par DeepFace, au contrat commun."""

    #: Le moteur PILOTÉ — même graphie que `composition.runtime.engine` des 3 poids catalogués.
    #: Une graphie différente rouvrirait le trou que ce fichier existe pour fermer.
    ENGINE = 'deepface'

    #: Nom d'IMPORT (pas le nom pip) — `find_spec` est ce que `missing_packages()` interroge.
    REQUIRED_PACKAGES = ['deepface']
    #: `tf-keras` est le nom pip de l'API Keras 2 dont DeepFace a besoin sous TensorFlow ≥ 2.16 ;
    #: son module s'importe `tf_keras`. Les deux graphies diffèrent, d'où la déclaration séparée.
    PIP_PACKAGES = ['deepface', 'tf-keras>=2.21']

    #: Mesuré au chargement des 3 poids (expression 6 Mo, âge et genre ~514 Mo chacun) ; l'âge
    #: et le genre ne se chargent QUE si l'appelant les demande, d'où une borne haute assumée.
    recommended_vram_gb = 2.5
    description = "Analyse faciale DeepFace : émotions, et âge/genre à la demande"

    def __init__(self, deepface_detector: str = 'opencv'):
        self._recognizer = None
        self._detector = deepface_detector

    @property
    def is_loaded(self) -> bool:
        return self._recognizer is not None

    def load(self, model: Optional[str] = None, *, enable_age_gender: bool = False) -> bool:
        """Instancie le reconnaisseur. `model` est ignoré : DeepFace choisit ses poids seul.

        ⚠ Le chargement RÉEL des `.h5` est PARESSEUX chez DeepFace (au premier appel), donc la
        mesure de VRAM autour de `load()` sera nulle et le gouverneur retombera sur
        `recommended_vram_gb`. C'est le comportement prévu par le contrat commun — le noter ici
        évite qu'on prenne un jour cette mesure nulle pour une absence d'empreinte.
        """
        if self.is_loaded:
            return True
        from wama_lab.face_analyzer.emotions import EmotionRecognizer
        self._recognizer = EmotionRecognizer(backend='deepface',
                                             enable_age_gender=enable_age_gender)
        logger.info("[face_analyzer] backend DeepFace chargé (âge/genre=%s)", enable_age_gender)
        return True

    def unload(self) -> None:
        self._recognizer = None

    def process(self, frame=None, timestamp: float = None, **kwargs):
        """Analyse UNE image. Rend l'`EmotionResult` de l'app, ou None si aucun visage."""
        if frame is None:
            raise ValueError("DeepFaceBackend.process attend une image (`frame`)")
        if not self.is_loaded:
            self.load(enable_age_gender=bool(kwargs.get('enable_age_gender')))
        return self._recognizer.process(frame, timestamp)
