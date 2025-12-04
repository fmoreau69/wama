from ultralytics import YOLO
from wama.settings import BASE_DIR
import os
import logging
from typing import List

# Dossier des modèles
MODELS_ROOT = os.path.join(BASE_DIR, "anonymizer", "models")

def get_model_path(filename: str) -> str:
    """
    Retourne le chemin absolu d’un modèle YOLO.
    """
    return os.path.join(MODELS_ROOT, filename)

def get_yolo_class_choices(model_filename: str = "yolov8n.pt"):
    """
    Charge un modèle YOLO et retourne la liste des classes disponibles.
    """
    model_path = get_model_path(model_filename)

    try:
        model = YOLO(model_path)
        names_dict = model.model.names  # {0: 'person', 1: 'car', ...}
        return [(str(k), v.capitalize()) for k, v in names_dict.items()]
    except Exception as e:
        logging.warning(f"[YOLO] Could not load model at {model_path}: {e}")
        # Valeurs par défaut si le modèle ne se charge pas
        return [('0', 'Face'), ('1', 'Plate')]

def get_all_class_choices():
    yolo_choices = get_yolo_class_choices()

    fixed_classes = [("face", "Face"), ("plate", "Plate")]
    all_classes = fixed_classes + [
        (lbl, lbl) for _, lbl in yolo_choices if lbl.lower() not in ['face', 'plate']
    ]
    return all_classes


def list_available_models() -> List[str]:
    """List model files available in anonymizer/models directory."""
    if not os.path.isdir(MODELS_ROOT):
        return []
    return sorted([
        f for f in os.listdir(MODELS_ROOT)
        if os.path.isfile(os.path.join(MODELS_ROOT, f)) and not f.startswith('.')
    ])
