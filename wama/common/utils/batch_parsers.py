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
