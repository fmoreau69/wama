"""
pyannote.audio Speaker Diarizer for Transcriber

Post-processes Whisper segments to assign a speaker_id to each segment by
computing the maximum time-overlap between each Whisper segment and the
pyannote diarization turns.

Requires:
    pip install pyannote.audio>=3.3.1

The pyannote/speaker-diarization-3.1 model is gated on HuggingFace.
Provide an access token via settings.HUGGINGFACE_TOKEN or the hf_token arg.

CONTRAT COMMUN (2026-07-29) — ce module tenait auparavant son pipeline dans un GLOBAL
(`_pipeline`) chargé sur CUDA par une fonction : hors de toute classe backend, donc invisible
du gouverneur de ressources. Deux conséquences mesurées, corrigées ici :
  1. il se charge PAR-DESSUS un ASR déjà résident (whisper 10 Go réservés) sans rien déclarer,
     donc le gouverneur sous-estimait le pic réel du transcriber — c'est le chemin même de la
     « diarisation tueuse » de la boucle de crash WSL2 du 29/07 ;
  2. `MemoryManager._unload_transcriber_model` importait `unload_pipeline()`… qui n'existait
     PAS. L'ImportError étant avalé en `logger.debug`, le reclaim central croyait libérer la
     VRAM de pyannote et ne la libérait JAMAIS (fuite jusqu'à la mort du process).
Le pipeline vit maintenant dans un `BaseModelBackend` : `load()`/`unload()` sont enveloppés
automatiquement (déclaration/libération de l'empreinte), et `unload_pipeline()` existe.

L'API MODULE (`is_available`, `diarize`, `unload_pipeline`) est conservée telle quelle : c'est
ce que `workers.py` et `memory_manager.py` appellent.
"""

import logging
from typing import List, Optional

from wama.common.backends.base import BaseModelBackend

logger = logging.getLogger(__name__)


