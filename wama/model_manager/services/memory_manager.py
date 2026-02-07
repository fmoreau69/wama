"""
Memory Manager - GPU/RAM memory utilities for model management.

Provides centralized VRAM management and CPU offload strategies for all WAMA applications.
"""

import gc
import logging
from typing import Dict, Optional, Literal
from enum import Enum

logger = logging.getLogger(__name__)


class MemoryStrategy(Enum):
    """Memory loading strategies for AI models."""
    FULL_GPU = "full_gpu"              # Load entirely on GPU (fastest)
    MODEL_OFFLOAD = "model_offload"    # Move model components to GPU as needed (moderate)
    SEQUENTIAL_OFFLOAD = "sequential"  # Move layers to GPU one at a time (slowest, least VRAM)
    CPU_ONLY = "cpu"                   # Run entirely on CPU (no GPU)


# Model size categories in GB (approximate VRAM requirements)
MODEL_SIZE_PRESETS = {
    # Diffusion models
    'flux': 12.0,
    'flux-dev': 12.0,
    'flux-schnell': 12.0,
    'sdxl': 7.0,
    'sd15': 4.0,
    'sd21': 5.0,
    'hunyuan-image': 16.0,

    # Video models
    'hunyuan-video': 24.0,
    'cogvideox': 16.0,
    'ltx-video': 12.0,
    'mochi': 18.0,
    'wan-t2v': 14.0,
    'wan-i2v': 28.0,

    # Vision models
    'yolo-nano': 0.5,
    'yolo-small': 1.0,
    'yolo-medium': 2.0,
    'yolo-large': 4.0,
    'yolo-xlarge': 6.0,
    'sam3-tiny': 1.5,
    'sam3-base': 3.0,
    'sam3-large': 6.0,

    # Audio models
    'whisper-tiny': 0.5,
    'whisper-base': 0.8,
    'whisper-small': 1.5,
    'whisper-medium': 3.0,
    'whisper-large': 6.0,

    # LLM/Multimodal
    'blip': 2.0,
    'blip2': 4.0,
}


class MemoryManager:
    """Manages GPU and system memory for AI models."""

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
        """Unload Transcriber models (Whisper)."""
        try:
            # Whisper models are typically loaded per-request
            gc.collect()
            logger.info(f"Transcriber model cleanup requested: {model_id}")
            return True
        except Exception as e:
            logger.error(f"Error unloading transcriber model: {e}")
            return False

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
            """Try to load fully on GPU."""
            nonlocal pipeline
            logger.info(f"[MemoryManager] Applying FULL_GPU strategy")
            pipeline = pipeline.to(device)
            # Verify it worked by doing a simple operation
            if hasattr(pipeline, 'unet') and pipeline.unet is not None:
                _ = next(pipeline.unet.parameters()).device
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

        Args:
            pipeline_class: The Diffusers pipeline class (e.g., StableDiffusionPipeline)
            repo_id: HuggingFace repo ID (e.g., 'XpucT/Deliberate')
            filename: Weight file name (e.g., 'Deliberate_v6.safetensors')
            cache_dir: Optional cache directory for downloaded files
            **kwargs: Additional arguments passed to from_single_file()

        Returns:
            The loaded pipeline instance
        """
        # Build HuggingFace URL for from_single_file
        hf_url = f"https://huggingface.co/{repo_id}/blob/main/{filename}"
        logger.info(f"[MemoryManager] Loading single-file model: {repo_id}/{filename}")

        return pipeline_class.from_single_file(hf_url, **kwargs)

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
