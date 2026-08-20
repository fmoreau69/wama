"""
Backend Kokoro 82M — TTS multilingue ultra-léger (temps réel).

Un pipeline PAR LANGUE, chargés paresseusement (thread-safe). La POLITIQUE de
résidence (« Kokoro reste chaud, on ne le décharge jamais à la bascule ») est
celle du service TTS — `unload()` ici décharge RÉELLEMENT, c'est le service qui
choisit de ne pas l'appeler.
"""
from __future__ import annotations

import logging
import os
import threading

import numpy as np

from wama.common.tts.constants import KOKORO_LANG_MAP, KOKORO_VOICE_MAP

from .base import CATALOG_KEYS, TTSBackend, speech_dir, write_wav_int16

logger = logging.getLogger(__name__)

REPO_ID = 'hexgrad/Kokoro-82M'


class KokoroBackend(TTSBackend):
    engine = "kokoro"
    description = "Kokoro 82M — TTS léger FR/EN/ES/IT/PT/JA/ZH, temps réel."

    supports_cloning = False   # voix FIXES par langue (aligné sur le catalogue)
    #: Kokoro calcule les timestamps mot PENDANT la synthèse — `KPipeline.join_timestamps()`
    #: les dérive de `pred_dur`, la durée prédite par le modèle qui a GÉNÉRÉ l'audio : ils sont
    #: donc exacts par construction, pas estimés après coup. WAMA les jetait faute de les
    #: déclarer nulle part.
    #: MAIS la lib ne les produit que sur la branche anglaise (`pipeline.py` : `if
    #: self.lang_code in 'ab'`) ; la branche non-anglaise yield un `Result` SANS `tokens`.
    supports_timestamps = True
    #: DÉRIVÉE du mapping, jamais figée en dur : les langues sans pipeline propre (de/nl/pl/
    #: tr/ru/cs/ar/ko) sont RABATTUES sur le pipeline 'a' par KOKORO_LANG_MAP — elles passent
    #: donc par la branche anglaise et obtiennent les timestamps elles aussi. Une liste écrite
    #: à la main dirait `['en']` et se tromperait sur 8 langues ; et elle divergerait au premier
    #: changement du mapping. (La QUALITÉ de ces replis est un autre sujet, déjà connu :
    #: la capacité « horodatage » est orthogonale à la justesse de la voix.)
    timestamp_languages = sorted(l for l, c in KOKORO_LANG_MAP.items() if c in ('a', 'b'))

    REQUIRED_PACKAGES = ['kokoro', 'soundfile']

    recommended_vram_gb = 0.4

    def __init__(self):
        super().__init__()
        self._pipelines = {}          # lang_code → KPipeline
        self._lock = threading.Lock()

    @property
    def is_loaded(self) -> bool:
        return bool(self._pipelines)

    def load(self, model: str | None = None) -> bool:
        """Précharge le pipeline FR (langue de référence du poste)."""
        self._get_pipeline('f')
        self.loaded_model = "kokoro"
        self._current_model = CATALOG_KEYS['kokoro']
        return True

    def unload(self) -> None:
        if not self._pipelines:
            return
        logger.info(f"[Kokoro] déchargement de {len(self._pipelines)} pipeline(s)")
        self._pipelines.clear()
        self.loaded_model = None
        self._current_model = None
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:
            pass

    def resident_langs(self) -> list:
        """Codes de langue des pipelines chauds (consommé par /health)."""
        return sorted(self._pipelines.keys())

    def _get_pipeline(self, lang_code: str):
        if lang_code not in self._pipelines:
            with self._lock:
                if lang_code not in self._pipelines:
                    # ── CRITIQUE : cache HF isolé AVANT l'import kokoro/huggingface_hub ──
                    cache_dir = speech_dir('kokoro')
                    os.environ['HF_HUB_CACHE'] = str(cache_dir)
                    os.environ['HUGGINGFACE_HUB_CACHE'] = str(cache_dir)
                    from kokoro import KPipeline
                    self._pipelines[lang_code] = KPipeline(lang_code=lang_code, repo_id=REPO_ID)
        return self._pipelines[lang_code]

    def process(self, text: str = "", language: str = "fr",
                voice_preset: str = "default", **_ignored) -> str:
        lang_code = KOKORO_LANG_MAP.get(language, 'a')
        is_male = voice_preset in ('male_1', 'male_2')
        voice = (KOKORO_VOICE_MAP.get((lang_code, is_male))
                 or KOKORO_VOICE_MAP.get((lang_code, False), 'af_heart'))

        pipeline = self._get_pipeline(lang_code)

        samples = []
        for _, _, audio in pipeline(text, voice=voice, speed=1.0):
            if audio is not None:
                arr = audio.numpy() if hasattr(audio, 'numpy') else np.array(audio)
                samples.append(arr)

        if not samples:
            raise RuntimeError("Kokoro: aucun audio généré")

        return write_wav_int16(np.concatenate(samples).astype(np.float32), 24000)
