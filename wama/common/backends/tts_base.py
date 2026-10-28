"""
Backends TTS du synthesizer — contrat commun (`BaseModelBackend`), Django-FREE.

Django-free est une CONTRAINTE, pas un style : ces classes sont chargées par le
service TTS (`common/tts/service.py`, uvicorn:8001), un process qui n'initialise pas
Django. Ne rien importer ici qui tire `django.conf.settings` au niveau module —
les chemins passent par `speech_dir()` (repli repo-relatif identique aux
constantes historiques du service).

Le MÉCANISME (charger / générer / décharger, comptabilité VRAM au gouverneur via
les enveloppes du contrat) vit ici ; la POLITIQUE (quel moteur est résident, la
résolution des presets de voix vers un fichier de référence, la file HTTP) reste
dans `common/tts/service.py` — même partage que l'anonymizer (brique = mécanisme,
app = politique).

⚠ Deux préparations PROCESS restent dans le service, PAS ici : le patch
`torch.load(weights_only=False)` (PyTorch 2.6+, requis par Bark ET les
checkpoints picklés Coqui) et `configure_cuda_process()`. Un backend importé
dans un autre process (tests nocturnes : `is_available()`) n'en a pas besoin
tant qu'il ne charge pas.
"""
from __future__ import annotations

import logging
import tempfile
from pathlib import Path
from typing import Optional

import numpy as np

from wama.common.backends.base import BaseModelBackend

logger = logging.getLogger(__name__)


def project_root() -> Path:
    """Racine du dépôt (…/web-app-for-media-automation)."""
    return Path(__file__).resolve().parents[3]


def ai_models_dir() -> Path:
    """`AI-models/` — via Django si configuré, sinon repli repo-relatif (service TTS)."""
    try:
        from django.conf import settings
        return Path(settings.AI_MODELS_DIR)
    except Exception:
        return project_root() / "AI-models"


def speech_dir(engine: str) -> Path:
    """Dossier de poids d'un moteur speech (créé si absent)."""
    d = ai_models_dir() / "models" / "speech" / engine
    d.mkdir(parents=True, exist_ok=True)
    return d


#: Suffixe de `AIModel.model_key` (catalogue) par nom de modèle UI. Table devenue IDENTITÉ
#: le 18/08 : l'app est ALIGNÉE sur les clés canoniques du catalogue (route SPEC §356 —
#: xtts_v2→coqui-xtts, higgs_audio→higgs-audio, speedy_speech→speedy-speech ; lignes
#: VoiceSynthesis migrées). Conservée comme point d'accroche (consommateurs existants +
#: un futur id divergent se déclarerait ICI, nulle part ailleurs).
CATALOG_KEYS = {
    'coqui-xtts': 'coqui-xtts',
    'bark': 'bark',
    'higgs-audio': 'higgs-audio',
    'kokoro': 'kokoro',
}


def _device() -> str:
    import torch
    return "cuda" if torch.cuda.is_available() else "cpu"


def write_wav_int16(audio: np.ndarray, sample_rate: int, normalize: bool = True) -> str:
    """Écrit un float32 mono en WAV int16 temporaire (logs/) et rend son chemin.

    La normalisation crête est le comportement historique des trois moteurs qui
    produisent du float (Bark sature au-delà de ±1.0 sans elle).
    """
    audio = np.asarray(audio, dtype=np.float32)
    if normalize:
        peak = np.abs(audio).max()
        if peak > 1e-6:
            audio = audio / peak
    audio_int16 = (audio * 32767).clip(-32768, 32767).astype(np.int16)

    from scipy.io.wavfile import write as write_wav
    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False,
                                      dir=str(project_root() / "logs"))
    tmp.close()
    write_wav(tmp.name, sample_rate, audio_int16)
    return tmp.name


#: Plafond d'une PAUSE demandée (s) — une valeur aberrante postée ne fige pas la voix.
MAX_PAUSE_S = 2.0


def bounded_pause(value) -> float:
    """Une pause demandée, en secondes, ramenée dans [0, MAX_PAUSE_S] (illisible = 0)."""
    try:
        return min(MAX_PAUSE_S, max(0.0, float(value or 0)))
    except (TypeError, ValueError):
        return 0.0


