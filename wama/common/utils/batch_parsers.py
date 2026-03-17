"""
WAMA Common — Batch file parsers

Common infrastructure for parsing batch import files across apps.

Batch formats by app
--------------------
anonymizer / describer / enhancer / transcriber:
    Plain text, one media path or URL per line.
    Lines starting with # are comments, blank lines are ignored.
    → use parse_media_list_batch()

synthesizer:
    Pipe-separated: nom_fichier|texte à synthétiser|voix|vitesse
    Columns 3 and 4 (voice, speed) are optional.
    → wama.synthesizer.utils.batch_parser (delegates extract_batch_file_text here)

composer:
    Pipe-separated: nom_fichier|prompt|modèle|durée
    Columns 3 (model) and 4 (duration in seconds) are optional.
    → wama.composer.utils.batch_parser (delegates extract_batch_file_text here)

imager / avatarizer: TBD
"""

import os
import logging
from typing import List, Tuple, Dict, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Low-level: text extraction from supported file formats
# ---------------------------------------------------------------------------

SUPPORTED_BATCH_EXTENSIONS = ('txt', 'md', 'csv', 'pdf', 'docx')


def extract_batch_file_text(file_path: str) -> str:
    """
    Read and return the raw text from a batch file.

    Supports: .txt, .md, .csv (read as plain text), .pdf (PyPDF2), .docx (python-docx).

    Raises:
        ValueError: unsupported extension
        RuntimeError: missing optional dependency
    """
    ext = os.path.splitext(file_path)[1].lower().lstrip('.')

    if ext in ('txt', 'md', 'csv'):
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            return f.read()

    if ext == 'pdf':
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

    if ext == 'docx':
        try:
            from docx import Document
            doc = Document(file_path)
            return '\n'.join(p.text for p in doc.paragraphs if p.text.strip())
        except ImportError:
            raise RuntimeError("python-docx non installé : pip install python-docx")

    raise ValueError(f"Format de fichier batch non supporté : .{ext}")


# ---------------------------------------------------------------------------
# URL / media path list parser
# (anonymizer, describer, enhancer, transcriber)
# ---------------------------------------------------------------------------

def parse_media_list_batch(
    file_path: str,
) -> Tuple[List[Dict], List[str]]:
    """
    Parse a batch file containing one media path or URL per line.

    Format:
        # commentaire (ignoré)
        /chemin/relatif/vers/media.mp4
        https://example.com/media.jpg
        ...

    Returns:
        (items, warnings)
        Each item dict has keys: path (str), line_num (int)
        warnings is a list of human-readable warning strings.
    """
    raw_text = extract_batch_file_text(file_path)
    return _parse_media_lines(raw_text)


def _parse_media_lines(text: str) -> Tuple[List[Dict], List[str]]:
    items: List[Dict] = []
    warnings: List[str] = []

    for line_num, line in enumerate(text.splitlines(), start=1):
        line = line.strip()
        if not line or line.startswith('#'):
            continue

        items.append({'path': line, 'line_num': line_num})

    if not items:
        warnings.append("Aucune entrée valide trouvée dans le fichier batch")

    return items, warnings


# ---------------------------------------------------------------------------
# Composer batch parser (music / SFX generation)
# Format: nom_fichier|prompt|modèle|durée
# ---------------------------------------------------------------------------

def parse_composer_batch(
    file_path: str,
    default_model: str = 'musicgen-small',
    default_duration: float = 10.0,
) -> Tuple[List[Dict], List[str]]:
    """
    Parse a Composer batch file (pipe-separated).

    Format:
        # commentaire (ignoré)
        nom_fichier|prompt de génération|modèle|durée_en_secondes
        intro|upbeat jazz piano|musicgen-medium|20
        ambiance|dark drone|musicgen-small|15
        rain|heavy rain on tin roof|audiogen-medium|10

    Columns 3 (model) and 4 (duration in seconds) are optional.
    The model also determines the generation type (music vs sfx).

    Returns:
        (tasks, warnings)
        Each task dict has keys:
            output_filename, prompt, model, duration, generation_type, line_num
    """
    raw_text = extract_batch_file_text(file_path)
    return _parse_composer_lines(raw_text, default_model, default_duration)


def _parse_composer_lines(
    text: str,
    default_model: str,
    default_duration: float,
) -> Tuple[List[Dict], List[str]]:
    """Parse pipe-separated Composer batch lines into task dicts."""
    from wama.composer.utils.model_config import COMPOSER_MODELS

    tasks: List[Dict] = []
    warnings: List[str] = []
    valid_models = set(COMPOSER_MODELS.keys())

    for line_num, line in enumerate(text.splitlines(), start=1):
        line = line.strip()
        if not line or line.startswith('#'):
            continue

        parts = [p.strip() for p in line.split('|')]

        if len(parts) < 2:
            warnings.append(
                f"Ligne {line_num} : format invalide (au moins 2 colonnes requises), ignorée"
            )
            continue

        # Column 1: output filename
        filename = parts[0]
        if not filename:
            warnings.append(f"Ligne {line_num} : nom de fichier vide, ignorée")
            continue
        if not os.path.splitext(filename)[1]:
            filename += '.wav'

        # Column 2: prompt
        prompt = parts[1]
        if not prompt:
            warnings.append(f"Ligne {line_num} : prompt vide, ignorée")
            continue

        # Column 3: model (optional)
        model = default_model
        if len(parts) > 2 and parts[2]:
            m = parts[2]
            if m in valid_models:
                model = m
            else:
                warnings.append(
                    f"Ligne {line_num} : modèle '{m}' inconnu, utilisation de '{default_model}'"
                )

        # Column 4: duration in seconds (optional)
        duration = default_duration
        if len(parts) > 3 and parts[3]:
            try:
                duration = float(parts[3])
                if not (1.0 <= duration <= 30.0):
                    warnings.append(
                        f"Ligne {line_num} : durée {duration}s hors limites (1–30s), ajustée"
                    )
                    duration = max(1.0, min(30.0, duration))
            except ValueError:
                warnings.append(
                    f"Ligne {line_num} : durée invalide '{parts[3]}', "
                    f"utilisation de {default_duration}s"
                )

        generation_type = COMPOSER_MODELS.get(model, {}).get('type', 'music')

        tasks.append({
            'output_filename': filename,
            'prompt': prompt,
            'model': model,
            'duration': duration,
            'generation_type': generation_type,
            'line_num': line_num,
        })

    return tasks, warnings
