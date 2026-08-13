"""
WAMA Common — transcription audio pour les apps NON-transcriber (describer).

DÉLÈGUE aux backends du transcriber depuis le 2026-08-13. Avant : ce module chargeait sa
PROPRE instance faster-whisper à CHAQUE appel puis la détruisait — un second chemin de
chargement à côté de `transcriber/backends/whisper_backend.py` (même modèle, même cache
`AI-models/models/speech/whisper` — vérifié identique —, mais ni singleton, ni VRAM
déclarée, ni hotwords). Le docstring prétendait même que le transcriber le partageait :
faux depuis longtemps, seul le describer l'importe.

Il ne reste ici que l'ADAPTATION : signature et `WhisperResult` conservés pour les
consommateurs (describer audio/vidéo n'utilisent que `.text`), exécution par
`get_backend('whisper')` — singleton géré, modèle GARDÉ chargé après l'appel (pattern
keep_loaded maison ; le reclaim du gouverneur l'évince si la VRAM manque ailleurs).

Usage:
    from wama.common.utils.whisper_utils import transcribe_audio, WhisperResult

    result = transcribe_audio(audio_path)
    print(result.text, result.language, result.duration)
"""

import logging
from dataclasses import dataclass, field
from typing import List, Optional

logger = logging.getLogger(__name__)

DEFAULT_MODEL = 'large-v3'


@dataclass
class WhisperSegment:
    start: float
    end: float
    text: str
    words: list = field(default_factory=list)


@dataclass
class WhisperResult:
    text: str
    language: str
    duration: float
    segments: List[WhisperSegment] = field(default_factory=list)


def transcribe_audio(
    audio_path: str,
    model_name: str = DEFAULT_MODEL,
    language: Optional[str] = None,
    device: str = 'auto',
    compute_type: Optional[str] = None,
    vad_filter: bool = True,
    word_timestamps: bool = True,
    beam_size: int = 5,
) -> WhisperResult:
    """
    Transcrit un fichier audio/vidéo VIA le backend Whisper du transcriber.

    Args:
        audio_path:      Chemin du fichier audio / vidéo.
        model_name:      Taille du modèle Whisper (défaut : 'large-v3').
        language:        Code ISO 639-1, ou None pour auto-détection.
        device:          IGNORÉ (délégué) — le backend choisit device et compute type.
        compute_type:    IGNORÉ (délégué) — idem.
        vad_filter:      Retirer les silences (Voice Activity Detection).
        word_timestamps: Timing mot-à-mot dans les segments.
        beam_size:       Largeur du beam search.

    Returns:
        WhisperResult avec .text, .language, .duration, .segments.
        NB : .duration = fin du dernier segment (le contrat TranscriptionResult ne porte
        pas la durée du média) — aucun consommateur actuel ne la lit.

    Raises:
        RuntimeError si le chargement ou la transcription échoue.
    """
    from wama.transcriber.backends.manager import get_backend

    backend = get_backend('whisper')
    if not backend.load(model_name):        # no-op si déjà chargé avec ce modèle
        raise RuntimeError(f"Chargement du modèle Whisper '{model_name}' impossible")

    res = backend.transcribe(
        audio_path,
        language=language,
        vad_filter=vad_filter,
        enable_timestamps=word_timestamps,
        beam_size=beam_size,
    )
    if not res.success:
        raise RuntimeError(res.error or 'Transcription échouée')

    segments = [
        WhisperSegment(start=s.start_time, end=s.end_time, text=s.text, words=s.words or [])
        for s in res.segments
    ]
    logger.info(f"[whisper_utils] Délégué au backend transcriber — "
                f"{len(res.text)} chars, {len(segments)} segments, lang={res.language}")
    return WhisperResult(
        text=res.text,
        language=res.language,
        duration=segments[-1].end if segments else 0.0,
        segments=segments,
    )
