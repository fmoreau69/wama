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
            doc = DocumentFile.from_images([str(path)])

        if progress_cb:
            progress_cb(40, "Initialisation du modèle OCR…")

        # det_arch and reco_arch can be customised; defaults work well
        model = ocr_predictor(pretrained=True)

        if progress_cb:
            progress_cb(55, "Reconnaissance du texte…")

        result = model(doc)

        if progress_cb:
            progress_cb(85, "Assemblage du texte…")

        text = self._extract_text(result)

        return text

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
