"""
WAMA Enhancer — Audio Speech Enhancement Backend

Engines:
  - Resemble Enhance (MIT): dual-stage denoising + enhancement, 44.1kHz output
  - DeepFilterNet 3 (MIT): real-time noise suppression, 48kHz, ultra-fast

⚠️  HF_HUB_CACHE is set BEFORE resemble_enhance import to redirect model download
    to AI-models/models/speech/resemble-enhance/ (same rule as other HF models).
"""

import gc
import logging
import os
from pathlib import Path
from typing import Literal, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# torchaudio 2.9+ compatibility patch (TorchCodec → soundfile shim)
# ---------------------------------------------------------------------------

def _patch_torchaudio_compat() -> None:
    """
    torchaudio 2.9 replaced load/save/info with TorchCodec (requires FFmpeg).
    deepfilternet also needs torchaudio.backend.common (removed in 2.0).

    Apply soundfile-based shims for all three — called once at module import
    so both ResembleEnhance and DeepFilterNet backends benefit.
    """
    import sys
    import types

    try:
        import torchaudio
        from collections import namedtuple

        # ── AudioMetaData ─────────────────────────────────────────────────
        AudioMetaData = getattr(torchaudio, 'AudioMetaData', None)
        if AudioMetaData is None:
            AudioMetaData = namedtuple(
                'AudioMetaData',
                ['sample_rate', 'num_frames', 'num_channels', 'bits_per_sample', 'encoding']
            )

        # ── torchaudio.backend.common stub ────────────────────────────────
        if 'torchaudio.backend.common' not in sys.modules:
            backend_mod = types.ModuleType('torchaudio.backend')
            common_mod = types.ModuleType('torchaudio.backend.common')
            common_mod.AudioMetaData = AudioMetaData
            sys.modules['torchaudio.backend'] = backend_mod
            sys.modules['torchaudio.backend.common'] = common_mod
            torchaudio.backend = backend_mod

        import soundfile as sf
        import torch as _torch

        _AudioMetaData = AudioMetaData  # capture for closure

        if not hasattr(torchaudio, 'info'):
            def _info_shim(path, **kwargs):
                with sf.SoundFile(path) as f:
                    return _AudioMetaData(
                        sample_rate=f.samplerate,
                        num_frames=f.frames,
                        num_channels=f.channels,
                        bits_per_sample=16,
                        encoding='PCM_S',
                    )
            torchaudio.info = _info_shim

        # Always override load/save to bypass TorchCodec (needs FFmpeg)
        def _load_shim(path, frame_offset=0, num_frames=-1, normalize=True,
                       channels_first=True, format=None, buffer_size=4096,
                       backend=None, **kwargs):
            read_kwargs = dict(start=frame_offset, dtype='float32', always_2d=True)
            if num_frames != -1:
                read_kwargs['frames'] = num_frames
            data, sr = sf.read(path, **read_kwargs)
            t = _torch.from_numpy(data.T if channels_first else data)
            return t, sr

        def _save_shim(path, src, sample_rate, channels_first=True, **kwargs):
            import numpy as np
            arr = src.numpy() if not isinstance(src, np.ndarray) else src
            if channels_first:
                arr = arr.T  # [C, T] → [T, C]
            sf.write(str(path), arr, sample_rate)

        torchaudio.load = _load_shim
        torchaudio.save = _save_shim

        logger.debug("[audio_enhancer] torchaudio compat patch applied (soundfile shims)")

    except Exception as e:
        logger.warning("[audio_enhancer] torchaudio compat patch failed: %s", e)


# Apply at import time so both backends benefit
_patch_torchaudio_compat()


# ---------------------------------------------------------------------------
# Torch 2.x / deepspeed compatibility patch
# ---------------------------------------------------------------------------

def _patch_torch_elastic() -> None:
    """
    deepspeed is incompatible with torch 2.x and is only used by resemble_enhance
    for training configuration — never called during inference.

    Strategy: install a meta-path finder that intercepts ALL deepspeed.* imports
    and returns stub modules, so resemble_enhance loads without error.
    """
    import sys
    if any(f.__class__.__name__ == '_DeepSpeedMockFinder' for f in sys.meta_path):
        return  # already installed

    import types
    import importlib.abc
    import importlib.machinery
    from unittest.mock import MagicMock

    _shared_mm = MagicMock()

    class _DeepSpeedMockLoader(importlib.abc.Loader):
        def create_module(self, spec):
            return None  # default module object

        def exec_module(self, module):
            module.__path__    = []
            module.__version__ = '0.0.0-mock'
            # Any attribute access (class names, functions, …) returns MagicMock
            module.__getattr__ = lambda name: _shared_mm

    class _DeepSpeedMockFinder(importlib.abc.MetaPathFinder):
        _loader = _DeepSpeedMockLoader()

        def find_spec(self, fullname, path, target=None):
            if fullname == 'deepspeed' or fullname.startswith('deepspeed.'):
                return importlib.machinery.ModuleSpec(
                    fullname, self._loader, is_package=True
                )
            return None

    sys.meta_path.insert(0, _DeepSpeedMockFinder())
    logger.debug("[audio_enhancer] deepspeed mock finder installed (all deepspeed.* → stubs)")


