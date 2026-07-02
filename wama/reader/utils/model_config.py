"""
Reader — OCR model configuration.
Deux backends initiaux :
  - olmOCR-2 7B (Allen AI) : modèle VLM HuggingFace, imprimé + manuscrit
  - docTR (Mindee)         : pipeline OCR PyTorch, CPU-friendly
"""
import logging
from pathlib import Path
from django.conf import settings

logger = logging.getLogger(__name__)

# ── Paths ─────────────────────────────────────────────────────────────────────
MODEL_PATHS = getattr(settings, 'MODEL_PATHS', {})

# Catégorie 'ocr' (ex-'reader' = nom d'app). Alias 'reader' conservé dans MODEL_PATHS.
OLMOCR_DIR = MODEL_PATHS.get('ocr', {}).get(
    'olmocr', settings.AI_MODELS_DIR / "models" / "ocr" / "olmocr"
)
DOCTR_DIR = MODEL_PATHS.get('ocr', {}).get(
    'doctr', settings.AI_MODELS_DIR / "models" / "ocr" / "doctr"
)

Path(OLMOCR_DIR).mkdir(parents=True, exist_ok=True)
Path(DOCTR_DIR).mkdir(parents=True, exist_ok=True)

# ── Model catalogue ───────────────────────────────────────────────────────────
# NOTE : pour olmOCR-2, vérifier le HF ID exact sur https://huggingface.co/allenai
# Candidats connus : allenai/olmOCR-7B-0225-preview, allenai/olmOCR-2-0328
READER_MODELS = {
    'olmocr': {
        'model_id':    'olmocr',
        'hf_model_id': 'allenai/olmOCR-7B-0225-preview',  # à ajuster si nécessaire
        'type':        'ocr-vlm',
        'vram_gb':     14.0,
        'description': 'olmOCR-2 7B — Allen AI — imprimé + manuscrit + tableaux + formules',
        'description_long': "olmOCR-2 7B (Allen AI) : OCR par modèle vision-langage — comprend la "
                            "mise en page, restitue tableaux, formules et manuscrit avec une "
                            "qualité de référence. Gourmand en VRAM ; à réserver aux documents "
                            "complexes.",
    },
    'doctr': {
        'model_id':    'doctr',
        'hf_model_id': '',   # modèles embarqués dans le package
        'type':        'ocr-pipeline',
        'vram_gb':     0.0,  # CPU
        'description': 'docTR (Mindee) — pipeline CPU, imprimé, bonne gestion des formulaires',
        'description_long': "docTR (Mindee) : pipeline OCR classique en deux étapes (détection + "
                            "reconnaissance), fonctionne sur CPU. Rapide et sobre pour documents "
                            "imprimés simples et formulaires ; moins adapté au manuscrit et aux "
                            "mises en page complexes.",
    },
}

DEFAULT_MODEL = 'olmocr'


def get_model_info(model_key: str = None) -> dict:
    k = model_key or DEFAULT_MODEL
    if k not in READER_MODELS:
        raise ValueError(f"Modèle inconnu : {k}. Disponibles : {list(READER_MODELS.keys())}")
    return READER_MODELS[k].copy()
