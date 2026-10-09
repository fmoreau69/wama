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

# (Le singleton olmOCR écrit ici à la main est devenu le cache COMMUN de la porte de lancement
#  — `manager.backend_instance_for_key`, 2026-10-07 : instance gardée PAR CLÉ de catalogue.)


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


def _select_best_backend(item=None) -> str:
    """Choisit le moteur OCR — la CLÉ de catalogue — par la brique COMMUNE de tirage
    (`resolve_model_choice`, celle des autres apps), sur le domaine que le schéma DÉCLARE
    (`params.py`, `utils/model_config.OCR_SPEC`).

    ⚠ La sonde de disponibilité propre au reader (`_backend_is_available` : « GLM-OCR répond-il
    dans Ollama ? ») est retirée le 2026-10-07 : c'est le BACKEND qui dit s'il est exécutable
    (`GlmOcrBackend.is_available`), et le sélecteur écarte déjà un modèle dont le backend ne
    l'est pas (`backend_missing`) — pour toute app, pas pour le seul reader.

    `item` (chantier C, 2026-09-20) : d'où lire le curseur rapide/qualité —
    `quality_intent_of(item, 'reader')` : réglage d'app de l'utilisateur, sinon équilibré.
    Jusque-là la brique était appelée SANS intention : le curseur n'existait pas au reader.

    Cette fonction ré-implémentait la cascade que le sélecteur commun fait déjà :
    préférence au modèle résident, sonde de disponibilité, seuil de VRAM libre, repli.
    Elle re-mesurait même la VRAM à la main (nvidia-smi puis torch) alors que
    `get_free_vram_gb()` existe et gère précisément le cas du worker Celery forké où
    `torch.cuda` n'est pas initialisé. Un seuil de 10 Go était écrit ici en dur, sans lien
    avec le `vram_gb` déclaré par olmOCR au catalogue : les deux pouvaient diverger
    silencieusement.

    Le REPLI reste intégral : catalogue vide ou injoignable → docTR, sur CPU, toujours
    disponible (`OCR_FALLBACK`). Une app ne doit jamais devenir intraitable parce que le
    catalogue n'a pas été synchronisé.
    """
    from wama.common.utils.auto_model import AUTO, resolve_model_choice
    from wama.reader.utils.model_config import OCR_FALLBACK
    return resolve_model_choice(
        AUTO, app_id='reader', item=item,
        # `prefer_loaded` : réutiliser un moteur déjà RÉSIDENT (olmOCR, ~10 min de chargement).
        prefer_loaded=True, downloaded_only=True,
        fallback=OCR_FALLBACK) or OCR_FALLBACK


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

    # `llm_chat` et non `ollama_chat` : dernier appelant direct porté le 2026-09-09 —
    # le contrat d'appel est documenté à `llm_utils.py::_APPEL_LLM` (dont le `model or None`).
    from wama.common.utils.llm_utils import llm_chat, get_describer_model
    model = get_describer_model('text', 'markdown')

    result, error = llm_chat(
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": text},
        ],
        model=model or None,
        num_predict=8192,
        num_ctx=8192,   # Cap KV cache — formatting needs no large context window
        think=False,
        timeout=30.0,  # Fast-fail when Ollama is unavailable
    )

    if error or not result:
        logger.warning(f"[Reader] Mise en forme Markdown échouée ({error}) — texte brut conservé")
        return text

    return result.strip()


def reader_eta_key_size(item, backend: str = None) -> tuple[str, float, str]:
    """(clé, taille, unité) de l'ETA d'une lecture — temps ∝ nombre de pages, clé par moteur. UN
    lieu, partagé par la glu (moteur RÉSOLU) et la vue de progression (le moteur employé, sinon
    celui de la card : « auto » y est sa propre famille d'estimation) — ROUTE §11 #37.
    Sous l'IDENTIFIANT (2026-10-07) : la colonne porte une clé de catalogue depuis la route F4b
    ⑤ ; l'identifiant garde l'historique appris (`reader:olmocr`)."""
    from wama.common.utils.model_keys import model_id
    backend = model_id(backend or item.used_backend or item.backend)
    return f'reader:{backend}', max(int(item.page_count or 0), 1), 'page'


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

        # For PDFs: try native text extraction first (digital/vector PDFs)
        if item.input_file.name.lower().endswith('.pdf'):
            ctx.progress(8, "Extraction native (texte vectoriel)…")
            direct_text = _try_direct_extraction(item.input_file.path)
            if direct_text:
                ctx.progress(100, "Terminé")
                return {
                    'fields': {'result_text': direct_text, 'raw_result': direct_text,
                               'used_backend': 'fitz_direct'},
                    'eta': reader_eta_key_size(item, backend='fitz_direct'),
                    'label': item.filename,
                    'console_success': f"[Reader] ✓ {item.filename} — "
                                       f"{len(direct_text)} caractères (PDF natif)",
                }

        # Le modèle : sa CLÉ de catalogue (route F4b ⑤, 2026-10-07), tirée si « auto ».
        from wama.common.utils.auto_model import is_auto
        backend = item.backend
        if not backend or is_auto(backend):
            backend = _select_best_backend(item)
            from wama.common.utils.auto_model import quality_intent_of
            ctx.console(f"[Reader] Backend auto-sélectionné : {backend} "
                        f"(curseur qualité {quality_intent_of(item, 'reader')}/100)")

        ctx.progress(5, f"Backend : {backend}")

        # Aperçu « PENDANT » (brique COMMUNE preview_utils, servi par `?side=during`) :
        # le texte OCR se CONSTRUIT page à page dans l'inspecteur (olmocr/glm), et le brut
        # complet s'affiche pendant la mise en forme LLM (étape longue à 98 %). Best-effort.
        from wama.common.utils.preview_utils import clear_partial, publish_partial_text

        def _partial(txt):
            publish_partial_text('reader', item.pk, txt)

        # La PORTE COMMUNE (2026-10-07) : la clé désigne le backend (contrat OCR), l'instance
        # reste chargée d'un fichier au suivant (olmOCR ~10 min — l'ancien singleton du reader),
        # et les réglages arrivent PAR LEUR NOM de schéma, le fichier par celui de son PORT. Un
        # `if/elif` par moteur vivait ici : un OCR installé demain — Ollama, un fournisseur — n'aurait
        # pas eu sa branche.
        from wama.common.backends.manager import backend_instance_for_key, run_contract
        engine = backend_instance_for_key(backend, user=item.user)
        raw_text = run_contract(engine, work_file=item.input_file.path, mode=item.mode,
                                language=item.language, progress_callback=ctx.progress,
                                on_partial=_partial)

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
            'eta': reader_eta_key_size(item, backend=backend),
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
