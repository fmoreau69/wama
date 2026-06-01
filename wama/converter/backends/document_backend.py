"""
WAMA Converter — Document Backend (Pandoc via pypandoc)

Supported conversions:
    Input  : pdf, docx, md, html, txt, rtf, odt, epub, latex
    Output : pdf, docx, md, html, txt, rtf, odt, epub

PDF input is handled specially: pandoc does not parse PDF natively, so we
extract text via PyMuPDF first then feed the result to pandoc as Markdown.
PDF output requires a LaTeX engine (xelatex) OR wkhtmltopdf; we try xelatex
first then fall back.
"""

import logging
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)


# Extension → pandoc format identifier (for `--from` / `--to`)
_PANDOC_FORMAT = {
    'md':       'markdown',
    'markdown': 'markdown',
    'html':     'html',
    'htm':      'html',
    'txt':      'plain',
    'docx':     'docx',
    'rtf':      'rtf',
    'odt':      'odt',
    'epub':     'epub',
    'tex':      'latex',
    'latex':    'latex',
    'pdf':      'pdf',
}


def _detect_pdf_engine() -> str | None:
    """Return the first PDF engine available on PATH, or None."""
    for engine in ('xelatex', 'pdflatex', 'lualatex', 'wkhtmltopdf', 'weasyprint'):
        if shutil.which(engine):
            return engine
    return None


def _extract_pdf_text(pdf_path: str) -> str:
    """Extract text from a PDF using PyMuPDF and return it as Markdown.

    PyMuPDF is already a WAMA dependency (used by Reader / Describer).
    """
    try:
        import fitz  # PyMuPDF
    except ImportError as exc:
        raise RuntimeError(
            "PyMuPDF requis pour lire les PDF en entrée (pip install pymupdf)"
        ) from exc

    doc = fitz.open(pdf_path)
    lines = []
    for page_num, page in enumerate(doc, start=1):
        lines.append(f"## Page {page_num}\n")
        lines.append(page.get_text("text"))
        lines.append("")
    doc.close()
    return "\n".join(lines)


def convert_document(input_path: str, output_path: str, output_format: str,
                     options: dict = None) -> None:
    """
    Convert a document via pandoc (with PDF-input special handling).

    Args:
        input_path: Source document path.
        output_path: Target file path.
        output_format: Lowercase target extension (e.g. 'pdf', 'docx', 'md').
        options: Reserved for future use (paper size, margins, TOC, etc.).
    """
    if options is None:
        options = {}

    in_ext  = Path(input_path).suffix.lower().lstrip('.')
    out_ext = output_format.lower().lstrip('.')

    if out_ext not in _PANDOC_FORMAT:
        raise ValueError(f"Format de sortie non supporté : {output_format}")

    # ── PDF input → extract text first ────────────────────────────────────────
    text_to_convert = None
    actual_input    = input_path
    actual_from_fmt = _PANDOC_FORMAT.get(in_ext)

    if in_ext == 'pdf':
        logger.info(f"PDF input → extracting text via PyMuPDF: {input_path}")
        text_to_convert = _extract_pdf_text(input_path)
        actual_from_fmt = 'markdown'

    if actual_from_fmt is None:
        raise ValueError(f"Format d'entrée non supporté : .{in_ext}")

    # ── PDF output → check engine ─────────────────────────────────────────────
    extra_args = []
    if out_ext == 'pdf':
        engine = _detect_pdf_engine()
        if engine is None:
            raise RuntimeError(
                "Aucun moteur PDF trouvé. Installez l'un de : "
                "texlive-xetex, wkhtmltopdf, ou weasyprint."
            )
        if engine in ('xelatex', 'pdflatex', 'lualatex'):
            extra_args = ['--pdf-engine=' + engine]
        else:
            extra_args = ['--pdf-engine=' + engine]
        logger.info(f"PDF output → using engine: {engine}")

    # ── Pandoc invocation via pypandoc ────────────────────────────────────────
    try:
        import pypandoc
    except ImportError as exc:
        raise RuntimeError(
            "pypandoc non installé. Lancez: pip install pypandoc"
        ) from exc

    pandoc_to = _PANDOC_FORMAT[out_ext]

    if text_to_convert is not None:
        # Convert from in-memory string (used for PDF input path)
        pypandoc.convert_text(
            source=text_to_convert,
            to=pandoc_to,
            format=actual_from_fmt,
            outputfile=output_path,
            extra_args=extra_args,
        )
    else:
        pypandoc.convert_file(
            source_file=actual_input,
            to=pandoc_to,
            format=actual_from_fmt,
            outputfile=output_path,
            extra_args=extra_args,
        )

    if not os.path.exists(output_path):
        raise RuntimeError(
            f"Pandoc a terminé sans erreur mais le fichier de sortie "
            f"est introuvable : {output_path}"
        )

    logger.info(f"Document converti : {input_path} → {output_path} [{out_ext.upper()}]")
