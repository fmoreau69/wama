"""FER — le contrat `face-analysis` sur la librairie `fer` (émotions seules).

Tranché le 2026-11-09, en construisant le service TensorFlow : FER est un backend du contrat, comme
DeepFace, et il tourne dans le même service. Il n'a PAS de ligne de catalogue (décision du
2026-09-05, `face_analyzer/utils/model_config.py`) : ses poids sont dans sa roue, il n'y a rien à
installer ni à retirer séparément. `BUNDLED_WEIGHTS` le dit à l'inventaire ; la porte commune le
trouve par son moteur (`backend_for_engine('fer', task='face-analysis')`).

Son modèle est l'interpréteur TensorFlow Lite de la roue, sur le processeur (`use_tflite` par défaut
dans `FER.__init__`) : il ne tient rien sur la carte, dans le service comme chez l'appelant.
"""
from typing import Optional

from wama.common.tensorflow_service import runtime

from .face_analysis_base import FaceAnalysisBackend
from .tensorflow_base import TensorFlowBackend


def _import_fer():
    """Rend la classe `FER`, quelle que soit la disposition du paquet.

    ⚠ DÉFAUT MESURÉ le 2026-09-05 : le backend FER — qui est le backend PAR DÉFAUT de cette
    app — levait `ImportError: cannot import name 'FER' from 'fer'`. Cause : `fer` 25.10.3
    n'expose plus que `log`/`logging` à sa racine ; la classe a migré dans le sous-module
    `fer.fer`. Le paquet est le même projet (justinshenk/fer), c'est sa surface publique qui
    a changé — et `requirements/linux.txt` demandait `fer>=22.5.0`, borne haute absente, donc
    la montée en 25.x s'est faite toute seule.

    On essaie les DEUX dispositions plutôt que d'épingler : rien à rétrograder, et l'app
    marche avec l'ancienne comme avec la nouvelle. *Un pin fige une version ; suivre les deux
    dispositions suit le paquet.*
    """
    try:
        from fer import FER            # disposition ≤ 24.x
        return FER
    except ImportError as racine:
        try:
            from fer.fer import FER    # disposition ≥ 25.x
            return FER
        except ImportError as feuille:
            # Les DEUX dispositions ont échoué : l'erreur utile est la SECONDE (la première
            # est attendue en 25.x), mais on garde la chaîne pour ne pas perdre le contexte.
            raise ImportError(
                f"`fer` présent mais inutilisable — racine: {racine} / sous-module: {feuille}"
            ) from feuille


class FERBackend(TensorFlowBackend, FaceAnalysisBackend):
    """Les sept émotions du premier visage, par FER (détecteur OpenCV, modèle TensorFlow Lite)."""

    ENGINE = 'fer'
    REQUIRED_PACKAGES = ['fer']
    BUNDLED_WEIGHTS = "poids embarqués dans la roue `fer` : rien à cataloguer ni à installer à part"
    recommended_vram_gb = 0
    description = "Émotions par FER, sur le processeur"

    def __init__(self):
        super().__init__()
        self._detector = None

    def load(self, model: Optional[str] = None) -> bool:
        if self._loaded:
            return True
        runtime.tensorflow()
        self._detector = _import_fer()(mtcnn=False)     # OpenCV : plus rapide
        self._loaded, self._current_model = True, 'fer'
        return True

    def unload(self) -> None:
        self._detector = None
        self._loaded, self._current_model = False, None

    def analyze_face(self, image, detector: str = 'opencv') -> Optional[dict]:
        if not self._loaded:
            raise RuntimeError("FERBackend : modèle non chargé (`load()` d'abord)")
        found = self._detector.detect_emotions(image)
        return {'emotions': found[0]['emotions']} if found else None
