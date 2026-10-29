"""
olmOCR backend — Allen AI VLM-based OCR.

Supporte : PDF, images (JPG, PNG, TIFF, WebP), imprimé + manuscrit.

Le modèle servi est DÉCLARÉ dans `SUPPORTED_MODELS` : olmOCR-2 (`allenai/olmOCR-2-7B-1025`, sur
Qwen2.5-VL, 82,3 sur olmOCR-Bench), installé par la route depuis sa proposition de successeur
(`prospector.seed_hf_successors`). Lu comme son auteur l'a entraîné (fiche du modèle, boîte à
outils olmocr ≥ 0.4) : la page à 1288 px sur son plus grand côté, la consigne
`build_no_anchoring_v4_yaml_prompt`, une réponse en Markdown précédée d'un en-tête YAML (langue,
rotation, tableau, schéma) que ce backend retire. Un modèle de la famille qui ne déclare pas sa
consigne serait lu avec celle du reader (`_build_prompt`, mode et langue).
olmOCR v1 « preview » (`allenai/olmOCR-7B-0225-preview`, la ligne `reader:olmocr`), servi ici
jusqu'au 2026-10-29, est RETIRÉ au profit d'olmOCR-2 (`REMOVAL_LEDGER` R190).
Le dépôt et le dossier des poids se lisent sur la LIGNE de catalogue confiée (`catalogue_key`) :
sans elle, rien à charger.
"""
import os
import logging
from pathlib import Path
from typing import Callable, Optional

from wama.common.backends.ocr_base import OCRBackend

logger = logging.getLogger(__name__)

#: La consigne d'olmOCR-2, mot pour mot : `build_no_anchoring_v4_yaml_prompt()` de la boîte à
#: outils olmocr (`olmocr/prompts/prompts.py`, Apache-2.0, lue le 2026-10-29) — celle sur laquelle le
#: modèle a été entraîné ; une consigne maison le ferait lire hors de son apprentissage. (« LateX »
#: est dans l'original.)
OLMOCR_V4_YAML_PROMPT = (
    "Attached is one page of a document that you must process. "
    "Just return the plain text representation of this document as if you were reading it naturally. Convert equations to LateX and tables to HTML.\n"
    "If there are any figures or charts, label them with the following markdown syntax ![Alt text describing the contents of the figure](page_startx_starty_width_height.png)\n"
    "Return your output as markdown, with a front matter section on top specifying values for the primary_language, is_rotation_valid, rotation_correction, is_table, and is_diagram parameters."
)


def _fit_longest_side(image, longest: int):
    """L'image redimensionnée pour que son plus grand côté fasse `longest` px (la taille sur
    laquelle olmOCR-2 a été entraîné), proportions gardées."""
    width, height = image.size
    scale = longest / float(max(width, height))
    if abs(scale - 1.0) < 1e-3:
        return image
    from PIL import Image
    return image.resize((max(1, round(width * scale)), max(1, round(height * scale))),
                        Image.LANCZOS)


def without_front_matter(text: str) -> str:
    """Le texte d'une réponse d'olmOCR-2 sans son en-tête YAML (`---` … `---` : langue, rotation,
    tableau, schéma) — ce que le contrat OCR rend est le texte LU. Sans en-tête, le texte tel quel."""
    from wama.common.utils.front_matter import split_front_matter
    header, body = split_front_matter((text or '').lstrip())
    return body.strip() if header else text


