"""
Contrat de la tâche `end-of-turn` — la personne a-t-elle FINI sa phrase, ou reprend-elle son souffle ?

Spécialisation MÉTIER de `wama.common.backends.base.BaseModelBackend`, sœur de
`language_identification_base.LanguageIdentificationBackend` : un juge de fin de tour ne transcrit
pas, il reçoit la phrase dite jusqu'ici et rend la probabilité que le tour soit fini. Écrit le
2026-11-08 : le service vocal chargeait Smart Turn lui-même (`_turn_session`, un dict de sessions
ONNX par chemin, et l'extracteur à côté), hors du contrat commun — ni l'enveloppe qui déclare un
chargement au gouverneur, ni le déchargement commun ne le voyaient.

Ce qui vient du COMMUN (ne pas dupliquer) : cycle de vie, dépendances, enveloppe load/unload du
gouverneur, `ENGINE` / `SUPPORTED_MODELS` pour la résolution depuis le catalogue. Ce qui est PROPRE
au domaine ici : le verbe `turn_end_probability`. Les SEUILS qui en font un verdict ne sont pas au
contrat : c'est l'écoute qui décide quoi faire d'un avis (`common/tts/end_of_turn.py`).
"""
from abc import abstractmethod

from .base import BaseModelBackend


class EndOfTurnBackend(BaseModelBackend):
    """`turn_end_probability(audio) → float` — un modèle `end-of-turn` du catalogue.

    Un nouveau moteur = une sous-classe qui déclare `ENGINE`, `SUPPORTED_MODELS`,
    `REQUIRED_PACKAGES` et implémente `load()/unload()/turn_end_probability()`. L'état de
    chargement vient d'ici : un backend pose `self._loaded` dans `load()`/`unload()`."""

    #: Fréquence d'échantillonnage attendue par `turn_end_probability()` (mono, float32).
    sample_rate: int = 16000

    def __init__(self):
        self._loaded = False
        self._current_model = None

    @property
    def is_loaded(self) -> bool:
        return self._loaded

    def process(self, **kwargs) -> float:
        """Point d'entrée générique (contrat commun) → délègue à `turn_end_probability()`."""
        return self.turn_end_probability(**kwargs)

    @abstractmethod
    def turn_end_probability(self, audio) -> float:
        """Probabilité ∈ [0, 1] que le tour de parole soit FINI à la fin de `audio` (ndarray mono
        float32 à `sample_rate`, la phrase dite jusqu'ici). Le moteur garde ce que sa recette
        écoute (la FIN de la phrase) : l'appelant envoie tout ce qu'il a."""
