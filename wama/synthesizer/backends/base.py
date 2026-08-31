"""
Backends TTS du synthesizer — contrat commun (`BaseModelBackend`), Django-FREE.

Django-free est une CONTRAINTE, pas un style : ces classes sont chargées par le
service TTS (`tts_service.py`, uvicorn:8001), un process qui n'initialise pas
Django. Ne rien importer ici qui tire `django.conf.settings` au niveau module —
les chemins passent par `speech_dir()` (repli repo-relatif identique aux
constantes historiques du service).

Le MÉCANISME (charger / générer / décharger, comptabilité VRAM au gouverneur via
les enveloppes du contrat) vit ici ; la POLITIQUE (quel moteur est résident, la
résolution des presets de voix vers un fichier de référence, la file HTTP) reste
dans `tts_service.py` — même partage que l'anonymizer (brique = mécanisme,
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
    #: DÉCLARÉ ici depuis le 2026-08-31 : la politique vivait dans `tts_service.py`
    #: sous la forme d'un `if _current_engine == "kokoro"` — un littéral que le moteur
    #: concerné ne pouvait ni déclarer ni hériter. Conséquence mesurée : `kokoro-onnx`,
    #: qui sert exactement le même rôle temps réel, aurait été déchargé à chaque
    #: bascule. Même geste que `composition` : *la politique se déclare, le service
    #: l'exécute*. `unload()` décharge toujours RÉELLEMENT — c'est le service qui
    #: choisit de ne pas l'appeler.
    keep_resident: bool = False

    def __init__(self):
        self._current_model: Optional[str] = None   # suffixe CATALOGUE (clé gouverneur)
        self.loaded_model: Optional[str] = None     # nom UI ('coqui-xtts'…) — /health

    def synthesize(self, **kwargs) -> str:
        """Alias métier : rend le CHEMIN d'un WAV temporaire généré."""
        return self.process(**kwargs)
