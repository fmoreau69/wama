"""
VibeVoice ASR Backend for Transcriber

Microsoft VibeVoice ASR — LLM-based model with native:
- Speaker diarization (who spoke when)
- Precise timestamps
- context_info: hotwords, speaker names, domain terms
- Up to 60 minutes of continuous audio (64K token budget)
- 50+ languages with code-switching

Installation (from GitHub — NOT pip install vibevoice):
    git clone https://github.com/microsoft/VibeVoice.git
    cd VibeVoice
    pip install -e .

Requires: CUDA GPU with ≥16 GB VRAM (tested on 24 GB).
"""

import gc
import logging
from typing import List, Optional

from .base import SpeechToTextBackend, TranscriptionResult, TranscriptionSegment

logger = logging.getLogger(__name__)

MODEL_ID = "microsoft/VibeVoice-ASR"


class VibeVoiceBackend(SpeechToTextBackend):
    """
    Speech-to-text backend using Microsoft VibeVoice ASR.

    The processor's `context_info` parameter accepts free-form text:
    hotwords, speaker names, topics, technical terms — anything that
    helps the model recognise domain-specific vocabulary.

    Output includes native speaker diarization and timestamps;
    pyannote post-processing is therefore NOT applied.
    """

    name = "vibevoice"
    display_name = "VibeVoice ASR (Microsoft)"

    supports_diarization = True   # native — no pyannote needed
    supports_timestamps  = True
    supports_hotwords    = True   # via context_info parameter
    supports_streaming   = False

    min_vram_gb         = 16
    recommended_vram_gb = 24

    def __init__(self):
        super().__init__()
        self._model     = None
        self._processor = None
        self._device    = None

    # ------------------------------------------------------------------
    # Availability
    # ------------------------------------------------------------------

    @classmethod
    def is_available(cls) -> bool:
        """
        Check if the VibeVoice package is installed from GitHub.

        The standard `pip install vibevoice` installs an unrelated TTS package.
        This backend requires: git clone + pip install -e .
        """
        try:
            from vibevoice.modular.modeling_vibevoice_asr import VibeVoiceASRForConditionalGeneration   # noqa: F401
            from vibevoice.processor.vibevoice_asr_processor import VibeVoiceASRProcessor               # noqa: F401
            return True
        except ImportError:
            return False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def load(self, model_name: str = None) -> bool:
        """
        Load VibeVoice ASR model (7B, bfloat16).

        Args:
            model_name: HuggingFace model ID (default: 'microsoft/VibeVoice-ASR').

        Returns:
            True if loaded successfully.
        """
        model_path = model_name or MODEL_ID

        if self._loaded and self._current_model == model_path:
            logger.info(f"[VibeVoice] '{model_path}' already loaded — reusing")
            return True

        try:
            import os
            import torch

            if self._model is not None:
                self.unload()

            if not torch.cuda.is_available():
                logger.error("[VibeVoice] CUDA required — no GPU detected")
                return False

            self._device = "cuda"

            # Centralised cache
            cache_dir = None
            try:
                from ..utils.model_config import VIBEVOICE_DIR
                cache_dir = str(VIBEVOICE_DIR)
                logger.info(f"[VibeVoice] Cache: {cache_dir}")
            except Exception:
                pass

            # ── CRITICAL: set HF_HUB_CACHE BEFORE importing vibevoice/transformers ─
            if cache_dir:
                os.environ['HF_HUB_CACHE'] = cache_dir
                os.environ['HUGGINGFACE_HUB_CACHE'] = cache_dir

            from vibevoice.modular.modeling_vibevoice_asr import VibeVoiceASRForConditionalGeneration
            from vibevoice.processor.vibevoice_asr_processor import VibeVoiceASRProcessor

            # Free VRAM before loading the 7B model
            torch.cuda.empty_cache()
            torch.cuda.synchronize()
            gc.collect()

            # Processor — no `language_model_pretrained_name` needed;
            # the model hub config contains that reference.
            logger.info("[VibeVoice] Loading processor…")
            proc_kwargs = {}
            if cache_dir:
                proc_kwargs['cache_dir'] = cache_dir
            self._processor = VibeVoiceASRProcessor.from_pretrained(
                model_path, **proc_kwargs
            )

            # Model — bfloat16 on CUDA
            # Use torch_dtype (standard HuggingFace key), not dtype —
            # dtype=<torch.dtype> is not JSON-serializable and crashes from_pretrained.
            logger.info("[VibeVoice] Loading model (may take a few minutes)…")
            model_kwargs = {
                "torch_dtype":        torch.bfloat16,
                "device_map":         "cuda",
                "attn_implementation": "sdpa",
                "trust_remote_code":  True,
            }
            if cache_dir:
                model_kwargs['cache_dir'] = cache_dir

            self._model = VibeVoiceASRForConditionalGeneration.from_pretrained(
                model_path, **model_kwargs
            )
            self._model.eval()

            self._loaded        = True
            self._current_model = model_path
            logger.info("[VibeVoice] Model loaded ✓ (7B bfloat16)")
            return True

        except ImportError as e:
            logger.error(
                f"[VibeVoice] Import failed — install from GitHub: "
                f"git clone https://github.com/microsoft/VibeVoice && pip install -e . ({e})"
            )
            return False
        except Exception as e:
            logger.error(f"[VibeVoice] Failed to load: {e}")
            self._model     = None
            self._processor = None
            self._loaded    = False
            return False

    def unload(self) -> None:
        """Unload model and free VRAM."""
        if self._model is not None or self._processor is not None:
            logger.info("[VibeVoice] Unloading…")
            del self._model
            del self._processor
            self._model     = None
            self._processor = None
            try:
                import torch
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
                    torch.cuda.synchronize()
            except Exception:
                pass
            gc.collect()
            self._loaded        = False
            self._current_model = None
            logger.info("[VibeVoice] Unloaded")

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
        Transcribe an audio file with VibeVoice ASR.

        Args:
            audio_path: Path to the audio file (any format ffmpeg can read).
            language:   Language hint — appended to context_info if provided.
            hotwords:   Comma-separated domain terms, speaker names, etc.
                        Passed as `context_info` to the processor.
            **kwargs:
                max_new_tokens (int, default 512)
                do_sample      (bool, default False)

        Returns:
            TranscriptionResult with native diarized segments.
        """
        if not self._loaded or self._model is None:
            if not self.load():
                return TranscriptionResult(
                    success=False, text='',
                    error="Failed to load VibeVoice model",
                )

        try:
            import torch
            logger.info(f"[VibeVoice] Transcribing: {audio_path}")

            # Build context_info string
            context_parts = []
            if hotwords and hotwords.strip():
                context_parts.append(hotwords.strip())
            if language:
                context_parts.append(f"Language: {language}")
            context_info = "\n".join(context_parts) if context_parts else None

            if context_info:
                logger.info(f"[VibeVoice] context_info: {context_info[:100]}…")

            # Process audio — context_info goes here, not to generate()
            inputs = self._processor(
                audio=audio_path,
                sampling_rate=None,      # processor auto-reads from file
                return_tensors="pt",
                padding=True,
                add_generation_prompt=True,
                context_info=context_info,
            )
            inputs = {
                k: v.to(self._model.device) if isinstance(v, torch.Tensor) else v
                for k, v in inputs.items()
            }

            # Generation parameters
            gen_kwargs = {
                "max_new_tokens": int(kwargs.get('max_new_tokens', 512)),
                "do_sample":      bool(kwargs.get('do_sample', False)),
                "pad_token_id":   self._processor.pad_id,
                "eos_token_id":   self._processor.tokenizer.eos_token_id,
            }

            # Generate
            logger.info("[VibeVoice] Generating…")
            with torch.inference_mode():
                output_ids = self._model.generate(**inputs, **gen_kwargs)

            # Decode only the newly generated tokens (skip the input prompt)
            input_len = inputs['input_ids'].shape[1]
            new_tokens = output_ids[0, input_len:]
            generated_text = self._processor.decode(new_tokens, skip_special_tokens=True)

            logger.info(f"[VibeVoice] Raw output: {len(generated_text)} chars")

            # Parse structured output using the official post-processor
            segments = self._build_segments(generated_text)
            full_text = " ".join(s.text for s in segments) if segments else generated_text.strip()

            logger.info(f"[VibeVoice] Done — {len(segments)} segments")
            return TranscriptionResult(
                success  = True,
                text     = full_text,
                language = language or '',
                segments = segments,
            )

        except Exception as e:
            import traceback
            logger.error(f"[VibeVoice] Transcription failed: {e}")
            logger.debug(traceback.format_exc())
            return TranscriptionResult(success=False, text='', error=str(e))

    # ------------------------------------------------------------------
    # Segment parsing
    # ------------------------------------------------------------------

    def _build_segments(self, generated_text: str) -> List[TranscriptionSegment]:
        """
        Parse VibeVoice structured output.

        Tries the official `post_process_transcription()` method first
        (returns dicts with start_time / end_time / speaker_id / text).
        Falls back to regex parsing if it is unavailable.
        """
        # 1) Official post-processor (preferred)
        try:
            raw_segs = self._processor.post_process_transcription(generated_text)
            if raw_segs:
                result = []
                for seg in raw_segs:
                    result.append(TranscriptionSegment(
                        speaker_id = str(seg.get('speaker_id', '')),
                        start_time = float(seg.get('start_time', 0)),
                        end_time   = float(seg.get('end_time',   0)),
                        text       = str(seg.get('text', seg.get('content', ''))).strip(),
                        confidence = None,
                    ))
                return result
        except Exception as e:
            logger.debug(f"[VibeVoice] post_process_transcription failed: {e}")

        # 2) Regex fallback — handles both JSON and bracket formats
        return self._regex_parse(generated_text)

    def _regex_parse(self, raw: str) -> List[TranscriptionSegment]:
        """
        Regex fallback for VibeVoice output.

        Handles bracket format:
          [Speaker_1 00:00:01.234 - 00:00:05.678] Hello world
        """
        import re
        pattern = (
            r'\[([^\]]+?)\s+'
            r'(\d{2}:\d{2}:\d{2}(?:\.\d+)?)'
            r'\s*-\s*'
            r'(\d{2}:\d{2}:\d{2}(?:\.\d+)?)\]\s*'
            r'(.+?)(?=\[|$)'
        )
        matches = re.findall(pattern, raw, re.DOTALL)
        segments = []
        for speaker, t_start, t_end, text in matches:
            text = text.strip()
            if text:
                segments.append(TranscriptionSegment(
                    speaker_id = speaker.strip(),
                    start_time = self._ts_to_seconds(t_start),
                    end_time   = self._ts_to_seconds(t_end),
                    text       = text,
                    confidence = None,
                ))

        if not segments and raw.strip():
            segments.append(TranscriptionSegment(
                speaker_id = '',
                start_time = 0.0,
                end_time   = 0.0,
                text       = raw.strip(),
                confidence = None,
            ))
        return segments

    @staticmethod
    def _ts_to_seconds(ts: str) -> float:
        """Convert HH:MM:SS[.mmm] string to seconds."""
        try:
            parts = ts.split(':')
            if len(parts) == 3:
                return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
            if len(parts) == 2:
                return int(parts[0]) * 60 + float(parts[1])
            return float(ts)
        except (ValueError, IndexError):
            return 0.0
