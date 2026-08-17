"""
Reader — Celery tasks for OCR processing.
"""
import json
import logging
from celery import shared_task
from django.core.cache import cache
from django.db import close_old_connections

from wama.common.utils.console_utils import push_console_line

logger = logging.getLogger(__name__)

PROGRESS_CACHE_TTL = 3600  # 1 hour

# ── Module-level singleton — persiste entre tasks dans le même worker ────────
# Évite de recharger olmOCR-7B (~10 min) entre deux fichiers d'un même batch.
_olmocr_singleton = None


def _get_olmocr():
    """Retourne le backend olmOCR partagé, le charge si nécessaire."""
    global _olmocr_singleton
    from .backends.olmocr_backend import OlmOCRBackend
    if _olmocr_singleton is None or _olmocr_singleton._model is None:
        _olmocr_singleton = OlmOCRBackend()
        _olmocr_singleton.load()
    return _olmocr_singleton


def _set_progress(item, pct: int, msg: str = ''):
    """`progress_fn` déclaré à la brique task_skeleton : le front du reader polle un DICT
    {'pct','msg'} (messages d'étape), pas l'entier nu du défaut."""
    cache.set(f'reader_progress_{item.pk}', {'pct': pct, 'msg': msg}, PROGRESS_CACHE_TTL)


def _console(user_id: int, message: str, level: str = None) -> None:
    try:
        if level is None:
            low = message.lower()
            if any(w in low for w in ('erreur', 'error', 'failed', 'échec')):
                level = 'error'
            elif any(w in low for w in ('warning', 'attention', 'warn')):
                level = 'warning'
            elif any(w in low for w in ('debug',)):
                level = 'debug'
            else:
                level = 'info'
        push_console_line(user_id, message, level=level, app='reader')
    except Exception:
        pass


def _count_pdf_pages(file_path: str) -> int:
    try:
        try:
            import pymupdf as fitz  # PyMuPDF >= 1.24
        except ImportError:
            import fitz  # legacy name
        doc = fitz.open(file_path)
        n = doc.page_count
        doc.close()
        return n
    except ImportError:
        pass
    try:
        from pdf2image.exceptions import PDFInfoNotInstalledError
        from pdf2image import pdfinfo_from_path
        info = pdfinfo_from_path(file_path)
        return info.get('Pages', 0)
    except Exception:
        pass
    return 0


def _olmocr_is_resident() -> bool:
    """Le singleton olmOCR est-il déjà chargé ? (sonde `prefer_loaded` du sélecteur commun)"""
    return _olmocr_singleton is not None and getattr(_olmocr_singleton, '_model', None) is not None


def _glm_ocr_available() -> bool:
    """GLM-OCR tourne dans Ollama : téléchargé ≠ joignable (serveur éteint)."""
    try:
        from .backends.glm_ocr_backend import is_available as glm_available
        return bool(glm_available())
    except Exception:
        return False


def _backend_is_available(model) -> bool:
    """Sonde de disponibilité RUNTIME passée au sélecteur commun (reçoit un `AIModel`).

    Le catalogue sait qu'un modèle est téléchargé ; il ne sait pas si le service qui le
    sert répond.
    """
    return _glm_ocr_available() if getattr(model, 'model_id', '') == 'glm-ocr' else True


def _select_best_backend() -> str:
    """Choisit le moteur OCR via la brique COMMUNE `select_model_id()`.

    Cette fonction ré-implémentait la cascade que le sélecteur commun fait déjà :
    préférence au modèle résident, sonde de disponibilité, seuil de VRAM libre, repli.
    Elle re-mesurait même la VRAM à la main (nvidia-smi puis torch) alors que
    `get_free_vram_gb()` existe et gère précisément le cas du worker Celery forké où
    `torch.cuda` n'est pas initialisé. Un seuil de 10 Go était écrit ici en dur, sans lien
    avec le `vram_gb` déclaré par olmOCR au catalogue : les deux pouvaient diverger
    silencieusement.

    Le REPLI reste intégral : catalogue vide, model_manager en erreur ou modèle inconnu →
    on retombe sur la cascade statique ci-dessous. Une app ne doit jamais devenir
    intraitable parce que le catalogue n'a pas été synchronisé.
    """
    try:
        from wama.model_manager.services.model_selector import select_model_id
        chosen = select_model_id(
            'reader',
            task='ocr',
            # `prefer_loaded` couvre le pas 1 de l'ancienne cascade (réutiliser olmOCR
            # déjà résident) sans que l'app ait à inspecter son propre singleton.
            prefer_loaded=True,
            downloaded_only=True,
            availability_probe=_backend_is_available,
            fallback='doctr',   # CPU, toujours disponible
        )
        if chosen:
            return chosen
    except Exception as e:
        logger.debug(f"[Reader] Sélection via model_manager indisponible ({e}) — repli statique.")

    # ── Repli statique (ordre de préférence historique) ──────────────────────────
    if _olmocr_is_resident():
        return 'olmocr'
    if _glm_ocr_available():
        return 'glm-ocr'
    return 'doctr'


