"""Whisper, IDENTIFICATEUR de langue parlée — le contrat `language-identification` sur faster-whisper.

La sonde des langues du transcriber (`common/utils/spoken_language`) écoute Whisper tiny avant un
moteur qui transcrit par passages (Canary, Parakeet, Qwen3-ASR). Jusqu'au 2026-11-06 elle le
chargeait elle-même (`WhisperModel(...)` dans un singleton de module) : hors de la porte de
lancement, de l'enveloppe du gouverneur et du déchargement commun. Ce backend est ce chargement,
au contrat — à côté de `WhisperBackend`, pas dedans : le cache commun garde UNE instance par classe
(`manager.backend_instance`), et un `load('tiny')` de l'instance qui transcrit déchargerait
large-v3.

Sur le PROCESSEUR, délibérément (`device`) : 75 Mo, quelques secondes par sonde, aucun détenteur
de VRAM de plus à arbitrer — d'où `recommended_vram_gb = 0`, que l'enveloppe lit pour ne rien
mesurer (`base._holds_no_local_vram`). Les tailles et leur lecture sans réseau sont celles du moteur
(`whisper_backend.WHISPER_REPOS`, `whisper_model_source`), jamais recopiées.
"""
from __future__ import annotations

import gc
import logging
from typing import Optional, Tuple

from .language_identification_base import LanguageIdentificationBackend
from .whisper_backend import whisper_folder, whisper_model_source

logger = logging.getLogger(__name__)


class WhisperLanguageBackend(LanguageIdentificationBackend):
    """La langue parlée d'une fenêtre d'audio, par la détection de Whisper (30 s au plus)."""

    #: Moteur piloté (contrat commun) — celui de `WhisperBackend` : la librairie faster-whisper.
    ENGINE = 'faster-whisper'
    #: Modèles servis : clé = dernier segment de la clé de catalogue ; `size` = la taille déclarée
    #: du moteur (`WHISPER_REPOS`). ⚠ En LITTÉRAL : l'inventaire lit les clés par AST.
    SUPPORTED_MODELS = {
        'Systran/faster-whisper-tiny': {'size': 'tiny',
                                        'model_key': 'huggingface:Systran/faster-whisper-tiny'},
    }
    name = 'whisper-language'
    display_name = 'Whisper (langue parlée)'
    description = "Langue parlée d'un audio, fenêtre par fenêtre (Whisper tiny, processeur)."

    REQUIRED_PACKAGES = ['faster_whisper']
    PIP_PACKAGES = ['faster-whisper']

    #: Le processeur, déclaré : l'enveloppe du gouverneur ne publie rien pour lui.
    device = 'cpu'
    recommended_vram_gb = 0

    def __init__(self):
        super().__init__()
        self._model = None

    def _size_for(self, model: Optional[str]) -> str:
        """La taille d'un modèle demandé (clé de catalogue ou identifiant), la clé posée sur
        l'instance à défaut — le seul servi si rien ne le dit. Inconnu → `ValueError`."""
        from wama.common.utils.model_keys import backend_model_id
        name = model or self.catalogue_key
        if not name and len(self.SUPPORTED_MODELS) == 1:
            return next(iter(self.SUPPORTED_MODELS.values()))['size']
        spec = self.SUPPORTED_MODELS.get(backend_model_id(name or ''))
        if spec is None:
            raise ValueError(f"WhisperLanguageBackend : modèle non servi « {name} » "
                             f"(servis : {list(self.SUPPORTED_MODELS)})")
        return spec['size']

    def load(self, model: Optional[str] = None) -> bool:
        size = self._size_for(model)
        if self._loaded and self._current_model == size:
            return True
        self.unload()
        # Une taille déclarée absente LÈVE (`whisper_model_source`) : la route l'installe, le moteur
        # ne télécharge pas lui-même — le dire vaut mieux qu'un False muet.
        source, local_only = whisper_model_source(size)
        from faster_whisper import WhisperModel
        self._model = WhisperModel(source, device=self.device, compute_type='int8',
                                   download_root=str(whisper_folder()),
                                   local_files_only=local_only)
        self._loaded, self._current_model = True, size
        logger.info('[WhisperLanguage] %s chargé (processeur)', size)
        return True

    def unload(self) -> None:
        if self._model is not None:
            del self._model
            self._model = None
            gc.collect()
        self._loaded, self._current_model = False, None

    def identify_language(self, audio) -> Tuple[str, float]:
        if not self._loaded:
            raise RuntimeError("WhisperLanguageBackend : modèle non chargé (`load()` d'abord)")
        language, probability, _ = self._model.detect_language(audio=audio)
        return language, float(probability)
