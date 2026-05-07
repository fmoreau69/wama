"""
YOLOPv2 multi-task model wrapper for road / drivable-area segmentation.

YOLOPv2 (CAIC-AD/YOLOPv2) is a TorchScript model with three heads:
  - Object detection (bypassed here — YOLO runs that pass already)
  - Drivable-area segmentation  → exposed as 'road_mask' polygons
  - Lane-line segmentation      → exposed as 'lane_mask' polygons

The class exposes the same load() / unload() / segment_frame() surface as
RoadSegmenter, so tasks.py can swap one for the other based on the model
filename without further plumbing.

Reference: github.com/CAIC-AD/YOLOPv2 (demo.py / utils/utils.py)
"""
from __future__ import annotations

import gc
import logging

import cv2
import numpy as np
import torch

logger = logging.getLogger(__name__)

# YOLOPv2 official input size (height, width)
_INPUT_H, _INPUT_W = 384, 640
# Stride used by the seg-head upsample (matches official demo)
_SEG_STRIDE = 8


def _letterbox(img: np.ndarray, new_h: int, new_w: int) -> tuple[np.ndarray, float, int, int]:
    """Letterbox-resize while preserving aspect ratio, padding with grey."""
    h, w = img.shape[:2]
    r = min(new_h / h, new_w / w)
    nw, nh = int(round(w * r)), int(round(h * r))
    pad_w = (new_w - nw) // 2
    pad_h = (new_h - nh) // 2
    resized = cv2.resize(img, (nw, nh), interpolation=cv2.INTER_LINEAR)
    out = np.full((new_h, new_w, 3), 114, dtype=np.uint8)
    out[pad_h:pad_h + nh, pad_w:pad_w + nw] = resized
    return out, r, pad_w, pad_h


def _mask_to_polygons(mask: np.ndarray, min_area: int = 500) -> list[list[list[float]]]:
    """Extract polygon contours from a binary mask. Returns list of [[x,y],...]."""
    if mask.dtype != np.uint8:
        mask = mask.astype(np.uint8)
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    polygons = []
    for c in contours:
        if cv2.contourArea(c) < min_area:
            continue
        # Simplify to ≤ 60 vertices so the JSON payload stays compact
        eps = max(1.0, 0.003 * cv2.arcLength(c, True))
        c = cv2.approxPolyDP(c, eps, True)
        pts = c.reshape(-1, 2).astype(float).tolist()
        if len(pts) >= 3:
            polygons.append(pts)
    return polygons


class YOLOPv2RoadSegmenter:
    """
    Drop-in replacement for RoadSegmenter when the user's road_model_path
    points at yolopv2.pt. Loads the TorchScript model and runs inference,
    returning drivable-area + lane-line polygons in the original frame's
    pixel coordinate system.
    """

    def __init__(self, model_path: str, device: str = 'cuda', **_unused):
        self.model_path = model_path
        self.device = device
        self._model = None

    # ─── Lifecycle ────────────────────────────────────────────────────────────

    def load(self):
        if self.device == 'cuda' and not torch.cuda.is_available():
            logger.warning("[YOLOPv2] CUDA unavailable — falling back to CPU")
            self.device = 'cpu'
        self._model = torch.jit.load(self.model_path, map_location=self.device)
        self._model.eval()
        # Warmup so first real inference doesn't pay the JIT specialization cost
        with torch.no_grad():
            dummy = torch.zeros(1, 3, _INPUT_H, _INPUT_W, device=self.device)
            try:
                self._model(dummy)
            except Exception as exc:
                logger.warning(f"[YOLOPv2] warmup failed (non-fatal): {exc}")
        logger.info(f"[YOLOPv2] Loaded: {self.model_path} on {self.device}")

    def unload(self):
        if self._model is not None:
            del self._model
            self._model = None
            gc.collect()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()

    # ─── Inference ────────────────────────────────────────────────────────────

    def segment_frame(self, frame_bgr: np.ndarray) -> list:
        """
        Run YOLOPv2 on a BGR frame and return drivable-area + lane polygons in
        the original image's pixel coordinates.

        Output format matches RoadSegmenter.segment_frame() so the consumers
        (IntersectionAnalyzer + frontend canvas) need no changes:

            [
                {'type': 'road_mask', 'class_name': 'drivable area (yolopv2)',
                 'polygon': [[x,y],...], 'confidence': 1.0},
                {'type': 'road_mask', 'class_name': 'lane (yolopv2)',
                 'polygon': [[x,y],...], 'confidence': 1.0},
                ...
            ]
        """
        if self._model is None:
            return []

        h0, w0 = frame_bgr.shape[:2]
        lb, ratio, pad_w, pad_h = _letterbox(frame_bgr, _INPUT_H, _INPUT_W)

        # BGR → RGB, HWC → CHW, /255, unsqueeze
        rgb = cv2.cvtColor(lb, cv2.COLOR_BGR2RGB)
        tensor = torch.from_numpy(rgb).to(self.device).float() / 255.0
        tensor = tensor.permute(2, 0, 1).unsqueeze(0).contiguous()

        try:
            with torch.no_grad():
                out = self._model(tensor)
        except Exception as exc:
            logger.warning(f"[YOLOPv2] inference failed: {exc}")
            return []

        # The TorchScript model returns a tuple/list — official demo unpacks it
        # as ([pred, anchor_grid], seg, ll). Be defensive about exact layout.
        seg, ll = None, None
        try:
            if isinstance(out, (list, tuple)) and len(out) >= 3:
                seg, ll = out[1], out[2]
            elif isinstance(out, (list, tuple)) and len(out) == 2:
                seg, ll = out
        except Exception:
            pass
        if seg is None and ll is None:
            return []

        # Both heads upsample by 8× internally on the official path. We let
        # the model's own output shape drive the resize and normalize back to
        # the letterboxed canvas, then crop the padding and rescale to the
        # original frame.
        regions: list = []

        def _decode_mask(t):
            if t is None:
                return None
            # If the head produces 2 channels (background, foreground), argmax;
            # otherwise threshold.
            if t.dim() == 4 and t.shape[1] == 2:
                m = torch.argmax(t, dim=1).squeeze(0)
            else:
                m = (t.squeeze() > 0.5).int()
            mask = m.detach().cpu().numpy().astype(np.uint8)
            # Resize to letterbox canvas
            mask = cv2.resize(mask, (_INPUT_W, _INPUT_H), interpolation=cv2.INTER_NEAREST)
            # Crop padding
            mask = mask[pad_h:_INPUT_H - pad_h if pad_h else _INPUT_H,
                        pad_w:_INPUT_W - pad_w if pad_w else _INPUT_W]
            # Resize to original
            mask = cv2.resize(mask, (w0, h0), interpolation=cv2.INTER_NEAREST)
            return mask

        da_mask = _decode_mask(seg)
        ll_mask = _decode_mask(ll)

        if da_mask is not None:
            for poly in _mask_to_polygons(da_mask, min_area=2000):
                regions.append({
                    'type': 'road_mask',
                    'class_name': 'drivable area (yolopv2)',
                    'polygon': poly,
                    'confidence': 1.0,
                })

        if ll_mask is not None:
            for poly in _mask_to_polygons(ll_mask, min_area=200):
                regions.append({
                    'type': 'road_mask',
                    'class_name': 'lane (yolopv2)',
                    'polygon': poly,
                    'confidence': 1.0,
                })

        return regions
