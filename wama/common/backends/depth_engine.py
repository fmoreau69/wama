"""Depth Pro — cycle de vie du modèle et inférence. AUCUN ORM.

Extrait de `cam_analyzer/utils/depth_estimator.py` le 2026-09-07 (coupe pur/ORM). Ce module
mélangeait deux natures : le chargement + l'inférence, qui ne touchent aucun modèle Django, et
l'orchestration de session (`session.cameras.all()`, `DepthFrame.objects`), qui ne fait que ça.
Seule la première peut suivre les backends vers le substrat transversal — c'était le dernier
des quatre « backends attachés » avec son jumeau de face_analyzer.

⚠ `settings` est lu ici, et ce n'est PAS une dépendance d'app : tous les backends lisent
`MODEL_PATHS`. La propriété qui rend un backend déplaçable est l'absence d'**ORM**, pas
l'absence de Django.

La partie ORM reste dans `utils/depth_estimator.py` et IMPORTE ce module — le sens de la
dépendance compte : l'orchestration connaît le moteur, jamais l'inverse.
"""
import logging
import math

import numpy as np
from django.conf import settings

logger = logging.getLogger(__name__)


# « Path d'abord, env vars ensuite, import après » (AGENTS.md §Ajout d'un nouveau modèle AI).
DEPTH_MODEL_ID = 'apple/DepthPro-hf'  # natif transformers, métrique + focale estimée, Apache-2.0
DEPTH_MODEL_DIR = (settings.MODEL_PATHS.get('vision', {}).get('depth')
                   or settings.AI_MODELS_DIR / "models" / "vision" / "depth-pro")

# keep_loaded : Depth Pro est coûteux à charger et identique pour toutes les caméras/analyses →
# cache module (chargé 1×, réutilisé), même patron que `yolopv2_segmenter._MODEL_CACHE`.
_MODEL_CACHE = {}   # (model_id, device) -> (processor, model)


def is_available() -> bool:
    """Vrai si les poids Depth Pro sont présents sur disque (téléchargés via `pull_model`)."""
    try:
        from pathlib import Path
        root = Path(DEPTH_MODEL_DIR)
        return root.exists() and any(root.rglob('*.safetensors'))
    except Exception:
        return False


def clear_model_cache():
    """Libère Depth Pro gardé en cache (keep_loaded) et rend la VRAM. À appeler avant une étape
    VRAM-critique (comme `yolopv2_segmenter.clear_model_cache`)."""
    global _MODEL_CACHE
    _MODEL_CACHE.clear()
    try:
        import gc
        import torch
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception:
        pass


def load(device: str = 'cuda'):
    """Charge Depth Pro (keep_loaded) et retourne (processor, model, device_effectif).

    Pattern obligatoire (AGENTS.md §Ajout d'un nouveau modèle AI, corrigé le 2026-09-03) :
    `cache_dir=` passé à `from_pretrained`, et **jamais** de mutation d'environnement — elle
    emporterait les sous-dépendances du modèle hors du cache partagé (ROADMAP §5b).
    """
    cache = str(DEPTH_MODEL_DIR)

    import torch
    if device == 'cuda' and not torch.cuda.is_available():
        logger.warning("[DepthPro] CUDA indisponible — repli CPU")
        device = 'cpu'

    _key = (DEPTH_MODEL_ID, device)
    cached = _MODEL_CACHE.get(_key)
    if cached is not None:
        return cached[0], cached[1], device

    from transformers import AutoModelForDepthEstimation, AutoImageProcessor
    dtype = torch.float16 if device == 'cuda' else torch.float32
    processor = AutoImageProcessor.from_pretrained(DEPTH_MODEL_ID, cache_dir=cache)
    model = AutoModelForDepthEstimation.from_pretrained(
        DEPTH_MODEL_ID, cache_dir=cache, torch_dtype=dtype,
    ).to(device).eval()
    _MODEL_CACHE[_key] = (processor, model)
    logger.info(f"[DepthPro] Chargé (cache) : {DEPTH_MODEL_ID} sur {device}")
    return processor, model, device


def estimate_depth(frame_bgr, device: str = 'cuda'):
    """Profondeur métrique d'une frame BGR.

    Retourne (depth_m, focal_px) :
      - depth_m : ndarray HxW float32, profondeur métrique le long de l'axe optique (mètres) ;
      - focal_px : focale estimée par Depth Pro (pixels, résolution d'origine) ou None.
    Brique réutilisable (les autres usages profondeur §[E] la partagent).
    """
    import torch
    from PIL import Image
    import cv2

    processor, model, device = load(device)
    h0, w0 = frame_bgr.shape[:2]
    image = Image.fromarray(cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB))
    inputs = processor(images=image, return_tensors='pt')
    inputs = {k: (v.to(device) if hasattr(v, 'to') else v) for k, v in inputs.items()}
    with torch.no_grad():
        outputs = model(**inputs)
    post = processor.post_process_depth_estimation(outputs, target_sizes=[(h0, w0)])[0]

    depth = post['predicted_depth']
    depth_m = depth.detach().float().cpu().numpy().astype(np.float32)
    def _scalar(x):
        if x is None:
            return None
        if hasattr(x, 'item'):
            try:
                return float(x.item())
            except Exception:
                return float(np.asarray(x).reshape(-1)[0])
        return float(x)

    focal_px = _scalar(post.get('focal_length', None))
    if not focal_px:
        # Selon la version transformers, seul l'angle de champ horizontal peut être fourni.
        fov_h = _scalar(post.get('field_of_view', None))
        if fov_h:
            focal_px = (w0 / 2.0) / math.tan(math.radians(fov_h) / 2.0)
    return depth_m, focal_px


def unload():
    """keep_loaded : ne libère PAS le cache (réutilisé sur les vues/analyses suivantes)."""
    return None
