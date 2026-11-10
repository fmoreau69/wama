"""docTR, CLASSIFIEUR d'orientation de page — le contrat `page-orientation` sur le moteur `doctr`.

Le reader redresse une photo avant TOUT moteur d'OCR (`ocr_base.upright_image`, card #1335 : une
note prise de côté, que GLM-OCR ne lisait pas couchée). Jusqu'au 2026-11-07, `ocr_base` chargeait le
classifieur lui-même (`page_orientation_predictor`, gardé dans une liste de module) : hors de la
porte de lancement, de l'enveloppe du gouverneur et du déchargement commun. Ce backend est ce
chargement, au contrat — à côté de `DocTRBackend`, pas dedans : le cache commun garde UNE instance
par classe (`manager.backend_instance`), et le classifieur sert aussi les autres moteurs d'OCR.

Sur le PROCESSEUR, comme tout docTR dans WAMA (ses modèles restent où la librairie les crée) :
6 Mo, ~0,04 s par image — `recommended_vram_gb = 0`. Ses poids sont DÉCLARÉS à côté de la brique
d'OCR (`ocr_base.PAGE_ORIENTATION_FILES`) et installés par la route ; le contrat OCR le déclare
(`OCRBackend.OPTIONAL_MODELS`, 2026-11-10), la route l'amène donc avec tout moteur d'OCR — la glu
de partition du reader le demande elle-même, c'est elle qui y redresse.
"""
from __future__ import annotations

import gc
import logging
from typing import Optional, Tuple

from .ocr_base import PAGE_ORIENTATION_KEY, doctr_folder, page_orientation_installed
from .page_orientation_base import PageOrientationBackend

logger = logging.getLogger(__name__)


class DocTROrientationBackend(PageOrientationBackend):
    """L'angle d'une page (0, 90, 180, 270°), par `mobilenet_v3_small_page_orientation` de docTR."""

    #: Moteur piloté (contrat commun) — celui de `DocTRBackend` : la librairie docTR.
    ENGINE = 'doctr'
    #: Modèles servis : clé = dernier segment de la clé de catalogue (`github:mindee/doctr:v0.8.1`,
    #: la version GitHub qui publie les poids). ⚠ En LITTÉRAL : l'inventaire lit les clés par AST.
    SUPPORTED_MODELS = {
        'v0.8.1': {'model_key': 'github:mindee/doctr:v0.8.1'},
    }
    REQUIRED_PACKAGES = ['doctr']
    name = 'doctr-orientation'
    display_name = "docTR (orientation de page)"
    description = "Angle dont une page photographiée est tournée, avant tout moteur d'OCR."

    #: Le processeur, déclaré : l'enveloppe du gouverneur ne publie rien pour lui.
    device = 'cpu'
    recommended_vram_gb = 0

    def __init__(self):
        super().__init__()
        self._predictor = None

    def load(self, model: Optional[str] = None) -> bool:
        if self._loaded:
            return True
        # Absent, on le DIT : la route l'installe, la librairie ne le télécharge pas d'elle-même.
        if not page_orientation_installed():
            raise RuntimeError(f"Le classifieur d'orientation n'est pas installé ({doctr_folder()}) — "
                               f"il s'installe par le model manager (ligne « {PAGE_ORIENTATION_KEY} »).")
        from doctr.models import page_orientation_predictor
        self._predictor = page_orientation_predictor(pretrained=True)
        self._loaded, self._current_model = True, PAGE_ORIENTATION_KEY
        logger.info('[DocTROrientation] chargé (processeur)')
        return True

    def unload(self) -> None:
        self._predictor = None
        gc.collect()
        self._loaded, self._current_model = False, None

    def page_orientation(self, image) -> Tuple[int, float]:
        if not self._loaded:
            raise RuntimeError("DocTROrientationBackend : modèle non chargé (`load()` d'abord)")
        _, angles, confidences = self._predictor([image])
        # docTR rend un angle SIGNÉ (mesuré le 2026-11-07 : -90 pour une page tournée de 90° par
        # `PIL.rotate`) ; ramené au domaine du contrat — la même rotation.
        return int(angles[0]) % 360, float(confidences[0])
