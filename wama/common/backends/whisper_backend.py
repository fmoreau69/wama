"""
Whisper Backend for Transcriber — powered by faster-whisper.

Uses CTranslate2 (float16 on GPU, int8 on CPU) for significantly faster
inference than the original openai-whisper while keeping the same accuracy.

Default model: large-v3 (best accuracy, ≈10 GB VRAM).

Poids : les tailles que le catalogue connaît sont DÉCLARÉES ici (`WHISPER_REPOS`) — le dépôt
CTranslate2 que le moteur lit, et le modèle d'origine dont il est la conversion. La route les
installe comme tout dépôt du Hub (pilote `hf`, dossier de famille, empreintes publiées vérifiées)
et le moteur lit le snapshot SANS réseau (`local_files_only`). Historique : jusqu'au 2026-11-02
la librairie tirait le dépôt au premier usage ; du 02 au 05/11 ses fichiers étaient déclarés un à
un (pilote `files`) ; depuis le 2026-11-05, la règle commune des modèles du Hub (REMOVAL_LEDGER).
"""

import gc
import logging
from pathlib import Path
from typing import Optional

from .speech_to_text_base import SpeechToTextBackend, TranscriptionResult, TranscriptionSegment

logger = logging.getLogger(__name__)

DEFAULT_WHISPER_MODEL = 'large-v3'


#: Les tailles que le catalogue DÉCLARE (`transcriber:whisper` lit large-v3, la sonde des langues
#: tiny — `spoken_language`) : le dépôt que le moteur LIT, et le modèle d'ORIGINE dont il est la
#: conversion. faster-whisper ne lit que le format CTranslate2, qu'OpenAI ne publie pas ; Systran,
#: l'auteur de faster-whisper, le publie (« conversion of openai/whisper-large-v3 to the
#: CTranslate2 model format », `--quantization float16`, carte du dépôt), sans déclarer de
#: `base_model` dans sa carte. La relation est donc DÉCLARÉE ici, dans le vocabulaire du Hub :
#: `quantized`, celui qu'il pose sur un export de format (ONNX, GGUF) — c'est elle qui relie la
#: ligne à son modèle d'origine (bancs, `AIModel.quantized_base`) sans en faire une dorsale.
WHISPER_REPOS = {
    'large-v3': {'repo': 'Systran/faster-whisper-large-v3', 'base_model': 'openai/whisper-large-v3'},
    'tiny': {'repo': 'Systran/faster-whisper-tiny', 'base_model': 'openai/whisper-tiny'},
}


def whisper_folder() -> Path:
    """Le dossier de famille de Whisper (`MODEL_PATHS['speech']['whisper']`) — et, hors Django
    (service vocal, uvicorn :8001), le MÊME dossier par le repli des moteurs de parole : jamais le
    `$HOME` (cache HF par défaut de faster-whisper) — `tts_base.speech_folder`."""
    from wama.common.backends.tts_base import speech_folder
    return speech_folder('whisper')


def whisper_snapshot_root(size: str) -> Path:
    """La racine `models--org--nom` d'une taille déclarée, sous le dossier de famille — là où la
    route l'installe (`snapshot_download(cache_dir=…)`) et où faster-whisper la relit."""
    from wama.common.utils.model_locations import hf_folder_name
    return whisper_folder() / hf_folder_name(WHISPER_REPOS[size]['repo'])


def whisper_installed(size: str) -> bool:
    """Des POIDS complets pour cette taille — LE jugement commun de « téléchargé », celui de la
    découverte (`prospector.installed_weights_complete`)."""
    from wama.model_manager.services.prospector import installed_weights_complete
    return installed_weights_complete(whisper_snapshot_root(size))


def whisper_model_source(model_name: str) -> tuple[str, bool]:
    """`(ce que reçoit WhisperModel, local_files_only)`. Une taille DÉCLARÉE (`WHISPER_REPOS`)
    se lit par son dépôt dans le dossier de famille, sans réseau : la route l'installe ; si
    elle manque, on le dit (`RuntimeError`, le moteur ne télécharge pas lui-même). Une taille
    que le catalogue ne déclare pas (un `WAMA_ASSISTANT_STT_MODEL` réglé autrement) garde son
    nom : faster-whisper la range dans le même dossier (`download_root`), le levier A
    d'`hf_weights`. Lue par les DEUX backends du moteur (`WhisperBackend`,
    `WhisperLanguageBackend`)."""
    declared = WHISPER_REPOS.get(model_name)
    if declared is None:
        return model_name, False
    if not whisper_installed(model_name):
        raise RuntimeError(
            f"Whisper {model_name} n'est pas installé ({whisper_snapshot_root(model_name)}) — "
            f"il s'installe par le model manager (dépôt « {declared['repo']} »).")
    return declared['repo'], True


def whisper_base_model(size: str) -> dict:
    """`{base_model, base_model_relation}` d'une taille déclarée — la paire que la découverte pose
    sur la ligne (vocabulaire du Hub, `AIModel.BASE_MODEL_RELATIONS`)."""
    from wama.model_manager.models import BASE_RELATION_QUANTIZED
    return {'base_model': WHISPER_REPOS[size]['base_model'],
            'base_model_relation': BASE_RELATION_QUANTIZED}


class WhisperBackend(SpeechToTextBackend):
    """
    Speech-to-text backend using faster-whisper (CTranslate2).

    Supports large-v3 (default), large-v3-turbo, medium, small, base, tiny.
    Diarization is handled externally by pyannote_diarizer (see workers.py).
    """

    #: Moteur piloté (contrat commun) — voir BaseModelBackend.ENGINE.
    ENGINE = 'faster-whisper'
    #: Modèles servis (2026-11-06) : `faster-whisper` est AUSSI le moteur de l'identificateur de
    #: langue (`WhisperLanguageBackend`, Whisper tiny) — un moteur partagé se départage par la
    #: liste de chacun (`backend_inventory.resolve_entry`, règle 2). Clé = dernier segment de la
    #: clé de catalogue ; `size` = la taille que `load()` reçoit. ⚠ En LITTÉRAL : l'inventaire lit
    #: les clés par AST, sans importer.
    SUPPORTED_MODELS = {
        'whisper': {'size': 'large-v3', 'model_key': 'transcriber:whisper'},
    }
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
    # Repli du gouverneur quand le chargement ne se mesure pas : CTranslate2 alloue hors de
    # l'allocateur PyTorch, sa mesure vient du contexte CUDA (`base._measured_outside_torch_gb`).
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
        """Le dossier de famille (`whisper_folder`) — là où faster-whisper range une taille que le
        catalogue ne déclare pas. ⚠ Hors Django, rendre None ici laissait faster-whisper
        télécharger dans le `$HOME` (2026-10-10)."""
        return str(whisper_folder())

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
        # Un modèle LISTÉ se reçoit par son identifiant de catalogue, comme chez NeMo et Qwen3-ASR
        # (`TranscriberBackendManager.model_for_request`) : `whisper` → la taille qu'il déclare.
        model_name = (self.SUPPORTED_MODELS.get(model_name) or {}).get('size', model_name)

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

            source, local_only = whisper_model_source(model_name)
            self._model = WhisperModel(
                source,
                device=self._device,
                compute_type=self._compute_type,
                download_root=download_root,
                local_files_only=local_only,
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
