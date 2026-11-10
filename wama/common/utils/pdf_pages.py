"""Les PAGES d'un PDF en images — une par page, écrites dans un dossier FOURNI par l'appelant ;
et l'inverse, des pages (images, PDF) en UN PDF (`pages_to_pdf`, 2026-11-10).

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


#: La résolution d'une image posée en page de PDF : celle du converter pour une image → PDF
#: (`converter/backends/image_backend._build_save_kwargs`, option `pdf_dpi`), la même règle.
PAGE_DPI = 150
#: Les formats d'image posés TELS QUELS dans une page (PyMuPDF les lit) ; les autres sont
#: réencodés en JPEG.
_AS_IS = ('JPEG', 'PNG')


def pages_to_pdf(paths, output_path: str, dpi: int = PAGE_DPI) -> str:
    """UN PDF fait de `paths`, dans l'ordre (2026-11-10, décision de Fabien : « fusionner tous
    les éléments du lot en un seul fichier pdf ») — une IMAGE devient une page à sa taille lue à
    `dpi` (une photo de 1848 px à 150 ppp : 12,3 pouces), un PDF apporte toutes ses pages. Écrit
    `output_path` et le rend ; lève `ValueError` sur un fichier qui n'est ni l'un ni l'autre, ou
    sans aucune page. L'EXIF d'orientation d'une photo est appliqué : la page est la photo telle
    qu'elle s'affiche.

    Le pendant de `pdf_page_images`, et la conversion image → PDF du converter passée d'un
    fichier à N (§6.4 : reformater est le métier du converter) ; PyMuPDF, déjà au venv."""
    import io
    from pathlib import Path

    try:
        import pymupdf as fitz
    except ImportError:
        import fitz
    from PIL import Image, ImageOps

    from wama.common.app_registry import category_of_path
    out = fitz.open()
    for path in paths:
        path = Path(path)
        if path.suffix.lower() == '.pdf':
            with fitz.open(str(path)) as source:
                out.insert_pdf(source)
            continue
        if category_of_path(path) != 'image':
            raise ValueError(f"{path.name} : ni une image ni un PDF, pas une page")
        with Image.open(path) as image:
            turned = (image.getexif().get(0x0112) or 1) != 1          # 0x0112 = Orientation
            if not turned and image.format in _AS_IS:
                # Les octets d'origine : une photo JPEG n'est pas réencodée (ni perte, ni poids).
                data, (width, height) = path.read_bytes(), image.size
            else:
                upright = ImageOps.exif_transpose(image)
                upright = upright.convert('RGB') if upright.mode not in ('RGB', 'L') else upright
                buffer = io.BytesIO()
                upright.save(buffer, 'JPEG', quality=95)
                data, (width, height) = buffer.getvalue(), upright.size
        page = out.new_page(width=width * 72.0 / dpi, height=height * 72.0 / dpi)
        page.insert_image(page.rect, stream=data)
    if not out.page_count:
        raise ValueError('aucune page à assembler')
    out.save(str(output_path), garbage=3, deflate=True)
    out.close()
    return str(output_path)
