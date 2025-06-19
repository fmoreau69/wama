from ultralytics import YOLO
from wama.settings import BASE_DIR
import os

MODEL_PATH = os.path.join(BASE_DIR, "anonymizer/models/yolov8n.pt")

def get_yolo_class_choices():
    try:
        model = YOLO(MODEL_PATH)
        names = model.model.names.values()
        return [(name, name.capitalize()) for name in names]
    except Exception as e:
        # In case of error (e.g. missing file), fallback
        return [('face', 'Face'), ('plate', 'Plate')]
