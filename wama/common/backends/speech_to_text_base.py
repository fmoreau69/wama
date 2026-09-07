"""
Transcriber Backend Base Classes

Spécialisation MÉTIER (speech-to-text) du contrat de backend COMMUN
`wama.common.backends.base.BaseModelBackend`.

⚠️ Ne PAS re-définir ici un contrat concurrent : jusqu'au 2026-07-29 cette classe héritait
directement d'`ABC`, si bien que les 3 moteurs ASR (whisper, vibevoice, qwen_asr) échappaient à
la déclaration automatique d'empreinte VRAM au gouverneur de ressources — c'est-à-dire au
mécanisme même dont le transcriber avait été l'app de référence. Cf. PROJECT_STATUS §0 (3bis).

Ce qui vient du COMMUN (ne pas dupliquer) : cycle de vie (load/is_loaded/unload/process),
`missing_packages()`/`is_available()`/`pip_install_spec()` dérivés de `REQUIRED_PACKAGES`,
l'enveloppe automatique load/unload qui déclare/libère la VRAM (`__init_subclass__`), et
— depuis le 2026-08-20 — les FLAGS DE CAPACITÉ `supports_*` (+ la borne `timestamp_languages`).
Ce qui est PROPRE au domaine ici : le verbe `transcribe()`, `TranscriptionResult/Segment`
et `max_audio_seconds`.
"""

from abc import abstractmethod
from dataclasses import dataclass, field
from typing import List, Optional
import logging

from wama.common.backends.base import BaseModelBackend

logger = logging.getLogger(__name__)


@dataclass
class TranscriptionSegment:
    """A segment of transcription with speaker and timing info."""
    speaker_id: str
    start_time: float  # seconds
    end_time: float    # seconds
    text: str
    confidence: Optional[float] = None
    # Timing mot-à-mot (si dispo) : liste de {word, start, end, probability}.
    # Alimente la synchro fine onde↔texte et la granularité de la heatmap.
    words: Optional[List[dict]] = None

    def to_dict(self) -> dict:
        d = {
            'speaker_id': self.speaker_id,
            'start_time': self.start_time,
            'end_time': self.end_time,
            'text': self.text,
            'confidence': self.confidence,
        }
        if self.words:
            d['words'] = self.words
        return d


@dataclass
class TranscriptionResult:
    """Result from a transcription operation."""
    success: bool
    text: str
    language: str = ''
    segments: List[TranscriptionSegment] = field(default_factory=list)
    error: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            'success': self.success,
            'text': self.text,
            'language': self.language,
            'segments': [s.to_dict() for s in self.segments],
            'error': self.error,
        }


class SpeechToTextBackend(BaseModelBackend):
    """
    Contrat des moteurs de reconnaissance de parole — spécialisation de `BaseModelBackend`.

    Un nouveau moteur = une sous-classe qui déclare ses `REQUIRED_PACKAGES`, ses capacités,
    et implémente `load()/unload()/transcribe()`. Rien d'autre : l'empreinte VRAM est déclarée
    au gouverneur automatiquement par le contrat commun.
    """

    # Class-level attributes to be overridden by subclasses
    name: str = "base"
    display_name: str = "Base Backend"
    # Descriptif COURT (une ligne) affiché sous le choix du moteur (volet/modale).
    description: str = ""
    # Descriptif LONG (paragraphe) pour l'à-propos / le tooltip détaillé / le catalogue.
    # Vide → on retombe sur `description`.
    description_long: str = ""

    # Feature flags : HÉRITÉS du contrat commun depuis le 2026-08-20 (ils y sont déclarés avec
    # les mêmes défauts `False`). Redéclarés ici jusque-là, ils faisaient croire que « capacité »
    # était une notion STT — or `supports_timestamps`/`supports_streaming` sont des notions de
    # PAROLE (la TTS les a aussi), et le vocabulaire commun listait même `supports_cloning`, qui
    # est purement TTS. Les moteurs concrets (whisper/qwen/vibevoice) continuent de les déclarer :
    # c'est leur rôle. Ne pas les re-poser ici — ce serait rouvrir la divergence.

    # Resource requirements
    min_vram_gb: float = 0
    # `recommended_vram_gb` est HÉRITÉ du contrat commun : c'est la valeur de repli que le
    # gouverneur réserve quand la mesure autour de load() n'est pas concluante. Ce repli n'est
    # pas théorique ici — faster-whisper (CTranslate2) alloue HORS de l'allocateur PyTorch, donc
    # `torch.cuda.memory_allocated()` ne bouge pas : c'est la valeur déclarée qui fait foi.

    # Durée audio MAX (secondes) que le moteur traite d'un seul tenant. None = illimité
    # (ex. Whisper, fenêtré). Si un audio dépasse, la couche d'orchestration (workers) le
    # DÉCOUPE automatiquement en morceaux ≤ cette limite et recolle les timestamps. Sert
    # notamment aux moteurs génératifs (VibeVoice ≈ 60 min de budget tokens).
    max_audio_seconds: Optional[float] = None

    def __init__(self):
        self._loaded = False
        self._current_model = None

    # `is_available()` / `missing_packages()` / `pip_install_spec()` viennent du contrat commun
    # et se déduisent de `REQUIRED_PACKAGES` (find_spec). N'override que si la présence du paquet
    # ne suffit PAS à conclure — cf. VibeVoiceBackend, dont le paquet pip homonyme est un TTS
    # sans rapport (on vérifie alors le fichier de modeling ASR).

    @abstractmethod
    def load(self, model_name: str = None) -> bool:
        """
        Load the transcription model into memory.

        Args:
            model_name: Optional model identifier. If None, use default.

        Returns:
            True if loaded successfully, False otherwise.
        """
        pass

    @abstractmethod
    def transcribe(
        self,
        audio_path: str,
        language: str = None,
        hotwords: str = None,
        **kwargs
    ) -> TranscriptionResult:
        """
        Transcribe an audio file.

        Args:
            audio_path: Path to the audio file.
            language: Optional language code (e.g., 'en', 'fr'). Auto-detect if None.
            hotwords: Optional comma-separated list of domain-specific terms.
            **kwargs: Additional backend-specific parameters.

        Returns:
            TranscriptionResult with text and optional segments.
        """
        pass

    def process(self, **kwargs) -> TranscriptionResult:
        """Point d'entrée métier générique (contrat commun BaseModelBackend) → délègue à transcribe()."""
        return self.transcribe(**kwargs)

    @abstractmethod
    def unload(self) -> None:
        """
        Unload the model from memory to free resources.
        """
        pass

    @property
    def is_loaded(self) -> bool:
        """Check if a model is currently loaded."""
        return self._loaded

    def get_info(self) -> dict:
        """Get backend information."""
        return {
            'name': self.name,
            'display_name': self.display_name,
            'available': self.is_available(),
            'loaded': self.is_loaded,
            'current_model': self._current_model,
            'supports_diarization': self.supports_diarization,
            'supports_timestamps': self.supports_timestamps,
            'supports_hotwords': self.supports_hotwords,
            'supports_streaming': self.supports_streaming,
            'min_vram_gb': self.min_vram_gb,
            'recommended_vram_gb': self.recommended_vram_gb,
        }
