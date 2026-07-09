"""
SAM3 road markings analyzer for cam_analyzer (Phase Avancée).

Detects road markings (stop lines, pedestrian crossings) using SAM3 text prompts,
and optionally produces road-area masks as a fallback when no BDD100K YOLO model is
configured.

Results are stored in DetectionFrame.detections as:
  {'type': 'sam3_marking', 'label': 'stop_line'|str, 'prompt': str,
   'bbox': [x1,y1,x2,y2], 'confidence': float, 'class_name': str,
   'track_id': None, 'proximity': 0.0}

  {'type': 'road_mask', 'class_name': 'drivable area (sam3)',
   'polygon': [[x,y],...], 'confidence': float}

The SAM3 inference is CPU/GPU agnostic and only runs on frames that fall inside
GPS-gated intersection windows (see tasks.py for the window pre-computation).
"""
import gc
import logging

import cv2
import numpy as np

logger = logging.getLogger(__name__)

# ─── Default prompts ──────────────────────────────────────────────────────────

DEFAULT_MARKING_PROMPTS = [
    {'label': 'stop_line', 'prompt': 'white stop line painted on road surface'},
    {'label': 'crossing',  'prompt': 'pedestrian crossing zebra stripes on road'},
]

DEFAULT_ROAD_PROMPT = 'drivable road surface area in front of the vehicle'

CONFIDENCE_THRESHOLD = 0.30


def _as_seq(x):
    """[] si None, sinon x tel quel (liste OU Tensor). Évite `x or []` qui lève
    « Boolean value of Tensor is ambiguous » quand x est un Tensor SAM3."""
    return [] if x is None else x

# Polygon simplification: epsilon = ratio × perimeter
POLY_EPSILON_RATIO = 0.005


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _to_numpy(mask, target_hw: tuple) -> np.ndarray:
    """Convert SAM3 mask (tensor or ndarray) to uint8 binary at target size."""
    try:
        import torch
        if torch.is_tensor(mask):
            mask = mask.cpu().numpy()
    except ImportError:
        pass
    mask = np.asarray(mask)
    if mask.ndim == 3:
        mask = mask.squeeze()
    if mask.ndim == 4:
        mask = mask.squeeze(0).squeeze(0)
    if mask.max() <= 1.0:
        mask = (mask * 255).astype(np.uint8)
    else:
        mask = mask.astype(np.uint8)
    if mask.shape[:2] != target_hw:
        mask = cv2.resize(mask, (target_hw[1], target_hw[0]),
                          interpolation=cv2.INTER_LINEAR)
    return mask


def _mask_to_polygon(mask_np: np.ndarray) -> list:
    """Largest simplified contour of a binary mask → [[x,y], ...]."""
    binary = (mask_np > 127).astype(np.uint8) * 255
    contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return []
    largest = max(contours, key=cv2.contourArea)
    perimeter = cv2.arcLength(largest, True)
    approx = cv2.approxPolyDP(largest, POLY_EPSILON_RATIO * perimeter, True)
    pts = approx.squeeze()
    if pts.ndim == 1:          # single point
        return []
    return pts.tolist()


def _mask_to_bbox(mask_np: np.ndarray) -> list:
    """Return [x1, y1, x2, y2] from binary mask, or [0,0,0,0]."""
    binary = (mask_np > 127).astype(np.uint8)
    rows = np.any(binary, axis=1)
    cols = np.any(binary, axis=0)
    if not rows.any():
        return [0, 0, 0, 0]
    r0, r1 = np.where(rows)[0][[0, -1]]
    c0, c1 = np.where(cols)[0][[0, -1]]
    return [int(c0), int(r0), int(c1), int(r1)]


# ─── Main class ──────────────────────────────────────────────────────────────

