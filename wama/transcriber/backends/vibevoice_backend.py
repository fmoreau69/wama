"""
VibeVoice ASR Backend for Transcriber

Microsoft VibeVoice ASR-based speech-to-text backend with:
- Speaker diarization
- Timestamps
- Hotwords/context support
- Up to 60 minutes of audio
"""

import gc
import logging
import re
from typing import List, Optional

from .base import SpeechToTextBackend, TranscriptionResult, TranscriptionSegment

logger = logging.getLogger(__name__)


class VibeVoiceBackend(SpeechToTextBackend):
    """
    Speech-to-text backend using Microsoft VibeVoice ASR.

    Features:
    - Speaker diarization (who is speaking)
    - Precise timestamps
    - Hotwords/context for domain-specific terms
    - 60 minutes of continuous audio
    - 50+ languages with code-switching
    """

    name = "vibevoice"
    display_name = "VibeVoice ASR (Microsoft)"

    supports_diarization = True
    supports_timestamps = True
    supports_hotwords = True
    supports_streaming = False

    min_vram_gb = 16
    recommended_vram_gb = 24

    def __init__(self):
        super().__init__()
        self._model = None
        self._processor = None
        self._torch = None
        self._device = None

    @classmethod
    def is_available(cls) -> bool:
        """Check if VibeVoice is installed."""
        try:
            from vibevoice.modular.modeling_vibevoice_asr import VibeVoiceASRForConditionalGeneration
            from vibevoice.processor.vibevoice_asr_processor import VibeVoiceASRProcessor
            return True
        except ImportError:
            return False

    def _get_device(self) -> str:
        """Determine the best device to use."""
        if self._torch is None:
            import torch
            self._torch = torch

        if self._torch.cuda.is_available():
            return "cuda"
        else:
            logger.warning("[VibeVoice] CUDA not available. VibeVoice requires GPU.")
            return "cpu"

    def load(self, model_name: str = None) -> bool:
        """
        Load VibeVoice ASR model.

        Args:
            model_name: HuggingFace model ID. Defaults to 'microsoft/VibeVoice-ASR'.

        Returns:
            True if loaded successfully.
        """
        model_path = model_name or "microsoft/VibeVoice-ASR"

        # Check if already loaded
        if self._loaded and self._current_model == model_path:
            logger.info(f"[VibeVoice] Model already loaded: {model_path}")
            return True

        try:
            import torch
            from vibevoice.modular.modeling_vibevoice_asr import VibeVoiceASRForConditionalGeneration
            from vibevoice.processor.vibevoice_asr_processor import VibeVoiceASRProcessor

            self._torch = torch
            self._device = self._get_device()

            # Unload previous model if any
            if self._model is not None:
                self.unload()

            logger.info(f"[VibeVoice] Loading model: {model_path}")

            # Clear CUDA cache before loading
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
                torch.cuda.synchronize()
                gc.collect()

            # Load processor
            logger.info("[VibeVoice] Loading processor...")
            self._processor = VibeVoiceASRProcessor.from_pretrained(
                model_path,
                language_model_pretrained_name="Qwen/Qwen2.5-7B"
            )

            # Load model with optimizations
            logger.info("[VibeVoice] Loading model (this may take a while)...")
            self._model = VibeVoiceASRForConditionalGeneration.from_pretrained(
                model_path,
                dtype=torch.bfloat16,
                device_map="auto",
                attn_implementation="sdpa",
                trust_remote_code=True
            )

            self._model.eval()
            self._loaded = True
            self._current_model = model_path

            logger.info(f"[VibeVoice] Model loaded successfully")
            return True

        except ImportError as e:
            logger.error(f"[VibeVoice] Import error - VibeVoice not installed: {e}")
            return False
        except Exception as e:
            logger.error(f"[VibeVoice] Failed to load model: {e}")
            self._loaded = False
            return False

    def transcribe(
        self,
        audio_path: str,
        language: str = None,
        hotwords: str = None,
        **kwargs
    ) -> TranscriptionResult:
        """
        Transcribe audio using VibeVoice ASR.

        Args:
            audio_path: Path to audio file.
            language: Optional language hint (auto-detected by default).
            hotwords: Comma-separated domain-specific terms for improved accuracy.
            **kwargs: Additional parameters:
                - temperature (float): Sampling temperature (0.0-2.0)
                - max_tokens (int): Maximum output tokens (default: 32768)
                - do_sample (bool): Enable sampling (default: False)
                - top_p (float): Nucleus sampling parameter (0.0-1.0)
                - repetition_penalty (float): Repetition penalty (1.0-1.2)

        Returns:
            TranscriptionResult with text, segments, and speaker info.
        """
        if not self._loaded or self._model is None:
            if not self.load():
                return TranscriptionResult(
                    success=False,
                    text='',
                    error="Failed to load VibeVoice model"
                )

        try:
            import torch
            import numpy as np

            logger.info(f"[VibeVoice] Transcribing: {audio_path}")

            # Load and process audio
            audio_inputs = self._processor.load_audio(
                audio_path,
                return_tensors="pt",
                padding=True
            )

            # Move to device
            audio_inputs = {k: v.to(self._model.device) for k, v in audio_inputs.items()}

            # Build generation config
            generation_kwargs = {
                'max_new_tokens': kwargs.get('max_tokens', 32768),
                'do_sample': kwargs.get('do_sample', False),
            }

            if kwargs.get('do_sample', False):
                generation_kwargs['temperature'] = kwargs.get('temperature', 0.0)
                generation_kwargs['top_p'] = kwargs.get('top_p', 1.0)

            if 'repetition_penalty' in kwargs:
                generation_kwargs['repetition_penalty'] = kwargs['repetition_penalty']

            # Add context/hotwords if provided
            context_info = hotwords
            if context_info:
                logger.info(f"[VibeVoice] Using context: {context_info[:100]}...")

            # Generate transcription
            logger.info("[VibeVoice] Generating transcription...")
            with torch.inference_mode():
                output_ids = self._model.generate(
                    **audio_inputs,
                    context_info=context_info,
                    **generation_kwargs
                )

            # Decode output
            generated_text = self._processor.batch_decode(
                output_ids,
                skip_special_tokens=True
            )[0]

            logger.info(f"[VibeVoice] Raw output length: {len(generated_text)} chars")

            # Post-process to extract segments
            segments = self._parse_segments(generated_text)

            # Combine segment texts for full text
            full_text = " ".join(s.text for s in segments) if segments else generated_text

            # Try to detect language from output
            detected_language = self._detect_language(generated_text)

            logger.info(f"[VibeVoice] Transcription complete: {len(segments)} segments")

            return TranscriptionResult(
                success=True,
                text=full_text,
                language=detected_language,
                segments=segments
            )

        except Exception as e:
            import traceback
            logger.error(f"[VibeVoice] Transcription failed: {e}")
            logger.error(traceback.format_exc())
            return TranscriptionResult(
                success=False,
                text='',
                error=str(e)
            )

    def _parse_segments(self, raw_output: str) -> List[TranscriptionSegment]:
        """
        Parse VibeVoice structured output into segments.

        VibeVoice output format:
        [Speaker_1 00:00:01.234 - 00:00:05.678] Hello, how are you?
        [Speaker_2 00:00:06.000 - 00:00:08.500] I'm fine, thanks!

        Args:
            raw_output: Raw text from VibeVoice model.

        Returns:
            List of TranscriptionSegment objects.
        """
        segments = []

        # Pattern to match VibeVoice segment format
        # [Speaker_X HH:MM:SS.mmm - HH:MM:SS.mmm] text
        pattern = r'\[([^\]]+?)\s+(\d{2}:\d{2}:\d{2}(?:\.\d+)?)\s*-\s*(\d{2}:\d{2}:\d{2}(?:\.\d+)?)\]\s*(.+?)(?=\[|$)'

        matches = re.findall(pattern, raw_output, re.DOTALL)

        for i, match in enumerate(matches):
            speaker_id = match[0].strip()
            start_time_str = match[1]
            end_time_str = match[2]
            text = match[3].strip()

            # Parse timestamps
            start_time = self._parse_timestamp(start_time_str)
            end_time = self._parse_timestamp(end_time_str)

            if text:  # Only add if there's actual text
                segments.append(TranscriptionSegment(
                    speaker_id=speaker_id,
                    start_time=start_time,
                    end_time=end_time,
                    text=text,
                    confidence=None
                ))

        # If no structured segments found, create single segment from raw text
        if not segments and raw_output.strip():
            segments.append(TranscriptionSegment(
                speaker_id='',
                start_time=0,
                end_time=0,
                text=raw_output.strip(),
                confidence=None
            ))

        return segments

    def _parse_timestamp(self, time_str: str) -> float:
        """
        Parse timestamp string to seconds.

        Args:
            time_str: Timestamp in format HH:MM:SS.mmm or HH:MM:SS

        Returns:
            Time in seconds as float.
        """
        try:
            parts = time_str.split(':')
            if len(parts) == 3:
                hours = int(parts[0])
                minutes = int(parts[1])
                seconds = float(parts[2])
                return hours * 3600 + minutes * 60 + seconds
            elif len(parts) == 2:
                minutes = int(parts[0])
                seconds = float(parts[1])
                return minutes * 60 + seconds
            else:
                return float(time_str)
        except (ValueError, IndexError):
            return 0.0

    def _detect_language(self, text: str) -> str:
        """
        Simple language detection based on text content.
        Returns empty string if unsure.
        """
        # This is a simple heuristic - VibeVoice should ideally provide this
        # For now, return empty and let the caller handle it
        return ''

    def unload(self) -> None:
        """Unload model from memory."""
        if self._model is not None or self._processor is not None:
            logger.info("[VibeVoice] Unloading model...")

            del self._model
            del self._processor
            self._model = None
            self._processor = None

            # Clear CUDA cache
            if self._torch is not None and self._torch.cuda.is_available():
                self._torch.cuda.empty_cache()
                self._torch.cuda.synchronize()

            gc.collect()

            self._loaded = False
            self._current_model = None
            logger.info("[VibeVoice] Model unloaded")
