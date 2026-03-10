"""
WAMA Synthesizer - Batch File Parser

Parses pipe-separated batch synthesis files.
Format: nom_fichier|texte à synthétiser|voix|vitesse
Colonnes voix et vitesse sont optionnelles.
Lignes commençant par # = commentaires, lignes vides ignorées.

Formats de fichier supportés : TXT, MD, PDF, DOCX, CSV.
"""

import os
import logging
from typing import List, Tuple, Dict

logger = logging.getLogger(__name__)


def parse_batch_file(
    file_path: str,
    default_voice: str = 'default',
    default_speed: float = 1.0,
) -> Tuple[List[Dict], List[str]]:
    """
    Parse a batch synthesis file (pipe-separated).

    Args:
        file_path: Path to the batch file
        default_voice: Voice to use when column 3 is absent or empty
        default_speed: Speed to use when column 4 is absent or empty

    Returns:
        (tasks, warnings)
        Each task dict has keys: output_filename, text, voice, speed, line_num
    """
    ext = os.path.splitext(file_path)[1].lower()
    raw_text = _extract_text(file_path, ext)
    return _parse_pipe_lines(raw_text, default_voice, default_speed)


def _extract_text(file_path: str, ext: str) -> str:
    """Extract raw text from the batch file."""
    if ext in ('.txt', '.md'):
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            return f.read()

    elif ext == '.pdf':
        try:
            import PyPDF2
            pages = []
            with open(file_path, 'rb') as f:
                reader = PyPDF2.PdfReader(f)
                for page in reader.pages:
                    t = page.extract_text()
                    if t:
                        pages.append(t)
            return '\n'.join(pages)
        except ImportError:
            raise RuntimeError("PyPDF2 non installé : pip install PyPDF2")

    elif ext == '.docx':
        try:
            from docx import Document
            doc = Document(file_path)
            return '\n'.join(p.text for p in doc.paragraphs if p.text.strip())
        except ImportError:
            raise RuntimeError("python-docx non installé : pip install python-docx")

    elif ext == '.csv':
        # Batch CSV files use | as separator — read as plain text
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            return f.read()

    else:
        raise ValueError(f"Format de fichier non supporté : {ext}")


def _parse_pipe_lines(
    text: str,
    default_voice: str,
    default_speed: float,
) -> Tuple[List[Dict], List[str]]:
    """Parse pipe-separated lines into task dicts."""
    tasks: List[Dict] = []
    warnings: List[str] = []

    for line_num, line in enumerate(text.splitlines(), start=1):
        line = line.strip()
        if not line or line.startswith('#'):
            continue

        parts = [p.strip() for p in line.split('|')]

        if len(parts) < 2:
            warnings.append(f"Ligne {line_num} : format invalide (au moins 2 colonnes requises), ignorée")
            continue

        # Column 1 : output filename
        filename = parts[0]
        if not filename:
            warnings.append(f"Ligne {line_num} : nom de fichier vide, ignorée")
            continue
        # Add .wav extension if none present
        if not os.path.splitext(filename)[1]:
            filename += '.wav'

        # Column 2 : text to synthesize
        text_content = parts[1]
        if not text_content:
            warnings.append(f"Ligne {line_num} : texte vide, ignorée")
            continue

        # Column 3 : voice (optional)
        voice = default_voice
        if len(parts) > 2 and parts[2]:
            voice = parts[2]

        # Column 4 : speed (optional)
        speed = default_speed
        if len(parts) > 3 and parts[3]:
            try:
                speed = float(parts[3])
                if not (0.5 <= speed <= 2.0):
                    warnings.append(
                        f"Ligne {line_num} : vitesse {speed} hors limites (0.5–2.0), ajustée"
                    )
                    speed = max(0.5, min(2.0, speed))
            except ValueError:
                warnings.append(
                    f"Ligne {line_num} : vitesse invalide '{parts[3]}', "
                    f"utilisation de {default_speed}"
                )

        tasks.append({
            'output_filename': filename,
            'text': text_content,
            'voice': voice,
            'speed': speed,
            'line_num': line_num,
        })

    return tasks, warnings