class OlmOCRBackend(OCRBackend):

    #: Moteur piloté (contrat commun) — voir BaseModelBackend.ENGINE.
    ENGINE = 'transformers'

    #: Modèles du catalogue que CE backend sert — le lien FIN, déclaré le 2026-09-06.
    #: `ENGINE` ne suffit pas comme clé : `transformers` est piloté par 4 backends de 4 apps
    #: différentes, donc résoudre par moteur seul serait indécidable. Cette liste tranche.
    #: Les clés sont les `model_id` du catalogue (segment après `<source>:`), vocabulaire
    #: PARTAGÉ avec `SUPPORTED_MODELS` des backends imager — une graphie différente rouvrirait
    #: le trou qu'on ferme.
    #: ⚠ En LITTÉRAL (l'inventaire lit par AST). Pour olmOCR-2, la façon de LIRE déclarée par son
    #: auteur : `prompt` (`v4_yaml` = la consigne de la boîte à outils olmocr ≥ 0.4, recopiée de sa
    #: source sous licence Apache-2.0), `longest_side` (px), `temperature`, `max_new_tokens`.
    SUPPORTED_MODELS = {
        'allenai/olmOCR-2-7B-1025': {'prompt': 'v4_yaml', 'longest_side': 1288,
                                     'temperature': 0.1, 'max_new_tokens': 8000},
    }
    REQUIRED_PACKAGES = ['transformers', 'torch']
    recommended_vram_gb = 8.0
    description = "olmOCR-2 (Qwen2.5-VL) — OCR de documents."

    def __init__(self):
        self._model = None
        self._processor = None
        self._loaded_repo = ''
        self.catalogue_key = ''

    def _served(self) -> dict:
        """Ce que `SUPPORTED_MODELS` déclare du modèle confié (`catalogue_key`), {} sinon."""
        from wama.common.utils.model_keys import model_id
        return dict(self.SUPPORTED_MODELS.get(model_id(self.catalogue_key)) or {})

    def _weights(self) -> tuple:
        """`(dépôt, cache_dir)` du modèle confié : le dépôt sur SA ligne de catalogue
        (`AIModel.hf_repo`), le dossier où la ROUTE a installé ses poids — le lien de la
        désinstallation (`model_installer.weights_dir_of`) ; à défaut de poids repérés, le
        dossier de la catégorie. Sans ligne confiée, rien à charger : `ValueError` le dit (la ligne
        du reader et sa déclaration, son ancien repli, sont retirées avec olmOCR v1, R190)."""
        from django.conf import settings

        from wama.model_manager.models import AIModel
        from wama.model_manager.services.model_installer import weights_dir_of
        row = (AIModel.objects.filter(model_key=self.catalogue_key).first()
               if self.catalogue_key else None)
        if row is None or not row.hf_repo:
            raise ValueError(f"olmOCR : aucune ligne de catalogue confiée à charger "
                             f"({self.catalogue_key or 'aucune clé'}).")
        where = weights_dir_of(row)
        default_dir = str(settings.MODEL_PATHS.get('ocr', {}).get('root', ''))
        return row.hf_repo, (str(where.parent) if where is not None
                             and where.name.startswith('models--') else default_dir)

    @classmethod
    def is_available(cls) -> bool:
        try:
            import transformers, torch  # noqa: F401
            return True
        except Exception:
            return False

    @property
    def is_loaded(self) -> bool:
        return self._model is not None

    # `process()` → `run()` : celui du contrat OCR (`ocr_base.OCRBackend`, 2026-10-07).

    @staticmethod
    def _unload_ollama_models() -> int:
        """Décharge les modèles que l'Ollama hôte tient en mémoire ; rend le nombre déchargé.

        Par les briques (2026-10-20) : le lecteur commun de `/api/ps` (`ModelRegistry.ollama_ps`)
        et le déchargement de `MemoryManager.unload_model`, qui retire aussi la ligne de résidence
        du gouverneur. Ce bloc tenait son propre client HTTP pour les deux."""
        unloaded = 0
        try:
            from wama.model_manager.services.memory_manager import MemoryManager
            from wama.model_manager.services.model_registry import ModelRegistry
            for m in ModelRegistry.ollama_ps():
                name = m.get('name', '')
                if name and MemoryManager.unload_model(f'ollama:{name}'):
                    unloaded += 1
                    logger.info(f"[olmOCR] Ollama déchargé : {name}")
        except Exception as e:
            logger.debug(f"[olmOCR] Ollama unload skipped : {e}")
        return unloaded

    def _free_vram_before_load(self):
        """Libère la VRAM avant le chargement du modèle :
        1. Décharge les modèles Ollama actifs
        2. Vide le cache CUDA PyTorch
        3. Désactive caching_allocator_warmup (transformers 4.57+) qui alloue
           ~14 GiB contigu pour le « warmup » — provoque OOM sur RTX 4090.
        """
        import gc

        # 1. Unload Ollama models (keep_alive=0)
        self._unload_ollama_models()

        # 2. Clear PyTorch CUDA cache
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
                torch.cuda.synchronize()
        except Exception:
            pass

        gc.collect()

        # 3. Disable transformers 4.57+ caching_allocator_warmup
        #    This warmup allocates the full model size as a contiguous block,
        #    causing OOM on fragmented VRAM even when enough total memory is free.
        try:
            import transformers.modeling_utils as _tmu
            if hasattr(_tmu, 'caching_allocator_warmup'):
                _tmu.caching_allocator_warmup = lambda *a, **kw: None
                logger.debug("[olmOCR] caching_allocator_warmup désactivé")
        except Exception:
            pass

    def load(self, model: Optional[str] = None) -> bool:
        # Le dépôt et le dossier : ceux de la ligne confiée (`_weights`) — un chemin de poids
        # vient de la route qui l'a installé, une déclaration du passe-plat commun.
        repo_id, cache_dir = self._weights()
        if self._model is not None and self._loaded_repo == repo_id:
            return True
        if self._model is not None:
            self.unload()

        # Env NON muté (ROADMAP §5b, 2026-09-04) : les deux `from_pretrained` ci-dessous
        # portent `cache_dir=`, qui route le modèle PRINCIPAL. La mutation n'ajoutait rien
        # pour lui et emportait ses sous-dépendances hors du cache partagé.

        self._free_vram_before_load()

        import torch
        from transformers import AutoModelForImageTextToText, AutoProcessor

        logger.info(f"[olmOCR] Chargement {repo_id} depuis {cache_dir}")
        device = 'cuda' if torch.cuda.is_available() else 'cpu'

        self._processor = AutoProcessor.from_pretrained(
            repo_id,
            cache_dir=cache_dir,
            trust_remote_code=True,
        )
        # La classe VL que dit la config du dépôt (Qwen2.5-VL pour olmOCR-2) — jamais
        # `AutoModelForCausalLM`, qui n'a pas la tour de vision.
        self._model = AutoModelForImageTextToText.from_pretrained(
            repo_id,
            cache_dir=cache_dir,
            torch_dtype=torch.bfloat16 if device == 'cuda' else torch.float32,
            device_map=device,
            trust_remote_code=True,
        )
        self._model.eval()
        self._loaded_repo = repo_id
        logger.info(f"[olmOCR] Modèle chargé sur {device}")
        return self.is_loaded

    def unload(self):
        import gc
        try:
            import torch
            if self._model is not None:
                del self._model
                self._model = None
            if self._processor is not None:
                del self._processor
                self._processor = None
            self._loaded_repo = ''
            gc.collect()
            if hasattr(torch, 'cuda'):
                torch.cuda.empty_cache()
        except Exception as e:
            logger.warning(f"[olmOCR] unload error: {e}")

    def run(
        self,
        work_file: str,
        mode: str = 'auto',
        language: str = '',
        progress_callback: Optional[Callable[[int, str], None]] = None,
        keep_loaded: bool = False,
        on_partial: Optional[Callable[[str], None]] = None,
    ) -> str:
        """
        Extract text from a document file.
        Returns the full extracted text as a string.

        keep_loaded: if True, do NOT unload the model after processing — useful
                     when the same worker will process another file immediately after
                     (singleton pattern in tasks.py avoids the 10-min reload).
        on_partial:  callback(texte_cumulé) appelé après CHAQUE page — aperçu « PENDANT »
                     (contrat commun preview_utils, même patron que l'on_audio du composer).
        """
        path = Path(work_file)
        ext = path.suffix.lower()

        if self._model is None:
            if progress_callback:
                progress_callback(5, "Chargement olmOCR-2…")
            self.load()

        pages = self._get_pages(path, ext)
        total = len(pages)
        texts = []

        for i, page_image in enumerate(pages):
            if progress_callback:
                pct = 10 + int((i / total) * 85)
                progress_callback(pct, f"Page {i + 1}/{total}…")

            text = self._process_image(page_image, mode, language)
            texts.append(text)
            if on_partial:
                try:
                    on_partial('\n\n'.join(texts))
                except Exception:
                    pass  # best-effort : un tick d'aperçu raté n'arrête pas l'OCR

        if not keep_loaded:
            self.unload()

        if progress_callback:
            progress_callback(98, "Assemblage du texte…")

        return '\n\n'.join(texts)

    def _get_pages(self, path: Path, ext: str):
        """Convert document to list of PIL Images (one per page)."""
        if ext == '.pdf':
            return self._pdf_to_images(path)
        else:
            from PIL import Image
            return [Image.open(str(path)).convert('RGB')]

    def _pdf_to_images(self, path: Path):
        """Convert PDF pages to images. Tries pymupdf then pdf2image."""
        try:
            try:
                import pymupdf as fitz  # PyMuPDF >= 1.24
            except ImportError:
                import fitz  # legacy name
            doc = fitz.open(str(path))
            images = []
            from PIL import Image
            import io
            for page in doc:
                pix = page.get_pixmap(dpi=150)
                img = Image.open(io.BytesIO(pix.tobytes('png'))).convert('RGB')
                images.append(img)
            doc.close()
            return images
        except Exception as e:
            # ImportError si non installé, mais aussi RuntimeError/AttributeError
            # selon la version de PyMuPDF — on log et on tente le fallback
            logger.warning(f"[olmOCR] pymupdf échoué ({type(e).__name__}: {e}), fallback pdf2image")

        try:
            from pdf2image import convert_from_path
            return convert_from_path(str(path), dpi=150)
        except ImportError:
            raise RuntimeError(
                "Aucun convertisseur PDF disponible. "
                "Installez pymupdf (`pip install pymupdf`) ou pdf2image (`pip install pdf2image`)."
            )

    def _process_image(self, image, mode: str, language: str) -> str:
        import torch

        served = self._served()
        if served.get('longest_side'):
            image = _fit_longest_side(image, served['longest_side'])
        if served.get('prompt') == 'v4_yaml':
            # L'ordre de la fiche du modèle : la consigne, puis l'image.
            content = [{"type": "text", "text": OLMOCR_V4_YAML_PROMPT},
                       {"type": "image", "image": image}]
        else:
            content = [{"type": "image", "image": image},
                       {"type": "text", "text": self._build_prompt(mode, language)}]

        # Qwen2-VL requires chat-template format with image + text in a message
        messages = [{"role": "user", "content": content}]

        text = self._processor.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True
        )

        inputs = self._processor(
            text=[text],
            images=[image],
            padding=True,
            return_tensors="pt",
        ).to(self._model.device)

        sampling = ({'do_sample': True, 'temperature': served['temperature']}
                    if served.get('temperature') else {'do_sample': False})
        with torch.no_grad():
            output_ids = self._model.generate(
                **inputs,
                max_new_tokens=served.get('max_new_tokens') or 4096,
                **sampling,
            )

        # Decode only the generated part (skip input tokens)
        input_len = inputs['input_ids'].shape[1]
        generated = output_ids[0][input_len:]
        result = self._processor.decode(generated, skip_special_tokens=True).strip()
        return without_front_matter(result) if served.get('prompt') == 'v4_yaml' else result

    def _build_prompt(self, mode: str, language: str) -> str:
        lang_hint = f" The document is in {language}." if language else ""
        if mode == 'handwritten':
            return (
                f"Please transcribe all handwritten text from this document page accurately.{lang_hint} "
                "Preserve the structure and layout as much as possible."
            )
        elif mode == 'printed':
            return (
                f"Extract all printed text from this document page.{lang_hint} "
                "Preserve headings, paragraphs, tables, and formatting."
            )
        else:  # auto
            return (
                f"Read and transcribe all text from this document page.{lang_hint} "
                "Preserve the original structure including headings, lists, tables, and formatting."
            )
