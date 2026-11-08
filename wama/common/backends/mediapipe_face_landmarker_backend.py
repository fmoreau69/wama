"""Face Landmarker de MediaPipe — le contrat `face-landmark-detection` sur la librairie `mediapipe`.

Le Face Analyzer (monde Lab) mesure la géométrie d'un visage image par image (`preprocessing.
FaceDetector`). Jusqu'au 2026-11-08, il chargeait le modèle lui-même — un `FaceLandmarker` par
pipeline, donc un par IMAGE en temps réel (`views.analyze_frame`), hors de la porte de lancement et
du déchargement commun. Ce backend est ce chargement, au contrat, avec les options que l'app
employait ; la porte commune le garde chargé.

LE MODÈLE RESTE CELUI DE L'APP : sa ligne (`face_analyzer:…`) la rattache au Face Analyzer — son
manifeste d'app et sa page « À propos » lisent `AIModel.source` —, et sa déclaration vit dans
`FACE_ANALYZER_MODELS`, que ce backend lit par le passe-plat commun (`model_declarations`) sans
importer l'app. Le dossier est une donnée d'INSTALLATION, lue dans `settings.MODEL_PATHS`
(`model_declarations`, en-tête). Installé par la route (pilote `files`) ; absent, on le DIT.

⚠ `mediapipe` sert aussi les GESTES de la main des scènes 3D, mais dans sa version NAVIGATEUR
(`static/vendors/mediapipe-tasks-vision-*`) : leur ligne ne déclare aucun moteur, ce backend ne la
sert pas — sa liste ne nomme que le Face Landmarker, et le contrat LIANT le borne à sa tâche.
"""
from __future__ import annotations

import gc
import logging
import threading
from pathlib import Path
from typing import List, Optional

from .face_landmark_detection_base import FaceLandmarkDetectionBackend

logger = logging.getLogger(__name__)


class MediaPipeFaceLandmarkerBackend(FaceLandmarkDetectionBackend):
    """Les 478 repères d'un visage (iris compris), par l'API « tasks » de MediaPipe, en mode IMAGE."""

    #: Moteur piloté (contrat commun) : la librairie `mediapipe`.
    ENGINE = 'mediapipe'
    #: Modèles servis : clé = dernier segment de la clé de catalogue. ⚠ En LITTÉRAL : l'inventaire
    #: lit les clés par AST.
    SUPPORTED_MODELS = {
        'mediapipe-face-landmarker': {'model_key': 'face_analyzer:mediapipe-face-landmarker'},
    }
    REQUIRED_PACKAGES = ['mediapipe']
    name = 'mediapipe-face-landmarker'
    display_name = 'MediaPipe Face Landmarker'
    description = "Repères du visage (478 points), sur le processeur."

    #: Les options que le Face Analyzer employait (`FaceDetector`, ses valeurs par défaut) : un
    #: visage, seuils de détection, de présence et de suivi à 0,5 ; ni expressions ni matrice.
    num_faces = 1
    min_confidence = 0.5

    #: Le processeur, déclaré (le délégué par défaut de MediaPipe) : l'enveloppe du gouverneur ne
    #: publie rien pour lui.
    device = 'cpu'
    recommended_vram_gb = 0

    def __init__(self):
        super().__init__()
        self._landmarker = None
        #: Une détection à la fois : l'instance est PARTAGÉE (porte commune) entre les requêtes du
        #: temps réel — gunicorn sert par fils (`gunicorn_conf.py`, `gthread`, 4 fils) —, et rien
        #: dans MediaPipe ne promet des appels simultanés sur un même `FaceLandmarker`.
        self._lock = threading.Lock()

    @classmethod
    def catalogue_key_for(cls, model: Optional[str] = None) -> str:
        """La clé de catalogue d'un modèle demandé (clé ou identifiant nu, la forme que passe un
        essai de contrat), le seul servi si rien ne le dit. Inconnu → `ValueError`."""
        from wama.common.utils.model_keys import backend_model_id
        if not model:
            return next(iter(cls.SUPPORTED_MODELS.values()))['model_key']
        spec = cls.SUPPORTED_MODELS.get(backend_model_id(model))
        if spec is None:
            raise ValueError(f"{cls.__name__} : modèle non servi « {model} » "
                             f"(servis : {list(cls.SUPPORTED_MODELS)})")
        return spec['model_key']

    @classmethod
    def model_file(cls, model: Optional[str] = None) -> Path:
        """Le fichier DÉCLARÉ du modèle — existe ou non, c'est l'appelant qui mesure."""
        from django.conf import settings

        from wama.common.utils.model_declarations import declaration_for
        key = cls.catalogue_key_for(model)
        declared = declaration_for(key)
        if not declared:
            raise ValueError(f"{cls.__name__} : aucune déclaration pour « {key} »")
        return Path(settings.MODEL_PATHS['vision']['mediapipe']) / declared['fichier']

    def load(self, model: Optional[str] = None) -> bool:
        if self._loaded:
            return True
        key = self.catalogue_key_for(model)
        path = self.model_file(key)
        if not path.is_file():
            raise RuntimeError(f"Modèle MediaPipe « {path.name} » absent ({path.parent}) — il "
                               f"s'installe par le model manager (« Installer ») ou : python "
                               f"manage.py pull_model {key}")
        from mediapipe.tasks import python
        from mediapipe.tasks.python import vision
        options = vision.FaceLandmarkerOptions(
            base_options=python.BaseOptions(model_asset_path=str(path)),
            running_mode=vision.RunningMode.IMAGE,
            num_faces=self.num_faces,
            min_face_detection_confidence=self.min_confidence,
            min_face_presence_confidence=self.min_confidence,
            min_tracking_confidence=self.min_confidence,
            output_face_blendshapes=False,
            output_facial_transformation_matrixes=False)
        self._landmarker = vision.FaceLandmarker.create_from_options(options)
        self._loaded, self._current_model = True, key
        logger.info('[FaceLandmarker] chargé (processeur)')
        return True

    def unload(self) -> None:
        with self._lock:
            if self._landmarker is not None:
                self._landmarker.close()
                self._landmarker = None
                gc.collect()
            self._loaded, self._current_model = False, None

    def detect_face_landmarks(self, image) -> List:
        if not self._loaded:
            raise RuntimeError("MediaPipeFaceLandmarkerBackend : modèle non chargé (`load()` d'abord)")
        import mediapipe as mp
        import numpy as np
        h, w = image.shape[:2]
        with self._lock:
            result = self._landmarker.detect(
                mp.Image(image_format=mp.ImageFormat.SRGB, data=np.ascontiguousarray(image)))
        return [np.array([[lm.x * w, lm.y * h, lm.z * w] for lm in face])
                for face in (result.face_landmarks or [])]