def _try_direct_extraction(file_path: str) -> str:
    """Extract native text from a digital PDF using PyMuPDF (fitz).

    Returns the extracted text if the PDF contains selectable text
    (i.e., it is a digital/vector PDF, not a scanned image).
    Returns an empty string if the PDF is image-only or has no readable text.
    """
    try:
        try:
            import pymupdf as fitz  # PyMuPDF >= 1.24
        except ImportError:
            import fitz  # legacy name
        doc = fitz.open(file_path)
        pages_text = []
        for page in doc:
            pages_text.append(page.get_text())
        doc.close()
        full_text = '\n\n'.join(t for t in pages_text if t.strip()).strip()
        # Heuristic: >= 20 chars per page on average → digital PDF
        avg_chars = len(full_text) / max(len(pages_text), 1)
        return full_text if avg_chars >= 20 else ''
    except Exception:
        return ''


def _extract_natural_text(text: str) -> str:
    """Extract natural_text from olmOCR JSON output, or return text as-is."""
    if not text:
        return text
    stripped = text.strip()
    if stripped.startswith('{'):
        try:
            data = json.loads(stripped)
            if isinstance(data, dict) and 'natural_text' in data:
                return data['natural_text']
        except Exception:
            pass
    return text


def _format_as_markdown(text: str, language: str = '') -> str:
    """
    Use a local LLM (Ollama) to reformat raw OCR text as clean Markdown.
    Preserves all content — only applies structure (headings, lists, tables, bold…).
    Falls back to the original text if the LLM is unavailable or fails.
    """
    if not text or not text.strip():
        return text

    lang_hint = f" The document language is {language}." if language else ""
    system_prompt = (
        "You are a document formatting assistant.{hint} "
        "The following text was extracted by an OCR engine. "
        "Reformat it as clean, well-structured Markdown. "
        "Rules: preserve ALL content exactly — do not add, remove, translate, or summarise anything; "
        "use # / ## / ### for headings, - or * for bullet lists, | for tables, "
        "**bold** for labels or emphasis already present in the source; "
        "fix obvious OCR artefacts (run-on words, stray hyphens, broken line breaks). "
        "Return only the formatted Markdown, no preamble or explanation."
    ).format(hint=lang_hint)

    from wama.common.utils.llm_utils import ollama_chat, get_describer_model
    model = get_describer_model('text', 'markdown')

    result, error = ollama_chat(
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": text},
        ],
        model=model,
        num_predict=8192,
        num_ctx=8192,   # Cap KV cache — formatting needs no large context window
        think=False,
        timeout=30.0,  # Fast-fail when Ollama is unavailable
    )

    if error or not result:
        logger.warning(f"[Reader] Mise en forme Markdown échouée ({error}) — texte brut conservé")
        return text

    return result.strip()


@shared_task(bind=True, name='wama.reader.tasks.read_document_task')
def read_document_task(self, item_id: int):
    """Squelette = brique commune task_skeleton (gardes, ingest, chrono, statuts, ETA,
    notifications) — olmOCR (~16 Go) et doctr chargent en VRAM depuis cette tâche : profil à
    risque exact de la garde anti-boucle-de-crash. Le front du reader pollant {'pct','msg'},
    l'écriture de progression est DÉCLARÉE (`progress_fn=_set_progress`)."""
    from wama.common.utils.task_skeleton import run_item_task
    from .models import ReadingItem
    run_item_task(self, app_id='reader', model=ReadingItem, item_id=item_id,
                  process=_read, notify_label='Reader', progress_fn=_set_progress)


