"""Profondeur monoculaire (Depth Pro, ZoeDepth) — cycle de vie du modèle et inférence. AUCUN ORM.

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

# Les modèles de profondeur que ce moteur sait charger — DÉCLARÉS, une ligne par modèle. La clé
# est celle du catalogue (`huggingface:<clé>`). Ajouté le 2026-09-28 : un banc sur les images du
# projet ENA (96 images, arbitres = rig connu, `CAM_ANALYZER_CHANGELOG` du jour) a montré que
# ZoeDepth-KITTI reproduit la FORME de la scène (profil de route à ±7 %) avec un facteur
# d'échelle constant, là où Depth Pro rend des cartes aberrantes sur ce rig grand-angle
# derrière vitrage. D'où le défaut.
#   • `metric_scale` : le modèle rend-il des mètres exploitables tels quels ? Sinon l'appelant
#     ANCRE l'échelle (hauteur de caméra du rig) — ce moteur ne le fait pas, il ne connaît pas
#     le véhicule ;
#   • `estimates_focal` : le post-traitement rend-il une focale ;
#   • `source_sizes` : ZoeDepth pad l'entrée, son post-traitement a besoin de la taille source ;
#   • `fp16_on_cuda` : demi-précision sur GPU (Depth Pro : oui ; ZoeDepth, 345 M : inutile).
DEPTH_MODELS = {
    'depthpro': {
        'hf_id': DEPTH_MODEL_ID, 'dir': DEPTH_MODEL_DIR, 'label': 'Apple Depth Pro',
        'metric_scale': True, 'estimates_focal': True, 'source_sizes': False, 'fp16_on_cuda': True,
    },
    'zoedepth-kitti': {
        'hf_id': 'Intel/zoedepth-kitti', 'label': 'ZoeDepth (KITTI)',
        'dir': (settings.MODEL_PATHS.get('vision', {}).get('zoedepth')
                or settings.AI_MODELS_DIR / "models" / "vision" / "zoedepth"),
        'metric_scale': False, 'estimates_focal': False, 'source_sizes': True, 'fp16_on_cuda': False,
    },
}
DEFAULT_DEPTH_MODEL = 'zoedepth-kitti'

# keep_loaded : un modèle de profondeur est coûteux à charger et identique pour toutes les
# caméras/analyses → cache module (chargé 1×, réutilisé), patron `yolopv2_segmenter._MODEL_CACHE`.
_MODEL_CACHE = {}   # (model_id, device) -> (processor, model)


def depth_model_spec(model_key=None) -> dict:
    """La déclaration d'un modèle (défaut : `DEFAULT_DEPTH_MODEL`). Clé inconnue → KeyError :
    un nom mal écrit ne doit pas retomber en silence sur un autre modèle."""
    return DEPTH_MODELS[model_key or DEFAULT_DEPTH_MODEL]


def is_available(model_key=None) -> bool:
    """Vrai si les poids du modèle sont présents sur disque (téléchargés via `pull_model`)."""
    try:
        from pathlib import Path
        root = Path(depth_model_spec(model_key)['dir'])
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


def load(device: str = 'cuda', model_key=None):
    """Charge un modèle de profondeur (keep_loaded) et retourne (processor, model, device_effectif).

    Pattern obligatoire (AGENTS.md §Ajout d'un nouveau modèle AI, corrigé le 2026-09-03) :
    `cache_dir=` passé à `from_pretrained`, et **jamais** de mutation d'environnement — elle
    emporterait les sous-dépendances du modèle hors du cache partagé (ROADMAP §5b).
    """
    spec = depth_model_spec(model_key)
    hf_id, cache = spec['hf_id'], str(spec['dir'])

    import torch
    if device == 'cuda' and not torch.cuda.is_available():
        logger.warning("[profondeur] CUDA indisponible — repli CPU")
        device = 'cpu'

    _key = (hf_id, device)
    cached = _MODEL_CACHE.get(_key)
    if cached is not None:
        return cached[0], cached[1], device

    from transformers import AutoModelForDepthEstimation, AutoImageProcessor
    dtype = torch.float16 if (device == 'cuda' and spec['fp16_on_cuda']) else torch.float32
    processor = AutoImageProcessor.from_pretrained(hf_id, cache_dir=cache)
    model = AutoModelForDepthEstimation.from_pretrained(
        hf_id, cache_dir=cache, torch_dtype=dtype,
    ).to(device).eval()
    _MODEL_CACHE[_key] = (processor, model)
    logger.info(f"[profondeur] Chargé (cache) : {hf_id} sur {device}")
    return processor, model, device


def estimate_depth(frame_bgr, device: str = 'cuda', model_key=None):
    """Profondeur d'une frame BGR, le long de l'axe optique.

    Retourne (depth_m, focal_px) :
      - depth_m : ndarray HxW float32 — en MÈTRES si le modèle déclare `metric_scale`, sinon à un
        facteur d'échelle près que l'appelant ancre (cf. `DEPTH_MODELS`) ;
      - focal_px : focale estimée (pixels, résolution d'origine), ou None si le modèle n'en rend pas.
    Brique réutilisable (les autres usages profondeur §[E] la partagent).
    """
    import torch
    from PIL import Image
    import cv2

    spec = depth_model_spec(model_key)
    processor, model, device = load(device, model_key)
    h0, w0 = frame_bgr.shape[:2]
    image = Image.fromarray(cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB))
    inputs = processor(images=image, return_tensors='pt')
    inputs = {k: (v.to(device=device, dtype=model.dtype) if hasattr(v, 'is_floating_point')
                  and v.is_floating_point() else (v.to(device) if hasattr(v, 'to') else v))
              for k, v in inputs.items()}
    with torch.no_grad():
        outputs = model(**inputs)
    extra = {'source_sizes': [(h0, w0)]} if spec['source_sizes'] else {}
    post = processor.post_process_depth_estimation(outputs, target_sizes=[(h0, w0)], **extra)[0]

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

    if not spec['estimates_focal']:
        return depth_m, None
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
