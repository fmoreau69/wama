"""
Backend DOCUMENT/TEXTE du describer — extraction (PDF/DOCX/TXT/HTML) + résumé LLM.

Contrat commun « texte » (voir `image_backend`) :
    callable(input_path, options=dict, progress_callback=fn, partial_callback=fn,
             console=fn) -> str

Traduit de `utils/text_describer.py` (2026-09-03, marche B1) — mêmes moteurs, signature
ORM-free. Domicile UNIQUE de `translate_to_french` (l'ancienne copie d'image_describer
doublonnait celle-ci — résorbée par le portage).
"""

import logging

logger = logging.getLogger(__name__)


def _noop(*_a, **_k):
    return None


def extract_text_from_file(file_path: str) -> str:
    """Extract text content from various file formats."""
    ext = file_path.rsplit('.', 1)[-1].lower() if '.' in file_path else ''

    if ext == 'pdf':
        return extract_from_pdf(file_path)
    elif ext == 'docx':
        return extract_from_docx(file_path)
    elif ext in ('txt', 'md', 'csv'):
        return extract_from_text(file_path)
    elif ext in ('html', 'htm'):
        return extract_from_html(file_path)
    else:
        # Try reading as text; sniff for HTML content
        text = extract_from_text(file_path)
        stripped = text.lstrip()
        if any(tag in stripped[:500].lower() for tag in ('<!doctype', '<html', '<head')):
            return _html_to_readable_text(text)
        return text


def extract_from_html(file_path: str) -> str:
    """Extract readable text from an HTML file."""
    with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
        html = f.read()
    return _html_to_readable_text(html)


# _html_to_readable_text : extraction portee au commun (reutilisable partout).
from wama.common.utils.url_ingest import html_to_readable_text as _html_to_readable_text  # noqa: E402,F401


def extract_from_pdf(file_path: str) -> str:
    """Extract text from PDF file."""
    try:
        import fitz  # PyMuPDF

        doc = fitz.open(file_path)
        text_parts = []

        for page in doc:
            text_parts.append(page.get_text())

        doc.close()
        return '\n'.join(text_parts)

    except ImportError:
        logger.warning("PyMuPDF not installed, trying pdfplumber...")

        try:
            import pdfplumber

            with pdfplumber.open(file_path) as pdf:
                text_parts = []
                for page in pdf.pages:
                    text = page.extract_text()
                    if text:
                        text_parts.append(text)
                return '\n'.join(text_parts)

        except ImportError:
            logger.error("No PDF library available")
            raise ImportError(
                "PDF extraction requires PyMuPDF or pdfplumber. "
                "Run: pip install PyMuPDF pdfplumber"
            )


def extract_from_docx(file_path: str) -> str:
    """Extract text from DOCX file."""
    try:
        from docx import Document

        doc = Document(file_path)
        paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
        return '\n'.join(paragraphs)

    except ImportError:
        logger.error("python-docx not installed")
        raise ImportError(
            "DOCX extraction requires python-docx. "
            "Run: pip install python-docx"
        )


def extract_from_text(file_path: str) -> str:
    """Extract text from plain text file."""
    encodings = ['utf-8', 'latin-1', 'cp1252']

    for encoding in encodings:
        try:
            with open(file_path, 'r', encoding=encoding) as f:
                return f.read()
        except UnicodeDecodeError:
            continue

    # Last resort: read with errors ignored
    with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
        return f.read()