# ---------------------------------------------------------------------------
# Model cache directories
# ---------------------------------------------------------------------------

def _get_resemble_cache() -> Path:
    try:
        from django.conf import settings
        d = Path(settings.MODEL_PATHS['speech']['resemble_enhance'])
        d.mkdir(parents=True, exist_ok=True)
        return d
    except Exception:
        d = Path.home() / ".cache" / "resemble-enhance"
        d.mkdir(parents=True, exist_ok=True)
        return d


def _get_deepfilternet_cache() -> Path:
    try:
        from django.conf import settings
        d = Path(settings.MODEL_PATHS['speech']['deepfilternet'])
        d.mkdir(parents=True, exist_ok=True)
        return d
    except Exception:
        d = Path.home() / ".cache" / "DeepFilterNet"
        d.mkdir(parents=True, exist_ok=True)
        return d


# ---------------------------------------------------------------------------
# Resemble Enhance backend
# ---------------------------------------------------------------------------

class ResembleEnhanceBackend:
    """
    Resemble Enhance — dual-stage speech enhancement (MIT).

    Stage 1 — Denoiser:  CRUSE-based noise separation
    Stage 2 — Enhancer:  diffusion-based bandwidth extension (44.1 kHz output)

    VRAM: 4–6 GB  |  Speed: fast
    """

    def __init__(self):
        self._cache_dir = _get_resemble_cache()
        # Set HF cache BEFORE any resemble_enhance import
        cache_str = str(self._cache_dir)
        os.environ['HF_HUB_CACHE'] = cache_str
        os.environ['HUGGINGFACE_HUB_CACHE'] = cache_str

    @classmethod
    def is_available(cls) -> bool:
        try:
            _patch_torch_elastic()
            import resemble_enhance  # noqa: F401
            return True
        except (ImportError, Exception):
            return False

    def _get_device(self) -> str:
        try:
            import torch
            return "cuda" if torch.cuda.is_available() else "cpu"
        except ImportError:
            return "cpu"

    def _load_resemble(self):
        """Import resemble_enhance after applying the torch 2.x compatibility patch."""
        _patch_torch_elastic()
        from resemble_enhance.enhancer.inference import denoise as re_denoise, enhance as re_enhance
        return re_denoise, re_enhance

    def enhance(
        self,
        input_path: str,
        output_path: str,
        mode: Literal["both", "denoise", "enhance"] = "both",
        denoising_strength: float = 0.5,
        nfe: int = 64,
        progress_callback=None,
    ) -> str:
        """
        Enhance speech audio with Resemble Enhance.

        Args:
            input_path:         Path to input audio file
            output_path:        Path to output WAV file
            mode:               'both' (denoise+enhance), 'denoise', 'enhance'
            denoising_strength: tau parameter 0.0–1.0 (denoising amount)
            nfe:                Number of function evaluations (32=fast, 64=balanced, 128=best)
            progress_callback:  Optional 0–100 progress function

        Returns:
            output_path on success
        """
        import torchaudio  # already patched at module load; import for local reference

        device = self._get_device()
        logger.info(f"[ResembleEnhance] device={device}, mode={mode}, nfe={nfe}, tau={denoising_strength}")

        if progress_callback:
            progress_callback(10)

        # Load audio
        audio, sr = torchaudio.load(input_path)
        logger.info(f"[ResembleEnhance] Input: sr={sr}, shape={audio.shape}")

        # Mono
        if audio.shape[0] > 1:
            audio = audio.mean(dim=0, keepdim=True)

        # Squeeze to 1-D tensor (resemble_enhance expects shape [T])
        dwav = audio.squeeze(0)

        if progress_callback:
            progress_callback(20)

        # Import AFTER setting HF_HUB_CACHE and patching torch 2.x compat
        re_denoise, re_enhance = self._load_resemble()

        if mode == "denoise":
            logger.info("[ResembleEnhance] Denoising only…")
            out_wav, out_sr = re_denoise(dwav, sr, device)
        elif mode == "enhance":
            logger.info("[ResembleEnhance] Enhancing only (no denoising)…")
            out_wav, out_sr = re_enhance(dwav, sr, device, nfe=nfe, solver="midpoint", tau=0.0)
        else:  # both
            logger.info("[ResembleEnhance] Denoise + Enhance…")
            out_wav, out_sr = re_enhance(dwav, sr, device, nfe=nfe, solver="midpoint", tau=denoising_strength)

        if progress_callback:
            progress_callback(85)

        # Save output
        import soundfile as sf
        import numpy as np

        out_np = out_wav.cpu().numpy() if hasattr(out_wav, 'cpu') else np.array(out_wav)
        sf.write(output_path, out_np, int(out_sr))
        logger.info(f"[ResembleEnhance] Saved to {output_path} (sr={out_sr})")

        if progress_callback:
            progress_callback(100)

        return output_path


