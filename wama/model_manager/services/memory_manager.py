"""
Memory Manager - GPU/RAM memory utilities for model management.

Provides centralized VRAM management and CPU offload strategies for all WAMA applications.
"""

import gc
import logging
from typing import Dict, Optional, Literal
from enum import Enum

logger = logging.getLogger(__name__)


# Marge minimale de VRAM libre à préserver pendant un chargement FULL_GPU (activations
# + fragmentation). En dessous, on abandonne FULL_GPU et on retombe sur MODEL_OFFLOAD.
FULL_GPU_MIN_FREE_GB = 1.5

# Fraction du total physique au-delà de laquelle l'allocateur CUDA doit ÉCHOUER.
_ALLOCATOR_CAP_FRACTION = 0.95
_allocator_capped = False


def _cap_cuda_allocator() -> None:
    """
    Plafonne l'allocateur CUDA à ``_ALLOCATOR_CAP_FRACTION`` de la VRAM physique.

    CRITIQUE sous WSL2/WDDM : sans ce plafond, une allocation qui dépasse la VRAM
    physique n'échoue PAS — le pilote la fait déborder silencieusement en RAM hôte et
    pagine à travers la frontière GPU-PV. Cette pagination sature `dxgkio_make_resident`
    (ENOMEM en rafale) et finit par faire paniquer le noyau invité : la VM WSL entière
    est réinitialisée, pas seulement le worker.

    Vécu 29/07/2026 : génération imager #42 (qwen-image-2), stratégie FULL_GPU décidée
    sur 24 Go libres, transformer déplacé jusqu'à 38,1 Go sur une carte de 24 Go →
    4 min 14 de pagination → 4 kernel panics WSL2 d'affilée (`Fatal machine check`).

    Avec le plafond, PyTorch lève un OOM franc et la chaîne de repli
    (MODEL_OFFLOAD → SEQUENTIAL_OFFLOAD) fait son travail.
    """
    global _allocator_capped
    if _allocator_capped:
        return
    try:
        import torch
        if not torch.cuda.is_available():
            return
        torch.cuda.set_per_process_memory_fraction(_ALLOCATOR_CAP_FRACTION)
        total_gb = torch.cuda.get_device_properties(0).total_memory / (1024 ** 3)
        logger.info(
            f"[MemoryManager] Allocateur CUDA plafonné à "
            f"{_ALLOCATOR_CAP_FRACTION:.0%} de {total_gb:.1f} GB "
            f"(= {total_gb * _ALLOCATOR_CAP_FRACTION:.1f} GB) — anti-débordement WDDM"
        )
        _allocator_capped = True
    except Exception as exc:
        logger.warning(f"[MemoryManager] Plafond allocateur CUDA non appliqué : {exc}")


def _component_size_gb(component) -> float:
    """
    Empreinte réelle d'un composant de pipeline (paramètres + buffers), en Go.

    Complémentaire de ``MemoryManager.estimate_model_size(path)``, qui estime depuis
    un CHEMIN (presets + taille de fichier) : ici on mesure un module DÉJÀ instancié,
    seul moyen de connaître l'empreinte vraie quand le preset est faux.
    """
    try:
        n = sum(p.numel() * p.element_size() for p in component.parameters())
        n += sum(b.numel() * b.element_size() for b in component.buffers())
        return n / (1024 ** 3)
    except Exception:
        return 0.0


class MemoryStrategy(Enum):
    """Memory loading strategies for AI models."""
    FULL_GPU = "full_gpu"              # Load entirely on GPU (fastest)
    MODEL_OFFLOAD = "model_offload"    # Move model components to GPU as needed (moderate)
    SEQUENTIAL_OFFLOAD = "sequential"  # Move layers to GPU one at a time (slowest, least VRAM)
    CPU_ONLY = "cpu"                   # Run entirely on CPU (no GPU)


