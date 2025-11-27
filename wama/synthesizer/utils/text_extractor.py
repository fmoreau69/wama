"""
WAMA Synthesizer - Text Extractor (version simplifiée)
Extraction de texte depuis différents formats
"""

import os
import logging
import re

logger = logging.getLogger(__name__)


def extract_text_from_file(file_path: str) -> str:
    """
    Extrait le texte d'un fichier (TXT, PDF, DOCX, CSV, MD).

    Args:
        file_path: Chemin du fichier

    Returns:
        str: Texte extrait
    """
    ext = os.path.splitext(file_path)[1].lower()

    try:
        if ext in ['.txt', '.md']:
            return _extract_from_txt(file_path)
        elif ext == '.pdf':
            return _extract_from_pdf(file_path)
        elif ext == '.docx':
            return _extract_from_docx(file_path)
        elif ext == '.csv':
            return _extract_from_csv(file_path)
        else:
            raise ValueError(f"Format de fichier non supporté: {ext}")
    except Exception as e:
        logger.error(f"Error extracting text from {file_path}: {e}")
        raise


def _extract_from_txt(file_path: str) -> str:
    """Extrait le texte d'un fichier TXT ou MD."""
    with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
        return f.read()


def _extract_from_pdf(file_path: str) -> str:
    """Extrait le texte d'un fichier PDF."""
    try:
        import PyPDF2

        text = []
        with open(file_path, 'rb') as f:
            reader = PyPDF2.PdfReader(f)
            for page in reader.pages:
                page_text = page.extract_text()
                if page_text:
                    text.append(page_text)

        return '\n'.join(text)

    except ImportError:
        raise RuntimeError("PyPDF2 n'est pas installé. Installez avec: pip install PyPDF2")
    except Exception as e:
        raise RuntimeError(f"Erreur lors de l'extraction PDF: {str(e)}")


def _extract_from_docx(file_path: str) -> str:
    """Extrait le texte d'un fichier DOCX."""
    try:
        from docx import Document

        doc = Document(file_path)
        text = []

        for paragraph in doc.paragraphs:
            if paragraph.text.strip():
                text.append(paragraph.text)

        return '\n'.join(text)

    except ImportError:
        raise RuntimeError("python-docx n'est pas installé. Installez avec: pip install python-docx")
    except Exception as e:
        raise RuntimeError(f"Erreur lors de l'extraction DOCX: {str(e)}")


def _extract_from_csv(file_path: str) -> str:
    """Extrait le texte d'un fichier CSV."""
    import csv

    text = []
    try:
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            reader = csv.reader(f)
            for row in reader:
                # Joindre les colonnes avec des espaces
                row_text = ' '.join(str(cell) for cell in row if cell)
                if row_text.strip():
                    text.append(row_text)

        return '\n'.join(text)
    except Exception as e:
        raise RuntimeError(f"Erreur lors de l'extraction CSV: {str(e)}")


def clean_text_for_tts(text: str) -> str:
    """
    Nettoie et prépare un texte pour la synthèse vocale.

    Args:
        text: Texte brut

    Returns:
        str: Texte nettoyé
    """
    if not text:
        return ""

    # Supprimer les URLs
    text = re.sub(r'http[s]?://\S+', '', text)

    # Supprimer les emails
    text = re.sub(r'\S+@\S+', '', text)

    # Normaliser les espaces multiples
    text = re.sub(r'\s+', ' ', text)

    # Supprimer les caractères de contrôle sauf retours à la ligne
    text = ''.join(char for char in text if ord(char) >= 32 or char in '\n\r\t')

    # Normaliser les sauts de ligne multiples
    text = re.sub(r'\n{3,}', '\n\n', text)

    return text.strip()


def estimate_reading_time(text: str, wpm: int = 150) -> float:
    """
    Estime le temps de lecture d'un texte.

    Args:
        text: Texte à évaluer
        wpm: Mots par minute (words per minute)

    Returns:
        float: Temps estimé en secondes
    """
    if not text:
        return 0.0

    word_count = len(text.split())
    minutes = word_count / wpm
    return minutes * 60


def split_text_by_sentences(text: str, max_length: int = 1000) -> list:
    """
    Divise un texte en morceaux respectant les limites de phrases.

    Args:
        text: Texte à diviser
        max_length: Longueur maximale de chaque morceau

    Returns:
        list: Liste de morceaux de texte
    """
    if not text:
        return []

    # Diviser en phrases
    sentences = re.split(r'(?<=[.!?])\s+', text)

    chunks = []
    current_chunk = ""

    for sentence in sentences:
        if len(current_chunk) + len(sentence) + 1 <= max_length:
            current_chunk += sentence + " "
        else:
            if current_chunk:
                chunks.append(current_chunk.strip())
            current_chunk = sentence + " "

    if current_chunk:
        chunks.append(current_chunk.strip())

    return chunks