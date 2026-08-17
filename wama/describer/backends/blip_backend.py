"""
Backend BLIP du describer — contrat commun (`BaseModelBackend`).

REMPLACE (2026-08-17) le pattern « modèle en variables de MODULE + unloader explicite »
(`image_describer._blip_model/_blip_processor` + `apps.py::_unload_blip`) : le contrat
enveloppe load/unload/process → comptabilité VRAM au gouverneur (ligne mesurée par
modèle), unloader AUTOMATIQUE à la première résidence, `mark_used` à chaque légende,
et dépendances DÉCLARATIVES (`REQUIRED_PACKAGES` — consommées par le model_installer
et les tests nocturnes via `is_available()`).

BLIP est le REPLI local de la cascade vision (Ollama d'abord — HTTP, hors contrat).
"""
from __future__ import annotations

import logging

from wama.common.backends.base import BaseModelBackend

logger = logging.getLogger(__name__)


class BlipBackend(BaseModelBackend):
    REQUIRED_PACKAGES = ['transformers', 'torch', 'PIL']
    PIP_PACKAGES = ['transformers', 'torch', 'pillow']   # import `PIL` ↔ pip `pillow`
    recommended_vram_gb = 1.8
    description = "BLIP — légende d'image locale (repli quand Ollama vision est indisponible)."

    _singleton = None

    @classmethod
    def get(cls) -> "BlipBackend":
        """Instance partagée du process (même sémantique que l'ancien cache de module)."""
        if cls._singleton is None:
            cls._singleton = cls()
        return cls._singleton

    def __init__(self):
        self._processor = None
        self._model = None
        self._current_model = None   # suffixe catalogue (clé d'owner gouverneur)

    @property
    def is_loaded(self) -> bool:
        return self._model is not None

    def load(self, model: str | None = None) -> bool:
        if self.is_loaded:
            return True
        import os
        import torch
        from wama.model_manager.services.memory_manager import MemoryManager, MemoryStrategy
        from wama.describer.utils.model_config import get_model_info

        model_info = get_model_info('blip')
        model_name = model_info['model_id']
        cache_dir = str(model_info['local_dir'])

        # ── CRITIQUE : cache HF isolé AVANT l'import transformers (règle CLAUDE.md) ──
        os.environ['HF_HUB_CACHE'] = cache_dir
        os.environ['HUGGINGFACE_HUB_CACHE'] = cache_dir

        from transformers import BlipForConditionalGeneration, BlipProcessor

        # Stratégie VRAM via MemoryManager (~1,8 Go pour BLIP)
        strategy = MemoryManager.get_memory_strategy(self.recommended_vram_gb)
        device = "cpu" if strategy == MemoryStrategy.CPU_ONLY else (
            "cuda" if torch.cuda.is_available() else "cpu"
        )
        logger.info(f"[BLIP] chargement {model_name} — strategy: {strategy.value}, device: {device}")

        self._processor = BlipProcessor.from_pretrained(model_name, cache_dir=cache_dir, use_fast=True)
        self._model = BlipForConditionalGeneration.from_pretrained(
            model_name, cache_dir=cache_dir).to(device)
        self._current_model = 'blip'
        logger.info(f"[BLIP] chargé sur {device.upper()}")
        return True

    def unload(self) -> None:
        if self._model is None and self._processor is None:
            return
        self._processor = None
        self._model = None
        self._current_model = None
        import gc
        gc.collect()
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:
            pass
        logger.info("[BLIP] déchargé")

    def process(self, image=None, prefix: str | None = None, max_new_tokens: int = 100,
                num_beams: int = 5, repetition_penalty: float | None = None, **_ignored) -> str:
        """Légende UNE image PIL. `prefix` = amorce de conditionnement optionnelle
        (« a photograph of »…) — la POLITIQUE de style reste chez l'appelant."""
        self.load()
        device = str(next(self._model.parameters()).device)
        inputs = (self._processor(image, prefix, return_tensors="pt") if prefix
                  else self._processor(image, return_tensors="pt")).to(device)
        kwargs = {'max_new_tokens': max_new_tokens, 'num_beams': num_beams}
        if repetition_penalty:
            kwargs['repetition_penalty'] = repetition_penalty
        out = self._model.generate(**inputs, **kwargs)
        return self._processor.decode(out[0], skip_special_tokens=True)
