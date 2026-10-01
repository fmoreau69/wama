"""
Whisper Backend for Transcriber — powered by faster-whisper.

Uses CTranslate2 (float16 on GPU, int8 on CPU) for significantly faster
inference than the original openai-whisper while keeping the same accuracy.

Default model: large-v3 (best accuracy, ≈10 GB VRAM).
"""

import gc
import logging
from typing import Optional

from .speech_to_text_base import SpeechToTextBackend, TranscriptionResult, TranscriptionSegment

logger = logging.getLogger(__name__)

DEFAULT_WHISPER_MODEL = 'large-v3'


class WhisperBackend(SpeechToTextBackend):
    """
    Speech-to-text backend using faster-whisper (CTranslate2).

    Supports large-v3 (default), large-v3-turbo, medium, small, base, tiny.
    Diarization is handled externally by pyannote_diarizer (see workers.py).
    """

    #: Moteur piloté (contrat commun) — voir BaseModelBackend.ENGINE.
    ENGINE = 'faster-whisper'
    name = "whisper"
    display_name = "Whisper (faster-whisper)"
    description = "large-v3 — rapide, polyvalent, multilingue. Diarisation via pyannote."
    description_long = (
        "Whisper large-v3 (faster-whisper / CTranslate2) : transcription multilingue "
        "rapide et robuste, excellente qualité en français. Pas de diarisation native — "
        "l'attribution des locuteurs est faite en post-traitement par pyannote "
        "(backend-agnostique). ~10 Go VRAM. Bon défaut polyvalent."
    )

    supports_diarization = False   # pyannote post-processing in workers.py
    supports_timestamps  = True
    supports_hotwords    = True    # param NATIF `hotwords` de faster-whisper (cf. transcribe(), ~l.211)
    supports_streaming   = False
    supports_vad_filter  = True    # `vad_filter` natif de faster-whisper (Silero)

    # Dépendances (contrat commun) : nom d'IMPORT ≠ nom pip.
    REQUIRED_PACKAGES = ['faster_whisper']
    PIP_PACKAGES      = ['faster-whisper']

    min_vram_gb         = 2
    # Repli du gouverneur : CTranslate2 alloue hors de l'allocateur PyTorch, la mesure autour de
    # load() reste donc à ~0 et c'est CETTE valeur qui est réservée. Ne pas la sous-estimer.
    recommended_vram_gb = 10

    MODEL_VRAM = {
        'tiny':             1,
        'base':             1,
        'small':            2,
        'medium':           5,
        'large':            10,
        'large-v2':         10,
        'large-v3':         10,
        'large-v3-turbo':   6,
        'distil-large-v3':  4,
    }

    def __init__(self):
        super().__init__()
        self._model  = None
        self._device = None
        self._compute_type = None

    # ------------------------------------------------------------------
    # Class-level helpers
    # ------------------------------------------------------------------

    # is_available() : hérité du contrat commun (find_spec sur REQUIRED_PACKAGES — sans importer :
    # ~ms vs import lourd). Aucune dépendance native cachée à sonder ici.

    def _get_device_and_compute(self) -> tuple[str, str]:
        """Auto-select device and matching CTranslate2 compute type."""
        try:
            import torch
            if torch.cuda.is_available():
                return 'cuda', 'float16'
            if hasattr(torch.backends, 'mps') and torch.backends.mps.is_available():
                # faster-whisper does not support MPS natively → CPU
                return 'cpu', 'int8'
        except ImportError:
            pass
        return 'cpu', 'int8'

    def _get_download_root(self) -> Optional[str]:
        """Return the centralized Whisper model cache, or None."""
        try:
            # Étape 2 (complétée le 06/09) : dossier lu à sa SOURCE. Ces constantes dérivaient
            # déjà de `settings.MODEL_PATHS` ; l'import d'app n'ajoutait qu'une indirection —
            # et il était RELATIF, donc invisible à la 1ʳᵉ version de la garde, qui ne
            # cherchait que les imports ABSOLUS. *Une garde ne couvre que la forme qu'elle
            # sait lire.*
            from django.conf import settings
            return str(settings.MODEL_PATHS.get('speech', {}).get('whisper') or '')
        except Exception:
            return None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def load(self, model_name: str = None) -> bool:
        """
        Load a faster-whisper model.

        Args:
            model_name: Model size identifier (default: 'large-v3').

        Returns:
            True if loaded successfully.
        """
        if model_name is None:
            model_name = DEFAULT_WHISPER_MODEL

        # Already loaded with the same model — reuse
        if self._loaded and self._current_model == model_name:
            logger.info(f"[Whisper] {model_name} already loaded — reusing")
            return True

        try:
            from faster_whisper import WhisperModel

            # Unload previous model if any
            if self._model is not None:
                self.unload()

            self._device, self._compute_type = self._get_device_and_compute()
            download_root = self._get_download_root()

            logger.info(
                f"[Whisper] Loading '{model_name}' on {self._device} "
                f"({self._compute_type})"
                + (f" → {download_root}" if download_root else "")
            )

            self._model = WhisperModel(
                model_name,
                device=self._device,
                compute_type=self._compute_type,
                download_root=download_root,
            )

            self._loaded        = True
            self._current_model = model_name
            logger.info(f"[Whisper] '{model_name}' loaded ✓")
            return True

        except Exception as e:
            logger.error(f"[Whisper] Failed to load '{model_name}': {e}")
            self._loaded = False
            return False

    def unload(self) -> None:
        """Unload model and free VRAM."""
        if self._model is not None:
            logger.info("[Whisper] Unloading model…")
            del self._model
            self._model = None
            try:
                import torch
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
            except Exception:
                pass
            gc.collect()
            self._loaded        = False
            self._current_model = None
            logger.info("[Whisper] Model unloaded")

    # ------------------------------------------------------------------
    # Transcription
    # ------------------------------------------------------------------

    #: Fenêtre de décision de langue de Whisper (la sienne, en mode multilingue).
    LANGUAGE_WINDOW_SECONDS = 30

    def _label_window_languages(self, audio_path: str, segments: list, fallback: str) -> None:
        """Pose sa langue sur chaque segment, fenêtre de 30 s par fenêtre de 30 s.

        faster-whisper redétecte la langue à chaque fenêtre en mode multilingue mais ne la rend
        PAS par segment (champs de `Segment` : aucun `language`). On la redemande donc au MÊME
        modèle, sur la fenêtre de l'audio ORIGINAL qui contient le milieu du segment — pas sur ses
        fenêtres internes, décalées par le filtre de parole (il décode un audio condensé). Une
        seule détection par fenêtre qui porte au moins un segment ; échec → langue globale.
        """
        from wama.common.utils.audio_decode import decode_window
        span = self.LANGUAGE_WINDOW_SECONDS
        by_window = {}
        for s in segments:
            by_window.setdefault(int(((s.start_time + s.end_time) / 2) // span), []).append(s)
        for index, members in by_window.items():
            language = fallback
            try:
                audio, _ = decode_window(audio_path, start_s=index * span, duration_s=span)
                if len(audio):
                    language = self._model.detect_language(audio=audio)[0] or fallback
            except Exception as exc:
                logger.warning(f"[Whisper] langue de la fenêtre {index} illisible : {exc}")
            for s in members:
                s.language = language

    def transcribe(
        self,
        audio_path: str,
        language: str = None,
        hotwords: str = None,         # param NATIF faster-whisper (utilisé, cf. ~l.211)
        **kwargs,
    ) -> TranscriptionResult:
        """
        Transcribe an audio file with faster-whisper.

        Supported kwargs:
            enable_timestamps (bool, default True)
            vad_filter        (bool, default True)
            multilingual      (bool, default False) — langue redétectée par fenêtre de 30 s
            beam_size         (int,  default 5)
            temperature       (float)

        Returns:
            TranscriptionResult — segments have empty speaker_id (filled by
            pyannote post-processing in workers.py if diarization is enabled).
        """
        if not self._loaded or self._model is None:
            if not self.load():
                return TranscriptionResult(
                    success=False, text='',
                    error="Failed to load Whisper model",
                )

        try:
            logger.info(f"[Whisper] Transcribing: {audio_path}")

            transcribe_opts: dict = {
                'language':        language or None,
                'vad_filter':      kwargs.get('vad_filter', True),
                'word_timestamps': kwargs.get('enable_timestamps', True),
                'beam_size':       int(kwargs.get('beam_size', 5)),
            }
            if 'temperature' in kwargs:
                transcribe_opts['temperature'] = float(kwargs['temperature'])
            # Plusieurs langues dans l'audio : faster-whisper redétecte la langue à CHAQUE
            # fenêtre de 30 s au lieu de décider une fois sur les 30 premières secondes.
            multilingual = bool(kwargs.get('multilingual')) and not language
            if multilingual:
                transcribe_opts['multilingual'] = True

            # Mots-clés contextuels → param NATIF `hotwords` de faster-whisper.
            # ⚠️ NE PAS utiliser initial_prompt : un prompt sans ponctuation fait que
            # Whisper imite ce style (= sortie sans majuscules/ponctuation).
            hw = (hotwords or kwargs.get('hotwords') or '').strip()
            if hw:
                transcribe_opts['hotwords'] = hw
                logger.info(f"[Whisper] hotwords: {hw[:120]}")

            segments_gen, info = self._model.transcribe(audio_path, **transcribe_opts)

            segments:    list[TranscriptionSegment] = []
            text_parts:  list[str]                  = []

            # Progression intermédiaire : faster-whisper yield les segments au fil de l'audio
            # → on reporte `seg.end / durée` (sinon la barre reste figée toute la transcription,
            # ce qui empêche l'ETA de s'estimer). Throttlé à ~2 % pour limiter les écritures DB.
            total_dur = float(getattr(info, 'duration', 0) or 0)
            prog_cb = kwargs.get('progress_callback')
            last_emit = 0.0

            for seg in segments_gen:
                confidence = getattr(seg, 'avg_logprob', None)
                if prog_cb and total_dur > 0:
                    ratio = min(1.0, max(0.0, (getattr(seg, 'end', 0) or 0) / total_dur))
                    if ratio - last_emit >= 0.02:
                        last_emit = ratio
                        try:
                            prog_cb(ratio)
                        except Exception:
                            pass
                # Timing mot-à-mot (word_timestamps=True) → conservé pour la synchro
                # fine onde↔texte et la heatmap par mot (probability = confiance mot).
                words = None
                seg_words = getattr(seg, 'words', None)
                if seg_words:
                    words = [{
                        'word': w.word,
                        'start': w.start,
                        'end': w.end,
                        'probability': getattr(w, 'probability', None),
                    } for w in seg_words]
                segments.append(TranscriptionSegment(
                    speaker_id = '',          # filled by pyannote later
                    start_time = seg.start,
                    end_time   = seg.end,
                    text       = seg.text.strip(),
                    confidence = confidence,
                    words      = words,
                ))
                text_parts.append(seg.text.strip())

            full_text = ' '.join(text_parts).strip()
            if multilingual:
                self._label_window_languages(audio_path, segments, info.language)
            else:
                for s in segments:
                    s.language = info.language
            logger.info(
                f"[Whisper] Done — {len(full_text)} chars, "
                f"{len(segments)} segments, lang={info.language}"
            )

            return TranscriptionResult(
                success  = True,
                text     = full_text,
                language = info.language,
                segments = segments,
            )

        except Exception as e:
            logger.error(f"[Whisper] Transcription failed: {e}")
            return TranscriptionResult(success=False, text='', error=str(e))
