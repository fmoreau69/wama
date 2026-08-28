"""
Backend Coqui TTS (XTTS v2).

Le backend reste keyé par `COQUI_MODEL_MAPPING` — il ne connaît aucun identifiant
`tts_models/...` en dur — bien que la table n'ait plus qu'une entrée depuis le retrait
des trois moteurs EN-only (R32) : un second modèle Coqui se brancherait sans y toucher.
XTTS v2 exige un audio de référence (clonage).
"""
from __future__ import annotations

import logging
import os
import tempfile

from wama.common.tts.constants import COQUI_MODEL_MAPPING

from .base import CATALOG_KEYS, TTSBackend, _device, project_root, speech_dir

logger = logging.getLogger(__name__)

#: VRAM a-priori par modèle UI (repli si la mesure du contrat est non concluante).
_VRAM_GB = {'coqui-xtts': 2.5}


class CoquiBackend(TTSBackend):
    engine = "coqui"
    description = "Coqui TTS — XTTS v2 (clonage multilingue) et moteurs EN légers."

    supports_cloning = True    # XTTS = clonage par speaker_wav (aligné sur le catalogue)

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
        model = model or 'coqui-xtts'
        if self._tts is not None and self.loaded_model == model:
            return True

        cache_dir = speech_dir('coqui')
        # TTS_HOME AVANT l'import : c'est lui qui fixe où Coqui télécharge/lit ses poids.
        os.environ.setdefault('COQUI_TOS_AGREED', '1')
        os.environ['TTS_HOME'] = str(cache_dir)

        # torchaudio.load → soundfile : torchcodec est cassé sur ce poste et Coqui lit
        # ses références via torchaudio — BRIQUE COMMUNE (partagée avec l'enhancer).
        from wama.common.utils.torchaudio_compat import patch_torchaudio_soundfile
        patch_torchaudio_soundfile()

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

        if (model or self.loaded_model) == "coqui-xtts":
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

