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
    'fb2':      'fb2',
    'tex':      'latex',
    'latex':    'latex',
    'pdf':      'pdf',
}

# Formats only Calibre's `ebook-convert` can produce/read (not Pandoc).
_CALIBRE_FORMATS = {'mobi', 'azw3', 'azw'}


def _calibre_convert(input_path: str, output_path: str) -> None:
    """Convert via Calibre's `ebook-convert` CLI (handles epub/mobi/azw3/pdf/…).

    Used when either side is a Calibre-only format (mobi/azw3/azw).
    """
    exe = shutil.which('ebook-convert')
    if not exe:
        raise RuntimeError(
            "Conversion mobi/azw3 : Calibre requis (binaire 'ebook-convert' "
            "introuvable). Installez Calibre."
        )
    proc = subprocess.run([exe, input_path, output_path],
                          capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"ebook-convert a échoué : {proc.stderr[-400:]}")


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


def _pdf_to_docx(input_path: str, output_path: str) -> None:
    """PDF → DOCX en préservant la mise en page (texte, images, tableaux).

    Utilise pdf2docx (reconstruit la disposition page par page). Fallback en
    erreur explicite si la lib n'est pas installée (la route texte pandoc
    perdrait tout le formatage, on préfère un message clair).
    """
    try:
        from pdf2docx import Converter
    except ImportError as exc:
        raise RuntimeError(
            "pdf2docx requis pour convertir PDF → DOCX en préservant la mise en "
            "forme et les images. Installez-le : pip install pdf2docx"
        ) from exc

    cv = Converter(input_path)
    try:
        cv.convert(output_path, start=0, end=None)
    finally:
        cv.close()


def _html_to_pdf_weasyprint(input_path: str, output_path: str) -> bool:
    """HTML → PDF via WeasyPrint (moteur CSS complet, SVG inline natif).

    Rend la page fidèlement (couleurs, mise en page, <svg> inline) sans dépendre
    de LaTeX ni de `rsvg-convert`. La route pandoc→xelatex, elle, jette tout le
    CSS et exige rsvg-convert pour rasteriser les <svg> inline (cause de l'échec
    « rsvg-convert does not exist »).

    Retourne False si WeasyPrint n'est pas installé — l'appelant retombe alors
    proprement sur la route pandoc (aucune régression si la lib est absente).
    """
    try:
        from weasyprint import HTML
    except ImportError:
        return False
    # base_url = dossier source → résout les chemins relatifs (CSS/images locaux)
    HTML(filename=input_path, base_url=os.path.dirname(input_path)).write_pdf(output_path)
    if not os.path.exists(output_path):
        raise RuntimeError(f"WeasyPrint n'a produit aucun fichier : {output_path}")
    return True


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

    # ── PDF → DOCX : conversion fidèle (images, tableaux, mise en forme) ──────
    # Pandoc ne lit pas le PDF : la route texte (PyMuPDF→markdown) perd tout le
    # formatage. pdf2docx reconstruit la mise en page (texte, images, tableaux).
    if in_ext == 'pdf' and out_ext == 'docx':
        _pdf_to_docx(input_path, output_path)
        if not os.path.exists(output_path):
            raise RuntimeError(f"Fichier de sortie introuvable : {output_path}")
        logger.info(f"PDF → DOCX (pdf2docx, mise en forme préservée) : {input_path} → {output_path}")
        return

    # ── HTML → PDF : rendu fidèle du CSS + SVG inline via WeasyPrint ──────────
    # Une page HTML stylée (présentation, fiche…) passée à pandoc→xelatex perd
    # tout son CSS et casse sur les <svg> inline (rsvg-convert requis, absent).
    # WeasyPrint est un vrai moteur CSS (pango/cairo) : il rend la page telle
    # quelle, SVG inline compris. Fallback pandoc si WeasyPrint indisponible.
    if in_ext in ('html', 'htm') and out_ext == 'pdf':
        if _html_to_pdf_weasyprint(input_path, output_path):
            logger.info(f"HTML → PDF (WeasyPrint, CSS+SVG fidèles) : {input_path} → {output_path}")
            return
        logger.warning("WeasyPrint indisponible → fallback pandoc/LaTeX pour HTML→PDF")

    # Calibre route : any mobi/azw3/azw side goes through ebook-convert, which
    # handles the full chain (epub↔mobi↔azw3↔pdf↔docx…) on its own.
    if in_ext in _CALIBRE_FORMATS or out_ext in _CALIBRE_FORMATS:
        _calibre_convert(input_path, output_path)
        if not os.path.exists(output_path):
            raise RuntimeError(f"Fichier de sortie introuvable : {output_path}")
        logger.info(f"Ebook converti (Calibre) : {input_path} → {output_path} [{out_ext}]")
        return

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