class TTSBackend(BaseModelBackend):
    """Classe intermédiaire des moteurs TTS (le verbe métier est `synthesize`).

    Contrat d'appel UNIFORME : `process(**kwargs)` reçoit toujours le même jeu de
    clés (text, language, voice_preset, speaker_wav, multi_speaker,
    scene_description, options, model) — chaque moteur consomme ce qui le
    concerne et ignore le reste. C'est ce qui permet au service de ne pas porter
    un if/elif de signatures par moteur.
    """

    #: Nom de moteur ('coqui', 'bark', 'higgs', 'kokoro') — vocabulaire de
    #: `SYNTHESIZER_MODELS[*]['engine']` et de `_switch_model` historique.
    engine: str = ""

    #: Le moteur sert le TEMPS RÉEL (vocalisation assistant, preview) → le service TTS
    #: le garde chaud : il n'est jamais déchargé à une bascule de moteur, et un
    #: `TTS_PRELOAD` qui le nomme le charge SANS en faire le « moteur courant ».
    #: DÉCLARÉ ici depuis le 2026-08-31 : la politique vivait dans `common/tts/service.py`
    #: sous la forme d'un `if _current_engine == "kokoro"` — un littéral que le moteur
    #: concerné ne pouvait ni déclarer ni hériter. Conséquence mesurée : `kokoro-onnx`,
    #: qui sert exactement le même rôle temps réel, aurait été déchargé à chaque
    #: bascule. Même geste que `composition` : *la politique se déclare, le service
    #: l'exécute*. `unload()` décharge toujours RÉELLEMENT — c'est le service qui
    #: choisit de ne pas l'appeler.
    keep_resident: bool = False

    def takes_lexicon_phonemes(self, language: str) -> bool:
        """Le moteur reçoit-il des PHONÈMES pour `language` ? Alors il dit le lexique de
        prononciation lui-même (`tts_text.phonemes_with_lexicon`, Kokoro) ; sinon le contrat
        remplace, avant lui, chaque terme qui a une orthographe à dire (`synthesize`)."""
        return False

    def __init__(self):
        self._current_model: Optional[str] = None   # suffixe CATALOGUE (clé gouverneur)
        self.loaded_model: Optional[str] = None     # nom UI ('coqui-xtts'…) — /health

    def synthesize(self, **kwargs) -> str:
        """Le verbe métier — rend le CHEMIN d'un WAV temporaire généré, avec les PAUSES demandées.

        `options` (contrat uniforme) peut porter `sentence_pause` / `clause_pause`, en secondes
        (2026-10-18 : réglages de l'assistant et du synthesizer). Un moteur ne sait pas, seul,
        allonger une pause À L'INTÉRIEUR d'un texte qu'il dit d'un trait — mesuré sur kokoro-onnx,
        dont le modèle ne rend pas ses durées (`has_timings` faux : 3,58 s de son quelles que soient
        les pauses passées). Le texte est donc découpé là où il respire
        (`tts_text.pause_segments`), chaque segment dit par le moteur, et le silence posé entre
        eux — ICI, pour tous les moteurs ; la boucle vivait dans le seul `kokoro_onnx_backend`.
        Sans pause demandée, un seul appel : le rendu d'avant.

        ⚠ Le mode MULTI-VOIX (Higgs) n'est pas découpé : ses balises de locuteur (`[S1]`)
        valent pour la suite du texte, un segment les perdrait. La description de scène ouvre le
        dialogue : premier segment seulement (la règle de `speech_render`).

        Le LEXIQUE de prononciation (2026-10-27) se dit ICI aussi, pour tous les moteurs : le
        fichier système et les lignes que le serveur web a jointes (`options['lexicon']`). Un
        moteur qui reçoit des phonèmes le dit lui-même (`takes_lexicon_phonemes`) ; pour les
        autres, chaque terme qui a une orthographe à dire est remplacé avant eux."""
        from wama.common.utils.audio_decode import decode_audio
        from wama.common.utils.tts_text import pause_segments, respell_with_lexicon
        options = kwargs.get('options') or {}
        language = kwargs.get('language') or ''
        if not self.takes_lexicon_phonemes(language):
            kwargs = {**kwargs, 'text': respell_with_lexicon(kwargs.get('text') or '', language,
                                                             options.get('lexicon'))}
        segments = [] if kwargs.get('multi_speaker') else pause_segments(
            kwargs.get('text') or '', bounded_pause(options.get('sentence_pause')),
            bounded_pause(options.get('clause_pause')))
        if len(segments) <= 1:
            return self.process(**kwargs)
        import os
        parts, rate = [], None
        for segment, pause in segments:
            if not any(c.isalnum() for c in segment):
                # Rien à DIRE (« … » seul entre deux phrases) : son silence, pas d'appel — un
                # moteur sans phonème lèverait « aucun audio » pour tout le texte.
                if parts and pause:
                    parts.append(np.zeros((int(pause * rate),) + parts[0].shape[1:],
                                          dtype=np.float32))
                continue
            path = self.process(**{**kwargs, 'text': segment,
                                   'scene_description': '' if parts
                                   else kwargs.get('scene_description', '')})
            try:
                # Le décodeur COMMUN (branche soundfile : fréquence native, float32, mono).
                audio, segment_rate = decode_audio(path, mono=True)
            finally:
                os.remove(path)
            if rate is not None and segment_rate != rate:
                raise RuntimeError(f"{self.engine} : fréquence d'échantillonnage variable entre "
                                   f"segments ({rate} puis {segment_rate} Hz)")
            rate = segment_rate
            parts.append(audio)
            if pause:
                parts.append(np.zeros((int(pause * rate),) + audio.shape[1:], dtype=np.float32))
        if not parts:
            return self.process(**kwargs)      # rien de dicible : le moteur en décide, comme avant
        # Chaque segment est déjà au niveau du moteur : l'assemblage ne renormalise pas.
        return write_wav_int16(np.concatenate(parts), rate, normalize=False)
