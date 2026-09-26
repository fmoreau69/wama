"""
WAMA Synthesizer - Text Extractor (version simplifiée)
Extraction de texte depuis différents formats
"""

import os
import logging
import re

from wama.common.utils.tts_text import text_for_speech

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
    """Prépare un texte pour la synthèse vocale — DÉLÈGUE à la brique commune.

    ⚠ Le corps vivait ici jusqu'au 2026-09-26, et il retirait les URL, les e-mails et les
    espaces multiples : rien de faux, mais il ignorait les EMOJIS et les RESPIRATIONS, qui
    étaient écrites dans `wama/views.py` sous le MÊME NOM de fonction. Le synthesizer, dont
    tout le métier est de lire un document à voix haute, lisait donc les listes à puces d'un
    trait et faisait verbaliser les pictogrammes par espeak.

    Les six appelants de ce nom sont conservés (rien à réécrire chez eux) ; ce qu'ils appellent
    est désormais la chaîne complète. Nouveau comportement pour eux : pause en fin de ligne non
    ponctuée, retrait des emojis, aplatissement du Markdown.
    """
    return text_for_speech(text)
