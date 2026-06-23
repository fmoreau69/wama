"""
Compréhension de fichiers de référence (ROADMAP §10.B / §16.6, hook de la PromptPipeline).

Transforme un ou plusieurs fichiers fournis À LA VOLÉE (image, document, texte) en un RÉSUMÉ
textuel concis, destiné à être replié dans un prompt comme **contexte de grounding**. Multimodal :
- image    → description via `vision_probe.describe_image_ollama` (modèle vision Ollama local) ;
- doc/texte → texte extrait via `batch_parsers.extract_batch_file_text` (.txt/.md/.csv/.pdf/.docx).

C'est la « graine compréhension des fichiers d'entrée » de §10.B — DISTINCTE du RAG :
compréhension PONCTUELLE de l'entrée, AUCUNE persistance / store vectoriel.

Garde-fous RESSOURCES (pas de cascade) :
- **Data-gated** : ne fait rien si aucun fichier n'est fourni (l'utilisateur a explicitement
  joint une référence → le coût est attendu). Pas besoin d'interrupteur maître.
- **Budget de caractères** par fichier + global → pas d'explosion du prompt.
- **Plafond du nombre d'images** (chaque image = 1 appel vision) pour borner le coût.
- **Fail-safe** : un fichier illisible est ignoré (jamais d'exception remontée à l'app).
"""
from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

_IMAGE_EXTS = {'.png', '.jpg', '.jpeg', '.webp', '.bmp', '.gif', '.tiff'}
_DOC_EXTS = {'.txt', '.md', '.csv', '.pdf', '.docx'}

_MAX_CHARS_PER_FILE = 1200   # extrait par fichier replié dans le prompt
_TOTAL_BUDGET = 3000         # budget global du bloc contexte
_MAX_IMAGES = 2              # chaque image = 1 appel vision → borner


def comprehend_files(paths, *, language: str = 'en', console=None, timeout: int = 120) -> str:
    """
    Comprend une liste de fichiers de référence → bloc de contexte texte concis (ou '' si rien).

    `language` : langue de description souhaitée (= langue du prompt après routing).
    """
    if not paths:
        return ''
    if isinstance(paths, (str, os.PathLike)):
        paths = [paths]

    parts: list[str] = []
    used = 0
    images_done = 0
    for p in paths:
        p = str(p)
        if not p or not os.path.exists(p):
            continue
        ext = os.path.splitext(p)[1].lower()
        name = os.path.basename(p)
        try:
            if ext in _IMAGE_EXTS:
                if images_done >= _MAX_IMAGES:
                    continue
                chunk = _describe_image(p, language, timeout)
                images_done += 1
            elif ext in _DOC_EXTS:
                chunk = _extract_doc(p)
            else:
                continue
        except Exception as e:  # fail-safe : un fichier ne doit jamais casser le run
            logger.debug(f"[reference_comprehension] {name}: {e}")
            continue

        chunk = (chunk or '').strip()
        if not chunk:
            continue
        chunk = chunk[:_MAX_CHARS_PER_FILE]
        if used + len(chunk) > _TOTAL_BUDGET:
            chunk = chunk[:max(0, _TOTAL_BUDGET - used)]
        if not chunk:
            break
        parts.append(f"- {name} : {chunk}")
        used += len(chunk)
        if used >= _TOTAL_BUDGET:
            break

    if not parts:
        return ''
    if console:
        console(f"📎 {len(parts)} fichier(s) de référence pris en compte ({used} caractères de contexte).")
    return "\n".join(parts)


# ── interne ──────────────────────────────────────────────────────────────────────
def _describe_image(path: str, language: str, timeout: int) -> str:
    from wama.model_manager.services.vision_probe import describe_image_ollama
    try:
        from wama.describer.utils.image_describer import _best_ollama_vision_model
        model = _best_ollama_vision_model()
    except Exception:
        model = None
    lang_name = 'en français' if (language or 'en').startswith('fr') else f"in {language}"
    prompt = f"Describe this reference image precisely and concisely ({lang_name})."
    res = describe_image_ollama(path, model=model or 'gemma4:12b', prompt=prompt, timeout=timeout)
    return res.get('description', '') if res.get('ok') else ''


def _extract_doc(path: str) -> str:
    from wama.common.utils.batch_parsers import extract_batch_file_text
    return extract_batch_file_text(path) or ''
