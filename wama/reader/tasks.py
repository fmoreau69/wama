"""
Reader — Celery tasks for OCR processing.
"""
import logging
from celery import shared_task
from django.core.cache import cache
from django.db import close_old_connections

from wama.common.utils.console_utils import push_console_line

logger = logging.getLogger(__name__)

PROGRESS_CACHE_TTL = 3600  # 1 hour


def _set_progress(item_id: int, pct: int, msg: str = ''):
    cache.set(f'reader_progress_{item_id}', {'pct': pct, 'msg': msg}, PROGRESS_CACHE_TTL)


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
        import fitz
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


def _select_best_backend() -> str:
    """Choose olmocr if GPU is available with >= 10 GB free VRAM, else doctr.

    Uses nvidia-smi (subprocess) as the primary check because torch.cuda
    is often uninitialized in forked Celery workers and returns False even
    when a GPU is present.
    """
    # Primary: nvidia-smi subprocess — reliable in forked workers
    try:
        import subprocess
        result = subprocess.run(
            ['nvidia-smi', '--query-gpu=memory.free', '--format=csv,noheader,nounits'],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            values = [int(v.strip()) for v in result.stdout.strip().split('\n') if v.strip().isdigit()]
            if values and max(values) / 1024 >= 10:
                return 'olmocr'
    except Exception:
        pass
    # Fallback: torch (may fail in forked contexts but handles non-NVIDIA GPUs)
    try:
        import torch
        if torch.cuda.is_available():
            free_vram = torch.cuda.mem_get_info()[0] / 1024 ** 3
            if free_vram >= 10:
                return 'olmocr'
    except Exception:
        pass
    return 'doctr'


def _try_direct_extraction(file_path: str) -> str:
    """Extract native text from a digital PDF using PyMuPDF (fitz).

    Returns the extracted text if the PDF contains selectable text
    (i.e., it is a digital/vector PDF, not a scanned image).
    Returns an empty string if the PDF is image-only or has no readable text.
    """
    try:
        import fitz  # PyMuPDF
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


@shared_task(bind=True, name='wama.reader.tasks.read_document_task')
def read_document_task(self, item_id: int):
    close_old_connections()
    from .models import ReadingItem

    try:
        item = ReadingItem.objects.select_related('user').get(pk=item_id)
    except ReadingItem.DoesNotExist:
        logger.error(f"[Reader] ReadingItem {item_id} introuvable")
        return

    user_id = item.user_id
    _console(user_id, f"[Reader] Démarrage : {item.filename}")
    _set_progress(item_id, 2, "Démarrage…")

    try:
        item.status = 'RUNNING'
        item.result_text = ''
        item.error_message = ''
        item.save(update_fields=['status', 'result_text', 'error_message'])

        # Count pages for PDF if not yet done
        if item.page_count == 0 and item.input_file.name.lower().endswith('.pdf'):
            n = _count_pdf_pages(item.input_file.path)
            if n:
                item.page_count = n
                item.save(update_fields=['page_count'])

        # For PDFs: try native text extraction first (digital/vector PDFs)
        if item.input_file.name.lower().endswith('.pdf'):
            _set_progress(item_id, 8, "Extraction native (texte vectoriel)…")
            direct_text = _try_direct_extraction(item.input_file.path)
            if direct_text:
                item.result_text = direct_text
                item.used_backend = 'fitz_direct'
                item.status = 'DONE'
                item.progress = 100
                item.save(update_fields=['result_text', 'used_backend', 'status', 'progress'])
                _set_progress(item_id, 100, "Terminé")
                _console(user_id, f"[Reader] ✓ {item.filename} — {len(direct_text)} caractères (PDF natif)")
                return

        # Select backend
        backend = item.backend
        if backend == 'auto':
            backend = _select_best_backend()
            _console(user_id, f"[Reader] Backend auto-sélectionné : {backend}")

        _set_progress(item_id, 5, f"Backend : {backend}")

        # Run OCR
        def progress_cb(pct: int, msg: str):
            _set_progress(item_id, pct, msg)

        if backend == 'olmocr':
            from .backends.olmocr_backend import OlmOCRBackend
            result_text = OlmOCRBackend().run(
                item.input_file.path, item.mode, item.language, progress_cb
            )
        elif backend == 'doctr':
            from .backends.doctr_backend import DocTRBackend
            result_text = DocTRBackend().run(
                item.input_file.path, item.mode, item.language, progress_cb
            )
        else:
            raise ValueError(f"Backend inconnu : {backend}")

        item.result_text = result_text
        item.used_backend = backend
        item.status = 'DONE'
        item.progress = 100
        item.save(update_fields=['result_text', 'used_backend', 'status', 'progress'])

        _set_progress(item_id, 100, "Terminé")
        _console(user_id, f"[Reader] ✓ {item.filename} — {len(result_text)} caractères extraits")

    except Exception as exc:
        logger.error(f"[Reader] Erreur item {item_id}: {exc}", exc_info=True)
        item.status = 'ERROR'
        item.error_message = str(exc)
        item.save(update_fields=['status', 'error_message'])
        _set_progress(item_id, 0, f"Erreur : {exc}")
        _console(user_id, f"[Reader] ✗ {item.filename} — {exc}")


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
