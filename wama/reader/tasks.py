"""
Reader — Celery tasks for OCR processing.
"""
import json
import logging
from celery import shared_task
from django.core.cache import cache
from django.db import close_old_connections

from wama.common.utils.task_skeleton import ServiceNotReady

logger = logging.getLogger(__name__)

PROGRESS_CACHE_TTL = 3600  # 1 hour

# (Le singleton olmOCR écrit ici à la main est devenu le cache COMMUN de la porte de lancement
#  — `manager.backend_instance_for_key`, 2026-10-07 : instance gardée PAR CLÉ de catalogue.)


def _set_progress(item, pct: int, msg: str = ''):
    """`progress_fn` déclaré à la brique task_skeleton : le front du reader polle un DICT
    {'pct','msg'} (messages d'étape), pas l'entier nu du défaut."""
    cache.set(f'reader_progress_{item.pk}', {'pct': pct, 'msg': msg}, PROGRESS_CACHE_TTL)


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


def _format_as_markdown(text: str, language: str = '', model: str = '',
                        provider: str = None, temperature=None) -> str:
    """
    Use a local LLM (Ollama) to reformat raw OCR text as clean Markdown.
    Preserves all content — only applies structure (headings, lists, tables, bold…).

    `model` / `provider` : le modèle de langage de la card (`llm_model`), ou '' = le tier
    historique. Un échec LÈVE depuis le 2026-10-13 : il était avalé (texte brut rendu sans un mot)
    — c'est désormais le process `format` qui échoue, sur SA ligne, le texte lu restant en place.
    `temperature` : celle de la card (`llm_temperature`), None = celle du modèle.
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
    model = model or get_describer_model('text', 'markdown')

    result, error = llm_chat(
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": text},
        ],
        model=model or None,
        provider=provider,
        num_predict=8192,
        num_ctx=8192,   # Cap KV cache — formatting needs no large context window
        think=False,
        timeout=30.0,  # Fast-fail when Ollama is unavailable
        temperature=temperature,
    )

    if error or not result:
        raise RuntimeError(f"Mise en forme Markdown échouée : {error or 'réponse vide'}")

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
def read_document_task(self, item_id: int, process: str = None):
    """Squelette = brique commune task_skeleton (gardes, ingest, chrono, statuts, ETA,
    notifications) — olmOCR (~16 Go) et doctr chargent en VRAM depuis cette tâche : profil à
    risque exact de la garde anti-boucle-de-crash. Le front du reader pollant {'pct','msg'},
    l'écriture de progression est DÉCLARÉE (`progress_fn=_set_progress`).

    Depuis le 2026-10-13 la card porte un PIPELINE (`function_specs.PIPELINE` : lecture, mise en
    forme, analyse) : le squelette joue les process qu'un lancement retient, une ligne d'exécution
    chacun. `process` : lancement borné à ce process (▶ de la bande — ⚠ argument de tâche du
    2026-10-13 : workers à relancer)."""
    from wama.common.utils.task_skeleton import run_item_task
    from .function_specs import PIPELINE
    from .models import ReadingItem
    run_item_task(self, app_id='reader', model=ReadingItem, item_id=item_id,
                  pipeline=PIPELINE, processes=PROCESSES, notify_label='Reader',
                  progress_fn=_set_progress, only=process)


def _read(item, ctx):
    """Process `read` (glu, contrat task_skeleton) : texte natif d'un PDF numérique (chemin
    court), sinon le moteur OCR de la card. Rend le texte LU — sa mise en forme est le process
    `format`. Le résultat d'avant n'est plus vidé au départ : il l'est quand CE process le
    réécrit (relancer la seule analyse ne relit pas le document)."""
    ctx.console(f"[Reader] Démarrage : {item.filename}")
    ctx.progress(2, "Démarrage…")
    try:
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
                    'output_fingerprint': _fingerprint(direct_text),
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
        ctx.ensure_model(backend)          # absent : la route l'installe, la tâche attend

        # Aperçu « PENDANT » (brique COMMUNE preview_utils, servi par `?side=during`) :
        # le texte OCR se CONSTRUIT page à page dans l'inspecteur (olmocr/glm). Best-effort.
        from wama.common.utils.preview_utils import clear_partial, publish_partial_text

        def _partial(txt):
            publish_partial_text('reader', item.pk, txt)

        # La PORTE COMMUNE (2026-10-07) : la clé désigne le backend (contrat OCR), l'instance
        # reste chargée d'un fichier au suivant (olmOCR ~10 min — l'ancien singleton du reader),
        # et les réglages arrivent PAR LEUR NOM de schéma, le fichier par celui de son PORT. Un
        # `if/elif` par moteur vivait ici : un OCR installé demain — Ollama, un fournisseur — n'aurait
        # pas eu sa branche.
        from wama.common.backends.manager import backend_instance_for_key, run_contract
        from wama.common.backends.ocr_base import upright_image
        from wama.common.utils.work_dir import work_dir
        engine = backend_instance_for_key(backend, user=item.user)
        with work_dir('reader_upright') as travail:
            # Une IMAGE est redressée avant tout moteur (EXIF, puis classifieur d'orientation de
            # docTR) — card #1335 : une note photographiée de côté, illisible couchée. L'original
            # reste intact ; la copie droite vit le temps de la lecture. Les PDF sont rastérisés
            # par le moteur, qui redresse ses pages lui-même.
            work_file = item.input_file.path
            if not work_file.lower().endswith('.pdf'):
                work_file = upright_image(work_file, str(travail))
            raw_text = run_contract(engine, work_file=work_file, mode=item.mode,
                                    language=item.language, progress_callback=ctx.progress,
                                    on_partial=_partial)

        result_text = _extract_natural_text(raw_text)

        # La mise en forme Markdown est le process `format` (2026-10-13) : ici, le texte LU.
        clear_partial('reader', item.pk)   # la face SORTIE prend le relais
        ctx.progress(100, "Terminé")
        return {
            'fields': {'result_text': result_text, 'raw_result': raw_text,
                       'used_backend': backend},
            'models': [backend],
            'eta': reader_eta_key_size(item, backend=backend),
            'output_fingerprint': _fingerprint(raw_text),
            'label': item.filename,
            'console_success': f"[Reader] ✓ {item.filename} — "
                               f"{len(result_text)} caractères extraits",
        }
    except ServiceNotReady:
        raise                              # une ATTENTE, pas une erreur : la card la dit
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


def _fingerprint(text) -> str:
    """Empreinte d'une sortie qui n'est pas un fichier — ce qui périme l'aval quand elle change."""
    from wama.common.services.revisions import text_fingerprint
    return text_fingerprint(text or '')


