"""
Model Registry - Unified model discovery across all WAMA apps and external sources.
"""

import logging
import subprocess
import re
from pathlib import Path
from typing import Dict, List, Optional
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


def _check_hf_model_downloaded(cache_dir: Path, hf_id: str) -> bool:
    """
    Check if a HuggingFace model is downloaded in the cache directory.

    HuggingFace cache structure: models--<org>--<model>/snapshots/<hash>/
    """
    if not cache_dir or not hf_id:
        return False

    try:
        cache_dir = Path(cache_dir)
        if not cache_dir.exists():
            return False

        # Convert hf_id to cache folder name (e.g., "Wan-AI/Wan2.2-T2V" -> "models--Wan-AI--Wan2.2-T2V")
        folder_name = f"models--{hf_id.replace('/', '--')}"
        model_path = cache_dir / folder_name

        # Simple check: if the model folder exists, consider it downloaded
        if model_path.exists() and model_path.is_dir():
            # Verify it has some content (snapshots or blobs)
            snapshots = model_path / "snapshots"
            blobs = model_path / "blobs"
            if snapshots.exists() or blobs.exists():
                return True

        # Scan cache dir for matching folders (handles nested/varied structures)
        try:
            for path in cache_dir.iterdir():
                if path.is_dir() and folder_name in path.name:
                    return True
        except (PermissionError, OSError):
            pass

    except Exception as e:
        logger.debug(f"Error checking HF model {hf_id}: {e}")

    return False


class ModelType(Enum):
    VISION = "vision"
    DIFFUSION = "diffusion"
    SPEECH = "speech"
    VLM = "vlm"
    LLM = "llm"
    SUMMARIZATION = "summarization"
    UPSCALING = "upscaling"


class ModelSource(Enum):
    WAMA_IMAGER = "imager"
    WAMA_DESCRIBER = "describer"
    WAMA_ANONYMIZER = "anonymizer"
    WAMA_TRANSCRIBER = "transcriber"
    WAMA_SYNTHESIZER = "synthesizer"
    WAMA_ENHANCER = "enhancer"
    OLLAMA = "ollama"


@dataclass
class ModelInfo:
    """Unified model information structure."""
    id: str
    name: str
    model_type: ModelType
    source: ModelSource
    description: str = ""
    hf_id: Optional[str] = None
    vram_gb: float = 0
    ram_gb: float = 0
    is_loaded: bool = False
    is_downloaded: bool = False
    backend_ref: Optional[str] = None
    extra_info: Dict = field(default_factory=dict)


