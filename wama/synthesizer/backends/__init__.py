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
from .kokoro_onnx_backend import KokoroOnnxBackend

#: Moteur → classe de backend (vocabulaire `SYNTHESIZER_MODELS[*]['engine']`).
ENGINE_BACKENDS = {
    'coqui': CoquiBackend,
    'bark': BarkBackend,
    'higgs': HiggsAudioBackend,
    'kokoro': KokoroBackend,
    'kokoro-onnx': KokoroOnnxBackend,
}


#: Moteur d'un nom de modèle UI quand il diffère du nom de moteur (table d'EXCEPTIONS).
_MODELE_VERS_MOTEUR = {'higgs-audio': 'higgs'}


def engine_for_model(model_name: str) -> str:
    """Nom de moteur pour un modèle UI.

    ⚠ Le repli historique était `return 'coqui'` pour TOUT nom inconnu — donc un nom mal
    orthographié, hérité, ou d'un moteur pas encore enregistré faisait **charger XTTS v2
    (plusieurs Go, des dizaines de secondes) EN SILENCE**, à la place du moteur demandé.
    C'est un candidat sérieux au « XTTS qui prend la relève » observé sans explication
    (Fabien, 2026-08-31) : rien dans les journaux ne distingue ce cas d'un choix délibéré.
    Un routage qui se trompe doit le DIRE — on lève, l'appelant a déjà son repli.
    """
    if model_name in COQUI_MODEL_MAPPING:
        return 'coqui'
    if model_name in _MODELE_VERS_MOTEUR:
        return _MODELE_VERS_MOTEUR[model_name]
    if model_name in ENGINE_BACKENDS:
        return model_name          # le nom de modèle EST le nom de moteur (bark, kokoro…)
    raise ValueError(
        f"Moteur TTS inconnu pour le modèle {model_name!r} — moteurs enregistrés : "
        f"{sorted(ENGINE_BACKENDS)} ; modèles Coqui : {sorted(COQUI_MODEL_MAPPING)}")


__all__ = [
    'BarkBackend', 'CoquiBackend', 'HiggsAudioBackend', 'KokoroBackend',
    'KokoroOnnxBackend', 'TTSBackend', 'ENGINE_BACKENDS', 'CATALOG_KEYS',
    'engine_for_model',
]
