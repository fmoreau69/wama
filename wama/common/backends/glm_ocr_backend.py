"""
GLM-OCR backend — ZhipuAI GLM-OCR 0.9B via Ollama.

GLM-OCR is a 0.9B vision-language model specialized for OCR tasks.
It ranked #1 on OmniDocBench V1.5 (score 94.62) while being dramatically
smaller than olmOCR-7B (~2.2 GB vs ~14 GB).

Requirements:
    ollama pull glm-ocr    (or glm-ocr:0.9b)

No local model files or VRAM management required — Ollama handles everything.
"""

import base64
import logging
import tempfile
from pathlib import Path
from typing import Callable, Optional

from wama.common.backends.ocr_base import OCRBackend

logger = logging.getLogger(__name__)

# Ollama model name (first matching name wins)
# `glm-ocr:0.9b` a disparu du registre Ollama (2026-09-02) : `latest` (bf16, 2,2 Go) et
# `q8_0` (1,6 Go) sont les tags vivants ; le préfixe nu attrape n'importe lequel des deux.
_MODEL_NAMES = ['glm-ocr:latest', 'glm-ocr:q8_0', 'glm-ocr']


def _get_ollama_host() -> str:
    # Brique commune : porte la réécriture WSL2 → passerelle Windows, que la lecture brute du
    # réglage n'a jamais faite (Ollama tourne sur l'hôte ; `127.0.0.1` y désigne la VM Linux).
    from wama.common.utils.ollama_host import ollama_base
    return ollama_base()


def _find_glm_ocr_model() -> Optional[str]:
    """Return the exact Ollama model tag for glm-ocr, or None if not pulled."""
    try:
        import httpx
        host = _get_ollama_host()
        # 3 s, comme les autres sondes d'Ollama : c'est désormais l'exécutabilité que le sélecteur
        # lit (mémorisée une minute) — un démon éteint ne doit pas figer une liste d'options.
        with httpx.Client(timeout=3.0, trust_env=False) as client:
            resp = client.get(f"{host}/api/tags")
        if resp.status_code == 200:
            available = {m['name'] for m in resp.json().get('models', [])}
            for name in _MODEL_NAMES:
                if name in available:
                    return name
                # Also accept prefix match (e.g. 'glm-ocr' matches 'glm-ocr:latest')
                for avail in available:
                    if avail == name or avail.startswith(name + ':'):
                        return avail
    except Exception as e:
        logger.debug(f"[GlmOcr] Ollama unavailable: {e}")
    return None


def ollama_serves_glm_ocr() -> bool:
    """Ollama répond-il, et sert-il un tag `glm-ocr` ? (téléchargé ≠ joignable : serveur éteint)"""
    return _find_glm_ocr_model() is not None


def _image_to_b64(image_path: str) -> str:
    """Read an image file and return its base64-encoded content."""
    with open(image_path, 'rb') as fh:
        return base64.b64encode(fh.read()).decode('utf-8')