class PyannoteDiarizerBackend(BaseModelBackend):
    """
    Diariseur (qui parle quand) en post-traitement des segments ASR.

    N'est VOLONTAIREMENT pas enregistré dans `TranscriberBackendManager` : ce n'est pas un
    moteur de transcription alternatif mais une passe complémentaire. L'y mettre exposerait
    « pyannote » au choix de moteur et à `get_backend('auto')`.
    """

    name = "pyannote"
    display_name = "pyannote speaker-diarization-3.1"
    description = "Diarisation des locuteurs en post-traitement des segments ASR (Whisper, Qwen3-ASR)."

    # Dépendances (contrat commun). Le modèle est GATED sur HuggingFace : la présence du paquet
    # ne garantit pas l'accès au modèle — l'échec de `load()` est traité comme non-fatal.
    REQUIRED_PACKAGES = ["pyannote.audio"]
    PIP_PACKAGES = ["pyannote.audio>=3.3.1"]

    # Repli du gouverneur si la mesure autour du chargement n'est pas concluante.
    # speaker-diarization-3.1 (segmentation + embedding) ≈ 2 Go sur GPU.
    recommended_vram_gb = 2

    def __init__(self):
        self._pipeline = None

    @property
    def is_loaded(self) -> bool:
        return self._pipeline is not None

    def load(self, model: Optional[str] = None, hf_token: Optional[str] = None) -> bool:
        """Charge (ou réutilise) le pipeline de diarisation. False si indisponible."""
        if self._pipeline is not None:
            return True

        import os

        import torch

        # ── CRITICAL: set HF_HUB_CACHE BEFORE importing pyannote/huggingface_hub ──
        # This routes all sub-downloads (weights, configs) to speech/diarization/
        # instead of the global AI-models/cache/huggingface/ fallback.
        try:
            from pathlib import Path

            from django.conf import settings as _s
            _dia_dir = _s.MODEL_PATHS.get('speech', {}).get(
                'diarization',
                _s.AI_MODELS_DIR / "models" / "speech" / "diarization"
            )
            Path(_dia_dir).mkdir(parents=True, exist_ok=True)
            _cache = str(_dia_dir)
            os.environ['HF_HUB_CACHE'] = _cache
            os.environ['HUGGINGFACE_HUB_CACHE'] = _cache
            logger.info(f"[pyannote] Cache → {_cache}")
        except Exception:
            pass

        from pyannote.audio import Pipeline

        # Resolve HuggingFace token from argument or Django settings
        token = hf_token
        if not token:
            try:
                from django.conf import settings
                token = getattr(settings, 'HUGGINGFACE_TOKEN', None)
            except Exception:
                pass

        logger.info("[pyannote] Loading speaker-diarization-3.1 pipeline…")
        pipeline = Pipeline.from_pretrained(
            "pyannote/speaker-diarization-3.1",
            token=token,
        )

        if torch.cuda.is_available():
            pipeline = pipeline.to(torch.device("cuda"))
            logger.info("[pyannote] Pipeline moved to CUDA")

        self._pipeline = pipeline
        logger.info("[pyannote] Pipeline loaded ✓")
        return True

    def unload(self) -> None:
        """Libère le pipeline (et la réservation VRAM, via l'enveloppe du contrat commun)."""
        if self._pipeline is None:
            return
        self._pipeline = None
        try:
            import gc

            import torch
            gc.collect()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:
            pass
        logger.info("[pyannote] Pipeline unloaded ✓")

    def process(self, **kwargs) -> list:
        """Point d'entrée métier générique (contrat commun) → délègue à diarize()."""
        return self.diarize(**kwargs)

    @staticmethod
    def _preload_audio(audio_path: str) -> dict:
        """
        Load audio into the {'waveform': tensor, 'sample_rate': int} dict expected by
        pyannote, bypassing its torchcodec/FFmpeg decoder (cassé dans ce venv).

        Délègue au helper commun `common/utils/audio_decode.decode_for_pyannote`
        (chaîne robuste soundfile → faster-whisper/PyAV → ffmpeg, gère m4a/mp3/aac).
        En cas d'échec total, on renvoie le chemin brut (dernier recours pyannote).
        """
        try:
            from wama.common.utils.audio_decode import decode_for_pyannote
            return decode_for_pyannote(audio_path, target_sr=16000)
        except Exception as e:
            logger.warning(f"[pyannote] decode failed ({e}), passing raw path")
            return audio_path  # type: ignore[return-value]

    def diarize(
        self,
        audio_path: str,
        segments: list,
        num_speakers: Optional[int] = None,
        hf_token: Optional[str] = None,
    ) -> list:
        """
        Run speaker diarization and assign speaker_id to each segment.

        Args:
            audio_path:   Path to the audio file.
            segments:     List of TranscriptionSegment (speaker_id='') from Whisper.
            num_speakers: Optional number of speakers hint.
            hf_token:     HuggingFace access token for the gated pyannote model.

        Returns:
            Same list with speaker_id populated.
            Falls back gracefully (empty speaker_id) on any failure.
        """
        if not segments:
            return segments

        try:
            self.load(hf_token=hf_token)
            pipeline = self._pipeline

            diarize_kwargs: dict = {}
            if num_speakers:
                diarize_kwargs["num_speakers"] = num_speakers

            # Pre-load audio as tensor to avoid torchcodec/FFmpeg dependency in pyannote
            audio_input = self._preload_audio(audio_path)

            logger.info(f"[pyannote] Diarizing: {audio_path}")
            diarization = pipeline(audio_input, **diarize_kwargs)

            # Compat pyannote 3.x (Annotation, .itertracks) ↔ 4.x (DiarizeOutput :
            # l'Annotation est dans .speaker_diarization / .diarization).
            annotation = diarization
            if not hasattr(annotation, 'itertracks'):
                annotation = (getattr(diarization, 'speaker_diarization', None)
                              or getattr(diarization, 'diarization', None)
                              or annotation)

            # Extract (start, end, speaker) turns from pyannote output
            dia_turns: List[tuple] = [
                (turn.start, turn.end, speaker)
                for turn, _, speaker in annotation.itertracks(yield_label=True)
            ]
            logger.info(f"[pyannote] {len(dia_turns)} diarization turns found")

            # Assign speaker to each Whisper segment by maximum time overlap
            unassigned = 0
            for seg in segments:
                best_speaker = ""
                best_overlap = 0.0
                for d_start, d_end, speaker in dia_turns:
                    overlap = min(seg.end_time, d_end) - max(seg.start_time, d_start)
                    if overlap > best_overlap:
                        best_overlap = overlap
                        best_speaker = speaker
                # Aucun recouvrement (mot isolé dans un trou entre deux tours) → on rattache au
                # locuteur du tour le PLUS PROCHE, plutôt que de laisser un segment sans locuteur
                # (sinon il apparaît « non identifié » et fausse le compte des intervenants).
                if not best_speaker:
                    mid = (seg.start_time + seg.end_time) / 2.0
                    nearest, ndist = "", float('inf')
                    for d_start, d_end, speaker in dia_turns:
                        dist = (d_start - mid) if mid < d_start else (mid - d_end if mid > d_end else 0.0)
                        if dist < ndist:
                            ndist, nearest = dist, speaker
                    best_speaker = nearest
                    unassigned += 1
                seg.speaker_id = best_speaker

            logger.info(f"[pyannote] Speaker IDs assigned ✓ ({unassigned} segment(s) rattaché(s) au plus proche)")
            return segments

        except Exception as e:
            logger.error(f"[pyannote] Diarization failed — returning original segments: {e}")
            return segments


# ──────────────────────────────────────────────────────────────────────────────
# API MODULE — surface historique conservée (workers.py, memory_manager.py)
# ──────────────────────────────────────────────────────────────────────────────

# Singleton de process : le pipeline reste chaud d'une transcription à l'autre, comme avant.
_backend: Optional[PyannoteDiarizerBackend] = None


def get_diarizer() -> PyannoteDiarizerBackend:
    """Instance unique du diariseur pour ce process."""
    global _backend
    if _backend is None:
        _backend = PyannoteDiarizerBackend()
    return _backend


def is_available() -> bool:
    """Return True if pyannote.audio is installed."""
    return PyannoteDiarizerBackend.is_available()


def diarize(
    audio_path: str,
    segments: list,
    num_speakers: Optional[int] = None,
    hf_token: Optional[str] = None,
) -> list:
    """Diarise `segments` (voir `PyannoteDiarizerBackend.diarize`)."""
    return get_diarizer().diarize(audio_path, segments, num_speakers, hf_token)


def unload_pipeline() -> bool:
    """
    Décharge le pipeline ; True si quelque chose a été libéré.

    ⚠ Cette fonction était APPELÉE par `MemoryManager._unload_transcriber_model` sans jamais
    avoir existé (ImportError avalé en debug) : le reclaim central croyait libérer la VRAM de
    pyannote sans rien libérer. Ne pas la renommer sans mettre à jour cet appelant.
    """
    backend = get_diarizer()
    if not backend.is_loaded:
        return False
    backend.unload()
    return True
