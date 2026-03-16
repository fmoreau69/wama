"""
WAMA Imager - LTX-Video Backend

Video generation using LTX-Video via HuggingFace Diffusers.
Uses LTXConditionPipeline (required since 0.9.8) for T2V and I2V.

Models:
- ltx-video-13b-0.9.8-distilled     : 13B Distilled — rapide, T2V + I2V (14GB)
  HF: Lightricks/LTX-Video-0.9.8-13B-distilled
- ltx-video-13b-0.9.8-distilled-fp8 : 13B Distilled FP8 — ~8GB, T2V + I2V
  HF: Lightricks/LTX-Video-0.9.8-13B-distilled (quantized post-load via torchao)
"""

import gc
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Callable, List

from django.conf import settings

from .base import ImageGenerationBackend, GenerationParams, GenerationResult

logger = logging.getLogger(__name__)


def _get_ltx_cache_dir() -> str:
    """Get cache directory for LTX-Video models."""
    try:
        from wama.imager.utils.model_config import LTX_DIR
        return str(LTX_DIR)
    except ImportError:
        pass
    base_dir = Path(settings.BASE_DIR)
    models_dir = base_dir / "AI-models" / "models" / "diffusion" / "ltx"
    models_dir.mkdir(parents=True, exist_ok=True)
    return str(models_dir)


@dataclass
class LTXVideoParams:
    """Parameters for LTX-Video generation."""
    prompt: str
    negative_prompt: Optional[str] = (
        "worst quality, inconsistent motion, blurry, jittery, distorted"
    )
    model: str = "ltx-video-13b-0.9.8-distilled-fp8"
    width: int = 704
    height: int = 480
    num_frames: int = 97          # Must be 8n + 1
    num_inference_steps: int = 30
    guidance_scale: float = 3.0
    seed: Optional[int] = None
    fps: int = 24
    reference_image: Optional[str] = None  # Path to image for I2V mode


# Canonical model registry — mirrors LTX_MODELS in model_config.py
SUPPORTED_MODELS = {
    "ltx-video-13b-0.9.8-distilled": {
        "name": "LTX-Video 13B Distilled",
        "hf_id": "Lightricks/LTX-Video-0.9.8-13B-distilled",
        "description": "Rapide, T2V + I2V (14GB VRAM)",
        "mode": "t2v+i2v",
        "vram": "14GB",
        "quantization": None,
    },
    "ltx-video-13b-0.9.8-distilled-fp8": {
        "name": "LTX-Video 13B Distilled FP8",
        "hf_id": "Lightricks/LTX-Video-0.9.8-13B-distilled",
        "description": "~8GB VRAM, T2V + I2V, quantification FP8",
        "mode": "t2v+i2v",
        "vram": "8GB",
        "quantization": "fp8",
    },
}


