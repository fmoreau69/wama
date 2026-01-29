"""
Memory Manager - GPU/RAM memory utilities for model management.
"""

import gc
import logging
from typing import Dict, Optional

logger = logging.getLogger(__name__)


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
