"""
docTR backend — Mindee, pipeline OCR CPU-friendly.

Installation : pip install "python-doctr[torch]"

Avantages : pas de GPU requis, bonne précision sur texte imprimé propre,
formulaires, reçus, documents structurés.
"""
import os
import logging
from pathlib import Path
from typing import Callable, Optional

logger = logging.getLogger(__name__)


class DocTRBackend:

    def run(
        self,
        file_path: str,
        mode: str = 'auto',
        language: str = '',
        progress_cb: Optional[Callable[[int, str], None]] = None,
    ) -> str:
        """
        Extract text from a document file using docTR.
        Returns the full extracted text as a string.
        """
        from wama.reader.utils.model_config import DOCTR_DIR

        # Redirect docTR model cache to our managed directory
        os.environ['DOCTR_CACHE_DIR'] = str(DOCTR_DIR)

        if progress_cb:
            progress_cb(10, "Chargement docTR…")

        try:
            from doctr.io import DocumentFile
            from doctr.models import ocr_predictor
        except ImportError:
            raise RuntimeError(
                "docTR n'est pas installé. "
                "Exécutez : pip install \"python-doctr[torch]\""
            )

        path = Path(file_path)
        ext = path.suffix.lower()

        if progress_cb:
            progress_cb(20, "Lecture du document…")

        if ext == '.pdf':
            doc = DocumentFile.from_pdf(str(path))
        else:
            doc = DocumentFile.from_images([self._ensure_min_size(str(path))])

        if progress_cb:
            progress_cb(40, "Initialisation du modèle OCR…")

        # det_arch and reco_arch can be customised; defaults work well
        model = ocr_predictor(pretrained=True)

        if progress_cb:
            progress_cb(55, "Reconnaissance du texte…")

        try:
            result = model(doc)
        except RuntimeError as e:
            if 'Output size is too small' not in str(e):
                raise
            # Thin bbox detected (rule, underline, artifact) → retry with
            # assume_straight_pages=True which skips rotation crops likely to produce
            # degenerate heights.
            logger.warning("[DocTR] Crop trop petit détecté — relance avec assume_straight_pages=True")
            if progress_cb:
                progress_cb(60, "Réessai (bbox trop fin)…")
            model2 = ocr_predictor(pretrained=True, assume_straight_pages=True)
            result = model2(doc)

        if progress_cb:
            progress_cb(85, "Assemblage du texte…")

        text = self._extract_text(result)

        return text

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
