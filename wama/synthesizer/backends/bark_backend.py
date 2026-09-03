"""
Backend Bark (Suno) — TTS expressif à presets, sans clonage libre.

Le mapping preset → locuteur Bark vit ICI (vocabulaire du moteur), la résolution
preset → fichier WAV de référence reste dans le service (politique média).
"""
from __future__ import annotations

import logging
import os

import numpy as np

from wama.common.tts.constants import BARK_LANG_DEFAULTS

from .base import CATALOG_KEYS, TTSBackend, speech_dir, write_wav_int16

logger = logging.getLogger(__name__)


def bark_speaker_for(voice_preset: str, language: str) -> str:
    """Preset UI → prompt locuteur Bark (`v2/<lang>_speaker_<n>`)."""
    if voice_preset.startswith("bark_v2_"):
        parts = voice_preset.replace("bark_v2_", "").split("_")
        if len(parts) == 2:
            return f"v2/{parts[0]}_speaker_{parts[1]}"
    return BARK_LANG_DEFAULTS.get(language, "v2/en_speaker_0")


class BarkBackend(TTSBackend):
    #: Moteur piloté (contrat commun) — voir BaseModelBackend.ENGINE.
    ENGINE = 'bark'
    engine = "bark"
    description = "Bark (Suno) — TTS expressif (rires, hésitations, bruitages)."

    supports_cloning = False   # presets de locuteurs, pas de clonage libre (aligné sur le catalogue)

    REQUIRED_PACKAGES = ['bark', 'scipy']
    # ⚠ `pip install bark` installe un paquet HOMONYME sans rapport — l'installation
    # passe par le dépôt Suno (même précédent que vibevoice) : rien d'automatique.
    PIP_PACKAGES = []

    recommended_vram_gb = 5.0

    def __init__(self):
        super().__init__()
        self._funcs = None   # {"generate_audio": ..., "SAMPLE_RATE": ...}

    @property
    def is_loaded(self) -> bool:
        return self._funcs is not None

    def load(self, model: str | None = None) -> bool:
        if self._funcs is not None:
            return True

        cache_dir = speech_dir('bark')
        # Bark met ses poids sous XDG_CACHE_HOME — à poser AVANT l'import.
        os.environ["XDG_CACHE_HOME"] = str(cache_dir)
        os.environ.setdefault("SUNO_USE_SMALL_MODELS", "False")
        logger.info(f"[Bark] XDG_CACHE_HOME={cache_dir}")

        from bark import SAMPLE_RATE, generate_audio, preload_models

        logger.info("[Bark] préchargement des modèles…")
        preload_models()

        self._funcs = {"generate_audio": generate_audio, "SAMPLE_RATE": SAMPLE_RATE}
        self.loaded_model = "bark"
        self._current_model = CATALOG_KEYS['bark']
        return True

    def unload(self) -> None:
        if self._funcs is None:
            return
        logger.info("[Bark] déchargement")
        self._funcs = None
        self.loaded_model = None
        self._current_model = None
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:
            pass

    def process(self, text: str = "", language: str = "fr",
                voice_preset: str = "default", **_ignored) -> str:
        speaker = bark_speaker_for(voice_preset, language)
        audio_array = self._funcs["generate_audio"](text, history_prompt=speaker)
        return write_wav_int16(np.asarray(audio_array, dtype=np.float32),
                               self._funcs["SAMPLE_RATE"])
