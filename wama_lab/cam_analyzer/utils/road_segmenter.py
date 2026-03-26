"""
Road segmentation for cam_analyzer.

Uses a YOLO segmentation model (e.g. trained on BDD100K) to detect the
drivable area / road in each frame.  The resulting polygons are stored in
DetectionFrame.detections (type='road_mask') and consumed by
IntersectionAnalyzer to decide whether a vehicle has entered the shuttle's lane.

Typical compatible models:
    - YOLOv8x-seg fine-tuned on BDD100K (has 'drivable area' class)
    - Any seg model whose class names include words from DEFAULT_ROAD_CLASSES
"""
import gc
import logging

logger = logging.getLogger(__name__)

# Class names typically found in road-focused segmentation models
DEFAULT_ROAD_CLASSES = frozenset({
    'road', 'drivable area', 'drivable_area',
    'direct drivable', 'alternative drivable',
    'lane', 'ego lane',
})


def _point_in_polygon(x: float, y: float, polygon: list) -> bool:
    """
    Ray-casting point-in-polygon test.
    polygon: list of [px, py] or (px, py) pairs.
    """
    n = len(polygon)
    if n < 3:
        return False
    inside = False
    px0, py0 = polygon[-1][0], polygon[-1][1]
    for pt in polygon:
        px1, py1 = pt[0], pt[1]
        if ((py1 > y) != (py0 > y)):
            cross_x = (px0 - px1) * (y - py1) / (py0 - py1 + 1e-9) + px1
            if x < cross_x:
                inside = not inside
        px0, py0 = px1, py1
    return inside


class RoadSegmenter:
    """
    Loads a YOLO segmentation model and detects road/drivable-area polygons
    in video frames.

    Args:
        model_path:       Absolute path to YOLO .pt file.
        road_class_names: Set of lowercase class names to treat as "road".
                          Defaults to DEFAULT_ROAD_CLASSES.
        device:           'cuda' or 'cpu'.
    """

    def __init__(self, model_path: str, road_class_names=None, device: str = 'cuda'):
        self.model_path = model_path
        self.road_class_names = road_class_names or DEFAULT_ROAD_CLASSES
        self.device = device
        self._model = None

    # ─── Lifecycle ────────────────────────────────────────────────────────────

    def load(self):
        """Load the YOLO model into memory."""
        from ultralytics import YOLO
        self._model = YOLO(self.model_path)
        logger.info(f"[RoadSegmenter] Loaded: {self.model_path}")

    def unload(self):
        """Release model from memory and free GPU cache."""
        import torch
        if self._model is not None:
            del self._model
            self._model = None
            gc.collect()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()

    # ─── Inference ────────────────────────────────────────────────────────────

    def segment_frame(self, frame_bgr) -> list:
        """
        Run road segmentation on a single BGR frame (numpy array).

        Returns a list of road-region dicts ready to be appended to
        DetectionFrame.detections:
        [
            {
                'type':       'road_mask',
                'class_name': str,          # e.g. 'drivable area'
                'polygon':    [[x,y], ...], # contour points (float pixel coords)
                'confidence': float,
            },
            ...
        ]
        Returns [] if no road regions found or model not loaded.
        """
        if self._model is None:
            return []

        try:
            results = self._model(frame_bgr, device=self.device, verbose=False, task='segment')
        except Exception as e:
            logger.warning(f"[RoadSegmenter] Inference failed: {e}")
            return []

        road_regions = []
        for r in results:
            if r.masks is None or r.boxes is None:
                continue
            for i, mask_xy in enumerate(r.masks.xy):
                if i >= len(r.boxes):
                    continue
                cls_id = int(r.boxes[i].cls)
                cls_name = r.names.get(cls_id, '').lower()
                if cls_name not in self.road_class_names:
                    continue
                polygon = mask_xy.tolist()  # list of [x, y]
                if len(polygon) < 3:
                    continue
                road_regions.append({
                    'type': 'road_mask',
                    'class_name': cls_name,
                    'polygon': polygon,
                    'confidence': round(float(r.boxes[i].conf), 3),
                })

        return road_regions

    # ─── Spatial helpers ──────────────────────────────────────────────────────

    @staticmethod
    def bbox_foot_in_road(bbox: list, road_regions: list) -> bool:
        """
        Returns True if the foot point (bottom-centre) of the bbox is inside
        any road-region polygon.

        bbox: [x1, y1, x2, y2]
        road_regions: list of dicts returned by segment_frame()
        """
        if not road_regions or not bbox or len(bbox) < 4:
            return False
        x_foot = (bbox[0] + bbox[2]) / 2.0
        y_foot = float(bbox[3])
        for region in road_regions:
            if _point_in_polygon(x_foot, y_foot, region.get('polygon', [])):
                return True
        return False
