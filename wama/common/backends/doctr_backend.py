"""
docTR backend — Mindee, pipeline OCR CPU-friendly.

Installation : pip install "python-doctr[torch]"

Avantages : pas de GPU requis, bonne précision sur texte imprimé propre,
formulaires, reçus, documents structurés.
"""
import logging
from pathlib import Path
from typing import Callable, Optional

from wama.common.backends.ocr_base import OCRBackend

logger = logging.getLogger(__name__)


class DocTRBackend(OCRBackend):
    """OCR docTR — SANS état persistant (le prédicteur se charge par appel dans run())."""

    #: Moteur piloté (contrat commun) — voir BaseModelBackend.ENGINE.
    ENGINE = 'doctr'
    REQUIRED_PACKAGES = ['doctr']
    #: docTR DÉTECTE puis reconnaît : chaque mot a sa boîte (`read_lines`).
    supports_text_positions = True
    recommended_vram_gb = 2.0
    description = "docTR — OCR de documents (détection + reconnaissance)."
    _warm = False

    @classmethod
    def is_available(cls) -> bool:
        try:
            import doctr  # noqa: F401
            return True
        except Exception:
            return False

    def load(self, model: Optional[str] = None) -> bool:
        # Sans état : on marque seulement « prêt » (le modèle se charge par appel).
        self._warm = True
        return True

    @property
    def is_loaded(self) -> bool:
        return self._warm

    def unload(self) -> None:
        self._warm = False

    # `process()` → `run()` : celui du contrat OCR (`ocr_base.OCRBackend`, 2026-10-07).

    def run(
        self,
        work_file: str,
        mode: str = 'auto',
        language: str = '',
        progress_callback: Optional[Callable[[int, str], None]] = None,
        on_partial: Optional[Callable[[str], None]] = None,
    ) -> str:
        """
        Extract text from a document file using docTR.
        Returns the full extracted text as a string.

        on_partial : docTR infère le document EN UN appel (pas de boucle par page) — le
        callback n'est émis qu'UNE fois, après assemblage : l'aperçu « pendant » montre le
        texte brut pendant la mise en forme LLM (l'étape longue vit dans la TÂCHE, à 98 %).
        """
        result, _ = self._predict(work_file, progress_callback)

        if progress_callback:
            progress_callback(85, "Assemblage du texte…")

        text = self._extract_text(result)
        if on_partial:
            try:
                on_partial(text)
            except Exception:
                pass

        return text

    def read_lines(
        self,
        work_file: str,
        language: str = '',
        progress_callback: Optional[Callable[[int, str], None]] = None,
    ) -> list:
        """Les pages avec la boîte de chaque ligne et de chaque mot (contrat :
        `OCRBackend.read_lines`). docTR les calcule de toute façon ; `run` les jette à l'assemblage
        du texte."""
        result, sizes = self._predict(work_file, progress_callback)
        if progress_callback:
            progress_callback(85, "Assemblage des lignes…")
        return self._positioned(result, sizes)

    def _predict(self, work_file: str, progress_callback=None):
        """La prédiction de docTR sur le document, et la taille de chaque page dans SON unité —
        points pour un PDF (lue par PyMuPDF, celle de `document_text`), pixels de l'image d'origine
        sinon (avant l'agrandissement d'une image trop fine : la géométrie de docTR est RELATIVE).
        Le cache des poids est `DOCTR_CACHE_DIR`, posé une fois dans `settings.py` (le backend le
        reposait à chaque appel jusqu'au 2026-10-29, à la même valeur)."""
        if progress_callback:
            progress_callback(10, "Chargement docTR…")

        try:
            from doctr.io import DocumentFile
            from doctr.models import ocr_predictor
        except ImportError:
            raise RuntimeError(
                "docTR n'est pas installé. "
                "Exécutez : pip install \"python-doctr[torch]\""
            )

        path = Path(work_file)
        ext = path.suffix.lower()

        if progress_callback:
            progress_callback(20, "Lecture du document…")

        if ext == '.pdf':
            doc = DocumentFile.from_pdf(str(path))
            import pymupdf
            with pymupdf.open(str(path)) as pdf:
                sizes = [(page.rect.width, page.rect.height, 'pt') for page in pdf]
        else:
            from PIL import Image
            with Image.open(str(path)) as image:
                sizes = [(image.width, image.height, 'px')]
            doc = DocumentFile.from_images([self._ensure_min_size(str(path))])

        if progress_callback:
            progress_callback(40, "Initialisation du modèle OCR…")

        # det_arch and reco_arch can be customised; defaults work well.
        # ⚠ docTR ≥ 1.1 (2026-10-09) : en 0.11, la détection rendait UNE boîte couvrant toute la
        # page (texte vide, ou « Output size is too small » sur une petite page) — mesuré sur une
        # A4 de 12 lignes nettes ; 1.1.0 y trouve 96 boîtes. La relance « assume_straight_pages=True »
        # qui vivait ici refaisait l'appel par défaut depuis la 0.11 : retirée.
        model = ocr_predictor(pretrained=True)

        if progress_callback:
            progress_callback(55, "Reconnaissance du texte…")

        return model(doc), sizes

    @staticmethod
    def _box(geometry, width: float, height: float) -> list:
        """La boîte `[x0, y0, x1, y1]` d'une géométrie RELATIVE de docTR, dans l'unité de la page :
        deux coins en page droite (le défaut, `assume_straight_pages`), un polygone sinon."""
        xs = [float(point[0]) for point in geometry]
        ys = [float(point[1]) for point in geometry]
        return [round(min(xs) * width, 2), round(min(ys) * height, 2),
                round(max(xs) * width, 2), round(max(ys) * height, 2)]

    @classmethod
    def _positioned(cls, result, sizes) -> list:
        """La prédiction de docTR dans la forme du contrat (`OCRBackend.read_lines`)."""
        pages = []
        for page, (width, height, unit) in zip(result.pages, sizes):
            lines = []
            for line in (line for block in page.blocks for line in block.lines):
                words = [{'bbox': cls._box(w.geometry, width, height), 'text': w.value,
                          'conf': round(float(w.confidence), 3)} for w in line.words]
                if not words:
                    continue
                lines.append({'bbox': cls._box(line.geometry, width, height),
                              'text': ' '.join(w['text'] for w in words),
                              'conf': round(sum(w['conf'] for w in words) / len(words), 3),
                              'words': words})
            pages.append({'width': width, 'height': height, 'unit': unit, 'lines': lines})
        return pages

    @staticmethod
    def _ensure_min_size(image_path: str, min_dim: int = 300) -> str:
        """
        Upscale an image if its smallest dimension is below min_dim pixels.
        Thin images cause docTR's CRNN VGG16 to crash with 'Output size is too small'
        when detected bboxes are downsampled below 1px height.
        Returns the original path if no upscaling needed, or a temp file path.
        """
        try:
            from PIL import Image as PILImage
            import tempfile
            img = PILImage.open(image_path)
            w, h = img.size
            if min(w, h) >= min_dim:
                return image_path
            scale = min_dim / min(w, h)
            img = img.resize((int(w * scale), int(h * scale)), PILImage.LANCZOS)
            suffix = Path(image_path).suffix or '.png'
            tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
            img.save(tmp.name)
            logger.info("[DocTR] Image upscalée (%dx%d → %dx%d) pour éviter les crops trop fins",
                        w, h, int(w * scale), int(h * scale))
            return tmp.name
        except Exception:
            return image_path  # fallback : passer l'original sans upscale

    @staticmethod
    def _extract_text(result) -> str:
        """Convert docTR result object to plain text string."""
        lines = []
        for page in result.pages:
            for block in page.blocks:
                block_lines = []
                for line in block.lines:
                    words = ' '.join(w.value for w in line.words)
                    block_lines.append(words)
                lines.append('\n'.join(block_lines))
            lines.append('')  # blank line between pages
        return '\n'.join(lines).strip()
