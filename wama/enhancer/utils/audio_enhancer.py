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
# Torch 2.x / deepspeed compatibility patch
# ---------------------------------------------------------------------------

def _patch_torch_elastic() -> None:
    """
    deepspeed 0.12.4 is incompatible with torch 2.x: it imports `log` and
    `_get_socket_with_port` from torch.distributed.elastic.agent.server.api,
    both of which were removed in torch 2.x.

    Strategy: replace deepspeed in sys.modules with a MagicMock BEFORE it starts
    loading.  resemble_enhance uses deepspeed only for training configuration;
    inference (loading weights + running the model) never calls deepspeed code
    paths, so the mock is safe.
    """
    import sys
    if 'deepspeed' not in sys.modules:
        import types
        from unittest.mock import MagicMock
        _mm = MagicMock()
        # Use types.ModuleType so __spec__, __path__, __package__ are proper
        # module-level attributes — MagicMock returns MagicMock objects for
        # those attributes, which breaks Python 3.12 importlib's checks.
        ds = types.ModuleType('deepspeed')
        ds.__spec__    = None   # importlib: "no ModuleSpec for this module"
        ds.__path__    = []     # makes it look like a package
        ds.__package__ = 'deepspeed'
        ds.__loader__  = None
        ds.__version__ = '0.0.0-mock'
        # Module-level __getattr__ returns MagicMock for any attribute access
        # (DeepSpeedConfig, ZeroOptimConfig, etc. used only for type hints)
        ds.__getattr__ = lambda name: _mm
        sys.modules['deepspeed'] = ds
        logger.debug("[audio_enhancer] deepspeed mocked for torch 2.x inference compat")


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
        import torchaudio

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
        except ImportError:
            return False

    def _ensure_loaded(self):
        if self._model is None:
            logger.info("[DeepFilterNet] Loading model…")
            os.environ['DF_MODEL_HOME'] = str(self._cache_dir)
            from df import init_df
            self._model, self._df_state, _ = init_df(model_base_dir=str(self._cache_dir))
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
