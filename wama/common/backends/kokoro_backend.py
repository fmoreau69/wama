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
from pathlib import Path
import threading

import numpy as np

from wama.common.tts.constants import KOKORO_LANG_MAP

from .tts_base import CATALOG_KEYS, TTSBackend, speech_dir, write_wav_int16

logger = logging.getLogger(__name__)

REPO_ID = 'hexgrad/Kokoro-82M'


#: Les codes de pipeline que KPipeline ne phonémise PAS par espeak (anglais, japonais, chinois) :
#: misaki y a son propre G2P, sans lexique à recevoir.
NOT_ESPEAK_CODES = 'abjz'


class LexiconG2P:
    """Le phonémiseur espeak d'un `KPipeline` (misaki `EspeakG2P`), le lexique de prononciation
    en plus (`tts_text.phonemes_with_lexicon`, 2026-10-27). La syntaxe `[mot](/phonèmes/)` de
    misaki n'existe que sur sa branche anglaise : hors d'elle, rien ne reçoit un lexique. Une
    entrée prend la notation de misaki (sa table `e2m` : `d^ʒ` → `ʤ`), comme ce qu'espeak rend.

    Les lignes d'un compte (`extra`) changent à chaque demande alors que le pipeline est partagé :
    elles sont posées pour le FIL qui synthétise (`use`), que KPipeline rappelle dans ce même fil."""

    def __init__(self, g2p, language: str):
        self.g2p = g2p
        self.language = language
        self._call = threading.local()

    def use(self, extra):
        self._call.extra = extra

    def _finish(self, entry: str) -> str:
        for old, new in getattr(self.g2p, 'e2m', ()):
            entry = entry.replace(old, new)
        return entry.replace('^', '')

    def __call__(self, text):
        from wama.common.utils.tts_text import phonemes_with_lexicon
        return phonemes_with_lexicon(text, self.language, lambda part: self.g2p(part)[0],
                                     finish=self._finish,
                                     extra=getattr(self._call, 'extra', None)), None


def say_lexicon_through(pipeline, lang_code: str, language: str, text: str, extra=None) -> str:
    """Le texte que `pipeline` doit recevoir pour dire le lexique (fichier + `extra`) : par
    espeak, le pipeline le dira lui-même dans ce fil, le texte est rendu tel quel ; sur la branche
    anglaise, japonaise ou chinoise de misaki, le texte où chaque terme qui a une orthographe à dire
    est remplacé. Le moteur l'appelle pour poser le lexique (le contrat a déjà remplacé
    l'orthographe, il en ignore le texte) ; le repli en processus de la voix de l'assistant, qui
    ne passe pas par le contrat, prend aussi le texte."""
    if lang_code in NOT_ESPEAK_CODES:
        from wama.common.utils.tts_text import respell_with_lexicon
        return respell_with_lexicon(text, language, extra)
    if not isinstance(pipeline.g2p, LexiconG2P):
        pipeline.g2p = LexiconG2P(pipeline.g2p, language)
    pipeline.g2p.use(extra)
    return text


class KokoroBackend(TTSBackend):
    #: Moteur piloté (contrat commun) — voir BaseModelBackend.ENGINE.
    ENGINE = 'kokoro'
    engine = "kokoro"
    description = "Kokoro 82M — TTS léger FR/EN/ES/IT/PT/JA/ZH, temps réel."

    supports_cloning = False   # voix FIXES par langue (aligné sur le catalogue)
    #: Il ne tire pas : la voix d'un texte est toujours la même (2026-10-21).
    default_temperature = None
    reproducible = True
    #: Rien à tirer, donc ni graine ni top_p (2026-10-22).
    reads_seed = False
    default_top_p = None
    #: Sert le temps réel (vocalisation assistant) → gardé chaud par le service TTS.
    #: C'était la règle `if _current_engine == "kokoro"` de `tts_service`, DÉCLARÉE
    #: depuis le 2026-08-31 (cf. `TTSBackend.keep_resident`) : comportement inchangé.
    keep_resident = True
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
    #: Ces mêmes 8 langues, vues sous l'autre angle : Kokoro les PRONONCE (par le pipeline
    #: anglais) sans les PARLER. Elles restent hors de `languages` au catalogue — le moteur ne
    #: les gère pas — mais l'UI a besoin de les distinguer d'un refus sec, sinon elle annonce
    #: « impossible » pour un cas qui rend du son. Dérivée du mapping comme sa jumelle
    #: ci-dessus : `'en'` retiré, c'est la langue du pipeline, pas un repli.
    fallback_languages = sorted(l for l, c in KOKORO_LANG_MAP.items()
                                if c in ('a', 'b') and l != 'en')

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
                    # 3ᵉ VOIE (ROADMAP §5b) : kokoro n'accepte pas de `cache_dir=`, mais
                    # `KModel` accepte des CHEMINS (`config=`, `model=`) — vérifié dans sa
                    # source : il ne télécharge que `if not config` / `if not model`. On range
                    # donc les poids nous-mêmes dans `speech/kokoro` et on les lui donne,
                    # SANS toucher l'environnement (l'ancienne mutation emportait avec elle
                    # les sous-dépendances de tout ce qui se chargeait ensuite).
                    from kokoro import KModel, KPipeline
                    from wama.common.utils.hf_weights import poids_locaux
                    racine = poids_locaux(REPO_ID, speech_dir('kokoro'))
                    modele = KModel(
                        repo_id=REPO_ID,
                        config=str(Path(racine) / 'config.json'),
                        model=str(Path(racine) / KModel.MODEL_NAMES[REPO_ID]),
                    )
                    self._pipelines[lang_code] = KPipeline(
                        lang_code=lang_code, repo_id=REPO_ID, model=modele)
        return self._pipelines[lang_code]

    def takes_lexicon_phonemes(self, language: str) -> bool:
        """Par espeak seulement : sur la branche anglaise de misaki, l'orthographe du lexique est
        dite par le contrat, comme pour un moteur qui lit du texte."""
        from wama.common.tts.voices import code_langue
        return code_langue(language) not in NOT_ESPEAK_CODES

    def process(self, text: str = "", language: str = "fr",
                voice_preset: str = "default", options: dict | None = None, **_ignored) -> str:
        # Résolution langue→voix : brique COMMUNE (le même calcul vivait ici et, en miroir,
        # dans la vue TTS de l'assistant). `voice_preset` reste du vocabulaire synthesizer.
        from wama.common.tts.voices import code_langue, voix_pour
        lang_code = code_langue(language)
        is_male = voice_preset in ('male_1', 'male_2')
        voice = voix_pour(language, is_male)

        pipeline = self._get_pipeline(lang_code)
        # Hors anglais, japonais et chinois, KPipeline phonémise par espeak (misaki `EspeakG2P`) :
        # le lexique de prononciation s'y glisse, comme chez le jumeau ONNX (2026-10-27).
        # (Sur la branche anglaise, le contrat a déjà dit l'orthographe : `takes_lexicon_phonemes`.)
        say_lexicon_through(pipeline, lang_code, language, text, (options or {}).get('lexicon'))

        samples = []
        for _, _, audio in pipeline(text, voice=voice, speed=1.0):
            if audio is not None:
                arr = audio.numpy() if hasattr(audio, 'numpy') else np.array(audio)
                samples.append(arr)

        if not samples:
            raise RuntimeError("Kokoro: aucun audio généré")

        return write_wav_int16(np.concatenate(samples).astype(np.float32), 24000)
