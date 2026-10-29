"""
Reader — OCR model configuration.
Deux backends initiaux :
  - olmOCR 7B v1 « preview » (Allen AI) : modèle VLM HuggingFace, imprimé + manuscrit — olmOCR-2 a
    sa propre ligne de catalogue (`huggingface:allenai/olmOCR-2-7B-1025`, 2026-10-29)
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
# `params` (2026-09-29) : les réglages du schéma que le moteur LIT réellement — recopiés en
# capacité canonique `params` au catalogue, d'où l'UI grise (sans cacher) ceux qu'il ignore
# (`WamaModelCaps`, même geste que les moteurs audio de l'enhancer). MESURÉ dans chaque backend :
# olmOCR met le mode ET la langue dans sa consigne (`_build_prompt`) ; GLM-OCR ne passe que la
# langue (`_ocr_image(model, img_path, language)`) ; docTR reçoit les deux et n'en lit aucun.
# ⚠ Corrigé le 2026-10-29 : cette ligne se présentait comme « olmOCR-2 » ; elle EST olmOCR v1
# « preview » (février 2025, Qwen2-VL). olmOCR-2 (`allenai/olmOCR-2-7B-1025`) a SA ligne de
# catalogue, installée par la route depuis sa proposition de successeur, et le même backend le sert.
READER_MODELS = {
    'olmocr': {
        'model_id':    'olmocr',
        'engine': 'transformers',
        'platform_ref': 'huggingface:allenai/olmOCR-7B-0225-preview',
        'type':        'ocr-vlm',
        'vram_gb':     14.0,
        'description': 'olmOCR 7B v1 « preview » (février 2025) — Allen AI — imprimé + manuscrit',
        'params':      ['mode', 'language'],
        'description_long': "olmOCR 7B v1 « preview » (Allen AI, février 2025) : OCR par modèle "
                            "vision-langage (Qwen2-VL). Son successeur, olmOCR-2, a sa propre ligne "
                            "au catalogue. Gourmand en VRAM.",
    },
    # GLM-OCR n'est PLUS déclaré ici (2026-10-07, décision de Fabien : « les modèles ne sont plus
    # déclarés par application, pour être réutilisables dans plusieurs »). Servi par Ollama, il a
    # SA ligne, découverte une fois pour toutes les apps (`ollama:glm-ocr:latest`), sa tâche et
    # ses réglages lus déclarés par famille (`model_registry.FAMILLES_OLLAMA`) — la ligne
    # `reader:glm-ocr` en était un DOUBLON (même modèle, deux clés). Le reader le propose par la
    # TÂCHE (`OCR_SPEC`) et le lance par la porte commune (`GlmOcrBackend`, contrat OCR).
    'doctr': {
        'model_id':    'doctr',
        'engine': 'doctr',
        # Pas de `platform_ref` : les modèles sont embarqués dans le paquet docTR.
        'type':        'ocr-pipeline',
        'vram_gb':     0.0,  # CPU
        'description': 'docTR (Mindee) — pipeline CPU, imprimé, bonne gestion des formulaires',
        'params':      [],
        'description_long': "docTR (Mindee) : pipeline OCR classique en deux étapes (détection + "
                            "reconnaissance), fonctionne sur CPU. Rapide et sobre pour documents "
                            "imprimés simples et formulaires ; moins adapté au manuscrit et aux "
                            "mises en page complexes.",
    },
}

DEFAULT_MODEL = 'olmocr'

#: DOMAINE du moteur OCR — UNE déclaration, que le select (`params.py`, `options_query`) et le
#: tirage « auto » (`tasks._select_best_backend`) lisent. Par TÂCHE (route F4b ⑤, 2026-10-07),
#: jamais par source : GLM-OCR est servi par Ollama, et un OCR installé demain d'une autre source
#: (ou chez un fournisseur) y entre sans une ligne du reader.
OCR_SPEC = {'task': 'ocr'}

#: Repli du tirage quand le catalogue ne propose rien : docTR, sur CPU, toujours disponible.
OCR_FALLBACK = 'reader:doctr'

#: Valeurs d'avant qui ne sont plus une clé du reader : l'identifiant nu d'un modèle dont la
#: ligne vit désormais sous sa vraie source (lu par `ReadingItem.save` et la migration 0012).
RETIRED_IDS = {'glm-ocr': 'ollama:glm-ocr:latest'}


def get_model_info(model_key: str = None) -> dict:
    k = model_key or DEFAULT_MODEL
    if k not in READER_MODELS:
        raise ValueError(f"Modèle inconnu : {k}. Disponibles : {list(READER_MODELS.keys())}")
    return READER_MODELS[k].copy()
