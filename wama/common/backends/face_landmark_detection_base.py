"""
Contrat de la tâche `face-landmark-detection` — les REPÈRES d'un visage, point par point.

Spécialisation MÉTIER de `wama.common.backends.base.BaseModelBackend`. Un détecteur de repères ne
juge rien (ni émotion, ni âge) : il rend la géométrie de chaque visage, que l'appelant mesure — le
Face Analyzer en tire la pose de la tête, les régions de la peau, les yeux. Écrit le 2026-11-08 :
le Face Analyzer chargeait le Face Landmarker de MediaPipe lui-même (`FaceDetector`, un par
pipeline — donc un par IMAGE en temps réel), hors de la porte de lancement et du déchargement
commun.

Ce qui vient du COMMUN (ne pas dupliquer) : cycle de vie, dépendances, enveloppe load/unload du
gouverneur, `ENGINE` / `SUPPORTED_MODELS` pour la résolution depuis le catalogue. Ce qui est PROPRE
au domaine ici : le verbe `detect_face_landmarks`.
"""
from abc import abstractmethod
from typing import List

from .base import BaseModelBackend


class FaceLandmarkDetectionBackend(BaseModelBackend):
    """`detect_face_landmarks(image) → [repères]` — un modèle `face-landmark-detection` du catalogue.

    Un nouveau moteur = une sous-classe qui déclare `ENGINE`, `SUPPORTED_MODELS`,
    `REQUIRED_PACKAGES` et implémente `load()/unload()/detect_face_landmarks()`. L'état de
    chargement vient d'ici : un backend pose `self._loaded` dans `load()`/`unload()`."""

    def __init__(self):
        self._loaded = False
        self._current_model = None

    @property
    def is_loaded(self) -> bool:
        return self._loaded

    def process(self, **kwargs) -> List:
        """Point d'entrée générique (contrat commun) → délègue à `detect_face_landmarks()`."""
        return self.detect_face_landmarks(**kwargs)

    @abstractmethod
    def detect_face_landmarks(self, image) -> List:
        """Les repères de chaque visage de `image` (ndarray RGB uint8, H×W×3), dans l'ordre que rend
        le modèle : une liste de ndarray (N, 3) en PIXELS — x, y, et la profondeur relative z à l'échelle
        de la largeur. Liste vide : aucun visage. Le NOMBRE de repères est celui du modèle ; leur
        numérotation, la sienne (l'appelant la lit, `preprocessing.FaceLandmarks`)."""