class SAM3RoadAnalyzer:
    """
    Wraps the SAM3 image model for road-marking and road-area detection.

    Args:
        marking_prompts : List of {label, prompt} dicts for road markings.
                          Defaults to stop_line + pedestrian crossing.
        road_fallback   : If True, also produce a road_mask entry per frame
                          (when the caller has no YOLO BDD100K model).
        device          : 'cuda' or 'cpu'.
    """

    def __init__(self, marking_prompts=None, road_fallback: bool = False,
                 device: str = 'cuda'):
        self.marking_prompts = marking_prompts or DEFAULT_MARKING_PROMPTS
        self.road_fallback   = road_fallback
        self.device          = device
        self._processor      = None   # Sam3ImageProcessor instance

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def load(self):
        """Load SAM3 image model. Must be called before analyze_frame()."""
        # Env setup BEFORE any SAM3 import (CLAUDE.md: env vars avant imports HF)
        from wama.anonymizer.core.sam3_processor import setup_sam3_hf_environment
        setup_sam3_hf_environment()

        try:
            from sam3.model_builder import build_sam3_image_model
            from sam3.model.sam3_image_processor import Sam3Processor as _Sam3Proc

            image_model = build_sam3_image_model()
            self._processor = _Sam3Proc(image_model)
            logger.info("[SAM3RoadAnalyzer] Model loaded")
        except ImportError as e:
            raise ImportError(f"SAM3 not installed. pip install sam3\n{e}")
        except Exception as e:
            raise RuntimeError(f"SAM3 model loading failed: {e}")

    def unload(self):
        """Release SAM3 from memory."""
        import torch
        self._processor = None
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        logger.info("[SAM3RoadAnalyzer] Model unloaded")

    # ── Inference ─────────────────────────────────────────────────────────────

    def analyze_frame(self, frame_bgr: np.ndarray, min_confidence: float = None) -> list:
        """
        Run SAM3 on a single BGR frame (numpy array).

        min_confidence : seuil de rejet (défaut = CONFIDENCE_THRESHOLD) ; passer 0.0
        pour tout retourner (outil de diagnostic « test SAM3 sur une image »).

        Returns a list of detection dicts ready to append to DetectionFrame.detections.
        Each dict is one of:

          Road marking (stop line / crossing / custom):
            {'type': 'sam3_marking', 'label': str, 'prompt': str,
             'bbox': [x1,y1,x2,y2], 'confidence': float,
             'class_name': str,  'track_id': None, 'proximity': 0.0}

          Road mask fallback (type matches RoadSegmenter output so it's picked up
          by IntersectionAnalyzer._classify_post_stop_v2):
            {'type': 'road_mask', 'class_name': 'drivable area (sam3)',
             'polygon': [[x,y],...], 'confidence': float}
        """
        if self._processor is None:
            return []

        from PIL import Image

        thr = CONFIDENCE_THRESHOLD if min_confidence is None else float(min_confidence)
        frame_rgb  = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        pil_frame  = Image.fromarray(frame_rgb)
        h, w       = frame_bgr.shape[:2]
        results    = []

        # ── Road markings ──────────────────────────────────────────────────
        for pd in self.marking_prompts:
            label  = pd.get('label', 'marking')
            prompt = pd.get('prompt', '').strip()
            if not prompt:
                continue
            try:
                state  = self._processor.set_image(pil_frame)
                output = self._processor.set_text_prompt(state=state, prompt=prompt)
            except Exception as e:
                logger.debug(f"[SAM3RoadAnalyzer] prompt '{label}' failed: {e}")
                continue

            masks  = _as_seq(output.get('masks'))
            scores = _as_seq(output.get('scores'))

            # Diagnostic : voir ce que SAM3 renvoie RÉELLEMENT (avant seuil). Permet
            # de distinguer « rien détecté » (0 mask) de « détecté mais score faible »
            # (masks présents mais < seuil) → ajuster CONFIDENCE_THRESHOLD si besoin.
            if len(masks):
                logger.info("[SAM3] '%s' : %d mask(s), scores=%s (seuil %.2f)",
                            label, len(masks),
                            [round(float(s), 3) for s in scores[:6]], CONFIDENCE_THRESHOLD)

            for i, mask in enumerate(masks):
                score = float(scores[i]) if i < len(scores) else 1.0
                if score < thr:
                    continue
                mask_np = _to_numpy(mask, (h, w))
                bbox    = _mask_to_bbox(mask_np)
                polygon = _mask_to_polygon(mask_np)   # nécessaire à l'auto-calibration (coins passage)
                results.append({
                    'type':       'sam3_marking',
                    'label':      label,
                    'prompt':     prompt,
                    'bbox':       bbox,
                    'polygon':    polygon,
                    'confidence': round(score, 3),
                    # Required fields for the main detections loop in tasks.py
                    'class_name': label,
                    'track_id':   None,
                    'proximity':  0.0,
                })

        # ── Road mask fallback ─────────────────────────────────────────────
        if self.road_fallback:
            try:
                state  = self._processor.set_image(pil_frame)
                output = self._processor.set_text_prompt(
                    state=state, prompt=DEFAULT_ROAD_PROMPT
                )
                masks  = _as_seq(output.get('masks'))
                scores = _as_seq(output.get('scores'))
                for i, mask in enumerate(masks):
                    score = float(scores[i]) if i < len(scores) else 1.0
                    if score < thr:
                        continue
                    mask_np = _to_numpy(mask, (h, w))
                    polygon = _mask_to_polygon(mask_np)
                    if not polygon:
                        continue
                    results.append({
                        'type':       'road_mask',
                        'class_name': 'drivable area (sam3)',
                        'polygon':    polygon,
                        'confidence': round(score, 3),
                    })
                    break  # one road mask per frame is enough
            except Exception as e:
                logger.debug(f"[SAM3RoadAnalyzer] road fallback failed: {e}")

        return results
