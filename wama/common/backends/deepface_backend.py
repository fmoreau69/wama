"""DeepFace — le contrat `face-analysis` sur la librairie `deepface` : émotions, âge, genre.

Trois lignes au catalogue, trois fichiers de poids, TROIS classes : le contrat garde une instance par
classe (`manager.backend_instance`), et c'est ainsi que chaque modèle a SA ligne au gouverneur, sa
mesure et son état chargé — l'âge et le genre ne se chargent qu'à la demande (décision du 2026-11-08).
La règle est celle des modèles auxiliaires (`WAMA_MANIFEST_SPEC §7.1`, 2026-11-06) : le moteur partagé
se départage par la liste de chacun (`SUPPORTED_MODELS`). Une demande d'âge et de genre est donc une
demande à deux modèles, dont `tensorflow_service.engine.run` fusionne les réponses.

SANS ÉTAT : une image, une réponse. Le lissage entre les images d'un flux reste à
`emotions.EmotionRecognizer`.

⚠ Les poids s'installent par la route (pilote `files`, `face_analyzer/utils/model_config.py`) : absents,
ce backend le DIT au lieu de laisser DeepFace les tirer lui-même au premier usage.
"""
import gc
import logging
from pathlib import Path
from typing import Optional

from wama.common.tensorflow_service import runtime

from .face_analysis_base import FaceAnalysisBackend
from .tensorflow_base import TensorFlowBackend

logger = logging.getLogger(__name__)


class DeepFaceBackend(TensorFlowBackend, FaceAnalysisBackend):
    """Les sept émotions du premier visage, par le modèle d'expression de DeepFace."""

    #: Le moteur PILOTÉ — même graphie que `composition.runtime.engine` des 3 poids catalogués.
    ENGINE = 'deepface'
    #: ⚠ En LITTÉRAL, sur chaque classe : l'inventaire lit par AST, sans héritage.
    SUPPORTED_MODELS = {'deepface-expression': {'model_key': 'face_analyzer:deepface-expression'}}
    REQUIRED_PACKAGES = ['deepface']
    #: `tf-keras` est le nom pip de l'API Keras 2 dont DeepFace a besoin sous TensorFlow ≥ 2.16.
    PIP_PACKAGES = ['deepface', 'tf-keras>=2.21']
    #: Mémoire OCCUPÉE de la carte, modèle seul dans son processus (2026-11-09, deux relevés sur
    #: trois à 0,65 Go, le troisième perturbé par un autre occupant). De même pour l'âge (6,59 et
    #: 6,51 Go) et le genre (6,50 Go, deux fois) : leur pic TensorFlow n'est que de 3 Go, mais sa
    #: réserve croît par paliers, et c'est elle que la carte garde. Chargés ensemble, ils la partagent.
    recommended_vram_gb = 0.7
    description = "Émotions du visage, par DeepFace"

    #: Le nom du modèle chez DeepFace, et l'action de `DeepFace.analyze` qui le lit.
    WEIGHTS = 'Emotion'
    ACTION = 'emotion'

    @classmethod
    def weights_file(cls) -> Path:
        """Le fichier DÉCLARÉ de ce modèle — existe ou non, c'est l'appelant qui mesure."""
        from django.conf import settings

        from wama.common.utils.model_declarations import declaration_for
        key = next(iter(cls.SUPPORTED_MODELS.values()))['model_key']
        return (Path(settings.MODEL_PATHS['vision']['deepface']) / '.deepface' / 'weights'
                / declaration_for(key)['fichier'])

    def load(self, model: Optional[str] = None) -> bool:
        if self._loaded:
            return True
        path = self.weights_file()
        if not path.is_file():
            model_id = next(iter(self.SUPPORTED_MODELS))
            raise RuntimeError(f"Poids DeepFace « {path.name} » absents ({path.parent}) — ils "
                               f"s'installent par le model manager (« Installer ») ou : python "
                               f"manage.py pull_model face_analyzer:{model_id}")
        runtime.tensorflow()
        import numpy as np
        from deepface.modules import modeling
        # La première prédiction place le modèle : sa mesure compte, et la première image n'attend pas.
        modeling.build_model(task='facial_attribute', model_name=self.WEIGHTS).predict(
            np.zeros((224, 224, 3), dtype=np.float32))
        self._loaded, self._current_model = True, next(iter(self.SUPPORTED_MODELS))
        logger.info('[DeepFace] %s chargé (%s)', self.WEIGHTS,
                    'carte' if runtime.on_the_card() else 'processeur')
        return True

    def unload(self) -> None:
        from deepface.modules import modeling
        getattr(modeling, 'cached_models', {}).get('facial_attribute', {}).pop(self.WEIGHTS, None)
        self._loaded, self._current_model = False, None
        gc.collect()

    def analyze_face(self, image, detector: str = 'opencv') -> Optional[dict]:
        if not self._loaded:
            raise RuntimeError(f"{type(self).__name__} : modèle non chargé (`load()` d'abord)")
        from deepface import DeepFace
        found = DeepFace.analyze(image, actions=[self.ACTION], enforce_detection=False,
                                 detector_backend=detector, silent=True)
        if not found:
            return None
        return self._read(found[0] if isinstance(found, list) else found)

    def _read(self, found: dict) -> dict:
        emotions = found.get('emotion') or {}
        if sum(emotions.values()) > 0:
            emotions = {k.lower(): float(v) / 100.0 for k, v in emotions.items()}
        return {'emotions': emotions}


class DeepFaceAgeBackend(DeepFaceBackend):
    """L'âge apparent du premier visage."""

    ENGINE = 'deepface'
    SUPPORTED_MODELS = {'deepface-age': {'model_key': 'face_analyzer:deepface-age'}}
    REQUIRED_PACKAGES = ['deepface']
    recommended_vram_gb = 6.6
    description = "Âge apparent du visage, par DeepFace"
    WEIGHTS = 'Age'
    ACTION = 'age'

    def _read(self, found: dict) -> dict:
        return {'age': int(found['age'])}


class DeepFaceGenderBackend(DeepFaceBackend):
    """Le genre du premier visage et la confiance du modèle."""

    ENGINE = 'deepface'
    SUPPORTED_MODELS = {'deepface-gender': {'model_key': 'face_analyzer:deepface-gender'}}
    REQUIRED_PACKAGES = ['deepface']
    recommended_vram_gb = 6.5
    description = "Genre du visage, par DeepFace"
    WEIGHTS = 'Gender'
    ACTION = 'gender'

    def _read(self, found: dict) -> dict:
        scores = found.get('gender') or {}
        return {'gender': found.get('dominant_gender', 'Unknown'),
                'gender_confidence': float(max(scores.values())) / 100.0 if scores else 0.0}
