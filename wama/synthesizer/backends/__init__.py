"""
Registre des backends TTS du synthesizer (contrat commun `BaseModelBackend`).

Consommé par `tts_service.py` (le process qui charge réellement) et par les
outils transverses (model_installer, tests nocturnes) via `is_available()` /
`missing_packages()` — SANS charger de modèle.
"""
from __future__ import annotations

from wama.common.tts.constants import COQUI_MODEL_MAPPING

from .bark_backend import BarkBackend
from .base import CATALOG_KEYS, TTSBackend
from .coqui_backend import CoquiBackend
from .higgs_backend import HiggsAudioBackend
from .kokoro_backend import KokoroBackend

#: Moteur → classe de backend (vocabulaire `SYNTHESIZER_MODELS[*]['engine']`).
ENGINE_BACKENDS = {
    'coqui': CoquiBackend,
    'bark': BarkBackend,
    'higgs': HiggsAudioBackend,
    'kokoro': KokoroBackend,
}


def engine_for_model(model_name: str) -> str:
    """Nom de moteur pour un modèle UI — repli historique : tenté comme modèle Coqui."""
    if model_name in COQUI_MODEL_MAPPING:
        return 'coqui'
    if model_name in ('bark', 'higgs_audio', 'kokoro'):
        return {'bark': 'bark', 'higgs_audio': 'higgs', 'kokoro': 'kokoro'}[model_name]
    return 'coqui'


__all__ = [
    'BarkBackend', 'CoquiBackend', 'HiggsAudioBackend', 'KokoroBackend',
    'TTSBackend', 'ENGINE_BACKENDS', 'CATALOG_KEYS', 'engine_for_model',
]
