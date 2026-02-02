"""
Model Registry - Unified model discovery across all WAMA apps and external sources.
"""

import json
import logging
import os
import subprocess
import sys
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
    # Format policy fields
    format: str = ""  # Current format: 'pt', 'safetensors', 'onnx', 'bin', etc.
    preferred_format: str = ""  # Recommended format per policy
    can_convert_to: List[str] = field(default_factory=list)  # Available conversions


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

        logger.info("[ModelRegistry] Starting model discovery...")

        self._discover_imager_models()
        self._discover_describer_models()
        self._discover_anonymizer_models()
        self._discover_transcriber_models()
        self._discover_synthesizer_models()
        self._discover_enhancer_models()
        self._discover_ollama_models()

        # Log summary
        formats_found = {}
        preferred_formats_found = {}
        for model in self._models.values():
            fmt = model.format or 'EMPTY'
            pref = model.preferred_format or 'EMPTY'
            formats_found[fmt] = formats_found.get(fmt, 0) + 1
            preferred_formats_found[pref] = preferred_formats_found.get(pref, 0) + 1

        logger.info(
            f"[ModelRegistry] Discovery complete. Total: {len(self._models)} models. "
            f"Formats: {formats_found}. Preferred: {preferred_formats_found}"
        )

        return self._models

    def get_models_by_type(self, model_type: ModelType) -> List[ModelInfo]:
        """Get all models of a specific type."""
        return [m for m in self._models.values() if m.model_type == model_type]

    def get_loaded_models(self) -> List[ModelInfo]:
        """Get all currently loaded models."""
        return [m for m in self._models.values() if m.is_loaded]

    def _discover_imager_models(self):
        """Discover Imager app models (SD, Wan, Hunyuan, CogVideoX, LTX, Mochi)."""
        try:
            from wama.imager.utils.model_config import (
                IMAGER_MODELS, WAN_MODELS, HUNYUAN_MODELS,
                COGVIDEOX_MODELS, LTX_MODELS, MOCHI_MODELS,
                WAN_DIR, HUNYUAN_DIR, STABLE_DIFFUSION_DIR,
                COGVIDEOX_DIR, LTX_DIR, MOCHI_DIR
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
                elif model_id in COGVIDEOX_MODELS:
                    cache_dir = Path(COGVIDEOX_DIR)
                elif model_id in LTX_MODELS:
                    cache_dir = Path(LTX_DIR)
                elif model_id in MOCHI_MODELS:
                    cache_dir = Path(MOCHI_DIR)
                else:
                    cache_dir = Path(STABLE_DIFFUSION_DIR)

                # Check if model is downloaded
                is_downloaded = _check_hf_model_downloaded(cache_dir, hf_id)

                # Also check main HF cache if not found
                if not is_downloaded and hf_cache:
                    is_downloaded = _check_hf_model_downloaded(Path(hf_cache), hf_id)

                name = config.get('description', model_id)

                # Detect format from HuggingFace cache directory
                model_format = ''
                if is_downloaded and hf_id:
                    # Try to detect format from the model's specific cache folder
                    hf_folder_name = f"models--{hf_id.replace('/', '--')}"
                    specific_cache = cache_dir / hf_folder_name
                    if specific_cache.exists():
                        model_format = self._detect_model_format(str(specific_cache))
                        logger.debug(f"[ModelRegistry] {model_id}: Detected format from specific cache: {model_format}")
                    # Fallback to parent directory
                    if not model_format:
                        model_format = self._detect_model_format(str(cache_dir))
                        if model_format:
                            logger.debug(f"[ModelRegistry] {model_id}: Detected format from parent dir: {model_format}")
                    # Default for diffusion models if nothing found
                    if not model_format:
                        model_format = 'safetensors'  # Most HF models use safetensors now
                        logger.debug(f"[ModelRegistry] {model_id}: Using default format: safetensors")
                else:
                    # For non-downloaded models, we assume safetensors as that's the HuggingFace standard
                    model_format = 'safetensors'
                    logger.debug(f"[ModelRegistry] {model_id}: Not downloaded, assuming format: safetensors")

                # Get preferred format for diffusion models
                preferred = self._get_preferred_format(ModelType.DIFFUSION)
                convert_options = self._get_conversion_options(model_format, ModelType.DIFFUSION)

                # Get VRAM from config
                vram_gb = config.get('vram_gb', 0)
                if not vram_gb:
                    vram_gb = config.get('vram', 0)  # Alternative key name

                logger.info(
                    f"[ModelRegistry] Discovered imager model: {model_id}, "
                    f"format={model_format or 'EMPTY'}, preferred={preferred or 'EMPTY'}, "
                    f"vram_gb={vram_gb}, downloaded={is_downloaded}"
                )

                self._models[f"imager:{model_id}"] = ModelInfo(
                    id=f"imager:{model_id}",
                    name=name,
                    model_type=ModelType.DIFFUSION,
                    source=ModelSource.WAMA_IMAGER,
                    description=config.get('description', ''),
                    hf_id=hf_id,
                    vram_gb=vram_gb,
                    is_loaded=is_loaded,
                    is_downloaded=is_downloaded,
                    backend_ref='imager',
                    format=model_format,
                    preferred_format=preferred,
                    can_convert_to=convert_options,
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

            # Get all possible model directories
            model_paths = settings.MODEL_PATHS

            for model_id, config in DESCRIBER_MODELS.items():
                model_type = ModelType.VLM
                if config.get('type') == 'summarization':
                    model_type = ModelType.SUMMARIZATION
                elif config.get('type') == 'speech-to-text':
                    model_type = ModelType.SPEECH

                is_loaded = model_id == 'blip' and blip_loaded
                hf_id = config.get('model_id')
                source_type = config.get('source', 'huggingface')

                # Check if model is downloaded
                is_downloaded = False
                model_format = ''
                cache_dirs = []

                # Special handling for Whisper (uses .pt files, not HuggingFace format)
                if 'whisper' in model_id.lower() or source_type == 'openai':
                    whisper_dir = model_paths.get('speech', {}).get('whisper')
                    if whisper_dir:
                        whisper_path = Path(whisper_dir)
                        if whisper_path.exists():
                            # Check for any .pt files (base.pt, small.pt, etc.)
                            pt_files = list(whisper_path.glob('*.pt'))
                            is_downloaded = len(pt_files) > 0
                            if is_downloaded:
                                model_format = 'pt'
                else:
                    # HuggingFace models (BLIP, BART)
                    # Add type-specific directories
                    if 'blip' in model_id.lower():
                        blip_dir = model_paths.get('vision_language', {}).get('blip')
                        if blip_dir:
                            cache_dirs.append(Path(blip_dir))
                    elif 'bart' in model_id.lower():
                        bart_dir = model_paths.get('vision_language', {}).get('bart')
                        if bart_dir:
                            cache_dirs.append(Path(bart_dir))

                    # Add generic directories as fallback
                    vlm_root = model_paths.get('vision_language', {}).get('root')
                    if vlm_root:
                        cache_dirs.append(Path(vlm_root))
                    hf_cache = model_paths.get('cache', {}).get('huggingface')
                    if hf_cache:
                        cache_dirs.append(Path(hf_cache))

                    # Check if model is downloaded in any of the directories
                    for cache_dir in cache_dirs:
                        if cache_dir and cache_dir.exists():
                            if _check_hf_model_downloaded(cache_dir, hf_id):
                                is_downloaded = True
                                break

                # Detect format (for HF models it's typically safetensors or bin)
                if is_downloaded and not model_format:
                    # Try specific HF cache folder first
                    if hf_id:
                        hf_folder_name = f"models--{hf_id.replace('/', '--')}"
                        for cache_dir in cache_dirs:
                            specific_cache = cache_dir / hf_folder_name
                            if specific_cache.exists():
                                model_format = self._detect_model_format(str(specific_cache))
                                if model_format:
                                    break
                    # Fallback to scanning cache directories
                    if not model_format and cache_dirs:
                        for cache_dir in cache_dirs:
                            if cache_dir and cache_dir.exists():
                                model_format = self._detect_model_format(str(cache_dir))
                                if model_format:
                                    break

                # Default based on model type if not found (even for non-downloaded models)
                if not model_format:
                    if model_type == ModelType.SPEECH:
                        model_format = 'pt'  # Whisper-style models
                    else:
                        model_format = 'safetensors'  # Default for HF models

                # Get preferred format based on model type
                preferred = self._get_preferred_format(model_type)
                logger.debug(f"[ModelRegistry] Describer {model_id}: format={model_format}, preferred={preferred}")
                convert_options = self._get_conversion_options(model_format, model_type)

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
                    format=model_format,
                    preferred_format=preferred,
                    can_convert_to=convert_options,
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

                    # Detect format from path
                    model_path = model.get('path', '')
                    model_format = self._detect_model_format(model_path) if model_path else ''

                    # Default format for YOLO models
                    if not model_format:
                        model_format = 'pt'  # YOLO models are typically .pt files

                    # Get preferred format for vision models
                    preferred = self._get_preferred_format(ModelType.VISION)
                    logger.debug(f"[ModelRegistry] YOLO {model_name}: format={model_format}, preferred={preferred}")
                    convert_options = self._get_conversion_options(model_format, ModelType.VISION)

                    self._models[f"anonymizer:yolo:{model_name}"] = ModelInfo(
                        id=f"anonymizer:yolo:{model_name}",
                        name=model_name,
                        model_type=ModelType.VISION,
                        source=ModelSource.WAMA_ANONYMIZER,
                        description=desc,
                        vram_gb=round(size_gb * 2, 1),  # Estimate VRAM as 2x model size
                        is_downloaded=True,
                        extra_info={'path': model_path, 'type': model_type},
                        backend_ref='anonymizer',
                        format=model_format,
                        preferred_format=preferred,
                        can_convert_to=convert_options,
                    )

            # Add SAM3 if available
            try:
                from wama.anonymizer.utils.sam3_manager import get_sam3_status
                status = get_sam3_status()

                # SAM3 uses safetensors/pt format
                preferred = self._get_preferred_format(ModelType.VISION)

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
                    format='safetensors',
                    preferred_format=preferred,
                    can_convert_to=['onnx'],
                )
            except Exception:
                pass

        except ImportError as e:
            logger.debug(f"Could not import Anonymizer models: {e}")

    def _discover_transcriber_models(self):
        """Discover Transcriber app models (Whisper)."""
        try:
            from wama.transcriber.utils.model_config import TRANSCRIBER_MODELS, WHISPER_DIR

            # Whisper uses .pt format
            model_format = 'pt'
            preferred = self._get_preferred_format(ModelType.SPEECH)
            convert_options = self._get_conversion_options(model_format, ModelType.SPEECH)

            for model_id, config in TRANSCRIBER_MODELS.items():
                # Check if model is downloaded (whisper models are stored as {model_id}.pt)
                short_id = config.get('model_id', model_id.replace('whisper-', ''))
                model_file = Path(WHISPER_DIR) / f"{short_id}.pt"
                is_downloaded = model_file.exists()

                self._models[f"transcriber:{model_id}"] = ModelInfo(
                    id=f"transcriber:{model_id}",
                    name=f"Whisper {short_id.capitalize()}",
                    model_type=ModelType.SPEECH,
                    source=ModelSource.WAMA_TRANSCRIBER,
                    description=config.get('description', f"OpenAI Whisper {short_id}"),
                    vram_gb=config.get('size_gb', 0.5),
                    is_downloaded=is_downloaded,
                    backend_ref='transcriber',
                    format=model_format,
                    preferred_format=preferred,
                    can_convert_to=convert_options,
                    extra_info={'path': str(model_file) if is_downloaded else ''},
                )

                logger.debug(f"[ModelRegistry] Whisper {short_id}: downloaded={is_downloaded}")

        except ImportError as e:
            logger.debug(f"Could not import Transcriber models: {e}")

    def _discover_synthesizer_models(self):
        """Discover Synthesizer app models (Coqui, Bark)."""
        try:
            from django.conf import settings

            # Get preferred format for speech models
            preferred = self._get_preferred_format(ModelType.SPEECH)

            # Get speech models directory
            speech_dir = settings.MODEL_PATHS.get('speech', {}).get('root')
            if not speech_dir:
                speech_dir = getattr(settings, 'AI_MODELS_DIR', Path('.')) / 'models' / 'speech'
            speech_dir = Path(speech_dir)

            # Check for Coqui XTTS v2
            coqui_downloaded = False
            coqui_format = 'pth'
            coqui_paths = [
                speech_dir / 'coqui' / 'tts' / 'tts_models--multilingual--multi-dataset--xtts_v2' / 'model.pth',
                speech_dir / 'coqui' / 'XTTS-v2' / 'model.pth',
                speech_dir / 'coqui' / 'xtts_v2' / 'model.pth',
            ]
            coqui_model_path = None
            for cpath in coqui_paths:
                if cpath.exists():
                    coqui_downloaded = True
                    coqui_model_path = cpath
                    coqui_format = cpath.suffix.lstrip('.') or 'pth'
                    logger.debug(f"[ModelRegistry] Found Coqui XTTS at: {cpath}")
                    break

            self._models["synthesizer:coqui-xtts"] = ModelInfo(
                id="synthesizer:coqui-xtts",
                name="Coqui XTTS v2",
                model_type=ModelType.SPEECH,
                source=ModelSource.WAMA_SYNTHESIZER,
                description="Multilingual TTS with voice cloning",
                vram_gb=2.0,
                ram_gb=4.0,
                is_downloaded=coqui_downloaded,
                backend_ref='synthesizer',
                format=coqui_format,
                preferred_format=preferred,
                can_convert_to=['onnx', 'safetensors'],
                extra_info={'path': str(coqui_model_path) if coqui_model_path else ''},
            )

            # Check for Bark TTS
            bark_downloaded = False
            bark_format = 'pt'
            bark_paths = [
                speech_dir / 'bark' / 'suno' / 'bark_v0' / 'fine_2.pt',
                speech_dir / 'bark' / 'suno' / 'bark_v0' / 'coarse_2.pt',
                speech_dir / 'bark' / 'fine_2.pt',
            ]
            bark_model_path = None
            for bpath in bark_paths:
                if bpath.exists():
                    bark_downloaded = True
                    bark_model_path = bpath.parent  # Store the directory
                    bark_format = bpath.suffix.lstrip('.') or 'pt'
                    logger.debug(f"[ModelRegistry] Found Bark at: {bpath.parent}")
                    break

            self._models["synthesizer:bark"] = ModelInfo(
                id="synthesizer:bark",
                name="Bark TTS",
                model_type=ModelType.SPEECH,
                source=ModelSource.WAMA_SYNTHESIZER,
                description="Expressive TTS with sound effects",
                vram_gb=4.0,
                ram_gb=8.0,
                is_downloaded=bark_downloaded,
                backend_ref='synthesizer',
                format=bark_format,
                preferred_format=preferred,
                can_convert_to=['onnx', 'safetensors'],
                extra_info={'path': str(bark_model_path) if bark_model_path else ''},
            )

            logger.info(f"[ModelRegistry] Synthesizer: Coqui downloaded={coqui_downloaded}, Bark downloaded={bark_downloaded}")

        except Exception as e:
            logger.error(f"Could not discover Synthesizer models: {e}")
            import traceback
            logger.debug(traceback.format_exc())

    def _discover_enhancer_models(self):
        """Discover Enhancer app models (ONNX upscalers)."""
        try:
            from django.conf import settings

            # Get preferred format for upscaling models
            preferred = self._get_preferred_format(ModelType.UPSCALING)

            onnx_dir = settings.MODEL_PATHS.get('upscaling', {}).get('onnx')
            if onnx_dir and Path(onnx_dir).exists():
                for onnx_file in Path(onnx_dir).glob('*.onnx'):
                    model_name = onnx_file.stem
                    size_mb = onnx_file.stat().st_size / (1024 * 1024)

                    # These models are already in ONNX format
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
                        format='onnx',
                        preferred_format=preferred,
                        can_convert_to=[],  # Already optimal format
                    )
        except Exception as e:
            logger.debug(f"Could not discover Enhancer models: {e}")

    def _discover_ollama_models(self):
        """Discover Ollama models (with short timeout to avoid blocking)."""
        # Try multiple methods to discover Ollama models
        models_found = False

        # Method 1: Try ollama command (works on native Windows/Linux)
        for cmd in ['ollama', 'ollama.exe']:
            if models_found:
                break
            try:
                result = subprocess.run(
                    [cmd, 'list'],
                    capture_output=True,
                    text=True,
                    timeout=3,
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

                            # Ollama models use GGUF format
                            preferred = self._get_preferred_format(ModelType.LLM)

                            self._models[f"ollama:{model_name}"] = ModelInfo(
                                id=f"ollama:{model_name}",
                                name=model_name,
                                model_type=ModelType.LLM,
                                source=ModelSource.OLLAMA,
                                description=f"Ollama LLM ({model_size})",
                                ram_gb=ram_gb,
                                is_downloaded=True,
                                backend_ref='ollama',
                                format='gguf',
                                preferred_format=preferred,
                                can_convert_to=[],  # Managed by Ollama
                            )
                            models_found = True
            except (FileNotFoundError, subprocess.TimeoutExpired):
                continue
            except Exception as e:
                logger.debug(f"Ollama command '{cmd}' failed: {e}")

        # Method 2: If command failed, scan Ollama models directory directly
        if not models_found:
            self._discover_ollama_from_directory()

    def _discover_ollama_from_directory(self):
        """Scan Ollama models directory directly (useful for WSL)."""
        # Possible Ollama model directories
        ollama_dirs = []

        # Check if running in WSL
        is_wsl = sys.platform == 'linux' and 'microsoft' in os.uname().release.lower() if hasattr(os, 'uname') else False

        if is_wsl:
            # WSL: Check Windows user's .ollama directory
            # Common locations: D:\.ollama, C:\Users\<user>\.ollama
            for drive in ['d', 'c']:
                ollama_dirs.append(Path(f"/mnt/{drive}/.ollama/models"))
            # Also check Windows user profile
            try:
                result = subprocess.run(
                    ['cmd.exe', '/c', 'echo', '%USERPROFILE%'],
                    capture_output=True, text=True, timeout=2
                )
                if result.returncode == 0:
                    userprofile = result.stdout.strip()
                    if userprofile and not userprofile.startswith('%'):
                        # Convert Windows path to WSL path
                        userprofile = userprofile.replace('\\', '/').replace('C:', '/mnt/c').replace('D:', '/mnt/d')
                        ollama_dirs.append(Path(userprofile) / ".ollama" / "models")
            except Exception:
                pass
        else:
            # Native Windows
            ollama_dirs.append(Path(os.path.expanduser("~")) / ".ollama" / "models")
            ollama_dirs.append(Path("D:/.ollama/models"))
            ollama_dirs.append(Path("C:/.ollama/models"))

        for ollama_dir in ollama_dirs:
            if not ollama_dir.exists():
                continue

            # Ollama stores models in manifests/registry.ollama.ai/library/<model>/<tag>
            manifests_dir = ollama_dir / "manifests" / "registry.ollama.ai" / "library"
            if manifests_dir.exists():
                try:
                    for model_dir in manifests_dir.iterdir():
                        if model_dir.is_dir():
                            model_name = model_dir.name
                            # Check for tags
                            for tag_file in model_dir.iterdir():
                                if tag_file.is_file():
                                    tag = tag_file.name
                                    full_name = f"{model_name}:{tag}" if tag != "latest" else model_name

                                    # Try to get size from blob
                                    size_gb = 0
                                    try:
                                        manifest = json.loads(tag_file.read_text())
                                        for layer in manifest.get('layers', []):
                                            size_gb += layer.get('size', 0) / (1024**3)
                                    except Exception:
                                        pass

                                    # Ollama models use GGUF format
                                    preferred = self._get_preferred_format(ModelType.LLM)

                                    self._models[f"ollama:{full_name}"] = ModelInfo(
                                        id=f"ollama:{full_name}",
                                        name=full_name,
                                        model_type=ModelType.LLM,
                                        source=ModelSource.OLLAMA,
                                        description=f"Ollama LLM ({size_gb:.1f}GB)" if size_gb > 0 else "Ollama LLM",
                                        ram_gb=round(size_gb, 1),
                                        is_downloaded=True,
                                        backend_ref='ollama',
                                        format='gguf',
                                        preferred_format=preferred,
                                        can_convert_to=[],  # Managed by Ollama
                                    )
                except Exception as e:
                    logger.debug(f"Error scanning Ollama directory {ollama_dir}: {e}")
                break  # Found models, stop searching

    # =========================================================================
    # Format Policy Methods
    # =========================================================================

    def get_models_needing_conversion(self) -> List[ModelInfo]:
        """
        Get models that are not in their preferred format according to policy.

        Returns:
            List of ModelInfo objects needing conversion
        """
        return [
            m for m in self._models.values()
            if m.format and m.preferred_format and m.format != m.preferred_format
        ]

    def get_format_stats(self) -> Dict[str, int]:
        """
        Get statistics of model formats.

        Returns:
            Dict mapping format names to counts
        """
        from wama.common.utils.format_policy import get_format_stats_template

        stats = get_format_stats_template()
        for model in self._models.values():
            if model.format:
                stats[model.format] = stats.get(model.format, 0) + 1
        return stats

    def get_compliance_stats(self) -> Dict[str, any]:
        """
        Get format policy compliance statistics.

        Returns:
            Dict with compliance percentages and counts
        """
        compliant = 0
        non_compliant = 0
        no_policy = 0

        for model in self._models.values():
            if not model.preferred_format:
                no_policy += 1
            elif model.format == model.preferred_format:
                compliant += 1
            else:
                non_compliant += 1

        total = compliant + non_compliant
        return {
            'compliant': compliant,
            'non_compliant': non_compliant,
            'no_policy': no_policy,
            'total': total,
            'percentage': round((compliant / total * 100) if total > 0 else 100, 1),
        }

    def _detect_model_format(self, model_path: Optional[str]) -> str:
        """
        Detect the format of a model from its path.

        Args:
            model_path: Path to the model file or directory

        Returns:
            Format string ('pt', 'safetensors', 'onnx', etc.) or empty string
        """
        if not model_path:
            logger.debug("[_detect_model_format] No model_path provided")
            return ''

        path = Path(model_path)

        # Check if path exists
        if not path.exists():
            logger.debug(f"[_detect_model_format] Path does not exist: {model_path}")
            # Try to infer from extension anyway
            suffix = path.suffix.lower()
            if suffix:
                format_map = {
                    '.pt': 'pt',
                    '.pth': 'pth',
                    '.safetensors': 'safetensors',
                    '.onnx': 'onnx',
                    '.bin': 'bin',
                    '.gguf': 'gguf',
                }
                fmt = format_map.get(suffix, '')
                if fmt:
                    logger.debug(f"[_detect_model_format] Inferred from extension: {fmt}")
                    return fmt
            return ''

        # Direct file
        if path.is_file():
            suffix = path.suffix.lower()
            format_map = {
                '.pt': 'pt',
                '.pth': 'pth',
                '.safetensors': 'safetensors',
                '.onnx': 'onnx',
                '.bin': 'bin',
                '.gguf': 'gguf',
            }
            fmt = format_map.get(suffix, 'unknown')
            logger.debug(f"[_detect_model_format] File format: {fmt} from {suffix}")
            return fmt

        # HuggingFace cache directory - check for safetensors or bin
        if path.is_dir():
            # Check snapshots for model files
            for pattern in ['**/*.safetensors', '**/*.bin', '**/*.pt']:
                files = list(path.glob(pattern))
                if files:
                    # Prefer safetensors if found
                    if 'safetensors' in pattern:
                        return 'safetensors'
                    elif 'bin' in pattern:
                        return 'bin'
                    else:
                        return 'pt'

        return ''

    def _get_preferred_format(self, model_type: ModelType) -> str:
        """
        Get the preferred format for a model type.

        Args:
            model_type: The ModelType enum value

        Returns:
            Preferred format string
        """
        try:
            from wama.common.utils.format_policy import get_preferred_format, get_category_for_model_type

            category = get_category_for_model_type(model_type.value)
            preferred = get_preferred_format(category)
            logger.debug(f"[ModelRegistry] Preferred format for {model_type.value} (category={category}): {preferred}")
            return preferred
        except Exception as e:
            logger.error(f"[ModelRegistry] Error getting preferred format for {model_type}: {e}")
            return 'safetensors'  # Default fallback

    def _get_conversion_options(self, current_format: str, model_type: ModelType) -> List[str]:
        """
        Get available conversion options for a model.

        Args:
            current_format: Current format of the model
            model_type: Type of the model

        Returns:
            List of formats the model can be converted to
        """
        options = []

        if current_format in ['pt', 'pth']:
            options.extend(['safetensors', 'onnx'])
        elif current_format == 'bin':
            options.append('safetensors')
        elif current_format == 'ckpt':
            options.extend(['safetensors', 'onnx'])

        return options
