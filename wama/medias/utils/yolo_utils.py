from ultralytics import YOLO
from wama.settings import BASE_DIR
import os
import logging

MODEL_PATH = os.path.join(BASE_DIR, "anonymizer/models/yolov8n.pt")

def get_yolo_class_choices():
    try:
        model = YOLO(MODEL_PATH)
        names_dict = model.model.names  # {0: 'person', 1: 'car', ...}
        return [(str(k), v.capitalize()) for k, v in names_dict.items()]
    except Exception as e:
        logging.warning(f"[YOLO] Could not load model at {MODEL_PATH}: {e}")
        return [('0', 'Face'), ('1', 'Plate')]