def _pdf_to_images(pdf_path: str, dpi: int = 200, dest_dir: str = None) -> list[str]:
    """Convertit un PDF en images (une par page) écrites dans `dest_dir`.

    PyMuPDF d'abord, `pdf2image` en repli.

    ⚠ `dest_dir` est FOURNI PAR L'APPELANT depuis le 2026-08-25, et ce n'est pas cosmétique.
    Cette fonction créait son propre `mkdtemp` et déléguait le nettoyage par un commentaire
    (« caller must delete them ») — l'appelant l'honorait, mais le contrat FUYAIT dans trois
    situations, toutes muettes :

      1. échec de conversion → on rendait `[]` alors que le dossier existait déjà (et que
         `convert_from_path` avait pu y écrire) : la boucle de nettoyage de l'appelant, qui
         itère sur la liste RENDUE, n'avait plus rien à parcourir ;
      2. `pix.save()` qui lève en cours de route → rien ne rattrapait, il n'y avait pas de
         `finally` ici ;
      3. repli `pdf2image` : `convert_from_path(output_folder=…)` écrit SES propres
         temporaires en plus des `page_XXXX.png`. L'appelant ne supprimant que ceux qu'il a
         reçus, le dossier n'était jamais vide — et son `rmdir` conditionné à « si vide » ne
         se produisait donc JAMAIS, y compris quand tout s'était bien passé.

    Rendre la propriété explicite règle les trois d'un coup : le dossier appartient au `with`
    de l'appelant, qui le supprime quoi qu'il advienne et sans se soucier de son contenu.
    """
    import os
    tmp_dir = dest_dir or tempfile.mkdtemp(prefix='glmocr_')
    image_paths = []

    try:
        # PyMuPDF (fastest, no poppler dependency)
        try:
            import pymupdf as fitz
        except ImportError:
            import fitz
        doc = fitz.open(pdf_path)
        zoom = dpi / 72.0
        mat = fitz.Matrix(zoom, zoom)
        for i, page in enumerate(doc):
            pix = page.get_pixmap(matrix=mat, alpha=False)
            img_path = os.path.join(tmp_dir, f"page_{i:04d}.png")
            pix.save(img_path)
            image_paths.append(img_path)
        doc.close()
        return image_paths
    except Exception as e:
        # ⚠ C'était `except ImportError` — donc le repli ne servait QUE si PyMuPDF était
        # absent, jamais s'il ÉCHOUAIT. Un PDF corrompu, protégé par mot de passe ou
        # simplement introuvable faisait remonter l'exception au lieu de basculer sur
        # `pdf2image` : la voie de secours existait sans jamais pouvoir se déclencher.
        # Trouvé le 2026-08-25 par un test, pas à la lecture.
        logger.warning(f"[GlmOcr] PyMuPDF indisponible ou en échec ({e}) — repli pdf2image.")
        image_paths = []

    try:
        from pdf2image import convert_from_path
        images = convert_from_path(pdf_path, dpi=dpi, fmt='PNG', output_folder=tmp_dir)
        for i, img in enumerate(images):
            img_path = os.path.join(tmp_dir, f"page_{i:04d}.png")
            img.save(img_path, 'PNG')
            image_paths.append(img_path)
        return image_paths
    except Exception as e:
        logger.error(f"[GlmOcr] PDF→image conversion failed: {e}")
        return []


def _ocr_image(model: str, image_path: str, language_hint: str = '') -> str:
    """Le texte d'UNE image, par le modèle Ollama `model` — appel par le client COMMUN
    (`llm_utils.llm_chat`, fournisseur `ollama`), qui porte l'adresse de l'hôte et le proxy.
    Jusqu'au 2026-10-07 ce module tenait son propre client HTTP vers `/api/chat`."""
    from wama.common.utils.llm_utils import llm_chat

    lang_note = f" The document language is {language_hint}." if language_hint else ""
    prompt = (
        "You are an expert OCR system. Extract ALL text from this image exactly as it appears, "
        "preserving the layout, paragraphs, lists, and tables."
        f"{lang_note} "
        "Output only the extracted text, nothing else."
    )
    text, error = llm_chat([{'role': 'user', 'content': prompt,
                             'images': [_image_to_b64(image_path)]}],
                           model=model, provider='ollama', num_predict=4096, think=False,
                           timeout=180.0, temperature=0.0)
    if error:
        logger.warning(f"[GlmOcr] {error}")
    return (text or '').strip()