class ModelRegistry:
    """Central registry for all WAMA models."""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._models: Dict[str, ModelInfo] = {}
        self._initialized = True

    def discover_all_models(self) -> Dict[str, ModelInfo]:
        """Discover models from all sources."""
        self._models.clear()

        self._discover_imager_models()
        self._discover_describer_models()
        self._discover_anonymizer_models()
        self._discover_transcriber_models()
        self._discover_synthesizer_models()
        self._discover_enhancer_models()
        self._discover_ollama_models()

        return self._models

    def get_models_by_type(self, model_type: ModelType) -> List[ModelInfo]:
        """Get all models of a specific type."""
        return [m for m in self._models.values() if m.model_type == model_type]

    def get_loaded_models(self) -> List[ModelInfo]:
        """Get all currently loaded models."""
        return [m for m in self._models.values() if m.is_loaded]

    def _discover_imager_models(self):
        """Discover Imager app models (SD, Wan, Hunyuan)."""
        try:
            from wama.imager.utils.model_config import (
                IMAGER_MODELS, WAN_MODELS, HUNYUAN_MODELS,
                WAN_DIR, HUNYUAN_DIR, STABLE_DIFFUSION_DIR
            )
            from django.conf import settings

            # Check for loaded backends
            loaded_model = None
            try:
                from wama.imager.backends.manager import get_manager
                manager = get_manager()
                if hasattr(manager, '_instances') and manager._instances:
                    for backend in manager._instances.values():
                        if hasattr(backend, '_current_model') and backend._current_model:
                            loaded_model = backend._current_model
                            break
            except Exception:
                pass

            # HuggingFace cache directory
            hf_cache = settings.MODEL_PATHS.get('cache', {}).get('huggingface')

            for model_id, config in IMAGER_MODELS.items():
                is_loaded = model_id == loaded_model
                hf_id = config.get('hf_id')

                # Determine cache directory based on model type
                if model_id in WAN_MODELS:
                    cache_dir = Path(WAN_DIR)
                elif model_id in HUNYUAN_MODELS:
                    cache_dir = Path(HUNYUAN_DIR)
                else:
                    cache_dir = Path(STABLE_DIFFUSION_DIR)

                # Check if model is downloaded
                is_downloaded = _check_hf_model_downloaded(cache_dir, hf_id)

                # Also check main HF cache if not found
                if not is_downloaded and hf_cache:
                    is_downloaded = _check_hf_model_downloaded(Path(hf_cache), hf_id)

                name = config.get('description', model_id)

                self._models[f"imager:{model_id}"] = ModelInfo(
                    id=f"imager:{model_id}",
                    name=name,
                    model_type=ModelType.DIFFUSION,
                    source=ModelSource.WAMA_IMAGER,
                    description=config.get('description', ''),
                    hf_id=hf_id,
                    vram_gb=config.get('vram_gb', 4),
                    is_loaded=is_loaded,
                    is_downloaded=is_downloaded,
                    backend_ref='imager',
                )
        except ImportError as e:
            logger.debug(f"Could not import Imager models: {e}")

    def _discover_describer_models(self):
        """Discover Describer app models (BLIP, BART, Whisper)."""
        try:
            from wama.describer.utils.model_config import DESCRIBER_MODELS
            from django.conf import settings

            # Check if BLIP is loaded
            blip_loaded = False
            try:
                from wama.describer.utils.image_describer import _blip_model
                blip_loaded = _blip_model is not None
            except Exception:
                pass

            # HuggingFace cache directory
            hf_cache = settings.MODEL_PATHS.get('cache', {}).get('huggingface')
            vlm_dir = settings.MODEL_PATHS.get('vision_language', {}).get('root')

            for model_id, config in DESCRIBER_MODELS.items():
                model_type = ModelType.VLM
                if config.get('type') == 'summarization':
                    model_type = ModelType.SUMMARIZATION
                elif config.get('type') == 'speech-to-text':
                    model_type = ModelType.SPEECH

                is_loaded = model_id == 'blip' and blip_loaded
                hf_id = config.get('model_id')

                # Check if model is downloaded
                is_downloaded = False
                if hf_cache:
                    is_downloaded = _check_hf_model_downloaded(Path(hf_cache), hf_id)
                if not is_downloaded and vlm_dir:
                    is_downloaded = _check_hf_model_downloaded(Path(vlm_dir), hf_id)

                self._models[f"describer:{model_id}"] = ModelInfo(
                    id=f"describer:{model_id}",
                    name=config.get('model_id', model_id),
                    model_type=model_type,
                    source=ModelSource.WAMA_DESCRIBER,
                    description=config.get('description', ''),
                    hf_id=hf_id,
                    vram_gb=config.get('size_gb', 2),
                    is_loaded=is_loaded,
                    is_downloaded=is_downloaded,
                    backend_ref='describer',
                )
        except ImportError as e:
            logger.debug(f"Could not import Describer models: {e}")

    def _discover_anonymizer_models(self):
        """Discover Anonymizer app models (YOLO, SAM3)."""
        try:
            from wama.anonymizer.utils.model_config import list_available_yolo_models

            yolo_models = list_available_yolo_models()
            for model_type, models in yolo_models.items():
                for model in models:
                    model_name = model['name']
                    specialty = model.get('specialty', '')
                    desc = f"YOLO {model_type}"
                    if specialty:
                        desc += f" ({specialty})"

                    # Size in MB to GB
                    size_gb = model.get('size', 0) / (1024 * 1024 * 1024)

                    self._models[f"anonymizer:yolo:{model_name}"] = ModelInfo(
                        id=f"anonymizer:yolo:{model_name}",
                        name=model_name,
                        model_type=ModelType.VISION,
                        source=ModelSource.WAMA_ANONYMIZER,
                        description=desc,
                        vram_gb=round(size_gb * 2, 1),  # Estimate VRAM as 2x model size
                        is_downloaded=True,
                        extra_info={'path': model.get('path', ''), 'type': model_type},
                        backend_ref='anonymizer',
                    )

            # Add SAM3 if available
            try:
                from wama.anonymizer.utils.sam3_manager import get_sam3_status
                status = get_sam3_status()
                self._models["anonymizer:sam3"] = ModelInfo(
                    id="anonymizer:sam3",
                    name="SAM3 (Segment Anything)",
                    model_type=ModelType.VISION,
                    source=ModelSource.WAMA_ANONYMIZER,
                    description="Meta SAM3 - Text-prompted segmentation",
                    vram_gb=3.0,
                    is_downloaded=status.get('models_cached', False),
                    extra_info=status,
                    backend_ref='anonymizer',
                )
            except Exception:
                pass

        except ImportError as e:
            logger.debug(f"Could not import Anonymizer models: {e}")

    def _discover_transcriber_models(self):
        """Discover Transcriber app models (Whisper)."""
        try:
            from wama.transcriber.utils.model_config import WHISPER_MODELS

            for model_id, config in WHISPER_MODELS.items():
                self._models[f"transcriber:{model_id}"] = ModelInfo(
                    id=f"transcriber:{model_id}",
                    name=f"Whisper {model_id}",
                    model_type=ModelType.SPEECH,
                    source=ModelSource.WAMA_TRANSCRIBER,
                    description=config.get('description', f"OpenAI Whisper {model_id}"),
                    vram_gb=config.get('size_gb', 0.5),
                    is_downloaded=config.get('downloaded', False),
                    backend_ref='transcriber',
                )
        except ImportError as e:
            logger.debug(f"Could not import Transcriber models: {e}")

    def _discover_synthesizer_models(self):
        """Discover Synthesizer app models (Coqui, Bark)."""
        try:
            # Add known synthesizer models
            self._models["synthesizer:coqui-xtts"] = ModelInfo(
                id="synthesizer:coqui-xtts",
                name="Coqui XTTS v2",
                model_type=ModelType.SPEECH,
                source=ModelSource.WAMA_SYNTHESIZER,
                description="Multilingual TTS with voice cloning",
                vram_gb=2.0,
                ram_gb=4.0,
                backend_ref='synthesizer',
            )

            self._models["synthesizer:bark"] = ModelInfo(
                id="synthesizer:bark",
                name="Bark TTS",
                model_type=ModelType.SPEECH,
                source=ModelSource.WAMA_SYNTHESIZER,
                description="Expressive TTS with sound effects",
                vram_gb=4.0,
                ram_gb=8.0,
                backend_ref='synthesizer',
            )
        except Exception as e:
            logger.debug(f"Could not add Synthesizer models: {e}")

    def _discover_enhancer_models(self):
        """Discover Enhancer app models (ONNX upscalers)."""
        try:
            from django.conf import settings

            onnx_dir = settings.MODEL_PATHS.get('upscaling', {}).get('onnx')
            if onnx_dir and Path(onnx_dir).exists():
                for onnx_file in Path(onnx_dir).glob('*.onnx'):
                    model_name = onnx_file.stem
                    size_mb = onnx_file.stat().st_size / (1024 * 1024)

                    self._models[f"enhancer:{model_name}"] = ModelInfo(
                        id=f"enhancer:{model_name}",
                        name=model_name,
                        model_type=ModelType.UPSCALING,
                        source=ModelSource.WAMA_ENHANCER,
                        description=f"ONNX upscaling model ({size_mb:.1f}MB)",
                        vram_gb=round(size_mb / 500, 1),  # Estimate
                        is_downloaded=True,
                        extra_info={'path': str(onnx_file), 'size_mb': size_mb},
                        backend_ref='enhancer',
                    )
        except Exception as e:
            logger.debug(f"Could not discover Enhancer models: {e}")

    def _discover_ollama_models(self):
        """Discover Ollama models (with short timeout to avoid blocking)."""
        try:
            # Try to get list of installed Ollama models with short timeout
            result = subprocess.run(
                ['ollama', 'list'],
                capture_output=True,
                text=True,
                timeout=2,  # Short timeout to avoid blocking page load
                creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0
            )

            if result.returncode == 0:
                lines = result.stdout.strip().split('\n')[1:]  # Skip header
                for line in lines:
                    if not line.strip():
                        continue
                    parts = line.split()
                    if len(parts) >= 2:
                        model_name = parts[0]
                        model_size = parts[1] if len(parts) > 1 else 'unknown'

                        # Parse size (e.g., "4.7 GB" -> 4.7)
                        ram_gb = 0
                        try:
                            size_str = parts[1].replace('GB', '').replace('MB', '').strip()
                            ram_gb = float(size_str)
                            if 'MB' in parts[1]:
                                ram_gb /= 1024
                        except (ValueError, IndexError):
                            pass

                        self._models[f"ollama:{model_name}"] = ModelInfo(
                            id=f"ollama:{model_name}",
                            name=model_name,
                            model_type=ModelType.LLM,
                            source=ModelSource.OLLAMA,
                            description=f"Ollama LLM ({model_size})",
                            ram_gb=ram_gb,
                            is_downloaded=True,
                            backend_ref='ollama',
                        )
        except FileNotFoundError:
            logger.debug("Ollama not installed")
        except subprocess.TimeoutExpired:
            logger.warning("Ollama command timed out - skipping Ollama models")
        except Exception as e:
            logger.debug(f"Could not discover Ollama models: {e}")
