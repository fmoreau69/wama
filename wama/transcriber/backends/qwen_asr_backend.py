"""
Qwen3-ASR Backend for Transcriber

Alibaba Qwen3-ASR — open-source ASR models with:
- Context biasing: hotwords injected as initial prompt to steer transcription
- 52 languages with auto-detection
- Noise robustness (RL-trained on noisy data)
- Word-level timestamps (via decoder timestamp tokens)
- Low VRAM: 0.6B ≈ 2 GB, 1.7B ≈ 4 GB

Models (HuggingFace):
  - Qwen/Qwen3-ASR-0.6B   — fast, low VRAM
  - Qwen/Qwen3-ASR-1.7B   — best accuracy (default)
"""

import gc
import logging
import re
from typing import List, Optional

from .base import SpeechToTextBackend, TranscriptionResult, TranscriptionSegment

logger = logging.getLogger(__name__)

DEFAULT_MODEL = 'Qwen/Qwen3-ASR-1.7B'


class QwenASRBackend(SpeechToTextBackend):
    """
    Speech-to-text backend using Alibaba Qwen3-ASR.

    Key differentiator: native context biasing — pass domain-specific terms
    as hotwords and the model will favour them during transcription.

    Diarization is handled externally by pyannote_diarizer (same as Whisper).
    """

    name = "qwen_asr"
    display_name = "Qwen3-ASR (Alibaba)"

    supports_diarization = False   # pyannote post-processing in workers.py
    supports_timestamps  = True    # timestamp tokens in decoder output
    supports_hotwords    = True    # context biasing via initial prompt
    supports_streaming   = False

    min_vram_gb         = 2
    recommended_vram_gb = 4

    MODEL_VRAM = {
        'Qwen/Qwen3-ASR-0.6B': 2,
        'Qwen/Qwen3-ASR-1.7B': 4,
    }

    def __init__(self):
        super().__init__()
        self._model     = None
        self._processor = None
        self._device    = None
        self._dtype     = None

    # ------------------------------------------------------------------
    # Availability
    # ------------------------------------------------------------------

    @classmethod
    def is_available(cls) -> bool:
        """
        Check whether the required packages are installed.

        We only check for `transformers` and `soundfile` here; the actual
        model download is checked at `load()` time.
        """
        try:
            import transformers  # noqa: F401
            import soundfile     # noqa: F401
            return True
        except ImportError:
            return False

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_device_and_dtype(self):
        """Auto-select device and torch dtype."""
        try:
            import torch
            if torch.cuda.is_available():
                return 'cuda', torch.float16
            if hasattr(torch.backends, 'mps') and torch.backends.mps.is_available():
                return 'mps', torch.float16
        except ImportError:
            pass
        return 'cpu', None

    def _get_cache_dir(self) -> Optional[str]:
        """Return centralized model cache directory, or None."""
        try:
            from ..utils.model_config import QWEN_ASR_DIR
            return str(QWEN_ASR_DIR)
        except Exception:
            return None

    def _load_audio(self, audio_path: str):
        """
        Load audio as a mono float32 numpy array at 16 kHz.

        Returns:
            (audio_array: np.ndarray, sample_rate: int)
        """
        import numpy as np
        import soundfile as sf

        audio, sr = sf.read(audio_path, dtype='float32', always_2d=True)
        # Stereo → mono
        if audio.shape[1] > 1:
            audio = audio.mean(axis=1)
        else:
            audio = audio[:, 0]

        if sr != 16000:
            audio = self._resample(audio, sr, 16000)
            sr = 16000

        return audio.astype(np.float32), sr

    def _resample(self, audio, orig_sr: int, target_sr: int):
        """Resample audio to target_sr using best available library."""
        import numpy as np

        try:
            import resampy
            return resampy.resample(audio, orig_sr, target_sr)
        except ImportError:
            pass
        try:
            import librosa
            return librosa.resample(audio, orig_sr=orig_sr, target_sr=target_sr)
        except ImportError:
            pass
        try:
            import torchaudio
            import torch
            t = torch.from_numpy(audio).unsqueeze(0)
            t_resampled = torchaudio.functional.resample(t, orig_sr, target_sr)
            return t_resampled.squeeze(0).numpy()
        except Exception:
            pass

        # Linear interpolation fallback
        ratio = target_sr / orig_sr
        new_len = int(len(audio) * ratio)
        x_old = np.linspace(0, len(audio) - 1, len(audio))
        x_new = np.linspace(0, len(audio) - 1, new_len)
        return np.interp(x_new, x_old, audio).astype(np.float32)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def load(self, model_name: str = None) -> bool:
        """
        Load a Qwen3-ASR model.

        Args:
            model_name: HuggingFace model ID (default: 'Qwen/Qwen3-ASR-1.7B').

        Returns:
            True if loaded successfully.
        """
        model_id = model_name or DEFAULT_MODEL

        if self._loaded and self._current_model == model_id:
            logger.info(f"[QwenASR] '{model_id}' already loaded — reusing")
            return True

        try:
            import os
            import torch

            if self._model is not None:
                self.unload()

            self._device, self._dtype = self._get_device_and_dtype()
            cache_dir = self._get_cache_dir()

            # ── CRITICAL: set HF_HUB_CACHE BEFORE importing transformers ──────
            # This ensures ALL sub-downloads (tokenizer, config, weights) go to
            # the correct model-specific directory, not the global HF cache.
            if cache_dir:
                os.environ['HF_HUB_CACHE'] = cache_dir
                os.environ['HUGGINGFACE_HUB_CACHE'] = cache_dir

            from transformers import AutoProcessor, AutoModelForSpeechSeq2Seq

            logger.info(
                f"[QwenASR] Loading '{model_id}' on {self._device}"
                + (f" → {cache_dir}" if cache_dir else "")
            )

            # Processor
            proc_kwargs = {'trust_remote_code': True}
            if cache_dir:
                proc_kwargs['cache_dir'] = cache_dir

            self._processor = AutoProcessor.from_pretrained(model_id, **proc_kwargs)

            # Model
            model_kwargs = {'trust_remote_code': True}
            if cache_dir:
                model_kwargs['cache_dir'] = cache_dir
            if self._dtype is not None:
                model_kwargs['torch_dtype'] = self._dtype
            if self._device != 'cpu':
                model_kwargs['device_map'] = 'auto'

            self._model = AutoModelForSpeechSeq2Seq.from_pretrained(model_id, **model_kwargs)

            if self._device == 'cpu':
                self._model = self._model.to('cpu')

            self._model.eval()
            self._loaded        = True
            self._current_model = model_id

            vram = self.MODEL_VRAM.get(model_id, self.recommended_vram_gb)
            logger.info(f"[QwenASR] '{model_id}' loaded ✓ (≈{vram} GB VRAM)")
            return True

        except Exception as e:
            logger.error(f"[QwenASR] Failed to load '{model_id}': {e}")
            self._model     = None
            self._processor = None
            self._loaded    = False
            return False

    def unload(self) -> None:
        """Unload model and free VRAM."""
        if self._model is not None or self._processor is not None:
            logger.info("[QwenASR] Unloading model…")
            del self._model
            del self._processor
            self._model     = None
            self._processor = None
            try:
                import torch
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
            except Exception:
                pass
            gc.collect()
            self._loaded        = False
            self._current_model = None
            logger.info("[QwenASR] Model unloaded")

    # ------------------------------------------------------------------
    # Transcription
    # ------------------------------------------------------------------

    def transcribe(
        self,
        audio_path: str,
        language: str = None,
        hotwords: str = None,
        **kwargs,
    ) -> TranscriptionResult:
        """
        Transcribe an audio file with Qwen3-ASR.

        Args:
            audio_path:  Path to the audio file.
            language:    ISO 639-1 code (e.g. 'fr', 'en') or None for auto-detect.
            hotwords:    Comma-separated domain terms for context biasing.
                         Example: "WAMA, anonymizer, transcriber"
            **kwargs:
                beam_size (int, default 1):        Beam search width.
                max_new_tokens (int, default 4096): Max generated tokens.
                enable_timestamps (bool, default True)

        Returns:
            TranscriptionResult — segments have empty speaker_id (filled by
            pyannote post-processing in workers.py if diarization is enabled).
        """
        if not self._loaded or self._model is None:
            if not self.load():
                return TranscriptionResult(
                    success=False, text='',
                    error="Failed to load Qwen3-ASR model",
                )

        try:
            import torch
            logger.info(f"[QwenASR] Transcribing: {audio_path}")

            # Load audio
            audio_array, sample_rate = self._load_audio(audio_path)

            # Processor inputs
            inputs = self._processor(
                audio_array,
                sampling_rate=sample_rate,
                return_tensors='pt',
            )
            inputs = {k: v.to(self._model.device) for k, v in inputs.items()}

            # Generation parameters
            gen_kwargs: dict = {
                'max_new_tokens':   int(kwargs.get('max_new_tokens', 4096)),
                'num_beams':        int(kwargs.get('beam_size', 1)),
                'return_timestamps': bool(kwargs.get('enable_timestamps', True)),
            }

            # Language hint
            if language and hasattr(self._processor, 'tokenizer'):
                try:
                    lang_token = f'<|{language}|>'
                    if lang_token in self._processor.tokenizer.get_vocab():
                        forced_ids = self._processor.tokenizer.convert_tokens_to_ids([lang_token])
                        gen_kwargs['forced_decoder_ids'] = [[1, forced_ids[0]]]
                except Exception:
                    pass

            # Context biasing: inject hotwords as initial prompt
            # This steers the decoder toward the provided vocabulary
            if hotwords and hotwords.strip():
                context = hotwords.strip()
                logger.info(f"[QwenASR] Context biasing active: {context[:80]}…")
                try:
                    if hasattr(self._processor, 'get_prompt_ids'):
                        prompt_ids = self._processor.get_prompt_ids(context, return_tensors='pt')
                        gen_kwargs['prompt_ids'] = prompt_ids.to(self._model.device)
                except Exception as e:
                    logger.debug(f"[QwenASR] Could not set prompt_ids: {e}")

            # Generate
            with torch.inference_mode():
                generated_ids = self._model.generate(**inputs, **gen_kwargs)

            # Decode — skip special tokens for clean text
            transcription = self._processor.batch_decode(
                generated_ids,
                skip_special_tokens=True,
            )
            full_text = transcription[0].strip() if transcription else ''

            # Extract timestamped segments from raw decoder output
            segments = self._extract_segments(generated_ids, full_text)

            logger.info(
                f"[QwenASR] Done — {len(full_text)} chars, "
                f"{len(segments)} segments"
            )

            return TranscriptionResult(
                success  = True,
                text     = full_text,
                language = language or '',
                segments = segments,
            )

        except Exception as e:
            import traceback
            logger.error(f"[QwenASR] Transcription failed: {e}")
            logger.debug(traceback.format_exc())
            return TranscriptionResult(success=False, text='', error=str(e))

    # ------------------------------------------------------------------
    # Segment extraction
    # ------------------------------------------------------------------

    def _extract_segments(
        self,
        generated_ids,
        full_text: str,
    ) -> List[TranscriptionSegment]:
        """
        Extract timestamped segments from raw decoder output.

        Handles Whisper-style timestamp tokens: <|0.00|> text <|1.50|>

        Falls back to a single segment covering the entire transcript if
        timestamp tokens are not present in the output.
        """
        try:
            raw_with_tokens = self._processor.batch_decode(
                generated_ids,
                skip_special_tokens=False,
            )
            if raw_with_tokens:
                segs = self._parse_timestamp_tokens(raw_with_tokens[0], full_text)
                if segs:
                    return segs
        except Exception as e:
            logger.debug(f"[QwenASR] Timestamp extraction skipped: {e}")

        # Fallback: single segment
        if full_text:
            return [TranscriptionSegment(
                speaker_id = '',
                start_time = 0.0,
                end_time   = 0.0,
                text       = full_text,
                confidence = None,
            )]
        return []

    def _parse_timestamp_tokens(self, raw: str, full_text: str) -> List[TranscriptionSegment]:
        """
        Parse Whisper-style timestamp tokens.

        Format:  <|0.00|> Hello world <|1.50|> How are you <|3.20|>
        """
        # Match: <|timestamp|> text (non-greedy until next token or end)
        pattern = r'<\|(\d+\.\d+)\|>\s*([^<]*)'
        matches = re.findall(pattern, raw)

        if not matches:
            return []

        segments: List[TranscriptionSegment] = []

        for i, (start_str, text) in enumerate(matches):
            text = text.strip()
            if not text:
                continue

            start = float(start_str)
            if i + 1 < len(matches):
                end = float(matches[i + 1][0])
            else:
                end = start + 2.0  # last segment: +2 s estimate

            segments.append(TranscriptionSegment(
                speaker_id = '',
                start_time = start,
                end_time   = end,
                text       = text,
                confidence = None,
            ))

        return segments