class GlmOcrBackend(OCRBackend):
    """
    OCR par GLM-OCR 0.9B, servi par OLLAMA — au contrat OCR depuis le 2026-10-07.

    Le patron d'`AlbertTranscriptionBackend` : un modèle hors processus qui fait une TÂCHE a un
    backend au contrat de cette tâche, dont le moteur est la source qui le sert (`ollama`).
    La résolution le lie aux modèles OCR d'Ollama (contrat LIANT) et à eux seuls — le chat
    d'Ollama n'a pas de contrat, Ollama est déclaré multi-tâches au registre des sources.
    Le modèle se REÇOIT (`catalogue_key`, posée par la porte commune), il ne se devine plus.

    Works on both images and PDFs (converts PDF pages to images first).
    Much lighter than olmOCR-7B: ~2.2 GB RAM/VRAM managed by Ollama.
    """

    #: Moteur piloté : la SOURCE qui sert le modèle, comme le déclare sa ligne de catalogue.
    ENGINE = 'ollama'
    name = 'glm_ocr'
    description = "GLM-OCR — OCR de documents, servi par Ollama."
    REQUIRED_PACKAGES = ['httpx']
    #: La mémoire est tenue par Ollama, hors du processus : rien à réserver ici.
    recommended_vram_gb = 0

    def __init__(self):
        self._ready = False

    @classmethod
    def is_available(cls) -> bool:
        """Exécutable = Ollama répond ET sert GLM-OCR. C'est ce que le sélecteur commun lit
        (`backend_missing`, verdict mémorisé une minute) : un Ollama éteint écarte GLM-OCR du
        tirage « auto » de TOUTE app — la sonde que le reader tenait seul jusqu'au 2026-10-07."""
        return ollama_serves_glm_ocr()

    def load(self, model: Optional[str] = None) -> bool:
        """Rien à charger ici : Ollama tient le modèle."""
        self._ready = True
        return True

    @property
    def is_loaded(self) -> bool:
        return self._ready

    def unload(self) -> None:
        self._ready = False

    def _model_tag(self) -> str:
        """Le tag Ollama du modèle désigné (`ollama:glm-ocr:latest` → `glm-ocr:latest`)."""
        from wama.common.utils.model_keys import model_id
        tag = model_id(self.catalogue_key) if self.catalogue_key else ''
        if not tag:
            raise ValueError("GLM-OCR : aucun modèle désigné — la porte commune pose sa clé de "
                             "catalogue (`backend_instance_for_key`).")
        return tag

    def run(
        self,
        file_path: str,
        mode: str = 'auto',
        language: str = '',
        progress_cb: Optional[Callable[[int, str], None]] = None,
        on_partial: Optional[Callable[[str], None]] = None,
    ) -> str:
        """
        Extract text from a document or image.

        Args:
            file_path:   Path to the input file (PDF, PNG, JPG, …)
            mode:        'auto' | 'printed' | 'handwritten' (hint only — GLM-OCR handles both)
            language:    ISO language code hint (e.g. 'fr', 'en')
            progress_cb: Optional callable(pct: int, msg: str)
            on_partial:  callback(texte_cumulé) après chaque page — aperçu « PENDANT »
                         (contrat commun preview_utils).

        Returns:
            Extracted text as a string.
        """
        model = self._model_tag()

        if progress_cb:
            progress_cb(5, "GLM-OCR : initialisation…")

        path = Path(file_path)
        ext  = path.suffix.lower()
        tmp_images: list[str] = []

        # Le dossier de travail appartient DÉSORMAIS à cette fonction (brique commune) : il
        # est supprimé quoi qu'il advienne — succès, exception, ou conversion qui rend [].
        from wama.common.utils.work_dir import work_dir
        with work_dir('glmocr') as travail:
            if ext == '.pdf':
                if progress_cb:
                    progress_cb(10, "Conversion PDF → images…")
                tmp_images = _pdf_to_images(file_path, dpi=200, dest_dir=str(travail))
                if not tmp_images:
                    raise RuntimeError("Impossible de convertir le PDF en images")
            else:
                # Single image file — use directly
                tmp_images = [file_path]

            n_pages  = len(tmp_images)
            texts    = []

            for i, img_path in enumerate(tmp_images):
                pct_start = 15 + int(i / n_pages * 75)
                msg = f"GLM-OCR : page {i + 1}/{n_pages}…" if n_pages > 1 else "GLM-OCR : extraction…"
                if progress_cb:
                    progress_cb(pct_start, msg)

                text = _ocr_image(model, img_path, language)
                texts.append(text)
                if on_partial:
                    try:
                        on_partial('\n\n---\n\n'.join(t for t in texts if t).strip())
                    except Exception:
                        pass  # best-effort : un tick d'aperçu raté n'arrête pas l'OCR

                if progress_cb:
                    progress_cb(pct_start + int(75 / n_pages), f"Page {i + 1}/{n_pages} terminée")

            if progress_cb:
                progress_cb(92, "Assemblage des pages…")

            # Join pages with a clear separator
            full_text = '\n\n---\n\n'.join(t for t in texts if t).strip()
            logger.info(f"[GlmOcr] Extracted {len(full_text)} chars from {path.name} ({n_pages} page(s))")
            return full_text
            # ⚠ Plus de bloc de nettoyage ici : il est porté par le `with work_dir(...)`.
            # L'ancien retirait les images une à une puis le dossier « s'il est vide » —
            # deux conditions qui le faisaient échouer précisément quand il restait quelque
            # chose à nettoyer. Le fichier d'origine n'a jamais été concerné : il vit dans
            # `media/`, pas dans le dossier de travail.