def describe_text(input_path: str, options: dict = None,
                  progress_callback=None, partial_callback=None, console=None) -> str:
    """Résume un document texte — contrat commun « texte » (voir tête de module)."""
    options = options or {}
    progress = progress_callback or _noop
    partial = partial_callback or _noop
    console = console or _noop

    output_style = options.get('output_style') or 'detailed'
    output_language = options.get('output_language') or 'fr'
    max_length = int(options.get('max_length') or 500)

    console("Extracting text content...")
    progress(20)

    try:
        # Extract text
        text = extract_text_from_file(input_path)

        if not text or not text.strip():
            return "No text content found in the file."

        word_count = len(text.split())
        console(f"Extracted {word_count} words")

        progress(30)

        # Meeting compte-rendu: bypass BART, use LLM directly
        if output_style == 'meeting':
            console("Génération du compte-rendu de réunion (Ollama)…")
            partial("Rédaction du compte-rendu…")
            from wama.common.utils.llm_utils import generate_meeting_summary, get_describer_model
            _model = get_describer_model('text', 'meeting')
            console(f"Modèle LLM : {_model}")
            result = generate_meeting_summary(text, language=output_language, model=_model)
            partial(result[:500])
            return result

        # If text is short, just format it
        if word_count <= max_length:
            console("Text is short, formatting directly...")
            result = format_text_result(text, output_style)
            partial(result[:500])
            return result

        # Use Ollama LLM for summarization (replaces BART pipeline)
        console("Génération du résumé LLM (Ollama)…")
        partial("Génération du résumé en cours…")
        progress(50)

        try:
            from wama.common.utils.llm_utils import generate_structured_summary, get_describer_model
            _model = get_describer_model('text', output_style)
            console(f"Modèle LLM : {_model}")
            summary_data = generate_structured_summary(
                text, content_hint='text', language=output_language or 'fr',
                model=_model,
            )
            progress(85)

            if output_style == 'bullet_points' and summary_data['key_points']:
                lines = [f"- {p}" for p in summary_data['key_points']]
                if summary_data['action_items']:
                    lines += ['', 'Actions :'] + [f"- {a}" for a in summary_data['action_items']]
                result = '\n'.join(lines)
            elif output_style == 'scientific':
                parts = [summary_data['summary']]
                if summary_data['key_points']:
                    parts += ['', 'Key points:'] + [f"- {p}" for p in summary_data['key_points']]
                body = '\n'.join(parts)
                result = f"Summary:\n\n{body}\n\n---\nThis summary was generated automatically using AI-based text summarization."
            elif output_style == 'detailed':
                parts = [summary_data['summary']]
                if summary_data['key_points']:
                    parts += ['', 'Points clés :'] + [f"- {p}" for p in summary_data['key_points']]
                if summary_data['action_items']:
                    parts += ['', 'Actions :'] + [f"- {a}" for a in summary_data['action_items']]
                result = '\n'.join(parts)
            else:  # 'summary'
                result = summary_data['summary']

        except Exception as llm_err:
            console(f"Avertissement: Ollama indisponible ({llm_err}), texte tronqué")
            logger.warning(f"Ollama summarization failed: {llm_err}")
            words = text.split()[:max_length]
            result = ' '.join(words) + ('…' if len(text.split()) > max_length else '')

        partial(result[:500])
        console("Résumé généré avec succès")
        progress(90)

        return result

    except Exception as e:
        logger.exception(f"Error summarizing text: {e}")
        raise


def format_text_result(text: str, output_style: str) -> str:
    """Format the summary based on output format."""
    text = text.strip()

    if output_style == 'bullet_points':
        # Split into sentences and format as bullets
        import re
        sentences = re.split(r'(?<=[.!?])\s+', text)
        bullets = []
        for s in sentences:
            s = s.strip()
            if s:
                if not s.endswith('.'):
                    s += '.'
                bullets.append(f"- {s}")
        return '\n'.join(bullets)

    elif output_style == 'scientific':
        return f"Summary:\n\n{text}\n\n---\nThis summary was generated automatically using AI-based text summarization."

    elif output_style == 'summary':
        # Keep it concise
        if len(text) > 500:
            text = text[:497] + '...'
        return text

    else:  # detailed
        return text


def translate_to_french(text: str, console=None) -> str:
    """Translate text to French using deep-translator. Domicile UNIQUE (cf. tête de module)."""
    console = console or _noop
    try:
        from deep_translator import GoogleTranslator

        translator = GoogleTranslator(source='auto', target='fr')

        if len(text) > 4500:
            # Split into chunks for long texts
            chunks = [text[i:i+4500] for i in range(0, len(text), 4500)]
            translated_chunks = []
            for i, chunk in enumerate(chunks):
                translated_chunks.append(translator.translate(chunk))
                console(f"Translated chunk {i+1}/{len(chunks)}")
            result = ' '.join(translated_chunks)
        else:
            result = translator.translate(text)

        console("Translation completed successfully")
        return result

    except ImportError:
        console("Warning: deep-translator not installed, skipping translation")
        logger.warning("deep-translator not installed - install with: pip install deep-translator")
        return text
    except Exception as e:
        console(f"Warning: Translation failed - {str(e)}")
        logger.warning(f"Translation failed: {e}")
        return text
