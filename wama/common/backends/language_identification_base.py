"""
Contrat de la tâche `language-identification` — quelle langue est PARLÉE dans un audio.

Spécialisation MÉTIER de `wama.common.backends.base.BaseModelBackend`, sœur de
`speech_to_text_base.SpeechToTextBackend` : un identificateur ne transcrit pas, il reçoit une
fenêtre d'audio et rend sa langue. Écrit le 2026-11-06 : la sonde des langues du transcriber
(`common/utils/spoken_language`) chargeait Whisper tiny elle-même, dans son propre singleton, hors
du contrat commun — ni la porte de lancement (`backend_instance_for_key`), ni l'enveloppe qui
déclare un chargement au gouverneur, ni le déchargement commun ne la voyaient.

Ce qui vient du COMMUN (ne pas dupliquer) : cycle de vie, dépendances (`REQUIRED_PACKAGES`,
`PIP_PACKAGES`), enveloppe load/unload du gouverneur, `ENGINE` / `SUPPORTED_MODELS` pour la
résolution depuis le catalogue. Ce qui est PROPRE au domaine ici : le verbe `identify_language`.

⚠ LES LANGUES NE SONT PAS UN ATTRIBUT DE CLASSE : c'est le MODÈLE qui les porte, au catalogue
(`capabilities['languages']`), comme pour l'aligneur (`forced_alignment_base`).
"""
from abc import abstractmethod
from typing import Tuple

from .base import BaseModelBackend


class LanguageIdentificationBackend(BaseModelBackend):
    """`identify_language(audio) → (code ISO 639-1, probabilité)` — un modèle
    `language-identification` du catalogue.

    Un nouveau moteur = une sous-classe qui déclare `ENGINE`, `SUPPORTED_MODELS`,
    `REQUIRED_PACKAGES` et implémente `load()/unload()/identify_language()`. L'état de chargement
    vient d'ici : un backend pose `self._loaded` dans `load()`/`unload()`."""

    #: Fréquence d'échantillonnage attendue par `identify_language()` (mono, float32).
    sample_rate: int = 16000

    def __init__(self):
        self._loaded = False
        self._current_model = None

    @property
    def is_loaded(self) -> bool:
        return self._loaded

    def process(self, **kwargs) -> Tuple[str, float]:
        """Point d'entrée générique (contrat commun) → délègue à `identify_language()`."""
        return self.identify_language(**kwargs)

    @abstractmethod
    def identify_language(self, audio) -> Tuple[str, float]:
        """(code ISO 639-1, probabilité) de la langue la plus probable de `audio` (ndarray mono
        float32 à `sample_rate`). Une seule fenêtre : c'est l'appelant qui choisit lesquelles
        écouter (`spoken_language.probe_languages`)."""
