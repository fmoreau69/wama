"""
Backend Coqui TTS (XTTS v2, VITS, Tacotron2, SpeedySpeech).

Un seul backend pour les quatre entrées Coqui de `TTS_MODEL_CHOICES` : même
librairie, même cycle de vie — seul l'identifiant `tts_models/...` change
(`COQUI_MODEL_MAPPING`). XTTS v2 exige un audio de référence (clonage).
"""
from __future__ import annotations

import logging
import os
import tempfile

from wama.common.tts.constants import COQUI_MODEL_MAPPING

from .base import CATALOG_KEYS, TTSBackend, _device, project_root, speech_dir

logger = logging.getLogger(__name__)

#: VRAM a-priori par modèle UI (repli si la mesure du contrat est non concluante).
#: XTTS v2 est le seul moteur Coqui lourd ; les EN-only sont légers.
_VRAM_GB = {'xtts_v2': 2.5, 'vits': 0.5, 'tacotron2': 0.5, 'speedy_speech': 0.5}


class CoquiBackend(TTSBackend):
    engine = "coqui"
    description = "Coqui TTS — XTTS v2 (clonage multilingue) et moteurs EN légers."

    REQUIRED_PACKAGES = ['TTS', 'soundfile']
    # `pip install TTS` est le paquet idiap/coqui-ai-TTS maintenu — nom pip = nom d'import.

    recommended_vram_gb = 2.5

    def __init__(self):
        super().__init__()
        self._tts = None

    @property
    def is_loaded(self) -> bool:
        return self._tts is not None

    def load(self, model: str | None = None) -> bool:
        model = model or 'xtts_v2'
        if self._tts is not None and self.loaded_model == model:
            return True

        cache_dir = speech_dir('coqui')
        # TTS_HOME AVANT l'import : c'est lui qui fixe où Coqui télécharge/lit ses poids.
        os.environ.setdefault('COQUI_TOS_AGREED', '1')
        os.environ['TTS_HOME'] = str(cache_dir)

        self._patch_torchaudio_load()

        from TTS.api import TTS

        full_id = COQUI_MODEL_MAPPING.get(model, model)
        logger.info(f"[Coqui] chargement {full_id} sur {_device()}")
        self._tts = TTS(full_id).to(_device())
        self.loaded_model = model
        self._current_model = CATALOG_KEYS.get(model, model)
        self.recommended_vram_gb = _VRAM_GB.get(model, 2.5)
        return True

    def unload(self) -> None:
        if self._tts is None:
            return
        logger.info(f"[Coqui] déchargement {self.loaded_model}")
        del self._tts
        self._tts = None
        self.loaded_model = None
        self._current_model = None
        self._empty_cuda_cache()

    def process(self, text: str = "", model: str | None = None, language: str = "fr",
                speaker_wav: str | None = None, **_ignored) -> str:
        """Génère un WAV temporaire. XTTS v2 exige `speaker_wav` (résolu par l'appelant)."""
        kwargs = {"text": text}

        tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False,
                                          dir=str(project_root() / "logs"))
        kwargs["file_path"] = tmp.name
        tmp.close()

        if (model or self.loaded_model) == "xtts_v2":
            kwargs["language"] = language
            if speaker_wav and os.path.exists(speaker_wav):
                kwargs["speaker_wav"] = speaker_wav
            else:
                raise ValueError("XTTS v2 requires a speaker_wav reference audio file")

        self._tts.tts_to_file(**kwargs)
        return tmp.name

    # ------------------------------------------------------------------

    @staticmethod
    def _empty_cuda_cache():
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:
            pass

    @staticmethod
    def _patch_torchaudio_load():
        """torchaudio.load → soundfile : torchcodec est cassé sur ce poste (mémoire
        reference_torchcodec_broken) et Coqui lit ses références via torchaudio."""
        try:
            import torch
            import torchaudio
            import soundfile as sf

            def _soundfile_load(uri, frame_offset=0, num_frames=-1, normalize=True,
                                channels_first=True, format=None, buffer_size=4096,
                                backend=None):
                data, sample_rate = sf.read(
                    str(uri), dtype="float32",
                    start=frame_offset,
                    stop=frame_offset + num_frames if num_frames > 0 else None,
                    always_2d=True,
                )
                audio_tensor = torch.from_numpy(data)
                if channels_first:
                    audio_tensor = audio_tensor.t()
                return audio_tensor, sample_rate

            torchaudio.load = _soundfile_load
            logger.info("[Coqui] torchaudio.load patché → backend soundfile")
        except Exception as e:
            logger.warning(f"[Coqui] patch torchaudio impossible : {e}")
