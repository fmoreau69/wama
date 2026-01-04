"""
Text and PDF description/summarization.
"""

import os
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# Global model cache
_summarizer = None


def get_summarizer(model_name: str = None):
    """Load and cache summarization pipeline."""
    global _summarizer

    if _summarizer is None:
        logger.info("Loading summarization model...")

        try:
            from transformers import pipeline
            import torch

            # Choose model based on available resources
            if model_name is None:
                # Use multilingual model for better French support
                model_name = "facebook/bart-large-cnn"

            device = 0 if torch.cuda.is_available() else -1

            _summarizer = pipeline(
                "summarization",
                model=model_name,
                device=device
            )

            logger.info(f"Summarization model loaded: {model_name}")

        except ImportError as e:
            logger.error(f"Failed to import transformers: {e}")
            raise ImportError(
                "transformers library not installed. "
                "Run: pip install transformers torch"
            )

    return _summarizer


def extract_text_from_file(file_path: str) -> str:
    """Extract text content from various file formats."""
    ext = file_path.rsplit('.', 1)[-1].lower() if '.' in file_path else ''

    if ext == 'pdf':
        return extract_from_pdf(file_path)
    elif ext == 'docx':
        return extract_from_docx(file_path)
    elif ext in ('txt', 'md', 'csv'):
        return extract_from_text(file_path)
    else:
        # Try reading as text
        return extract_from_text(file_path)


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


def chunk_text(text: str, max_tokens: int = 1024) -> list:
    """Split text into chunks for processing."""
    # Approximate tokens as words * 1.3
    words = text.split()
    max_words = int(max_tokens / 1.3)

    chunks = []
    current_chunk = []
    current_length = 0

    for word in words:
        if current_length + 1 > max_words:
            chunks.append(' '.join(current_chunk))
            current_chunk = [word]
            current_length = 1
        else:
            current_chunk.append(word)
            current_length += 1

    if current_chunk:
        chunks.append(' '.join(current_chunk))

    return chunks


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

        # If text is short, just format it
        if word_count <= max_length:
            console(user_id, "Text is short, formatting directly...")
            result = format_text_result(text, output_format)
            set_partial(description, result[:500])
            return result

        # Load summarizer
        set_partial(description, "Loading summarization model...")
        console(user_id, "Loading AI model...")

        summarizer = get_summarizer()

        set_progress(description, 50)
        console(user_id, "Generating summary...")

        # Chunk long text
        chunks = chunk_text(text, max_tokens=1024)
        console(user_id, f"Processing {len(chunks)} text chunks...")

        summaries = []
        for i, chunk in enumerate(chunks):
            if len(chunk.split()) < 50:
                # Skip very short chunks
                continue

            progress = 50 + int((i / len(chunks)) * 30)
            set_progress(description, progress)
            set_partial(description, f"Processing chunk {i+1}/{len(chunks)}...")

            try:
                # Calculate lengths based on output format
                if output_format == 'summary':
                    min_len, max_len = 30, 80
                elif output_format == 'bullet_points':
                    min_len, max_len = 50, 150
                else:
                    min_len, max_len = 80, 200

                summary = summarizer(
                    chunk,
                    max_length=max_len,
                    min_length=min_len,
                    do_sample=False
                )
                summaries.append(summary[0]['summary_text'])

            except Exception as e:
                logger.warning(f"Error summarizing chunk {i}: {e}")
                continue

        if not summaries:
            return "Could not generate summary from the content."

        # Combine summaries
        combined = ' '.join(summaries)

        set_progress(description, 85)

        # If combined is still too long, summarize again
        if len(combined.split()) > max_length * 2:
            console(user_id, "Condensing final summary...")
            try:
                final = summarizer(
                    combined,
                    max_length=max_length,
                    min_length=min(50, max_length // 2),
                    do_sample=False
                )
                combined = final[0]['summary_text']
            except:
                # If fails, just truncate
                words = combined.split()[:max_length]
                combined = ' '.join(words) + '...'

        # Format result
        result = format_text_result(combined, output_format)

        set_partial(description, result[:500])
        console(user_id, "Summary generated successfully")

        # Translate if needed
        if output_language == 'fr':
            result = translate_to_french(result, console, user_id)
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
