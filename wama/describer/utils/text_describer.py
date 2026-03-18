"""
Text and PDF description/summarization.
"""

import os
import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)


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


def _html_to_readable_text(html: str) -> str:
    """Convert HTML to readable plain text using BeautifulSoup + lxml."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, 'lxml')

    # Get page title
    title_tag = soup.find('title')
    title_text = title_tag.get_text(strip=True) if title_tag else ''

    # Remove non-content elements
    for tag in soup(['script', 'style', 'nav', 'footer', 'aside',
                     'noscript', 'meta', 'link', 'button', 'svg', 'form',
                     'iframe', 'template', 'header']):
        tag.decompose()

    # Find main content area.
    # Specific content containers are preferred over generic <main> (which on GitHub
    # includes the full page — file tree, navigation, sidebar — not just the README).
    main = (
        soup.find(id='readme') or          # GitHub README
        soup.find(class_='markdown-body') or  # GitHub/GitLab markdown render
        soup.find('article') or
        soup.find(attrs={'role': 'main'}) or
        soup.find('main') or
        soup.find(id='content') or
        soup.find(class_='content') or
        soup.body or
        soup
    )

    text = main.get_text(separator='\n', strip=True)
    text = re.sub(r'\n{3,}', '\n\n', text)

    if title_text:
        text = f"# {title_text}\n\n{text}"

    return text.strip()


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


def describe_text(description, set_progress, set_partial, console):
    """
    Summarize text content.

    Args:
        description: Description model instance
        set_progress: Function to update progress
        set_partial: Function to set partial result
        console: Function to log to console

    Returns:
        str: Summary text
    """
    user_id = description.user_id
    file_path = description.input_file.path
    output_format = description.output_format
    output_language = description.output_language
    max_length = description.max_length

    console(user_id, "Extracting text content...")
    set_progress(description, 20)

    try:
        # Extract text
        text = extract_text_from_file(file_path)

        if not text or not text.strip():
            return "No text content found in the file."

        word_count = len(text.split())
        console(user_id, f"Extracted {word_count} words")

        set_progress(description, 30)

        # Meeting compte-rendu: bypass BART, use LLM directly
        if output_format == 'meeting':
            console(user_id, "Génération du compte-rendu de réunion (Ollama)…")
            set_partial(description, "Rédaction du compte-rendu…")
            from wama.common.utils.llm_utils import generate_meeting_summary, get_describer_model
            _model = get_describer_model('text', 'meeting')
            console(user_id, f"Modèle LLM : {_model}")
            result = generate_meeting_summary(text, language=output_language, model=_model)
            set_partial(description, result[:500])
            return result

        # If text is short, just format it
        if word_count <= max_length:
            console(user_id, "Text is short, formatting directly...")
            result = format_text_result(text, output_format)
            set_partial(description, result[:500])
            return result

        # Use Ollama LLM for summarization (replaces BART pipeline)
        console(user_id, "Génération du résumé LLM (Ollama)…")
        set_partial(description, "Génération du résumé en cours…")
        set_progress(description, 50)

        try:
            from wama.common.utils.llm_utils import generate_structured_summary, get_describer_model
            _model = get_describer_model('text', output_format)
            console(user_id, f"Modèle LLM : {_model}")
            summary_data = generate_structured_summary(
                text, content_hint='text', language=output_language or 'fr',
                model=_model,
            )
            set_progress(description, 85)

            if output_format == 'bullet_points' and summary_data['key_points']:
                lines = [f"- {p}" for p in summary_data['key_points']]
                if summary_data['action_items']:
                    lines += ['', 'Actions :'] + [f"- {a}" for a in summary_data['action_items']]
                result = '\n'.join(lines)
            elif output_format == 'scientific':
                parts = [summary_data['summary']]
                if summary_data['key_points']:
                    parts += ['', 'Key points:'] + [f"- {p}" for p in summary_data['key_points']]
                body = '\n'.join(parts)
                result = f"Summary:\n\n{body}\n\n---\nThis summary was generated automatically using AI-based text summarization."
            elif output_format == 'detailed':
                parts = [summary_data['summary']]
                if summary_data['key_points']:
                    parts += ['', 'Points clés :'] + [f"- {p}" for p in summary_data['key_points']]
                if summary_data['action_items']:
                    parts += ['', 'Actions :'] + [f"- {a}" for a in summary_data['action_items']]
                result = '\n'.join(parts)
            else:  # 'summary'
                result = summary_data['summary']

        except Exception as llm_err:
            console(user_id, f"Avertissement: Ollama indisponible ({llm_err}), texte tronqué")
            logger.warning(f"Ollama summarization failed: {llm_err}")
            words = text.split()[:max_length]
            result = ' '.join(words) + ('…' if len(text.split()) > max_length else '')

        set_partial(description, result[:500])
        console(user_id, "Résumé généré avec succès")
        set_progress(description, 90)

        return result

    except Exception as e:
        logger.exception(f"Error summarizing text: {e}")
        raise


def format_text_result(text: str, output_format: str) -> str:
    """Format the summary based on output format."""
    text = text.strip()

    if output_format == 'bullet_points':
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

    elif output_format == 'scientific':
        return f"Summary:\n\n{text}\n\n---\nThis summary was generated automatically using AI-based text summarization."

    elif output_format == 'summary':
        # Keep it concise
        if len(text) > 500:
            text = text[:497] + '...'
        return text

    else:  # detailed
        return text


def translate_to_french(text: str, console, user_id: int) -> str:
    """Translate text to French using deep-translator."""
    try:
        from deep_translator import GoogleTranslator

        translator = GoogleTranslator(source='auto', target='fr')

        if len(text) > 4500:
            # Split into chunks for long texts
            chunks = [text[i:i+4500] for i in range(0, len(text), 4500)]
            translated_chunks = []
            for i, chunk in enumerate(chunks):
                translated_chunks.append(translator.translate(chunk))
                console(user_id, f"Translated chunk {i+1}/{len(chunks)}")
            result = ' '.join(translated_chunks)
        else:
            result = translator.translate(text)

        console(user_id, "Translation completed successfully")
        return result

    except ImportError:
        console(user_id, "Warning: deep-translator not installed, skipping translation")
        logger.warning("deep-translator not installed - install with: pip install deep-translator")
        return text
    except Exception as e:
        console(user_id, f"Warning: Translation failed - {str(e)}")
        logger.warning(f"Translation failed: {e}")
        return text