def _llm(item, auto=None):
    """`(nom, fournisseur)` du modèle de langage de la card (`llm_model`) — lecture COMMUNE."""
    from wama.common.utils.llm_utils import card_llm
    return card_llm(getattr(item, 'llm_model', '') or 'auto', auto=auto, owner='le Reader')


# ── ETA par process (`ProcessSpec.eta`) — `read` garde sa clé par moteur (son historique appris) ;
# les deux process LLM sont estimés appris seulement.

def read_eta(item):
    return (*reader_eta_key_size(item), True)


def format_eta(item):
    return 'reader:format', max(int(item.page_count or 0), 1), 'page', True, 0.0


def analyze_eta(item):
    return 'reader:analyze', 1.0, 'item', True, 0.0


def _format(item, ctx):
    """Process `format` (optionnel, coché par défaut) : le texte lu remis en Markdown. Le texte
    NATIF d'un PDF reste tel quel (il ne l'a jamais été). Lit le texte LU (`raw_result`), jamais
    une mise en forme d'avant : la rejouer ne reformate pas un texte déjà reformaté."""
    if item.used_backend == 'fitz_direct':
        return {'label': 'texte natif, gardé tel quel'}
    text = _extract_natural_text(item.raw_result or '')
    if not (text or '').strip():
        return {'label': 'rien à mettre en forme'}
    from wama.common.utils.llm_utils import ollama_catalog_key
    model, provider = _llm(item)
    ctx.progress(10, "Mise en forme…")
    ctx.console(f"[Reader] Mise en forme via LLM{f' — modèle : {model}' if model else ''}…")
    result = _format_as_markdown(text, item.language, model=model, provider=provider,
                                 temperature=getattr(item, 'llm_temperature', None))
    return {'fields': {'result_text': result}, 'label': 'Markdown',
            'models': [ollama_catalog_key(model)] if provider == 'ollama' else [],
            'output_fingerprint': _fingerprint(result), 'eta': format_eta(item)[:3]}


def _analyze(item, ctx):
    """Process `analyze` (optionnel) : résumé, points clés et actions du texte — mis en forme
    s'il l'a été."""
    if not (item.result_text or '').strip():
        return {'label': 'rien à analyser'}
    from wama.common.utils.llm_utils import generate_structured_summary, ollama_catalog_key
    model, provider = _llm(item)
    ctx.console(f"[Reader] Analyse LLM : {item.filename}…")
    data = generate_structured_summary(item.result_text, content_hint='description',
                                       language='fr', model=model, provider=provider,
                                       temperature=getattr(item, 'llm_temperature', None))
    lines = [data['summary']]
    if data['key_points']:
        lines.append('\nPoints clés :')
        lines.extend(f'• {p}' for p in data['key_points'])
    if data['action_items']:
        lines.append('\nActions :')
        lines.extend(f'• {a}' for a in data['action_items'])
    analysis = '\n'.join(lines)
    return {'fields': {'analysis': analysis}, 'label': 'analyse',
            'models': [ollama_catalog_key(model)] if provider == 'ollama' else [],
            'output_fingerprint': _fingerprint(analysis), 'eta': analyze_eta(item)[:3]}


#: La glu de chaque process du pipeline (`function_specs.PIPELINE`).
PROCESSES = {'read': _read, 'format': _format, 'analyze': _analyze}


@shared_task(bind=True, name='wama.reader.tasks.analyze_document_task')
def analyze_document_task(self, item_id: int):
    """L'analyse « à la demande » d'avant le pipeline (2026-10-13) — gardée pour un message encore
    en vol (nom de tâche = jumeau par chaîne) : elle active l'interrupteur et joue le seul process
    `analyze`. La route `analyze/` passe désormais par le ▶ de ce process (`views.analyze`)."""
    close_old_connections()
    from wama.common.utils.task_skeleton import run_item_task
    from .function_specs import PIPELINE
    from .models import ReadingItem
    ReadingItem.objects.filter(pk=item_id).update(generate_analysis=True)
    run_item_task(self, app_id='reader', model=ReadingItem, item_id=item_id,
                  pipeline=PIPELINE, processes=PROCESSES, notify_label='Reader',
                  progress_fn=_set_progress, only='analyze')
