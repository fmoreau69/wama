"""
docTR backend — Mindee, pipeline OCR CPU-friendly.

Installation : pip install "python-doctr[torch]"

Avantages : pas de GPU requis, bonne précision sur texte imprimé propre,
formulaires, reçus, documents structurés.

Poids : DÉCLARÉS ici (`DOCTR_FILES`, versions GitHub de `mindee/doctr` — le serveur de Mindee y
redirige), installés par la route sous `DOCTR_CACHE_DIR/models`, exactement là où la librairie les
cherche : un fichier présent dont l'empreinte commence par le préfixe de son nom se lit sans rien
télécharger (`doctr/utils/data.py`, `download_from_url`). Avant (2026-11-02), `ocr_predictor(
pretrained=True)` les tirait au premier usage, et la ligne du catalogue se disait installée dès
que le paquet s'importait.
"""
import logging
from pathlib import Path
from typing import Callable, Optional

from wama.common.backends.ocr_base import OCRBackend, doctr_folder, doctr_release_file

logger = logging.getLogger(__name__)

#: Les deux réseaux que charge `ocr_predictor(pretrained=True)` (docTR 1.1.0 : détection
#: `fast_base`, reconnaissance `crnn_vgg16_bn`). Tailles MESURÉES le 2026-11-02 sur les fichiers en
#: place = celles des assets GitHub ; empreintes conformes au préfixe du nom (et, pour `crnn`, au
#: condensé que GitHub publie).
DOCTR_FILES = [
    doctr_release_file('v0.8.1', 'fast_base-688a8b34.pt', 65814772,
                       '688a8b3489e9f5d0290c476c6272ec3b18de3ee646c8a0dc158203b1a9c62ace'),
    doctr_release_file('v0.12.0', 'crnn_vgg16_bn-0417f351.pt', 63303144,
                       '0417f3511f5c75369bdcbe06539853b9c2d170aa3baceb2acc454c775ddac087'),
]
DOCTR_KEY = 'reader:doctr'


def doctr_installed() -> bool:
    from wama.model_manager.services.model_installer import declared_files_present
    return declared_files_present(doctr_folder(), DOCTR_FILES)


class DocTRBackend(OCRBackend):
    """OCR docTR — le prédicteur (détection + reconnaissance) chargé par `load()` et gardé.

    ⚠ Jusqu'au 2026-11-07, `load()` ne chargeait RIEN (« sans état ») : le prédicteur se
    reconstruisait à chaque `run()`, et le backend annonçait 2 Go de VRAM au gouverneur pour un
    modèle qui n'était pas en mémoire — et qui tourne sur le PROCESSEUR (docTR laisse ses réseaux
    où il les crée ; la ligne du catalogue le dit, `reader:doctr`, `vram_gb: 0.0`)."""

    #: Moteur piloté (contrat commun) — voir BaseModelBackend.ENGINE.
    ENGINE = 'doctr'
    #: Modèles servis (2026-11-07) : `doctr` est AUSSI le moteur du classifieur d'orientation
    #: (`DocTROrientationBackend`) — un moteur partagé se départage par la liste de chacun.
    #: ⚠ En LITTÉRAL : l'inventaire lit les clés par AST.
    SUPPORTED_MODELS = {
        'doctr': {'model_key': 'reader:doctr'},
    }
    REQUIRED_PACKAGES = ['doctr']
    #: docTR DÉTECTE puis reconnaît : chaque mot a sa boîte (`read_lines`).
    supports_text_positions = True
    #: Le processeur, déclaré : l'enveloppe du gouverneur ne publie rien pour lui.
    device = 'cpu'
    recommended_vram_gb = 0
    description = "docTR — OCR de documents (détection + reconnaissance)."
    _predictor = None

    @classmethod
    def is_available(cls) -> bool:
        try:
            import doctr  # noqa: F401
            return True
        except Exception:
            return False

    def load(self, model: Optional[str] = None) -> bool:
        """Construit le prédicteur une fois (idempotent). Les fichiers DÉCLARÉS, installés par la
        route : absents, on le DIT — la glu du reader demande le modèle de la card à la route
        avant (`ctx.ensure_model`)."""
        if self._predictor is not None:
            return True
        if not doctr_installed():
            raise RuntimeError(
                f"docTR n'est pas installé ({doctr_folder()}) — il s'installe par le model manager "
                f"(ligne « {DOCTR_KEY} »).")
        try:
            from doctr.models import ocr_predictor
        except ImportError:
            raise RuntimeError(
                "La librairie docTR n'est pas installée — par la route library : "
                "python manage.py install_library python-doctr"
            )
        # ⚠ docTR ≥ 1.1 (2026-10-09) : en 0.11, la détection rendait UNE boîte couvrant toute la
        # page (texte vide, ou « Output size is too small » sur une petite page) — mesuré sur une
        # A4 de 12 lignes nettes ; 1.1.0 y trouve 96 boîtes. La relance « assume_straight_pages=True »
        # qui vivait ici refaisait l'appel par défaut depuis la 0.11 : retirée.
        self._predictor = ocr_predictor(pretrained=True)
        return True

    @property
    def is_loaded(self) -> bool:
        return self._predictor is not None

    def unload(self) -> None:
        self._predictor = None

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
        reposait à chaque appel jusqu'au 2026-10-29, à la même valeur) ; ses fichiers, la route."""
        if progress_callback:
            progress_callback(10, "Chargement docTR…")
        # Le prédicteur gardé par `load()` — chargé ici si l'appelant ne l'a pas fait (contrat :
        # `load` est idempotent). Absent du disque, `load` le DIT.
        self.load()
        from doctr.io import DocumentFile

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
            progress_callback(55, "Reconnaissance du texte…")

        return self._predictor(doc), sizes

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