class LTXVideoBackend(ImageGenerationBackend):
    """LTX-Video backend — uses LTXConditionPipeline for T2V and I2V."""

    name = "ltx_video"
    display_name = "LTX-Video"

    def __init__(self):
        super().__init__()
        self._pipe = None
        self._torch = None
        self._device = None
        self._loaded = False
        self._current_model = None
        self._cache_dir = _get_ltx_cache_dir()

    # ── Availability ─────────────────────────────────────────────────────────

    @classmethod
    def is_available(cls) -> bool:
        try:
            import torch
            from diffusers import LTXConditionPipeline  # noqa: F401

            if not torch.cuda.is_available():
                logger.warning("[LTX-Video] CUDA not available")
                return False

            vram_gb = torch.cuda.get_device_properties(0).total_memory / (1024 ** 3)
            if vram_gb < 6:
                logger.warning(f"[LTX-Video] Insufficient VRAM: {vram_gb:.1f}GB < 6GB")
                return False

            logger.info(f"[LTX-Video] Available — {vram_gb:.1f}GB VRAM")
            return True

        except ImportError as e:
            logger.warning(f"[LTX-Video] Import error: {e}")
            return False
        except Exception as e:
            logger.warning(f"[LTX-Video] Availability check failed: {e}")
            return False

    # ── Device helpers ────────────────────────────────────────────────────────

    def _get_device(self) -> str:
        if self._torch is None:
            import torch
            self._torch = torch
        if self._torch.cuda.is_available():
            name = self._torch.cuda.get_device_name(0)
            vram = self._torch.cuda.get_device_properties(0).total_memory / (1024 ** 3)
            logger.info(f"[LTX-Video] CUDA: {name} ({vram:.1f}GB)")
            return "cuda"
        logger.warning("[LTX-Video] No CUDA — using CPU (very slow)")
        return "cpu"

    def _get_vram_gb(self) -> float:
        if self._torch and self._torch.cuda.is_available():
            return self._torch.cuda.get_device_properties(0).total_memory / (1024 ** 3)
        return 0.0

    # ── Load ──────────────────────────────────────────────────────────────────

    def load(self, model_name: str = "ltx-video-13b-0.9.8-distilled-fp8",
             stage_callback: Optional[Callable[[str, int], None]] = None) -> bool:
        """Load the LTX-Video pipeline.

        Args:
            model_name: Model identifier from SUPPORTED_MODELS.
            stage_callback: Optional callable(stage_label, progress_0_100) called at
                key loading stages so the caller can report progress to the user.
        """
        def _stage(label: str, pct: int):
            logger.info(f"[LTX-Video] {label}")
            if stage_callback:
                stage_callback(label, pct)

        try:
            # ── CRITIQUE : env vars AVANT tout import HF ──────────────────
            os.environ['HF_HUB_CACHE'] = self._cache_dir
            os.environ['HUGGINGFACE_HUB_CACHE'] = self._cache_dir
            # ──────────────────────────────────────────────────────────────

            import torch
            from diffusers import LTXConditionPipeline

            self._torch = torch
            self._device = self._get_device()

            if model_name not in SUPPORTED_MODELS:
                logger.error(f"[LTX-Video] Unknown model: {model_name}")
                return False

            cfg = SUPPORTED_MODELS[model_name]
            hf_id = cfg["hf_id"]
            quantization = cfg.get("quantization")

            logger.info(f"[LTX-Video] ========================================")
            logger.info(f"[LTX-Video] Loading: {model_name}")
            logger.info(f"[LTX-Video] HF ID:   {hf_id}")
            logger.info(f"[LTX-Video] Cache:   {self._cache_dir}")
            if quantization:
                logger.info(f"[LTX-Video] Quantization: {quantization}")
            logger.info(f"[LTX-Video] ========================================")

            if self._pipe is not None:
                self.unload()

            self._pipe = LTXConditionPipeline.from_pretrained(
                hf_id,
                torch_dtype=torch.bfloat16,
                cache_dir=self._cache_dir,
            )
            _stage("✓ Pipeline chargé (composants prêts)", 55)

            # Apply FP8 quantization post-load (torchao)
            fp8_applied = False
            if quantization == "fp8":
                _stage("⚙ Quantification FP8 en cours (torchao)...", 60)
                fp8_applied = self._apply_fp8_quantization()
                if fp8_applied:
                    vram_after = torch.cuda.memory_allocated(0) / (1024 ** 3) if torch.cuda.is_available() else 0
                    _stage(f"✓ FP8 appliqué — VRAM utilisée : {vram_after:.1f}GB", 70)
                else:
                    _stage("⚠ FP8 ignoré (torchao incompatible) — mode bfloat16", 70)

            # Memory strategy
            if fp8_applied:
                # FP8 transformer is on CUDA after quantize_(device="cuda") — ~13GB.
                #
                # CANNOT use enable_model_cpu_offload() or enable_sequential_cpu_offload():
                # both eventually call module.to(device) on quantized Linear layers, which
                # triggers torchao's __torch_dispatch__ → return_and_correct_aliasing →
                # torch._functionalize_unsafe_set(cuda, cpu) → RuntimeError in torch 2.9.
                #
                # Solution: keep transformer on CUDA permanently (13GB), offload only T5
                # and VAE which are standard bfloat16 (no torchao tensors, no aliasing).
                # Peak VRAM: transformer(~13GB) + T5(~10GB) = ~23GB during text encoding.
                _stage("⚙ Stratégie mémoire : transformer FP8 sur CUDA, T5+VAE offloadés...", 75)
                try:
                    from accelerate import cpu_offload as _cpu_offload
                    _cpu_offload(self._pipe.text_encoder, "cuda")
                    _cpu_offload(self._pipe.vae, "cuda")
                    logger.info("[LTX-Video] CPU offload T5 + VAE (transformer FP8 reste sur CUDA)")
                    _stage("✓ CPU offload T5+VAE — transformer FP8 sur CUDA (~13GB)", 90)
                except Exception as e:
                    logger.warning(f"[LTX-Video] cpu_offload T5/VAE échoué: {e} — fallback: tout sur CUDA")
                    try:
                        self._pipe.to("cuda")
                    except Exception as e2:
                        logger.warning(f"[LTX-Video] pipe.to('cuda') aussi échoué: {e2}")
                    _stage("⚠ Fallback : pipeline sur CUDA directement", 90)
            else:
                # bfloat16 transformer is ~25GB — exceeds 24GB VRAM for both FULL_GPU and
                # MODEL_OFFLOAD (which loads the whole transformer at once).
                # Sequential CPU offload (layer-by-layer) is the only safe fallback:
                # peak VRAM ~1-2GB but inference is slow (~10-30 min per video).
                _stage("⚠ bfloat16 sans quantification — offload séquentiel couche par couche...", 75)
                logger.warning(
                    "[LTX-Video] Quantification ignorée — transformer bfloat16 ~25GB ne tient "
                    "pas sur 24GB VRAM. Utilisation de enable_sequential_cpu_offload() : "
                    "inférence très lente (~10-30 min). Installer torchao pour accélérer."
                )
                self._pipe.enable_sequential_cpu_offload()
                _stage("✓ Offload séquentiel couche par couche appliqué (bfloat16 — lent)", 90)

            # VAE tiling for large resolutions
            try:
                self._pipe.vae.enable_tiling()
                logger.info("[LTX-Video] VAE tiling enabled")
            except Exception as e:
                logger.warning(f"[LTX-Video] VAE tiling failed (non-fatal): {e}")

            vram_total = torch.cuda.get_device_properties(0).total_memory / (1024 ** 3) if torch.cuda.is_available() else 0
            vram_used = torch.cuda.memory_allocated(0) / (1024 ** 3) if torch.cuda.is_available() else 0
            _stage(f"✓ Modèle prêt — VRAM : {vram_used:.1f}GB / {vram_total:.1f}GB", 100)

            self._current_model = model_name
            self._loaded = True
            logger.info(f"[LTX-Video] {model_name} loaded successfully")
            return True

        except Exception as e:
            import traceback
            logger.error(f"[LTX-Video] Failed to load: {e}")
            logger.error(traceback.format_exc())
            self._loaded = False
            return False

    def _apply_fp8_quantization(self) -> bool:
        """Quantize transformer weights using torchao weight-only quantization.

        Strategy (in priority order):
        1. float8_weight_only  — FP8 weights, bfloat16 activations (~13GB, ~0s on GPU)
        2. int8_weight_only    — INT8 weights, bfloat16 activations (~13GB, reliable fallback)
        Both are compatible with enable_model_cpu_offload() because activations stay bfloat16
        (no custom __torch_dispatch__ on output tensors → no accelerate aliasing issue).

        After quantization, transformer is moved BACK to CPU so that sequential CPU offload
        keeps T5 and transformer from being on CUDA simultaneously (~10GB + ~13GB = OOM).
        """
        import time
        import torch
        import torch.nn as nn

        try:
            from torchao.quantization.quant_api import quantize_

            # Build weight-only config (no dynamic activation quantization).
            # Weight-only = activations stay bfloat16 → compatible with enable_model_cpu_offload().
            # Try multiple API variants across torchao versions (function vs class).
            config = None
            quant_label = None

            _candidates = [
                # Function-based API (some torchao builds)
                ("float8_weight_only", "FP8 weight-only"),
                ("int8_weight_only",   "INT8 weight-only"),
                # Class-based API (torchao 0.16+)
                ("Float8WeightOnlyConfig", "FP8 weight-only (class)"),
                ("Int8WeightOnlyConfig",   "INT8 weight-only (class)"),
            ]
            for _name, _label in _candidates:
                try:
                    import importlib
                    _mod = importlib.import_module("torchao.quantization.quant_api")
                    _obj = getattr(_mod, _name)
                    config = _obj()
                    quant_label = _label
                    break
                except (ImportError, AttributeError) as e:
                    logger.warning(f"[LTX-Video] {_name} non disponible: {e}")
                except Exception as e:
                    logger.warning(f"[LTX-Video] {_name} erreur: {e}")

            if config is None:
                logger.warning("[LTX-Video] Aucun config weight-only trouvé — quantification ignorée.")
                return False

            transformer = self._pipe.transformer
            total_linear = sum(1 for _, m in transformer.named_modules() if isinstance(m, nn.Linear))
            log_every = max(1, total_linear // 10)
            count = [0]
            t0 = time.time()

            logger.info(f"[LTX-Video] {quant_label}: {total_linear} couches linéaires à quantifier...")

            def _logged_filter(mod, fqn):
                if isinstance(mod, nn.Linear):
                    count[0] += 1
                    if count[0] == 1 or count[0] % log_every == 0 or count[0] == total_linear:
                        elapsed = time.time() - t0
                        pct = int(count[0] * 100 / total_linear)
                        logger.info(
                            f"[LTX-Video] Quantification: {count[0]}/{total_linear} ({pct}%) "
                            f"— {elapsed:.1f}s"
                        )
                return isinstance(mod, nn.Linear)

            # Quantize on CUDA for speed (device="cuda" moves transformer to GPU before quant)
            quantize_(transformer, config, filter_fn=_logged_filter, device="cuda")
            logger.info(f"[LTX-Video] {quant_label} terminé en {time.time() - t0:.1f}s")

            # Keep transformer on CUDA after quantization (~13GB FP8).
            # We must NOT call transformer.to("cpu") here: moving quantized (torchao custom)
            # tensors between devices triggers __torch_dispatch__ → return_and_correct_aliasing
            # → torch._functionalize_unsafe_set(cuda_tensor, cpu_tensor) → RuntimeError in
            # torch 2.9 ("devices must match").  13GB FP8 fits on 24GB VRAM; T5 + VAE will
            # be offloaded separately via accelerate.cpu_offload (standard bfloat16 only).
            vram_used = torch.cuda.memory_allocated(0) / (1024 ** 3)
            logger.info(f"[LTX-Video] Transformer FP8 sur CUDA: {vram_used:.1f}GB")
            return True

        except ImportError:
            logger.warning("[LTX-Video] torchao non disponible — quantification ignorée.")
            return False
        except Exception as e:
            logger.warning(f"[LTX-Video] Quantification échouée: {e}")
            return False

    # ── Unload ────────────────────────────────────────────────────────────────

    def unload(self) -> None:
        logger.info("[LTX-Video] Unloading model...")
        if self._pipe is not None:
            del self._pipe
            self._pipe = None
        self._loaded = False
        self._current_model = None
        gc.collect()
        if self._torch and self._torch.cuda.is_available():
            self._torch.cuda.empty_cache()
        logger.info("[LTX-Video] Unloaded")

    # ── Generate ──────────────────────────────────────────────────────────────

    def generate(
        self,
        params: LTXVideoParams,
        progress_callback: Optional[Callable[[int], None]] = None,
    ) -> GenerationResult:
        import torch

        # Load / switch model if needed
        target_model = params.model if params.model in SUPPORTED_MODELS else "ltx-video-13b-0.9.8-distilled-fp8"
        if not self._loaded or self._current_model != target_model:
            if not self.load(target_model):
                return GenerationResult(
                    success=False,
                    error=f"Failed to load LTX-Video model: {target_model}",
                )

        try:
            # Seed
            seed = params.seed
            if seed is None:
                seed = torch.randint(0, 2 ** 32, (1,)).item()
            generator = torch.Generator(device="cpu").manual_seed(seed)
            logger.info(f"[LTX-Video] Seed: {seed}")

            # Clear cache
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
                gc.collect()

            # Align dimensions to multiples of 32
            width = (params.width // 32) * 32
            height = (params.height // 32) * 32

            # Align frames to 8n + 1
            num_frames = ((params.num_frames - 1) // 8) * 8 + 1

            logger.info(f"[LTX-Video] {width}x{height} — {num_frames} frames — {params.num_inference_steps} steps")

            # Progress callback
            def callback_on_step_end(pipe, step_index, timestep, callback_kwargs):
                if progress_callback:
                    progress = int((step_index + 1) / params.num_inference_steps * 100)
                    progress_callback(progress)
                return callback_kwargs

            # Build conditions for I2V
            conditions = None
            if params.reference_image:
                conditions = self._build_i2v_conditions(
                    params.reference_image, width, height
                )

            # Common call kwargs
            call_kwargs = dict(
                prompt=params.prompt,
                negative_prompt=params.negative_prompt,
                width=width,
                height=height,
                num_frames=num_frames,
                num_inference_steps=params.num_inference_steps,
                guidance_scale=params.guidance_scale,
                generator=generator,
                callback_on_step_end=callback_on_step_end,
            )
            if conditions is not None:
                call_kwargs["conditions"] = conditions
                logger.info("[LTX-Video] I2V mode — image condition applied")

            # Use no_grad instead of inference_mode: inference_mode in torch 2.9 may
            # enable functionalization internally, which causes torchao's
            # return_and_correct_aliasing to call torch._functionalize_unsafe_set cross-device.
            with torch.no_grad():
                output = self._pipe(**call_kwargs)

            video_frames = output.frames[0]
            logger.info(f"[LTX-Video] Generated {len(video_frames)} frames")

            return GenerationResult(
                success=True,
                video_frames=video_frames,
                seed_used=seed,
            )

        except Exception as e:
            import traceback
            logger.error(f"[LTX-Video] Generation failed: {e}")
            logger.error(traceback.format_exc())
            return GenerationResult(success=False, error=str(e))

    def _build_i2v_conditions(self, image_path: str, width: int, height: int):
        """Build LTXVideoCondition list from a reference image path."""
        try:
            from diffusers.pipelines.ltx.pipeline_ltx_condition import LTXVideoCondition
            from PIL import Image

            img = Image.open(image_path).convert("RGB")
            img = img.resize((width, height))

            condition = LTXVideoCondition(
                video=img,
                frame_index=0,
            )
            logger.info(f"[LTX-Video] I2V condition built from {image_path}")
            return [condition]

        except ImportError:
            logger.warning(
                "[LTX-Video] LTXVideoCondition not available in this diffusers version — "
                "falling back to T2V (no image condition)"
            )
            return None
        except Exception as e:
            logger.warning(f"[LTX-Video] Could not build I2V condition: {e} — falling back to T2V")
            return None

    # ── Export ────────────────────────────────────────────────────────────────

    def export_video(self, frames: List, output_path: str, fps: int = 24) -> bool:
        try:
            from diffusers.utils import export_to_video
            export_to_video(frames, output_path, fps=fps)
            logger.info(f"[LTX-Video] Exported to {output_path}")
            return True
        except Exception as e:
            logger.error(f"[LTX-Video] Export failed: {e}")
            return False

    @classmethod
    def get_supported_models(cls) -> dict:
        return SUPPORTED_MODELS