# Model size categories in GB (measured VRAM requirement at runtime, bf16/fp16).
# Used by get_memory_strategy() to decide FULL_GPU vs CPU offload.
# RTX 4090 = 24 GB → headroom_gb=4 → models ≤ 20 GB fit entirely on GPU.
MODEL_SIZE_PRESETS = {
    # ── Image diffusion ──────────────────────────────────────────────────────
    # FLUX transformer alone is ~23 GB bfloat16 (12B params × 2 bytes).
    # Total pipeline (transformer + T5 + CLIP + VAE) ≈ 35 GB.
    # Use 24 GB so MemoryManager never picks FULL_GPU on a 24 GB card.
    'flux': 24.0,
    'flux-dev': 24.0,
    'flux-schnell': 12.0,
    'sdxl': 7.0,
    'sd15': 4.0,
    'sd21': 5.0,
    'hunyuan-image': 16.0,
    'hunyuan-image-2.1': 16.0,

    # Qwen Image (Alibaba) — Diffusers pipelines (not transformers)
    # MESURÉ 29/07/2026 : le transformer seul atteint 38,1 GB au chargement (log worker
    # gpu). L'ancienne valeur de 16.0 faisait choisir FULL_GPU sur une carte de 24 Go →
    # débordement WDDM en RAM hôte → kernel panic WSL2. Ne PAS rabaisser sans mesure.
    'qwen-image': 38.0,       # Qwen-Image-2512

    'qwen-image-edit': 12.0,  # Qwen-Image-Edit-2511  ~12 GB at bf16

    # ── Video diffusion ──────────────────────────────────────────────────────
    'hunyuan-video': 24.0,
    'cogvideox': 21.0,    # CogVideoX-5B measured: transformer 10.8 + text_encoder 8.9 + VAE 0.4 = 20.1 GB
    'ltx-video': 18.0,        # LTX-Video 13B bf16 — transformer ~14GB + text_encoder ~4GB
    'ltx-video-fp8': 8.0,    # LTX-Video 13B FP8 quantized (torchao)
    'mochi': 22.0,        # Mochi-1 Preview bf16 ~22 GB
    'wan-t2v': 14.0,
    'wan-i2v': 28.0,

    # ── Vision (detection / segmentation) ───────────────────────────────────
    'yolo-nano': 0.5,
    'yolo-small': 1.0,
    'yolo-medium': 2.0,
    'yolo-large': 4.0,
    'yolo-xlarge': 6.0,
    'sam3-tiny': 1.5,
    'sam3-base': 3.0,
    'sam3-large': 6.0,

    # ── Audio (ASR) ──────────────────────────────────────────────────────────
    'whisper-tiny': 0.5,
    'whisper-base': 0.8,
    'whisper-small': 1.5,
    'whisper-medium': 3.0,
    'whisper-large': 6.0,

    # ── Multimodal / captioning ──────────────────────────────────────────────
    'blip': 2.0,
    'blip2': 4.0,
}


# =============================================================================
# VRAM release registry — reusable memory-admission for ALL apps
# =============================================================================
#
# Problème résolu : jusqu'ici, `clear_gpu_memory()` / `unload_model()` codaient
# en dur quelles apps décharger (imager + describer), et les autres apps
# (transcriber, synthesizer, enhancer…) étaient des stubs no-op → invisibles au
# reclaim central. Chaque app charge/décharge ses modèles dans son coin, sans
# coordination : deux gros modèles peuvent cohabiter en VRAM et geler l'hôte.
#
# Ici, chaque app DÉCLARE un « unloader » (nom + callable qui libère sa VRAM).
# `ensure_free_vram()` / `release_vram()` itèrent ces unloaders pour faire de la
# place AVANT de charger un nouveau modèle — brique unique, réutilisable partout,
# sans rien coder en dur par app.
#
# Un unloader est enregistré via `register_vram_unloader(name, fn)` (idempotent :
# ré-enregistrer le même nom remplace). `fn()` renvoie True s'il a libéré qqch.

_VRAM_UNLOADERS: "dict[str, callable]" = {}


def register_vram_unloader(name: str, fn) -> None:
    """Déclare un callable qui libère la VRAM d'une app (idempotent par `name`)."""
    _VRAM_UNLOADERS[name] = fn
    logger.debug(f"[MemoryManager] VRAM unloader registered: {name}")


def unregister_vram_unloader(name: str) -> None:
    _VRAM_UNLOADERS.pop(name, None)


