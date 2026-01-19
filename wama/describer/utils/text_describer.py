"""
Text and PDF description/summarization.
"""

import os
import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)

# Global model cache
_summarizer = None
_summarizer_device = None  # Track current device


def reset_cuda():
    """Reset CUDA state after an error."""
    try:
        import torch
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            torch.cuda.synchronize()
    except Exception as e:
        logger.warning(f"Failed to reset CUDA: {e}")


def get_summarizer(model_name: str = None, force_cpu: bool = False):
    """Load and cache summarization pipeline."""
    global _summarizer, _summarizer_device

    target_device = -1 if force_cpu else None

    if _summarizer is not None and (target_device is None or target_device == _summarizer_device):
        return _summarizer

    logger.info("Loading summarization model...")

    try:
        from transformers import pipeline
        import torch

        # Choose model based on available resources
        if model_name is None:
            # Use multilingual model for better French support
            model_name = "facebook/bart-large-cnn"

        if target_device is None:
            device = 0 if torch.cuda.is_available() else -1
        else:
            device = target_device

        _summarizer = pipeline(
            "summarization",
            model=model_name,
            device=device
        )
        _summarizer_device = device

        device_name = "CUDA" if device >= 0 else "CPU"
        logger.info(f"Summarization model loaded: {model_name} on {device_name}")

    except ImportError as e:
        logger.error(f"Failed to import transformers: {e}")
        raise ImportError(
            "transformers library not installed. "
            "Run: pip install transformers torch"
        )

    return _summarizer