# ---------------------------------------------------------------------------
# DeepFilterNet 3 backend
# ---------------------------------------------------------------------------

class DeepFilterNetBackend:
    """
    DeepFilterNet 3 — real-time speech noise suppression (MIT).

    Ultra-fast, <1 GB VRAM, supports up to 48 kHz, streaming-capable.
    """

    def __init__(self):
        self._model = None
        self._df_state = None
        self._cache_dir = _get_deepfilternet_cache()

    @classmethod
    def is_available(cls) -> bool:
        try:
            import df  # noqa: F401
            return True
        except Exception as e:
            logger.warning("[DeepFilterNet] import df failed: %s", e)
            return False

    def _ensure_loaded(self):
        if self._model is None:
            logger.info("[DeepFilterNet] Loading model…")
            # Model lives at: <cache_dir>/DeepFilterNet3/config.ini
            # Pass the model directory directly; deepfilternet skips download
            # when the path is not one of the PRETRAINED_MODELS names.
            import df.enhance as _df_enhance
            model_dir = self._cache_dir / "DeepFilterNet3"
            if not (model_dir / "config.ini").exists():
                # First run: redirect get_cache_dir so maybe_download_model()
                # saves to our AI-models directory.
                _orig = _df_enhance.get_cache_dir
                _df_enhance.get_cache_dir = lambda: str(self._cache_dir)
                try:
                    from df import init_df
                    self._model, self._df_state, _ = init_df("DeepFilterNet3")
                finally:
                    _df_enhance.get_cache_dir = _orig
            else:
                from df import init_df
                self._model, self._df_state, _ = init_df(str(model_dir))
            logger.info("[DeepFilterNet] Model loaded ✓")

    def enhance(
        self,
        input_path: str,
        output_path: str,
        progress_callback=None,
    ) -> str:
        """
        Enhance speech audio with DeepFilterNet 3.

        Args:
            input_path:        Path to input audio file
            output_path:       Path to output WAV file
            progress_callback: Optional 0–100 progress function

        Returns:
            output_path on success
        """
        self._ensure_loaded()

        if progress_callback:
            progress_callback(20)

        from df.enhance import enhance as df_enhance, load_audio, save_audio

        # Load at model sample rate
        audio, _ = load_audio(input_path, sr=self._df_state.sr())
        logger.info(f"[DeepFilterNet] Input: sr={self._df_state.sr()}, shape={audio.shape}")

        if progress_callback:
            progress_callback(40)

        enhanced = df_enhance(self._model, self._df_state, audio, pad=True)

        if progress_callback:
            progress_callback(85)

        save_audio(output_path, enhanced, self._df_state.sr())
        logger.info(f"[DeepFilterNet] Saved to {output_path}")

        if progress_callback:
            progress_callback(100)

        return output_path

    def unload(self):
        self._model = None
        self._df_state = None
        gc.collect()


# ---------------------------------------------------------------------------
# Routing helper
# ---------------------------------------------------------------------------

def run_audio_enhancement(
    input_path: str,
    output_path: str,
    engine: str = "resemble",
    mode: str = "both",
    denoising_strength: float = 0.5,
    quality: int = 64,
    progress_callback=None,
) -> str:
    """
    Route to the correct audio enhancement engine.

    Args:
        input_path:         Input audio file path
        output_path:        Output audio file path (WAV)
        engine:             'resemble' | 'deepfilternet'
        mode:               'both' | 'denoise' | 'enhance'  (Resemble only)
        denoising_strength: 0.0–1.0  (Resemble only)
        quality:            NFE 32/64/128  (Resemble only)
        progress_callback:  Optional 0–100 progress function

    Returns:
        output_path on success
    """
    if engine == "deepfilternet":
        if not DeepFilterNetBackend.is_available():
            raise RuntimeError(
                "DeepFilterNet non installé. Exécutez : pip install deepfilternet"
            )
        backend = DeepFilterNetBackend()
        return backend.enhance(input_path, output_path, progress_callback=progress_callback)

    else:  # resemble (default)
        if not ResembleEnhanceBackend.is_available():
            raise RuntimeError(
                "Resemble Enhance non installé. Exécutez : pip install resemble-enhance"
            )
        backend = ResembleEnhanceBackend()
        return backend.enhance(
            input_path, output_path,
            mode=mode,
            denoising_strength=denoising_strength,
            nfe=quality,
            progress_callback=progress_callback,
        )