class MemoryManager:
    """Manages GPU and system memory for AI models."""

    # ---- VRAM release registry (voir bloc ci-dessus) ----------------------
    @staticmethod
    def register_unloader(name: str, fn) -> None:
        register_vram_unloader(name, fn)

    @staticmethod
    def release_vram(exclude: "Optional[set]" = None) -> int:
        """
        Décharge tous les modèles enregistrés (sauf `exclude`) pour récupérer la
        VRAM. Renvoie le nombre d'unloaders ayant effectivement libéré qqch.

        Ne casse pas les chemins hérités : les unloaders imager/describer codés
        en dur restent appelés par `clear_gpu_memory()`. Ce registre est le
        chemin NEUF que les apps adoptent progressivement.
        """
        exclude = exclude or set()
        freed = 0
        for name, fn in list(_VRAM_UNLOADERS.items()):
            if name in exclude:
                continue
            try:
                if fn():
                    freed += 1
                    logger.info(f"[MemoryManager] Released VRAM via unloader: {name}")
            except Exception as e:
                logger.warning(f"[MemoryManager] Unloader '{name}' failed: {e}")
        if freed:
            try:
                import torch
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
                gc.collect()
            except Exception:
                pass
        return freed

    @staticmethod
    def ensure_free_vram(needed_gb: float, headroom_gb: float = 1.5,
                         exclude: "Optional[set]" = None) -> bool:
        """
        Garantit ~`needed_gb` + `headroom_gb` de VRAM libre AVANT de charger un
        modèle. Si insuffisant, décharge les modèles enregistrés (`release_vram`)
        puis re-mesure. Renvoie True si l'objectif est atteint (ou pas de GPU :
        rien à garantir), False sinon (l'appelant peut alors dégrader : CPU,
        chunking, refus…).

        Brique réutilisable par TOUTE app avant un `load()` de modèle GPU.
        """
        target = needed_gb + headroom_gb
        info = MemoryManager.get_gpu_memory_info()
        if info is None:
            return True  # pas de GPU → rien à garantir
        if info['free_gb'] >= target:
            return True
        logger.info(
            f"[MemoryManager] ensure_free_vram: {info['free_gb']:.1f}GB libre "
            f"< {target:.1f}GB requis → reclaim…"
        )
        MemoryManager.release_vram(exclude=exclude)
        info = MemoryManager.get_gpu_memory_info()
        ok = info is not None and info['free_gb'] >= target
        logger.info(
            f"[MemoryManager] ensure_free_vram: après reclaim "
            f"{info['free_gb']:.1f}GB libre (objectif {target:.1f}GB) → "
            f"{'OK' if ok else 'INSUFFISANT'}"
        )
        return ok

    @staticmethod
    def get_gpu_memory_info() -> Optional[Dict]:
        """Get GPU memory information using PyTorch."""
        try:
            import torch
            if not torch.cuda.is_available():
                return None

            props = torch.cuda.get_device_properties(0)
            allocated = torch.cuda.memory_allocated(0)
            reserved = torch.cuda.memory_reserved(0)
            total = props.total_memory

            return {
                'device_name': props.name,
                'total_gb': round(total / (1024**3), 2),
                'allocated_gb': round(allocated / (1024**3), 2),
                'reserved_gb': round(reserved / (1024**3), 2),
                'free_gb': round((total - allocated) / (1024**3), 2),
                'utilization_percent': round((allocated / total) * 100, 1) if total > 0 else 0,
            }
        except ImportError:
            logger.debug("PyTorch not available")
            return None
        except Exception as e:
            logger.error(f"Error getting GPU memory: {e}")
            return None

    @staticmethod
    def get_system_memory_info() -> Dict:
        """Get system RAM information."""
        try:
            import psutil
            mem = psutil.virtual_memory()
            return {
                'total_gb': round(mem.total / (1024**3), 2),
                'available_gb': round(mem.available / (1024**3), 2),
                'used_gb': round(mem.used / (1024**3), 2),
                'percent': mem.percent,
            }
        except ImportError:
            return {
                'error': 'psutil not installed',
                'total_gb': 0,
                'available_gb': 0,
                'used_gb': 0,
                'percent': 0,
            }
        except Exception as e:
            logger.error(f"Error getting system memory: {e}")
            return {'error': str(e)}

    @staticmethod
    def clear_gpu_memory() -> bool:
        """Clear all GPU memory."""
        try:
            import torch
            if torch.cuda.is_available():
                # First unload all known backends
                MemoryManager._unload_all_backends()

                # Then clear CUDA cache
                torch.cuda.empty_cache()
                torch.cuda.synchronize()
                gc.collect()

                logger.info("GPU memory cleared")
                return True
        except ImportError:
            logger.debug("PyTorch not available")
        except Exception as e:
            logger.error(f"Error clearing GPU memory: {e}")
        return False

    @staticmethod
    def _unload_all_backends():
        """Unload all known model backends."""
        # Unload Imager backends
        try:
            from wama.imager.backends.manager import get_manager
            manager = get_manager()
            if hasattr(manager, '_instances'):
                for name, instance in list(manager._instances.items()):
                    try:
                        instance.unload()
                        logger.info(f"Unloaded imager backend: {name}")
                    except Exception as e:
                        logger.warning(f"Failed to unload {name}: {e}")
                manager._instances.clear()
        except Exception as e:
            logger.debug(f"Could not unload Imager backends: {e}")

        # Unload Describer models
        try:
            from wama.describer.utils import image_describer
            if hasattr(image_describer, '_blip_model') and image_describer._blip_model is not None:
                del image_describer._blip_model
                image_describer._blip_model = None
                logger.info("Unloaded BLIP model")
            if hasattr(image_describer, '_blip_processor') and image_describer._blip_processor is not None:
                del image_describer._blip_processor
                image_describer._blip_processor = None
                logger.info("Unloaded BLIP processor")
        except Exception as e:
            logger.debug(f"Could not unload Describer models: {e}")

        gc.collect()

    @staticmethod
    def unload_model(model_id: str) -> bool:
        """
        Unload a specific model from memory.

        Routes to the appropriate backend based on model_id prefix.
        """
        try:
            if model_id.startswith('imager:'):
                return MemoryManager._unload_imager_model(model_id)
            elif model_id.startswith('describer:'):
                return MemoryManager._unload_describer_model(model_id)
            elif model_id.startswith('anonymizer:'):
                return MemoryManager._unload_anonymizer_model(model_id)
            elif model_id.startswith('transcriber:'):
                return MemoryManager._unload_transcriber_model(model_id)
            elif model_id.startswith('synthesizer:'):
                return MemoryManager._unload_synthesizer_model(model_id)
            elif model_id.startswith('enhancer:'):
                return MemoryManager._unload_enhancer_model(model_id)
            elif model_id.startswith('ollama:'):
                # Ollama manages its own memory
                logger.info(f"Ollama models are managed by Ollama server: {model_id}")
                return True
            else:
                logger.warning(f"Unknown model source for: {model_id}")
                return False
        except Exception as e:
            logger.error(f"Error unloading model {model_id}: {e}")
            return False

    @staticmethod
    def _unload_imager_model(model_id: str) -> bool:
        """Unload an Imager backend model."""
        try:
            from wama.imager.backends.manager import get_manager
            manager = get_manager()

            # Unload all imager backends (they share GPU memory)
            if hasattr(manager, '_instances'):
                for name, instance in list(manager._instances.items()):
                    try:
                        instance.unload()
                    except Exception as e:
                        logger.warning(f"Failed to unload imager backend {name}: {e}")
                manager._instances.clear()

            gc.collect()

            try:
                import torch
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
            except ImportError:
                pass

            logger.info(f"Unloaded imager model: {model_id}")
            return True
        except Exception as e:
            logger.error(f"Error unloading imager model: {e}")
            return False

    @staticmethod
    def _unload_describer_model(model_id: str) -> bool:
        """Unload Describer global models."""
        try:
            from wama.describer.utils import image_describer

            if 'blip' in model_id:
                if hasattr(image_describer, '_blip_model'):
                    del image_describer._blip_model
                    image_describer._blip_model = None
                if hasattr(image_describer, '_blip_processor'):
                    del image_describer._blip_processor
                    image_describer._blip_processor = None

            gc.collect()

            try:
                import torch
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
            except ImportError:
                pass

            logger.info(f"Unloaded describer model: {model_id}")
            return True
        except Exception as e:
            logger.error(f"Error unloading describer model: {e}")
            return False

    @staticmethod
    def _unload_anonymizer_model(model_id: str) -> bool:
        """Unload Anonymizer models (YOLO, SAM3)."""
        try:
            # YOLO models are typically loaded per-request, not cached
            # SAM3 may have its own cache
            gc.collect()
            logger.info(f"Anonymizer model cleanup requested: {model_id}")
            return True
        except Exception as e:
            logger.error(f"Error unloading anonymizer model: {e}")
            return False

    @staticmethod
    def _unload_transcriber_model(model_id: str) -> bool:
        """
        Unload Transcriber models (ASR backends + pyannote diarizer).

        Was a no-op stub → the central reclaim could not free Transcriber's VRAM.
        Now delegates to the TranscriberManager (unloads the resident ASR backend)
        and to the pyannote diarizer pipeline cache.
        """
        freed = False
        # 1) ASR backends (whisper / qwen_asr / vibevoice) via leur manager
        try:
            from wama.transcriber.backends.manager import TranscriberBackendManager
            mgr = TranscriberBackendManager.get_instance()
            if any(getattr(i, 'is_loaded', False) for i in mgr._instances.values()):
                freed = True
            mgr.unload_all()  # décharge + vide le cache d'instances
        except Exception as e:
            logger.debug(f"Could not unload ASR backends: {e}")

        # 2) pyannote diarizer (pipeline caché module-level)
        try:
            from wama.transcriber.backends.pyannote_diarizer import unload_pipeline
            if unload_pipeline():
                freed = True
        except Exception as e:
            logger.debug(f"Could not unload pyannote pipeline: {e}")

        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:
            pass
        gc.collect()
        logger.info(f"Transcriber model cleanup done (freed={freed}): {model_id}")
        return True

    @staticmethod
    def _unload_synthesizer_model(model_id: str) -> bool:
        """Unload Synthesizer models (Coqui, Bark)."""
        try:
            gc.collect()
            logger.info(f"Synthesizer model cleanup requested: {model_id}")
            return True
        except Exception as e:
            logger.error(f"Error unloading synthesizer model: {e}")
            return False

    @staticmethod
    def _unload_enhancer_model(model_id: str) -> bool:
        """Unload Enhancer models (ONNX)."""
        try:
            # ONNX models are loaded per-request typically
            gc.collect()
            logger.info(f"Enhancer model cleanup requested: {model_id}")
            return True
        except Exception as e:
            logger.error(f"Error unloading enhancer model: {e}")
            return False

    # =========================================================================
    # GPU Memory Strategy Management
    # =========================================================================

    @staticmethod
    def get_memory_strategy(
        model_size_gb: float,
        headroom_gb: float = 2.0,
        prefer_speed: bool = True
    ) -> MemoryStrategy:
        """
        Determine the optimal memory strategy based on model size and available VRAM.

        Args:
            model_size_gb: Estimated model size in GB
            headroom_gb: Extra VRAM to keep free for activations/inference (default: 2GB)
            prefer_speed: If True, prefer faster strategies when possible

        Returns:
            MemoryStrategy enum indicating the recommended strategy
        """
        gpu_info = MemoryManager.get_gpu_memory_info()

        if gpu_info is None:
            logger.info(f"[MemoryManager] No GPU available, using CPU only")
            return MemoryStrategy.CPU_ONLY

        total_vram = gpu_info['total_gb']
        free_vram = gpu_info['free_gb']
        required_vram = model_size_gb + headroom_gb

        logger.info(f"[MemoryManager] VRAM: {total_vram:.1f}GB total, {free_vram:.1f}GB free")
        logger.info(f"[MemoryManager] Model needs ~{model_size_gb:.1f}GB + {headroom_gb:.1f}GB headroom = {required_vram:.1f}GB")

        # Strategy selection based on available VRAM
        if free_vram >= required_vram:
            # Enough VRAM for full GPU loading
            logger.info(f"[MemoryManager] Strategy: FULL_GPU (sufficient VRAM)")
            return MemoryStrategy.FULL_GPU

        elif total_vram >= required_vram:
            # Total VRAM is enough, but need to free some first
            # Use model offload which loads components as needed
            logger.info(f"[MemoryManager] Strategy: MODEL_OFFLOAD (VRAM sufficient after cleanup)")
            return MemoryStrategy.MODEL_OFFLOAD

        elif total_vram >= model_size_gb * 0.6:
            # VRAM can hold ~60% of model - use model offload
            logger.info(f"[MemoryManager] Strategy: MODEL_OFFLOAD (VRAM can hold partial model)")
            return MemoryStrategy.MODEL_OFFLOAD

        elif total_vram >= model_size_gb * 0.3:
            # VRAM can hold ~30% of model - use sequential offload
            logger.info(f"[MemoryManager] Strategy: SEQUENTIAL_OFFLOAD (limited VRAM)")
            return MemoryStrategy.SEQUENTIAL_OFFLOAD

        else:
            # Very limited VRAM - sequential offload or CPU
            if total_vram >= 4:  # At least 4GB for basic GPU acceleration
                logger.info(f"[MemoryManager] Strategy: SEQUENTIAL_OFFLOAD (minimal VRAM)")
                return MemoryStrategy.SEQUENTIAL_OFFLOAD
            else:
                logger.info(f"[MemoryManager] Strategy: CPU_ONLY (insufficient VRAM)")
                return MemoryStrategy.CPU_ONLY

    @staticmethod
    def get_strategy_for_model(model_type: str, headroom_gb: float = 2.0) -> MemoryStrategy:
        """
        Get memory strategy for a known model type.

        Args:
            model_type: Model type key (e.g., 'flux', 'sdxl', 'whisper-large')
            headroom_gb: Extra VRAM to keep free

        Returns:
            MemoryStrategy for the model
        """
        model_size = MODEL_SIZE_PRESETS.get(model_type.lower(), 4.0)  # Default 4GB
        return MemoryManager.get_memory_strategy(model_size, headroom_gb)

    @staticmethod
    def apply_memory_strategy(
        pipeline,
        strategy: MemoryStrategy,
        device: str = "cuda"
    ):
        """
        Apply a memory strategy to a Diffusers pipeline.

        Includes automatic fallback chain: FULL_GPU -> MODEL_OFFLOAD -> SEQUENTIAL_OFFLOAD
        This handles CUDA errors gracefully.

        Args:
            pipeline: A Diffusers pipeline object
            strategy: The MemoryStrategy to apply
            device: Target device ('cuda', 'cpu')

        Returns:
            The pipeline with the strategy applied
        """
        import torch

        _cap_cuda_allocator()

        def reset_cuda_state():
            """Reset CUDA state after errors."""
            if torch.cuda.is_available():
                try:
                    torch.cuda.synchronize()
                    torch.cuda.empty_cache()
                    gc.collect()
                    logger.info("[MemoryManager] CUDA state reset")
                except Exception:
                    pass

        def try_full_gpu():
            """
            Move each pipeline component to GPU one at a time with a CUDA sync
            between each.  This avoids the monolithic pipeline.to("cuda") call
            which, under WSL2/WDDM, iterates thousands of tensors individually
            in Python — each CUDA malloc taking ~8 ms, yielding 10–15 minutes
            total and eventually triggering Windows TDR.
            """
            nonlocal pipeline
            logger.info(f"[MemoryManager] Applying FULL_GPU strategy (per-component)")
            moved_any = False
            for attr in ('transformer', 'unet', 'denoising_unet', 'vae',
                         'text_encoder', 'text_encoder_2', 'image_encoder'):
                component = getattr(pipeline, attr, None)
                if component is None or not hasattr(component, 'parameters'):
                    continue

                # Re-vérifier AVANT chaque déplacement : la stratégie a été décidée une
                # seule fois sur une taille de modèle DÉCLARÉE (presets), qui peut être
                # très sous-estimée. Sans ce contrôle, un composant trop gros ne lève pas
                # d'OOM sous WDDM — il déborde en RAM hôte et fait paniquer le noyau WSL
                # (cf. _cap_cuda_allocator). On échoue net pour tomber sur MODEL_OFFLOAD.
                #
                # On passe par la brique COMMUNE ensure_free_vram (mesure → reclaim des
                # unloaders enregistrés → re-mesure) : un composant qui ne tient pas
                # seulement parce qu'une AUTRE app squatte la VRAM doit d'abord
                # déclencher un reclaim, pas faire échouer FULL_GPU.
                size_gb = _component_size_gb(component)
                if size_gb and not MemoryManager.ensure_free_vram(
                    size_gb, headroom_gb=FULL_GPU_MIN_FREE_GB
                ):
                    info = MemoryManager.get_gpu_memory_info() or {}
                    raise RuntimeError(
                        f"CUDA out of memory (pré-contrôle FULL_GPU) : {attr} pèse "
                        f"{size_gb:.1f} GB, seulement {info.get('free_gb', 0):.1f} GB "
                        f"libres après reclaim (marge requise {FULL_GPU_MIN_FREE_GB:.1f} GB)"
                    )

                logger.info(f"[MemoryManager]   → moving {attr} to {device} ({size_gb:.1f} GB)…")
                setattr(pipeline, attr, component.to(device))
                torch.cuda.synchronize()
                vram = torch.cuda.memory_allocated() / (1024 ** 3)
                logger.info(f"[MemoryManager]   ✓ {attr} on {device} (VRAM used: {vram:.1f} GB)")
                moved_any = True
            if not moved_any:
                # Fallback for pipelines with non-standard component names
                pipeline = pipeline.to(device)
            logger.info(f"[MemoryManager] Pipeline loaded fully on {device}")
            return True

        def try_model_offload():
            """Try model CPU offload."""
            nonlocal pipeline
            logger.info(f"[MemoryManager] Applying MODEL_OFFLOAD strategy")
            pipeline.enable_model_cpu_offload()
            logger.info(f"[MemoryManager] Model CPU offload enabled")
            return True

        def try_sequential_offload():
            """Try sequential CPU offload."""
            nonlocal pipeline
            logger.info(f"[MemoryManager] Applying SEQUENTIAL_OFFLOAD strategy")
            pipeline.enable_sequential_cpu_offload()
            logger.info(f"[MemoryManager] Sequential CPU offload enabled")
            return True

        try:
            if strategy == MemoryStrategy.FULL_GPU:
                try:
                    try_full_gpu()
                except Exception as e:
                    error_str = str(e).lower()
                    if 'cuda' in error_str or 'out of memory' in error_str:
                        logger.warning(f"[MemoryManager] FULL_GPU failed ({e}), falling back to MODEL_OFFLOAD")
                        reset_cuda_state()
                        try:
                            try_model_offload()
                        except Exception as e2:
                            logger.warning(f"[MemoryManager] MODEL_OFFLOAD failed ({e2}), trying SEQUENTIAL_OFFLOAD")
                            reset_cuda_state()
                            try_sequential_offload()
                    else:
                        raise

            elif strategy == MemoryStrategy.MODEL_OFFLOAD:
                try:
                    try_model_offload()
                except Exception as e:
                    logger.warning(f"[MemoryManager] MODEL_OFFLOAD failed ({e}), trying SEQUENTIAL_OFFLOAD")
                    reset_cuda_state()
                    try:
                        try_sequential_offload()
                    except Exception as e2:
                        logger.warning(f"[MemoryManager] SEQUENTIAL_OFFLOAD failed ({e2}), trying FULL_GPU")
                        reset_cuda_state()
                        try_full_gpu()

            elif strategy == MemoryStrategy.SEQUENTIAL_OFFLOAD:
                try:
                    try_sequential_offload()
                except Exception as e:
                    logger.warning(f"[MemoryManager] SEQUENTIAL_OFFLOAD failed ({e}), trying MODEL_OFFLOAD")
                    reset_cuda_state()
                    try:
                        try_model_offload()
                    except Exception as e2:
                        logger.warning(f"[MemoryManager] MODEL_OFFLOAD also failed ({e2})")
                        raise

            elif strategy == MemoryStrategy.CPU_ONLY:
                logger.info(f"[MemoryManager] Applying CPU_ONLY strategy")
                pipeline = pipeline.to("cpu")
                logger.info(f"[MemoryManager] Pipeline loaded on CPU")

            return pipeline

        except Exception as e:
            logger.error(f"[MemoryManager] All strategies failed: {e}")
            # Last resort - try sequential offload (most stable)
            reset_cuda_state()
            try:
                logger.info("[MemoryManager] Last resort: trying sequential CPU offload")
                pipeline.enable_sequential_cpu_offload()
                logger.info("[MemoryManager] Sequential CPU offload enabled as last resort")
            except Exception as e2:
                logger.error(f"[MemoryManager] Last resort also failed: {e2}")
            return pipeline

    # =========================================================================
    # Pipeline Loading (centralized format handling)
    # =========================================================================

    @staticmethod
    def load_pipeline(pipeline_class, model_id: str, **kwargs):
        """
        Load a Diffusers pipeline with automatic safetensors-to-bin fallback.

        Centralizes format handling so backends don't duplicate this logic.
        Tries safetensors first (faster, safer), falls back to .bin if unavailable.

        Args:
            pipeline_class: The Diffusers pipeline class (e.g., StableDiffusionPipeline)
            model_id: HuggingFace model ID or local path
            **kwargs: Additional arguments passed to from_pretrained()

        Returns:
            The loaded pipeline instance
        """
        try:
            return pipeline_class.from_pretrained(model_id, **kwargs)
        except EnvironmentError as e:
            if kwargs.get('use_safetensors', False):
                logger.warning(
                    f"[MemoryManager] No safetensors weights found for {model_id}, "
                    f"falling back to PyTorch .bin format"
                )
                kwargs['use_safetensors'] = False
                return pipeline_class.from_pretrained(model_id, **kwargs)
            raise

    @staticmethod
    def load_single_file_pipeline(pipeline_class, repo_id: str, filename: str, cache_dir: str = None, **kwargs):
        """
        Load a Diffusers pipeline from a single safetensors/ckpt file on HuggingFace.

        Used for models that are distributed as single checkpoint files
        (e.g., XpucT/Deliberate) rather than in diffusers multi-folder format.

        Downloads the file first using hf_hub_download (with progress tracking
        and proper caching), then loads from the local path.

        Args:
            pipeline_class: The Diffusers pipeline class (e.g., StableDiffusionPipeline)
            repo_id: HuggingFace repo ID (e.g., 'XpucT/Deliberate')
            filename: Weight file name (e.g., 'Deliberate_v6.safetensors')
            cache_dir: Optional cache directory for downloaded files
            **kwargs: Additional arguments passed to from_single_file()

        Returns:
            The loaded pipeline instance
        """
        from huggingface_hub import hf_hub_download

        logger.info(f"[MemoryManager] Loading single-file model: {repo_id}/{filename}")

        # Download to cache first (with progress bar and proper caching)
        download_kwargs = {"repo_id": repo_id, "filename": filename}
        if cache_dir:
            download_kwargs["cache_dir"] = cache_dir
        logger.info(f"[MemoryManager] Downloading {filename} from {repo_id} (cache: {cache_dir or 'default'})...")
        local_path = hf_hub_download(**download_kwargs)
        logger.info(f"[MemoryManager] File ready: {local_path}")

        return pipeline_class.from_single_file(local_path, **kwargs)

    @staticmethod
    def apply_strategy_for_model(
        pipeline,
        model_type: str,
        device: str = "cuda",
        headroom_gb: float = 2.0
    ):
        """
        Convenience method: determine and apply the best strategy for a model type.

        Args:
            pipeline: A Diffusers pipeline object
            model_type: Model type key (e.g., 'flux', 'sdxl')
            device: Target device
            headroom_gb: Extra VRAM headroom

        Returns:
            The pipeline with the optimal strategy applied
        """
        strategy = MemoryManager.get_strategy_for_model(model_type, headroom_gb)
        return MemoryManager.apply_memory_strategy(pipeline, strategy, device)

    @staticmethod
    def apply_offload_strategy(
        pipeline,
        model_size_gb: float,
        device: str = "cuda",
        headroom_gb: float = 2.0,
    ) -> tuple:
        """
        Select the optimal memory strategy for the given model size, apply it,
        and return ``(pipeline, is_on_gpu)``.

        ``is_on_gpu`` is True when the pipeline was placed entirely on GPU
        (faster, no Windows TDR risk from long GPU-idle periods).
        It is False when CPU offload is active (MODEL_OFFLOAD / SEQUENTIAL_OFFLOAD),
        in which case callers must use a CPU torch.Generator.

        On RTX 4090 (24 GB), any model ≤ 20 GB with headroom_gb=4 will use
        FULL_GPU automatically.  Callers should pass headroom_gb=4.0 for
        heavy diffusion models.

        Typical usage::

            self._pipe, is_on_gpu = MemoryManager.apply_offload_strategy(
                self._pipe, model_size_gb=16.0, headroom_gb=4.0
            )
            self._cpu_offload = not is_on_gpu
        """
        import torch

        strategy = MemoryManager.get_memory_strategy(model_size_gb, headroom_gb)
        pipeline = MemoryManager.apply_memory_strategy(pipeline, strategy, device)

        # Detect actual placement by probing the main denoising component.
        # After .to("cuda") all parameters are on CUDA.
        # After enable_{model,sequential}_cpu_offload they remain on CPU.
        is_on_gpu = False
        if torch.cuda.is_available():
            for attr in ('transformer', 'unet', 'denoising_unet'):
                component = getattr(pipeline, attr, None)
                if component is not None:
                    try:
                        param = next(component.parameters(), None)
                        if param is not None:
                            is_on_gpu = (param.device.type == 'cuda')
                    except Exception:
                        pass
                    break

        placement = 'CUDA (full GPU)' if is_on_gpu else 'CPU offload'
        logger.info(f"[MemoryManager] Pipeline placement: {placement}")
        return pipeline, is_on_gpu

    @staticmethod
    def estimate_model_size(model_path: str) -> float:
        """
        Estimate model size from file path or known patterns.

        Args:
            model_path: Path or identifier of the model

        Returns:
            Estimated size in GB
        """
        import os

        path_lower = model_path.lower()

        # Check against known presets
        for key, size in MODEL_SIZE_PRESETS.items():
            if key in path_lower:
                return size

        # Try to get actual file size
        if os.path.isfile(model_path):
            try:
                size_bytes = os.path.getsize(model_path)
                # Model in memory is typically larger than file (decompression, buffers)
                return (size_bytes / (1024**3)) * 1.3
            except Exception:
                pass

        # Default estimate based on common patterns
        if 'xl' in path_lower or 'xlarge' in path_lower:
            return 6.0
        elif 'large' in path_lower or '-l' in path_lower:
            return 4.0
        elif 'medium' in path_lower or '-m' in path_lower:
            return 2.0
        elif 'small' in path_lower or '-s' in path_lower:
            return 1.0
        elif 'nano' in path_lower or 'tiny' in path_lower or '-n' in path_lower:
            return 0.5

        # Conservative default
        return 4.0
