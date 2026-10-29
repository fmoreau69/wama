"""
Reader — OCR model configuration.
Le reader ne déclare plus que docTR (Mindee, pipeline OCR PyTorch, CPU-friendly) : les autres
moteurs OCR ont leur ligne sous la source qui les sert (GLM-OCR et Chandra par Ollama, olmOCR-2
par le Hub) et le reader les propose par la TÂCHE (`OCR_SPEC`). olmOCR v1 « preview », déclaré ici
jusqu'au 2026-10-29, est RETIRÉ au profit d'olmOCR-2 (`REMOVAL_LEDGER` R190).
"""
import logging
from pathlib import Path
from django.conf import settings

logger = logging.getLogger(__name__)

# ── Paths ─────────────────────────────────────────────────────────────────────
MODEL_PATHS = getattr(settings, 'MODEL_PATHS', {})

# Catégorie 'ocr' (ex-'reader' = nom d'app). Alias 'reader' conservé dans MODEL_PATHS.
DOCTR_DIR = MODEL_PATHS.get('ocr', {}).get(
    'doctr', settings.AI_MODELS_DIR / "models" / "ocr" / "doctr"
)

Path(DOCTR_DIR).mkdir(parents=True, exist_ok=True)

# ── Model catalogue ───────────────────────────────────────────────────────────
# `params` (2026-09-29) : les réglages du schéma que le moteur LIT réellement — recopiés en
# capacité canonique `params` au catalogue, d'où l'UI grise (sans cacher) ceux qu'il ignore
# (`WamaModelCaps`, même geste que les moteurs audio de l'enhancer). MESURÉ dans chaque backend :
# GLM-OCR ne passe que la langue (`_ocr_image(model, img_path, language)`) ; docTR reçoit les deux
# et n'en lit aucun.
# ⚠ olmOCR v1 « preview » (février 2025, Qwen2-VL), déclaré ici sous `olmocr`, est RETIRÉ le
# 2026-10-29 (décision de Fabien : « si la v2 est meilleure, aucun intérêt de garder la v1 ») :
# olmOCR-2 (`huggingface:allenai/olmOCR-2-7B-1025`) lui SUCCÈDE partout où il était choisi
# (`model_manager/services/succession.py`, `REMOVAL_LEDGER` R190).
READER_MODELS = {
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

#: DOMAINE du moteur OCR — UNE déclaration, que le select (`params.py`, `options_query`) et le
#: tirage « auto » (`tasks._select_best_backend`) lisent. Par TÂCHE (route F4b ⑤, 2026-10-07),
#: jamais par source : GLM-OCR est servi par Ollama, et un OCR installé demain d'une autre source
#: (ou chez un fournisseur) y entre sans une ligne du reader.
OCR_SPEC = {'task': 'ocr'}

#: Repli du tirage quand le catalogue ne propose rien : docTR, sur CPU, toujours disponible.
OCR_FALLBACK = 'reader:doctr'

#: Valeurs d'avant qui ne sont plus une clé du reader : l'identifiant nu d'un modèle dont la
#: ligne vit désormais sous sa vraie source (lu par `ReadingItem.save` et la migration 0012), et
#: olmOCR v1, retiré au profit de son successeur (R190) — un lot, l'assistant ou un fichier écrit
#: avant peuvent encore le nommer.
RETIRED_IDS = {'glm-ocr': 'ollama:glm-ocr:latest',
               'olmocr': 'huggingface:allenai/olmOCR-2-7B-1025',
               'reader:olmocr': 'huggingface:allenai/olmOCR-2-7B-1025'}
