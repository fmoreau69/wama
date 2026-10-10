"""EgoBlur (Meta, Apache-2.0) — détecteur de plaques fait pour anonymiser la vidéo embarquée.

Intégré le 2026-10-10 après un banc sur 320 images de caméras embarquées basse résolution
(~400×248), où les détecteurs de plaques du catalogue plafonnaient : rappel des plaques sur les
véhicules proches — YOLO plaques installés ≤ 20 %, SAM3 « license plate » 42 % (490 ms/image),
RT-DETR v2 40 % (69 ms), **EgoBlur gen1 59,5 % (42 ms)** une fois l'image agrandie à 600 px de
côté court et le seuil à 0,1 ; 50 % au seuil 0,25. Gen2 (Aria Gen2) fait moins bien sur ces
images (≤ 52 %) et exige le code détecteur de son paquet : il n'est pas servi.

Le modèle est un Faster R-CNN exporté en TorchScript TRACÉ : il prend une image BGR uint8
`C×H×W` et rend `(boîtes, étiquettes, scores, taille)` dans le repère de l'image reçue. Ni
paquet ni code tiers à vendoriser : `torch.jit.load` suffit — d'où le moteur `torchscript`.

⚠ Poids remis À LA MAIN : Meta les distribue derrière un formulaire (projectaria.com), aucun
dépôt ne les sert ; ils se posent dans `MODEL_PATHS['vision']['egoblur']` et la découverte du
catalogue les voit (`model_registry._discover_anonymizer_models`).
"""
from __future__ import annotations

import logging
from pathlib import Path

from wama.common.backends.detection_base import FrameDetectionBackend

logger = logging.getLogger(__name__)

def weights_dir() -> Path:
    """Dossier des poids — DÉCLARÉ dans `settings.MODEL_PATHS`, jamais deviné."""
    from django.conf import settings
    declared = (settings.MODEL_PATHS.get('vision') or {}).get('egoblur')
    return Path(declared) if declared else (
        Path(settings.AI_MODELS_DIR) / 'models' / 'vision' / 'egoblur')


class EgoBlurBackend(FrameDetectionBackend):
    """Plaques (et demain visages) d'EgoBlur, image par image."""

    ENGINE = 'torchscript'
    #: Poids servis : identifiant (dernier segment de la clé de catalogue) → fichier et réglages
    #: MESURÉS au banc. `short_side` : côté court où l'image est agrandie avant détection (le
    #: modèle a appris sur des images bien plus grandes que celles d'une caméra embarquée) ;
    #: `threshold` : seuil propre au modèle (ses scores n'ont pas l'échelle de ceux de YOLO).
    #: ⚠ En LITTÉRAL : l'inventaire lit les clés par AST, sans importer.
    SUPPORTED_MODELS = {
        'egoblur-lp-gen1': {'file': 'ego_blur_lp_gen1.jit', 'label': 'license_plate',
                            'short_side': 600, 'threshold': 0.1},
    }
    REQUIRED_PACKAGES = ['torch', 'torchvision', 'cv2']
    name = 'egoblur'
    display_name = 'EgoBlur (Meta)'
    description = ("EgoBlur (Meta) — plaques d'immatriculation dans la vidéo embarquée, "
                   "rappel d'abord.")
    #: Faster R-CNN ResNet : ~0,4 Go de poids, ~1,5 Go mesurés en inférence à 600 px.
    recommended_vram_gb = 2
    #: Le modèle tracé ne prend qu'une image par appel.
    BATCH_SIZE = 1

    def __init__(self, *args, **kwargs):
        super().__init__()
        self._model = None
        self._spec = None
        self.catalogue_key = ''

    @property
    def is_loaded(self) -> bool:
        return self._model is not None

    def _model_id(self) -> str:
        from wama.common.utils.model_keys import backend_model_id
        return backend_model_id(self.catalogue_key) if self.catalogue_key else 'egoblur-lp-gen1'

    def load(self, model: str = None, **kwargs) -> bool:
        model_id = model or self._model_id()
        spec = self.SUPPORTED_MODELS.get(model_id)
        if spec is None:
            raise ValueError(f"EgoBlur : modèle non servi « {model_id} » (servis : {list(self.SUPPORTED_MODELS)})")
        if self._model is not None and self._spec is spec:
            return True
        import torch
        path = weights_dir() / spec['file']
        if not path.is_file():
            raise FileNotFoundError(f"EgoBlur : poids absents ({path}) — Meta les distribue par "
                                    "formulaire, ils se déposent dans ce dossier.")
        # Chargé sur le processeur PUIS déplacé : chargé directement sur le GPU, le modèle tracé
        # garde des constantes sur le processeur et échoue au premier appel (mesuré).
        device = 'cuda' if torch.cuda.is_available() else 'cpu'
        self._model = torch.jit.load(str(path), map_location='cpu').to(device)
        self._device, self._spec = device, spec
        logger.info('[EgoBlur] %s chargé sur %s', spec['file'], device)
        return True

    def unload(self) -> None:
        self._model, self._spec = None, None
        self._empty_cuda_cache()

    def prepare(self, **kwargs) -> None:
        self.load()

    def threshold_for(self, **kwargs) -> float:
        """Le seuil MESURÉ du modèle : le seuil de la card est à l'échelle des scores YOLO."""
        return float(self._spec['threshold'])

    def document_meta(self, **kwargs) -> dict:
        return {'engine': 'egoblur', 'models': [self.catalogue_key or self._model_id()]}

    def output_tag(self) -> str:
        return 'egoblur'

    def detect_frames(self, images, threshold: float) -> list:
        import cv2
        import numpy as np
        import torch
        import torchvision

        from wama.common.utils import detections as dets
        results = []
        for image in images:
            h, w = image.shape[:2]
            scale = max(1.0, self._spec['short_side'] / min(h, w))
            nh, nw = int(h * scale + 0.5), int(w * scale + 0.5)
            x = image if scale == 1.0 else cv2.resize(image, (nw, nh), interpolation=cv2.INTER_CUBIC)
            tensor = torch.from_numpy(np.ascontiguousarray(x.transpose(2, 0, 1))).to(self._device)
            with torch.no_grad():
                boxes, _labels, scores, _size = self._model(tensor)
            keep = torchvision.ops.nms(boxes, scores, 0.3)
            boxes, scores = boxes[keep].cpu().numpy(), scores[keep].cpu().numpy()
            found = []
            for box, score in zip(boxes, scores):
                if score < threshold:
                    continue
                found.append(dets.detection(box=[box[0] * w / nw, box[1] * h / nh,
                                                 box[2] * w / nw, box[3] * h / nh],
                                            label=self._spec['label'], conf=float(score)))
            results.append(found)
        return results
