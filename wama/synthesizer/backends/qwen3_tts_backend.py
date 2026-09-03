"""
Backend Qwen3-TTS (12Hz, 1.7B CustomVoice) — moteur `qwen3-tts`, servi par le runtime
LOCAL officiel `qwen-tts` (github.com/QwenLM/Qwen3-TTS ; ce n'est PAS le SDK cloud
DashScope — vérifié sur le dépôt avant d'écrire).

B2 (série « backends des modèles installés sans backend », 2026-09-03) — 3ᵉ adaptateur du
motif « backend DÉCLARÉ » : chemin des poids depuis le CATALOGUE, repli Django-free.

⚠ RUNTIME NON INSTALLÉ, et c'est VOULU : `qwen-tts==0.1.1` épingle `transformers==4.57.3`
(le venv est en 4.57.6 — micro-rétrogradation) et monte `nvidia-nccl-cu12` — toucher au
venv PARTAGÉ passe par la validation humaine (`ensure_backend_deps`, contrat de
`pip_install_packages`). D'ici là, l'inventaire du grisage n'annonce que les moteurs
EXÉCUTABLES (`missing_packages()`) : Qwen3-TTS reste GRISÉ avec sa raison, et
l'installation du runtime le dé-grisera TOUTE SEULE — c'est le système du 02/09.

L'architecture (`Qwen3TTSForConditionalGeneration`) est absente de notre transformers et
le snapshot n'embarque aucun remote code : le paquet officiel est la SEULE voie locale.
"""
from __future__ import annotations

import logging
from pathlib import Path

import numpy as np

from .base import TTSBackend, ai_models_dir, write_wav_int16

logger = logging.getLogger(__name__)

#: Identité du modèle au catalogue (clé du balayage générique des snapshots HF).
CATALOG_KEY = 'huggingface:Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice'
FAMILY_DIR = 'Qwen3-TTS-12Hz-1.7B-CustomVoice'
SNAPSHOT_DIRNAME = 'models--Qwen--Qwen3-TTS-12Hz-1.7B-CustomVoice'

#: Codes langue WAMA → noms de langue du runtime (generate_custom_voice(language=…)) ;
#: absent → 'Auto' (le modèle s'adapte au texte).
QWEN_LANG = {
    'fr': 'French', 'en': 'English', 'de': 'German', 'es': 'Spanish', 'it': 'Italian',
    'pt': 'Portuguese', 'ja': 'Japanese', 'ko': 'Korean', 'zh-cn': 'Chinese', 'ru': 'Russian',
}

#: Presets WAMA → locuteurs nommés du checkpoint CustomVoice (liste du dépôt).
QWEN_SPEAKERS = {
    'default': 'Serena', 'female_1': 'Vivian', 'female_2': 'Serena',
    'male_1': 'Ryan', 'male_2': 'Eric',
}


def _declared_path() -> Path | None:
    """Chemin du dépôt DÉCLARÉ au catalogue — repli disque conventionnel (Django-free)."""
    try:
        from wama.model_manager.models import AIModel
        row = AIModel.objects.filter(model_key=CATALOG_KEY).first()
        chemin = (row.extra_info or {}).get('path') if row else ''
        if chemin and Path(chemin).is_dir():
            return Path(chemin)
    except Exception:
        pass
    repli = ai_models_dir() / 'models' / 'speech' / FAMILY_DIR / SNAPSHOT_DIRNAME
    return repli if repli.is_dir() else None


def _snapshot_dir() -> Path | None:
    depot = _declared_path()
    if depot is None:
        return None
    racine = depot / 'snapshots'
    if not racine.is_dir():
        return None
    revs = sorted((d for d in racine.iterdir() if d.is_dir()),
                  key=lambda d: d.stat().st_mtime)
    return revs[-1] if revs else None


class Qwen3TTSBackend(TTSBackend):
    engine = "qwen3-tts"
    description = ("Qwen3-TTS 12Hz 1.7B CustomVoice — 9 locuteurs nommés, 10 langues dont "
                   "le français, runtime local officiel qwen-tts.")

    supports_cloning = False        # checkpoint CustomVoice = locuteurs NOMMÉS (pas de réf audio)
    keep_resident = False
    supports_timestamps = False

    #: Nom d'IMPORT ≠ nom pip ; PIN EXACT — forme exigée par `pip_install_packages`
    #: (l'installation reste un geste humain : ensure_backend_deps sur GO).
    REQUIRED_PACKAGES = ['qwen_tts']
    PIP_PACKAGES = ['qwen-tts==0.1.1']

    recommended_vram_gb = 4.2       # ~poids bf16 du 1.7B + codec (à REMESURER au 1er run)

    def __init__(self):
        super().__init__()
        self._model = None

    @property
    def is_loaded(self) -> bool:
        return self._model is not None

    def load(self, model: str | None = None) -> bool:
        if self._model is not None:
            return True
        snapshot = _snapshot_dir()
        if snapshot is None:
            raise RuntimeError(
                f"Qwen3-TTS : snapshot absent ({FAMILY_DIR}) — installer "
                f"{CATALOG_KEY.split(':', 1)[1]} d'abord (prospection → installer).")
        import torch
        from qwen_tts import Qwen3TTSModel
        device = 'cuda:0' if torch.cuda.is_available() else 'cpu'
        dtype = torch.bfloat16 if torch.cuda.is_available() else torch.float32
        # Chemin LOCAL (aucun téléchargement). Pas d'attn_implementation : flash-attn
        # n'est pas dans le venv — l'attention par défaut (sdpa) suffit, on ne promet
        # pas une dépendance absente.
        self._model = Qwen3TTSModel.from_pretrained(
            str(snapshot), device_map=device, dtype=dtype)
        self.loaded_model = "qwen3-tts"
        self._current_model = CATALOG_KEY.split(':', 1)[1]
        logger.info("[Qwen3-TTS] chargé depuis %s (%s, %s)", snapshot.name, device, dtype)
        return True

    def unload(self) -> None:
        if self._model is None:
            return
        self._model = None
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
        if self._model is None:
            self.load()
        wavs, sr = self._model.generate_custom_voice(
            text=text,
            language=QWEN_LANG.get(language, 'Auto'),
            speaker=QWEN_SPEAKERS.get(voice_preset, QWEN_SPEAKERS['default']),
        )
        if wavs is None or not len(wavs):
            raise RuntimeError("Qwen3-TTS : aucun audio généré")
        return write_wav_int16(np.asarray(wavs[0], dtype=np.float32), int(sr))
