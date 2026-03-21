"""
olmOCR-2 backend — Allen AI VLM-based OCR.

Basé sur Qwen2-VL fine-tuné pour la reconnaissance de documents.
Supporte : PDF, images (JPG, PNG, TIFF, WebP), imprimé + manuscrit.

HuggingFace ID par défaut : allenai/olmOCR-7B-0225-preview
(configurable dans reader/utils/model_config.py)
"""
import os
import logging
from pathlib import Path
from typing import Callable, Optional

logger = logging.getLogger(__name__)


class OlmOCRBackend:

    def __init__(self):
        self._model = None
        self._processor = None

    def _free_vram_before_load(self):
        """Libère la VRAM avant le chargement du modèle :
        1. Décharge les modèles Ollama actifs
        2. Vide le cache CUDA PyTorch
        3. Désactive caching_allocator_warmup (transformers 4.57+) qui alloue
           ~14 GiB contigu pour le « warmup » — provoque OOM sur RTX 4090.
        """
        import gc

        # 1. Unload Ollama models (keep_alive=0)
        try:
            import httpx
            from django.conf import settings
            host = getattr(settings, 'OLLAMA_HOST', 'http://127.0.0.1:11434').rstrip('/')
            r = httpx.get(f'{host}/api/ps', timeout=3.0, trust_env=False)
            if r.status_code == 200:
                for m in r.json().get('models', []):
                    name = m.get('name', '')
                    if name:
                        httpx.post(
                            f'{host}/api/generate',
                            json={'model': name, 'keep_alive': 0},
                            timeout=10.0,
                            trust_env=False,
                        )
                        logger.info(f"[olmOCR] Ollama déchargé : {name}")
        except Exception as e:
            logger.debug(f"[olmOCR] Ollama unload skipped : {e}")

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

    def load(self):
        import os
        from wama.reader.utils.model_config import OLMOCR_DIR, READER_MODELS

        cache_dir = str(OLMOCR_DIR)
        hf_id = READER_MODELS['olmocr']['hf_model_id']

        # ── CRITIQUE : setter HF_HUB_CACHE AVANT tout import HuggingFace ──────
        os.environ['HF_HUB_CACHE'] = cache_dir
        os.environ['HUGGINGFACE_HUB_CACHE'] = cache_dir
        # ──────────────────────────────────────────────────────────────────────

        self._free_vram_before_load()

        import torch
        try:
            from transformers import AutoProcessor
        except ImportError:
            from transformers.models.auto.processing_auto import AutoProcessor

        # olmOCR is Qwen2-VL — must use the VL model class, not AutoModelForCausalLM
        try:
            from transformers import Qwen2VLForConditionalGeneration
        except ImportError:
            from transformers.models.qwen2_vl.modeling_qwen2_vl import Qwen2VLForConditionalGeneration

        logger.info(f"[olmOCR] Chargement {hf_id} depuis {cache_dir}")
        device = 'cuda' if torch.cuda.is_available() else 'cpu'

        self._processor = AutoProcessor.from_pretrained(
            hf_id,
            cache_dir=cache_dir,
            trust_remote_code=True,
        )
        self._model = Qwen2VLForConditionalGeneration.from_pretrained(
            hf_id,
            cache_dir=cache_dir,
            torch_dtype=torch.bfloat16 if device == 'cuda' else torch.float32,
            device_map=device,
            trust_remote_code=True,
        )
        self._model.eval()
        logger.info(f"[olmOCR] Modèle chargé sur {device}")

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
            gc.collect()
            if hasattr(torch, 'cuda'):
                torch.cuda.empty_cache()
        except Exception as e:
            logger.warning(f"[olmOCR] unload error: {e}")

    def run(
        self,
        file_path: str,
        mode: str = 'auto',
        language: str = '',
        progress_cb: Optional[Callable[[int, str], None]] = None,
    ) -> str:
        """
        Extract text from a document file.
        Returns the full extracted text as a string.
        """
        path = Path(file_path)
        ext = path.suffix.lower()

        if self._model is None:
            if progress_cb:
                progress_cb(5, "Chargement olmOCR-2…")
            self.load()

        pages = self._get_pages(path, ext)
        total = len(pages)
        texts = []

        for i, page_image in enumerate(pages):
            if progress_cb:
                pct = 10 + int((i / total) * 85)
                progress_cb(pct, f"Page {i + 1}/{total}…")

            text = self._process_image(page_image, mode, language)
            texts.append(text)

        self.unload()

        if progress_cb:
            progress_cb(98, "Assemblage du texte…")

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
            import fitz  # pymupdf
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
        except ImportError:
            pass

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

        prompt = self._build_prompt(mode, language)

        # Qwen2-VL requires chat-template format with image + text in a message
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "image", "image": image},
                    {"type": "text", "text": prompt},
                ],
            }
        ]

        text = self._processor.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True
        )

        inputs = self._processor(
            text=[text],
            images=[image],
            padding=True,
            return_tensors="pt",
        ).to(self._model.device)

        with torch.no_grad():
            output_ids = self._model.generate(
                **inputs,
                max_new_tokens=4096,
                do_sample=False,
            )

        # Decode only the generated part (skip input tokens)
        input_len = inputs['input_ids'].shape[1]
        generated = output_ids[0][input_len:]
        result = self._processor.decode(generated, skip_special_tokens=True).strip()
        return result

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