def sanitize_text_for_model(text: str) -> str:
    """
    Sanitize text to prevent CUDA tokenization errors.
    Removes or replaces problematic characters.
    BART model works best with clean ASCII-like text.
    """
    if not text:
        return text

    # Replace common problematic Unicode characters
    replacements = {
        '\u2018': "'",  # Left single quote
        '\u2019': "'",  # Right single quote
        '\u201c': '"',  # Left double quote
        '\u201d': '"',  # Right double quote
        '\u2013': '-',  # En dash
        '\u2014': '-',  # Em dash
        '\u2026': '...',  # Ellipsis
        '\u00a0': ' ',  # Non-breaking space
        '\u200b': '',   # Zero-width space
        '\ufeff': '',   # BOM
        '\u00ab': '"',  # French left quote «
        '\u00bb': '"',  # French right quote »
        '\u2022': '-',  # Bullet
        '\u2023': '-',  # Triangle bullet
        '\u25aa': '-',  # Square bullet
        '\u00b7': '-',  # Middle dot
        '\u2212': '-',  # Minus sign
        '\u00ad': '',   # Soft hyphen
        '\u200c': '',   # Zero-width non-joiner
        '\u200d': '',   # Zero-width joiner
        '\uf0b7': '-',  # Private use bullet
        '\uf0a7': '-',  # Private use symbol
    }

    for old, new in replacements.items():
        text = text.replace(old, new)

    # Normalize French accented characters to ASCII equivalents for BART
    # (BART is trained on English and may not handle accents well)
    accent_map = {
        'à': 'a', 'â': 'a', 'ä': 'a', 'á': 'a', 'ã': 'a',
        'è': 'e', 'ê': 'e', 'ë': 'e', 'é': 'e',
        'ì': 'i', 'î': 'i', 'ï': 'i', 'í': 'i',
        'ò': 'o', 'ô': 'o', 'ö': 'o', 'ó': 'o', 'õ': 'o',
        'ù': 'u', 'û': 'u', 'ü': 'u', 'ú': 'u',
        'ç': 'c', 'ñ': 'n', 'ÿ': 'y', 'ý': 'y',
        'À': 'A', 'Â': 'A', 'Ä': 'A', 'Á': 'A', 'Ã': 'A',
        'È': 'E', 'Ê': 'E', 'Ë': 'E', 'É': 'E',
        'Ì': 'I', 'Î': 'I', 'Ï': 'I', 'Í': 'I',
        'Ò': 'O', 'Ô': 'O', 'Ö': 'O', 'Ó': 'O', 'Õ': 'O',
        'Ù': 'U', 'Û': 'U', 'Ü': 'U', 'Ú': 'U',
        'Ç': 'C', 'Ñ': 'N', 'Ÿ': 'Y', 'Ý': 'Y',
        'œ': 'oe', 'Œ': 'OE', 'æ': 'ae', 'Æ': 'AE',
        '°': ' degrees ', '€': ' euros ', '£': ' pounds ',
        '©': '(c)', '®': '(R)', '™': '(TM)',
    }

    for old, new in accent_map.items():
        text = text.replace(old, new)

    # Remove control characters except newlines and tabs
    text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]', '', text)

    # Remove any remaining non-ASCII characters that might cause issues
    text = text.encode('ascii', 'ignore').decode('ascii')

    # Normalize whitespace
    text = re.sub(r'\s+', ' ', text)

    # Remove very long words (often garbage from PDF extraction)
    words = text.split()
    words = [w for w in words if len(w) <= 50]
    text = ' '.join(words)

    # Ensure text is not too long for tokenizer (BART max is 1024 tokens)
    # Rough estimate: 1 token ≈ 4 characters for English
    max_chars = 3500  # Be more conservative
    if len(text) > max_chars:
        text = text[:max_chars]

    return text.strip()


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
        cuda_failed = False  # Track if CUDA has failed

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

                # Sanitize chunk to prevent tokenization errors
                clean_chunk = sanitize_text_for_model(chunk)
                if not clean_chunk or len(clean_chunk.split()) < 30:
                    continue

                # If CUDA failed before, use CPU
                if cuda_failed:
                    summarizer = get_summarizer(force_cpu=True)

                summary = summarizer(
                    clean_chunk,
                    max_length=max_len,
                    min_length=min_len,
                    do_sample=False,
                    truncation=True
                )
                summaries.append(summary[0]['summary_text'])

            except RuntimeError as e:
                error_str = str(e)
                if 'CUDA' in error_str or 'device-side assert' in error_str:
                    logger.warning(f"CUDA error on chunk {i}, switching to CPU: {e}")
                    reset_cuda()
                    cuda_failed = True

                    # Retry on CPU
                    try:
                        summarizer = get_summarizer(force_cpu=True)
                        clean_chunk = sanitize_text_for_model(chunk)
                        if clean_chunk and len(clean_chunk.split()) >= 30:
                            summary = summarizer(
                                clean_chunk,
                                max_length=max_len,
                                min_length=min_len,
                                do_sample=False,
                                truncation=True
                            )
                            summaries.append(summary[0]['summary_text'])
                            console(user_id, f"Chunk {i+1} processed on CPU (fallback)")
                    except Exception as cpu_error:
                        logger.warning(f"CPU fallback also failed for chunk {i}: {cpu_error}")
                else:
                    logger.warning(f"Error summarizing chunk {i}: {e}")

            except IndexError as e:
                # "index out of range in self" - tokenizer issue
                logger.warning(f"Tokenizer error on chunk {i}: {e}")
                continue

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
                clean_combined = sanitize_text_for_model(combined)
                if cuda_failed:
                    summarizer = get_summarizer(force_cpu=True)

                final = summarizer(
                    clean_combined,
                    max_length=max_length,
                    min_length=min(50, max_length // 2),
                    do_sample=False,
                    truncation=True
                )
                combined = final[0]['summary_text']
            except RuntimeError as e:
                if 'CUDA' in str(e) or 'device-side assert' in str(e):
                    logger.warning(f"CUDA error in final summary, trying CPU: {e}")
                    reset_cuda()
                    try:
                        summarizer = get_summarizer(force_cpu=True)
                        clean_combined = sanitize_text_for_model(combined)
                        final = summarizer(
                            clean_combined,
                            max_length=max_length,
                            min_length=min(50, max_length // 2),
                            do_sample=False,
                            truncation=True
                        )
                        combined = final[0]['summary_text']
                    except:
                        words = combined.split()[:max_length]
                        combined = ' '.join(words) + '...'
                else:
                    words = combined.split()[:max_length]
                    combined = ' '.join(words) + '...'
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
