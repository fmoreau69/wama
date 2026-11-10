"""
Contrat de la tâche `face-analysis` — ce qu'on lit sur un visage : émotions, âge, genre.

Spécialisation MÉTIER de `wama.common.backends.base.BaseModelBackend`. SANS ÉTAT : une image, une
réponse. Ce qui dépend de la suite des images d'un flux (le lissage, la valence) reste à
`emotions.EmotionRecognizer`, qu'une pipeline instancie par flux. Écrit le 2026-11-09 pour le service
TensorFlow : le Face Analyzer appelait DeepFace et FER depuis `EmotionRecognizer`, à côté du contrat.

Ce qui vient du COMMUN : cycle de vie, dépendances, enveloppe du gouverneur, `ENGINE` /
`SUPPORTED_MODELS` pour la résolution. Ce qui est PROPRE au domaine ici : le verbe `analyze_face`.
"""
from abc import abstractmethod
from typing import Optional

from .base import BaseModelBackend


class FaceAnalysisBackend(BaseModelBackend):
    """`analyze_face(image) → {attributs}` — un modèle `face-analysis` du catalogue.

    Un modèle rend les attributs qu'il sait lire, et ceux-là seulement : la réponse d'une demande est
    la fusion de celles de ses modèles (`tensorflow_service.engine.run`). L'état de chargement vient
    d'ici : un backend pose `self._loaded` dans `load()`/`unload()`."""

    def __init__(self):
        self._loaded = False
        self._current_model = None

    @property
    def is_loaded(self) -> bool:
        return self._loaded

    def process(self, **kwargs) -> Optional[dict]:
        """Point d'entrée générique (contrat commun) → délègue à `analyze_face()`."""
        return self.analyze_face(**kwargs)

    @abstractmethod
    def analyze_face(self, image, detector: str = 'opencv') -> Optional[dict]:
        """Les attributs du premier visage de `image` (ndarray BGR uint8, H×W×3), None si le modèle
        n'y trouve aucun visage. Clés possibles :
        `emotions` — les sept émotions (`happy`, `sad`, `angry`, `fear`, `surprise`, `disgust`,
        `neutral`), de 0 à 1 ; `age` — un entier ; `gender` et `gender_confidence` (0 à 1).
        `detector` : le détecteur de visage, pour un moteur qui sait en changer."""
