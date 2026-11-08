"""
Backend copisteria — une page de partition imprimée (image ou PDF) → son MusicXML (tâche
`image-to-score`).

copisteria (KobiMusic, 2026, Apache-2.0 code et poids) : un détecteur de symboles (« v7 »,
copista-28m) lit la page, un petit modèle d'ÉVIDENCE (2 M de paramètres) corrige chaque lecture
par son contexte, un écrivain rend le MusicXML. Retenu à la veille du 2026-11-06
(`PROSPECTION_PIPELINE`) : le meilleur au banc publié par son auteur, homr ensuite pour départager.
Ce qu'il ne fait pas, dit par son auteur : les paroles, les triolets non marqués, le manuscrit.

Ce que ce backend décide, et pourquoi :
  • le CODE n'est pas sur PyPI : il est VENDORISÉ (route `library`, voie vendor,
    `manifests/libraries/copisteria.json`, dépôt épinglé au commit), importé par le geste commun
    `import_vendored` (disposition `src/`) ;
  • il ne TÉLÉCHARGE RIEN : les poids sont DÉCLARÉS ici (`COPISTERIA_FILES`, Hub à un commit),
    installés par le pilote `files` du model manager — comme MuScriptor. La librairie les cherche
    dans le dossier `models/` de son dépôt (`copisteria.paths`) : le modèle d'évidence se passe
    par son CHEMIN (`read.load_model`), le détecteur par la table que lit `paths.detector()` — un
    attribut du module, jamais une variable d'environnement du processus ;
  • un PDF se rend en pages par la brique commune (`pdf_pages`, PyMuPDF) : la librairie appelle
    poppler (`pdfimages`, `pdftoppm`), absent de l'hôte ;
  • la librairie écrit ses caches À CÔTÉ de la page (`<page>.dets_*.json`, `.feat_*.npz`) : chaque
    page est d'abord copiée dans un dossier de TRAVAIL (`work_dir`), jamais lue là où l'utilisateur
    l'a rangée ;
  • les pages lues deviennent UNE partition par la brique commune (`musicxml_score.merge_pages`) ;
  • le TEXTE de la page (2026-11-08) : la librairie lit titre, compositeur et mots dans des boîtes
    de texte à RÔLE (`<page>.texts.json`, que son auteur produit par un OCR à lui) ; WAMA les lui
    passe en mémoire (`transcribe(texts=…)`), tirées de `page_texts` (rôles de
    `score_page.text_roles`) par `_texts` — un nombre de passages (« x3 ») y entre comme des MOTS,
    seule forme que la librairie place sur une mesure (`musicxml_score.repeat_words`).
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable, Optional

from .score_reading_base import ScoreReadingBackend

logger = logging.getLogger(__name__)

HF_REPO = "kobimusic/copisteria"
MODEL_KEY = f"huggingface:{HF_REPO}"

# Clé LITTÉRALE : l'inventaire la lit par AST. Nom, description et VRAM sont au REGISTRE.
SUPPORTED_MODELS = {
    "kobimusic/copisteria": {"model_key": "huggingface:kobimusic/copisteria"},
}

#: Le commit du dépôt du Hub dont les poids sont tirés (révision FIGÉE, pilote `files`).
HF_REVISION = "faad5609fa8f59e65c379158a20de23b215205f8"
EVIDENCE = 'evidence-2m.pt'
DETECTOR = 'small/v7_obj-recall-30m_best.pt'

#: Les fichiers que ce code lit, DÉCLARÉS (forme du pilote `files`) : rangés comme dans le dossier
#: `models/` du dépôt de la librairie ; taille et empreinte relevées le 2026-11-06 sur l'API du Hub
#: au commit `HF_REVISION` (`lfs.oid`). Le détecteur copista-2m (`v7_obj-recall_best.pt`) n'est
#: pas lu : il n'est pas déclaré.
COPISTERIA_FILES = [
    {'path': EVIDENCE, 'size': 8145299,
     'sha256': '7a3eb0362b44016e941680c5df1e133239576592ab134057c3dbac8e9f3b8838',
     'origin': {'source': 'huggingface', 'repo': HF_REPO, 'revision': HF_REVISION,
                'file': 'evidence-2m.pt'}},
    {'path': DETECTOR, 'size': 115352175,
     'sha256': '9f1db282271fb1064461387da4a2e15de14b099c49b619c21429cdc45be85cfe',
     'origin': {'source': 'huggingface', 'repo': HF_REPO, 'revision': HF_REVISION,
                'file': 'v7_obj-recall-30m_best.pt'}},
]

#: La résolution d'une page de PDF rendue en image : ce que portent les scans (la librairie rend
#: aussi ses pages sans image à 300 ppi, `vision.page.scan.RENDER_PPI`).
PDF_DPI = 300

#: Le rôle d'une ligne de texte (`score_page.TEXT_ROLES`) → celui que la librairie lit
#: (`docs/ARCHITECTURE.md` §Text, `write.NOT_NAMES`).
TEXT_ROLE_NAMES = {'title': 'pgHead_title', 'composer': 'pgHead_composer',
                   'subtitle': 'pgHead_subtitle', 'page_number': 'pgFoot', 'footer': 'pgFoot',
                   'repeat_count': 'words', 'words': 'words'}


def _texts(page: Optional[dict], image_size) -> Optional[list]:
    """Les boîtes de texte d'une page dans la forme de la librairie (`{'text', 'xyxy', 'role'}`, en
    pixels de l'image LUE) — tirées d'une page de `page_texts`, dont les coordonnées sont dans SON
    unité (points d'un PDF, pixels d'une image) ; None sans page."""
    if not page or not page.get('lines'):
        return None
    from wama.common.backends.ocr_base import page_scale
    from wama.common.utils.musicxml_score import repeat_words
    sx, sy = page_scale(page, *image_size)
    out = []
    for line in page['lines']:
        role = TEXT_ROLE_NAMES.get(line.get('role'))
        if not role:
            continue
        x0, y0, x1, y1 = line['bbox']
        text = repeat_words(line['times']) if line.get('role') == 'repeat_count' else line['text']
        out.append({'text': text, 'xyxy': [x0 * sx, y0 * sy, x1 * sx, y1 * sy], 'role': role})
    return out or None


def model_folder() -> Path:
    """Le dossier du modèle (`settings.MODEL_PATHS['music']['copisteria']`), où le pilote `files`
    pose les fichiers déclarés."""
    from django.conf import settings
    return Path(settings.MODEL_PATHS['music']['copisteria'])


def installed_file(relative: str) -> Path:
    """Un fichier déclaré, présent — sinon une erreur qui dit d'installer par le catalogue (ce
    backend ne télécharge rien)."""
    path = model_folder() / relative
    if not path.exists():
        raise RuntimeError(f"copisteria : {path} absent — installer « copisteria » depuis le model "
                           f"manager (`pull_model {MODEL_KEY}`)")
    return path


class CopisteriaBackend(ScoreReadingBackend):
    """copisteria : une page de partition imprimée → son MusicXML."""

    ENGINE = "copisteria"
    VENDORED = True
    name = "copisteria"
    display_name = "copisteria"
    # Pic MESURÉ le 2026-11-07 (RTX 4090) : 0,3 Go sur une gamme, 0,68 Go sur une page dense de six
    # systèmes — détecteur 28,7 M et évidence 2 M de paramètres, lus en bf16 sur CUDA.
    recommended_vram_gb = 1.0
    description = "Partition imprimée (image, PDF) → MusicXML (copisteria, copista-28m)."
    # Ce que le code vendorisé importe (`pyproject.toml` du dépôt) — tout est déjà au venv.
    REQUIRED_PACKAGES = ["torch", "torchvision", "numpy", "scipy", "cv2", "PIL"]
    # Rien à installer par pip : le code vient de la route vendorisée, ses dépendances sont au venv.
    PIP_PACKAGES: list = []

    def __init__(self):
        super().__init__()
        self._model = None
        self._device = 'cpu'

    @classmethod
    def _library(cls):
        """Les modules de la librairie, le détecteur pointé sur le fichier DÉCLARÉ."""
        paths = cls.import_vendored('copisteria.paths', subdir='src')
        detector = installed_file(DETECTOR)
        # La table que lit `paths.detector()` (le défaut « 28m ») : le dossier du modèle, pas le
        # dossier `models/` du dépôt. Même étiquette de cache que la librairie (« v7 »).
        paths.DETECTORS = {**paths.DETECTORS, '28m': (detector, 'v7')}
        paths.DETECTOR = detector
        return (cls.import_vendored('copisteria.pipeline', subdir='src'),
                cls.import_vendored('copisteria.read', subdir='src'))

    def load(self, model: Optional[str] = None) -> bool:
        if self._model is not None:
            return True
        import torch
        _pipeline, read = self._library()
        self._device = "cuda" if torch.cuda.is_available() else "cpu"
        self._model = read.load_model(str(installed_file(EVIDENCE)), self._device)
        self._loaded = True
        self._current_model = HF_REPO
        logger.info("[copisteria] chargé (%s, %s)", HF_REVISION[:12], self._device)
        return True

    def unload(self) -> None:
        if self._model is None:
            return
        self._model = None
        self._loaded = False
        self._current_model = None
        try:
            # Le détecteur que la librairie garde d'une page à l'autre (`pipeline._DET`).
            pipeline, _read = self._library()
            pipeline._DET.clear()
        except Exception:
            pass
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:
            pass
        logger.info("[copisteria] déchargé")

    @staticmethod
    def _pages(work_file: str, folder: Path) -> list:
        """Les pages à lire, en PNG dans le dossier de travail — un PDF rendu page par page."""
        from PIL import Image
        source = Path(work_file)
        if source.suffix.lower() == '.pdf':
            from wama.common.utils.pdf_pages import pdf_page_images
            pages = pdf_page_images(str(source), str(folder), dpi=PDF_DPI)
            if not pages:
                raise ValueError(f"PDF illisible : aucune page convertie en image ({source.name})")
            return [Path(p) for p in pages]
        # Ce que le Reader lit — un PDF ou une image de page (`app_registry.OCR_INPUT_EXTENSIONS`).
        from wama.common.app_registry import OCR_INPUT_EXTENSIONS
        if source.suffix.lower() not in OCR_INPUT_EXTENSIONS:
            raise ValueError(f"« {source.suffix} » : une partition se lit d'une image ou d'un PDF")
        page = folder / 'page_0000.png'
        with Image.open(source) as image:
            image.convert('L').save(page)
        return [page]

    def read_score(
        self,
        model_id: str,
        work_file: str,
        output_dir: Optional[str] = None,
        progress_callback: Optional[Callable[[int], None]] = None,
        page_texts: Optional[list] = None,
    ) -> str:
        if self._model is None:
            self.load()
        from PIL import Image
        from wama.common.utils.musicxml_score import merge_pages, note_count
        from wama.common.utils.work_dir import work_dir
        pipeline, _read = self._library()
        if progress_callback:
            progress_callback(0)
        with work_dir('copisteria') as folder:
            pages = self._pages(work_file, folder)
            if progress_callback:
                progress_callback(5)
            read = []
            for index, page in enumerate(pages):
                texts = None
                if page_texts and index < len(page_texts):
                    with Image.open(page) as image:
                        texts = _texts(page_texts[index], image.size)
                read.append(pipeline.transcribe(page, self._model, texts=texts, device=self._device))
                if progress_callback:
                    progress_callback(5 + int(90 * (index + 1) / len(pages)))
        score = merge_pages(read)
        if not note_count(score):
            raise ValueError("Aucune note lue : la page ne porte pas de portée lisible "
                             "(une partition IMPRIMÉE est attendue — le manuscrit n'est pas lu)")
        if progress_callback:
            progress_callback(100)
        return score
