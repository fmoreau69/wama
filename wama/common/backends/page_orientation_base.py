"""
Contrat de la tâche `page-orientation` — de combien une page photographiée est TOURNÉE.

Spécialisation MÉTIER de `wama.common.backends.base.BaseModelBackend`, sœur de
`ocr_base.OCRBackend` : un classifieur d'orientation ne lit pas la page, il dit l'angle qui la
redresse — un seul redressement sert tous les moteurs d'OCR (`ocr_base.upright_image`). Écrit le
2026-11-07 : `ocr_base` chargeait le classifieur de docTR lui-même (`page_orientation_predictor`,
dans une liste de module), hors de la porte de lancement, de l'enveloppe du gouverneur et du
déchargement commun.

Ce qui vient du COMMUN (ne pas dupliquer) : cycle de vie, dépendances, enveloppe load/unload du
gouverneur, `ENGINE` / `SUPPORTED_MODELS` pour la résolution depuis le catalogue. Ce qui est PROPRE
au domaine ici : le verbe `page_orientation`.
"""
from abc import abstractmethod
from typing import Tuple

from .base import BaseModelBackend


class PageOrientationBackend(BaseModelBackend):
    """`page_orientation(image) → (angle, confiance)` — un modèle `page-orientation` du catalogue.

    Un nouveau moteur = une sous-classe qui déclare `ENGINE`, `SUPPORTED_MODELS`,
    `REQUIRED_PACKAGES` et implémente `load()/unload()/page_orientation()`. L'état de chargement
    vient d'ici : un backend pose `self._loaded` dans `load()`/`unload()`."""

    def __init__(self):
        self._loaded = False
        self._current_model = None

    @property
    def is_loaded(self) -> bool:
        return self._loaded

    def process(self, **kwargs) -> Tuple[int, float]:
        """Point d'entrée générique (contrat commun) → délègue à `page_orientation()`."""
        return self.page_orientation(**kwargs)

    @abstractmethod
    def page_orientation(self, image) -> Tuple[int, float]:
        """(angle en degrés ∈ {0, 90, 180, 270}, confiance 0-1) qui REDRESSE la page de `image`
        (ndarray RGB uint8, H×W×3) : `PIL.Image.rotate(angle, expand=True)` la remet droite
        (vérifié sur les quatre rotations d'une page de texte, 2026-11-07). Un moteur qui rend un
        angle signé le ramène à ce domaine."""
