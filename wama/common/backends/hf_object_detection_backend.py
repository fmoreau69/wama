"""Détecteurs d'objets `transformers` (`AutoModelForObjectDetection`) — RT-DETR, DETR…, au contrat
des détecteurs image par image (2026-10-10).

Premier servi : `justjuu/rtdetr-v2-license-plate-detection` (Apache-2.0), plaques. Sur le banc
des plaques en caméra embarquée basse résolution (cf. `egoblur_backend`) : 40 % de rappel à
69 ms/image, loin devant les YOLO plaques installés (≤ 20 %) ; et des erreurs DIFFÉRENTES
d'EgoBlur — leur union monte à 64,6 %. C'est un complément d'ensemble, pas un remplaçant.

Le code ne dépend pas du modèle : tout `AutoModelForObjectDetection` passe par ici. Un nouveau
modèle s'ajoute en le DÉCLARANT dans `SUPPORTED_MODELS` (le moteur `transformers` est piloté par
plusieurs backends : sans déclaration, la résolution ne sait pas lequel l'exécute).
"""
from __future__ import annotations

import logging
from pathlib import Path

from wama.common.backends.detection_base import FrameDetectionBackend

logger = logging.getLogger(__name__)


def weights_dir() -> Path:
    """Dossier de famille — DÉCLARÉ dans `settings.MODEL_PATHS`, passé en `cache_dir=`."""
    from django.conf import settings
    declared = (settings.MODEL_PATHS.get('vision') or {}).get('object_detection')
    return Path(declared) if declared else (
        Path(settings.AI_MODELS_DIR) / 'models' / 'vision' / 'object-detection')


class HFObjectDetectionBackend(FrameDetectionBackend):
    """Un détecteur `transformers` : ses classes sont celles de sa config (`id2label`)."""

    ENGINE = 'transformers'
    #: ⚠ En LITTÉRAL (l'inventaire lit par AST) ; clé = dernier segment de la clé de catalogue
    #: (`anonymizer:rtdetr-v2-license-plate`). Le DÉPÔT se lit sur la ligne du catalogue
    #: (`hf_id`, déclaré dans `anonymizer/utils/model_config.FRAME_DETECTORS`) — une seule source.
    SUPPORTED_MODELS = {'rtdetr-v2-license-plate': {}}
    REQUIRED_PACKAGES = ['transformers', 'torch']
    name = 'hf_object_detection'
    display_name = 'Détecteur transformers'
    description = "Détecteur d'objets transformers (RT-DETR…), image par image."
    #: RT-DETR v2 R18 : ~80 Mo de poids, < 1 Go en inférence par lots de 8 à 640 px.
    recommended_vram_gb = 1
    BATCH_SIZE = 8

    def __init__(self, *args, **kwargs):
        super().__init__()
        self._model = self._processor = None
        self._loaded_id = ''
        self.catalogue_key = ''

    @property
    def is_loaded(self) -> bool:
        return self._model is not None

    def _hf_id(self) -> str:
        """Le dépôt du modèle choisi, lu sur sa ligne de catalogue."""
        from wama.model_manager.models import AIModel
        hf_id = (AIModel.objects.filter(model_key=self.catalogue_key)
                 .values_list('hf_id', flat=True).first()) if self.catalogue_key else ''
        if not hf_id:
            raise ValueError(f"Détecteur transformers : aucun dépôt pour « {self.catalogue_key} »")
        return hf_id

    def load(self, model: str = None, **kwargs) -> bool:
        hf_id = model or self._hf_id()
        if self._model is not None and self._loaded_id == hf_id:
            return True
        import torch
        from transformers import AutoImageProcessor, AutoModelForObjectDetection
        cache_dir = str(weights_dir())
        self._processor = AutoImageProcessor.from_pretrained(hf_id, cache_dir=cache_dir)
        self._device = 'cuda' if torch.cuda.is_available() else 'cpu'
        self._model = AutoModelForObjectDetection.from_pretrained(
            hf_id, cache_dir=cache_dir).to(self._device).eval()
        self._loaded_id = hf_id
        logger.info('[HF detection] %s chargé sur %s', hf_id, self._device)
        return True

    def unload(self) -> None:
        self._model = self._processor = None
        self._loaded_id = ''
        self._empty_cuda_cache()

    def prepare(self, **kwargs) -> None:
        self.load()

    def document_meta(self, **kwargs) -> dict:
        return {'engine': 'transformers', 'models': [self.catalogue_key or self._loaded_id]}

    def output_tag(self) -> str:
        return self._loaded_id.rsplit('/', 1)[-1] or 'detr'

    def detect_frames(self, images, threshold: float) -> list:
        import cv2
        import torch

        from wama.common.utils import detections as dets
        rgb = [cv2.cvtColor(image, cv2.COLOR_BGR2RGB) for image in images]
        inputs = self._processor(images=rgb, return_tensors='pt').to(self._device)
        with torch.no_grad():
            outputs = self._model(**inputs)
        sizes = [image.shape[:2] for image in images]
        parsed = self._processor.post_process_object_detection(
            outputs, threshold=threshold, target_sizes=sizes)
        names = self._model.config.id2label
        return [[dets.detection(box=box.tolist(), label=names.get(int(label), str(int(label))),
                                conf=float(score))
                 for box, label, score in zip(p['boxes'].cpu(), p['labels'].cpu(), p['scores'].cpu())]
                for p in parsed]
