"""
AudioCraft Backend — MusicGen + AudioGen

Handles music and SFX generation via Meta's AudioCraft library.

CLAUDE.md rule: HF_HUB_CACHE is set BEFORE any audiocraft/transformers import.
"""

import gc
import io
import logging
import os
from pathlib import Path
from typing import Callable, Optional

logger = logging.getLogger(__name__)


class AudioCraftBackend:
    """
    Unified backend for MusicGen (music) and AudioGen (SFX).

    Each call to generate() sets HF_HUB_CACHE, loads the model, runs
    inference, unloads the model, and returns the output path.
    Models are NOT cached in memory between calls — the 4090 has 24GB
    but other apps share it; we load/unload like every other WAMA backend.
    """

    def generate(
        self,
        model_id: str,
        prompt: str,
        duration: float,
        output_path: str,
        melody_path: Optional[str] = None,
        progress_callback: Optional[Callable[[int], None]] = None,
    ) -> str:
        """
        Generate audio and save to output_path.

        Args:
            model_id: One of 'musicgen-small', 'musicgen-medium', 'musicgen-melody',
                      'audiogen-medium'
            prompt: Text description of the sound/music to generate
            duration: Duration in seconds (max 30)
            output_path: Absolute path where the .wav will be saved
            melody_path: Optional path to a melody reference audio (musicgen-melody only)
            progress_callback: Optional callable(percent: int)

        Returns:
            output_path (same as input, for convenience)
        """
        from wama.composer.utils.model_config import COMPOSER_MODELS

        config = COMPOSER_MODELS.get(model_id)
        if config is None:
            raise ValueError(f"Modèle inconnu : {model_id}")

        cache_dir = str(config['cache_dir'])
        audiocraft_name = config['audiocraft_name']
        sample_rate = config['sample_rate']
        model_type = config['type']

        # ── CLAUDE.md: env vars BEFORE any audiocraft import ──────────────
        os.environ['HF_HUB_CACHE'] = cache_dir
        os.environ['HUGGINGFACE_HUB_CACHE'] = cache_dir
        # ──────────────────────────────────────────────────────────────────

        logger.info(f"[Composer] Loading {model_id} (cache: {cache_dir})")

        if progress_callback:
            progress_callback(5)

        try:
            if model_type == 'music':
                wav = self._generate_music(
                    audiocraft_name, prompt, duration, melody_path,
                    progress_callback,
                )
            else:
                wav = self._generate_sfx(
                    audiocraft_name, prompt, duration, progress_callback,
                )

            if progress_callback:
                progress_callback(85)

            # Save to WAV
            import torchaudio
            Path(output_path).parent.mkdir(parents=True, exist_ok=True)
            torchaudio.save(output_path, wav.cpu(), sample_rate)
            logger.info(f"[Composer] Saved to {output_path}")

            if progress_callback:
                progress_callback(100)

            return output_path

        finally:
            # Free GPU memory
            gc.collect()
            try:
                import torch
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _generate_music(
        self,
        audiocraft_name: str,
        prompt: str,
        duration: float,
        melody_path: Optional[str],
        progress_callback: Optional[Callable],
    ):
        """Load MusicGen, generate, unload."""
        from audiocraft.models import MusicGen

        if progress_callback:
            progress_callback(15)

        model = MusicGen.get_pretrained(audiocraft_name)
        model.set_generation_params(duration=duration)

        if progress_callback:
            progress_callback(40)

        if melody_path and audiocraft_name == 'melody':
            import torch
            import torchaudio
            melody, sr = torchaudio.load(melody_path)
            # MusicGen expects (batch, channels, time) or None
            melody = melody.unsqueeze(0)  # (1, C, T)
            wav = model.generate_with_chroma([prompt], melody, sr)
        else:
            wav = model.generate([prompt])

        if progress_callback:
            progress_callback(80)

        # wav shape: (batch, channels, samples) — take first sample
        result = wav[0]  # (channels, samples)

        # Unload model from GPU
        del model
        return result

    def _generate_sfx(
        self,
        audiocraft_name: str,
        prompt: str,
        duration: float,
        progress_callback: Optional[Callable],
    ):
        """Load AudioGen, generate, unload."""
        from audiocraft.models import AudioGen

        if progress_callback:
            progress_callback(15)

        model = AudioGen.get_pretrained(audiocraft_name)
        model.set_generation_params(duration=duration)

        if progress_callback:
            progress_callback(40)

        wav = model.generate([prompt])

        if progress_callback:
            progress_callback(80)

        result = wav[0]  # (channels, samples)
        del model
        return result