def _read(item, ctx):
    """GLU reader (contrat task_skeleton) : extraction native PDF (chemin court), sinon
    sélection de backend OCR + mise en forme Markdown LLM. Le retour anticipé du PDF natif
    déclenche le flux de succès standard de la brique."""
    ctx.console(f"[Reader] Démarrage : {item.filename}")
    ctx.progress(2, "Démarrage…")
    try:
        item.status = 'RUNNING'
        item.result_text = ''
        item.raw_result = ''
        item.error_message = ''
        item.save(update_fields=['status', 'result_text', 'raw_result', 'error_message'])

        # Count pages for PDF if not yet done
        if item.page_count == 0 and item.input_file.name.lower().endswith('.pdf'):
            n = _count_pdf_pages(item.input_file.path)
            if n:
                item.page_count = n
                item.save(update_fields=['page_count'])

        pages = max(int(item.page_count or 0), 1)

        # For PDFs: try native text extraction first (digital/vector PDFs)
        if item.input_file.name.lower().endswith('.pdf'):
            ctx.progress(8, "Extraction native (texte vectoriel)…")
            direct_text = _try_direct_extraction(item.input_file.path)
            if direct_text:
                ctx.progress(100, "Terminé")
                return {
                    'fields': {'result_text': direct_text, 'raw_result': direct_text,
                               'used_backend': 'fitz_direct'},
                    'eta': ('reader:fitz_direct', pages, 'page'),
                    'label': item.filename,
                    'console_success': f"[Reader] ✓ {item.filename} — "
                                       f"{len(direct_text)} caractères (PDF natif)",
                }

        # Select backend
        backend = item.backend
        if backend == 'auto':
            backend = _select_best_backend()
            ctx.console(f"[Reader] Backend auto-sélectionné : {backend}")

        ctx.progress(5, f"Backend : {backend}")

        # Aperçu « PENDANT » (brique COMMUNE preview_utils, servi par `?side=during`) :
        # le texte OCR se CONSTRUIT page à page dans l'inspecteur (olmocr/glm), et le brut
        # complet s'affiche pendant la mise en forme LLM (étape longue à 98 %). Best-effort.
        from wama.common.utils.preview_utils import clear_partial, publish_partial_text

        def _partial(txt):
            publish_partial_text('reader', item.pk, txt)

        if backend == 'olmocr':
            # Singleton : le modèle reste chargé entre les fichiers d'un même batch
            raw_text = _get_olmocr().run(
                item.input_file.path, item.mode, item.language, ctx.progress,
                keep_loaded=True, on_partial=_partial,
            )
        elif backend == 'glm-ocr':
            from .backends.glm_ocr_backend import GlmOcrBackend
            raw_text = GlmOcrBackend().run(
                item.input_file.path, item.mode, item.language, ctx.progress,
                on_partial=_partial,
            )
        elif backend == 'doctr':
            from .backends.doctr_backend import DocTRBackend
            raw_text = DocTRBackend().run(
                item.input_file.path, item.mode, item.language, ctx.progress,
                on_partial=_partial,
            )
        else:
            raise ValueError(f"Backend inconnu : {backend}")

        result_text = _extract_natural_text(raw_text)

        # Post-processing: LLM Markdown formatting (always applied) — le brut reste lisible
        # en aperçu partiel pendant que le LLM formate.
        _partial(result_text)
        ctx.progress(98, "Mise en forme…")
        ctx.console("[Reader] Mise en forme via LLM…")
        result_text = _format_as_markdown(result_text, item.language)

        clear_partial('reader', item.pk)   # la face SORTIE prend le relais
        ctx.progress(100, "Terminé")
        return {
            'fields': {'result_text': result_text, 'raw_result': raw_text,
                       'used_backend': backend},
            'eta': (f'reader:{backend}', pages, 'page'),
            'label': item.filename,
            'console_success': f"[Reader] ✓ {item.filename} — "
                               f"{len(result_text)} caractères extraits",
        }
    except Exception as exc:
        # Le front affiche le message d'étape : y refléter l'erreur avant le flux FAILURE
        # standard de la brique (statut, console ✗, notification).
        try:
            from wama.common.utils.preview_utils import clear_partial
            clear_partial('reader', item.pk)
        except Exception:
            pass
        _set_progress(item, 0, f"Erreur : {exc}")
        raise


@shared_task(bind=True, name='wama.reader.tasks.analyze_document_task')
def analyze_document_task(self, item_id: int):
    """On-demand LLM analysis of an already-extracted text (summary + key points)."""
    close_old_connections()
    from .models import ReadingItem

    try:
        item = ReadingItem.objects.select_related('user').get(pk=item_id)
    except ReadingItem.DoesNotExist:
        logger.error(f"[Reader] ReadingItem {item_id} introuvable pour analyse")
        return {'ok': False, 'error': 'introuvable'}

    if not item.result_text:
        return {'ok': False, 'error': 'Pas de texte extrait'}

    user_id = item.user_id
    _console(user_id, f"[Reader] Analyse LLM : {item.filename}…")

    try:
        from wama.common.utils.llm_utils import generate_structured_summary
        summary_data = generate_structured_summary(
            item.result_text, content_hint='description', language='fr',
        )
        lines = [summary_data['summary']]
        if summary_data['key_points']:
            lines.append('\nPoints clés :')
            lines.extend(f'• {p}' for p in summary_data['key_points'])
        if summary_data['action_items']:
            lines.append('\nActions :')
            lines.extend(f'• {a}' for a in summary_data['action_items'])
        item.analysis = '\n'.join(lines)
        item.save(update_fields=['analysis'])
        _console(user_id, f"[Reader] Analyse terminée ✓ ({item.filename})")
        return {'ok': True, 'analysis': item.analysis}
    except Exception as exc:
        logger.error(f"[Reader] Analyse LLM item {item_id}: {exc}", exc_info=True)
        _console(user_id, f"[Reader] Analyse échouée : {exc}")
        return {'ok': False, 'error': str(exc)}
