"""Les PAGES d'un PDF en images — une par page, écrites dans un dossier FOURNI par l'appelant.

Brique commune (2026-11-06) : la même conversion vivait en deux copies privées, dans les moteurs
d'OCR GLM-OCR (`glm_ocr_backend._pdf_to_images`, fichiers sur disque) et olmOCR
(`OlmOCRBackend._pdf_to_images`, images en mémoire) ; la lecture de partition (copisteria) en
demandait une troisième. PyMuPDF d'abord (sans poppler, absent de l'hôte), `pdf2image` en repli.

⚠ `dest_dir` est FOURNI par l'appelant depuis le 2026-08-25, et ce n'est pas cosmétique : la
fonction créait son propre `mkdtemp` et déléguait le nettoyage par un commentaire. Le contrat
FUYAIT dans trois situations muettes — une conversion qui échoue rendait `[]` alors que le dossier
existait déjà, un `pix.save()` qui lève n'était rattrapé par rien, et le repli `pdf2image` écrit
SES propres temporaires à côté des pages. Le dossier appartient au `with` de l'appelant
(`work_dir`), qui le supprime quoi qu'il advienne et sans se soucier de son contenu.
"""
import logging
import os

logger = logging.getLogger(__name__)


def pdf_page_images(pdf_path: str, dest_dir: str, dpi: int = 200, prefix: str = 'page') -> list:
    """Les chemins des images (`<prefix>_0000.png`…, une par page, dans l'ordre) de `pdf_path`,
    rendues à `dpi` dans `dest_dir` — `[]` si aucune conversion n'aboutit (le dire reste à
    l'appelant). La rotation d'une page (`/Rotate`) est appliquée : la page est rendue telle
    qu'elle s'affiche."""
    paths = []
    try:
        try:
            import pymupdf as fitz      # PyMuPDF >= 1.24
        except ImportError:
            import fitz                 # ancien nom
        zoom = dpi / 72.0
        with fitz.open(pdf_path) as doc:
            for i, page in enumerate(doc):
                pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
                path = os.path.join(dest_dir, f"{prefix}_{i:04d}.png")
                pix.save(path)
                paths.append(path)
        return paths
    except Exception as e:
        # ⚠ C'était `except ImportError` — le repli ne servait alors QUE si PyMuPDF était absent,
        # jamais s'il ÉCHOUAIT (PDF corrompu, protégé…). Trouvé le 2026-08-25 par un test.
        logger.warning("[pdf_pages] PyMuPDF indisponible ou en échec (%s) — repli pdf2image.", e)
        paths = []
    try:
        from pdf2image import convert_from_path
        images = convert_from_path(pdf_path, dpi=dpi, fmt='PNG', output_folder=dest_dir)
        for i, image in enumerate(images):
            path = os.path.join(dest_dir, f"{prefix}_{i:04d}.png")
            image.save(path, 'PNG')
            paths.append(path)
        return paths
    except Exception as e:
        logger.error("[pdf_pages] conversion PDF → images impossible : %s", e)
        return []
