"""
Contrat des ALIGNEURS ACOUSTIQUES — l'étage B de l'alignement forcé.

Spécialisation MÉTIER de `wama.common.backends.base.BaseModelBackend`, sœur de
`speech_to_text_base.SpeechToTextBackend` : un aligneur ne TRANSCRIT pas, il reçoit un morceau
d'audio et les mots qu'on sait y être prononcés, et rend l'heure de chacun.

Ce qui vient du COMMUN (ne pas dupliquer) : cycle de vie, dépendances (`REQUIRED_PACKAGES`),
enveloppe load/unload qui déclare la VRAM au gouverneur (`__init_subclass__`), `ENGINE` /
`SUPPORTED_MODELS` pour la résolution depuis le catalogue.
Ce qui est PROPRE au domaine ici : le verbe `align()`, `AlignedWord` et `max_audio_seconds`.

⚠ LA LANGUE N'EST PAS UN ATTRIBUT DE CLASSE. Un aligneur acoustique ne connaît que l'alphabet de
son modèle : c'est le MODÈLE qui porte ses langues, au catalogue (`capabilities['languages']`),
comme tout modèle de WAMA — et c'est là que l'appelant le choisit (`select_model`). Une liste de
langues ici serait une seconde source de vérité.

Qui l'appelle : `word_anchoring.refine_turns`, par fenêtres courtes bornées par des mots déjà
sûrs. L'aligneur ne découpe jamais lui-même : il DÉCLARE sa capacité (`max_audio_seconds`) et
l'orchestration choisit ses fenêtres — même partage des rôles que le découpage des ASR.
"""

from abc import abstractmethod
from dataclasses import dataclass
from typing import List, Optional

from wama.common.backends.base import BaseModelBackend


@dataclass
class AlignedWord:
    """Heure d'un mot, en secondes DEPUIS LE DÉBUT DE LA FENÊTRE reçue."""
    start: float
    end: float
    # Confiance acoustique moyenne du mot (0-1), None si le moteur n'en donne pas.
    score: Optional[float] = None


class ForcedAlignmentBackend(BaseModelBackend):
    """Aligneur acoustique : `align(fenêtre, mots) → heure de chaque mot`.

    Un nouveau moteur = une sous-classe qui déclare `ENGINE`, `SUPPORTED_MODELS`,
    `REQUIRED_PACKAGES`, `max_audio_seconds`, et implémente `load()/unload()/align()`.
    """

    name: str = "base"
    display_name: str = "Base aligner"
    description: str = ""
    description_long: str = ""

    #: Fréquence d'échantillonnage attendue par `align()` (mono, float32).
    sample_rate: int = 16000

    #: Durée MAX (s) d'une fenêtre traitée d'un seul tenant. L'appelant découpe au-delà — entre
    #: deux mots, jamais dans un mot. None = illimité (aucun aligneur réel ne l'est : le coût de
    #: l'attention croît avec le CARRÉ de la durée).
    max_audio_seconds: Optional[float] = None

    @abstractmethod
    def load(self, model_name: str = None) -> bool:
        """Charge le modèle ; False s'il est indisponible."""

    @abstractmethod
    def align(self, waveform, words: List[str]) -> List[Optional[AlignedWord]]:
        """Heure de chaque mot de `words` dans `waveform` (ndarray mono à `sample_rate`).

        Rend une liste de MÊME LONGUEUR que `words` : None pour un mot que le modèle ne sait pas
        épeler (chiffres, ponctuation seule, alphabet étranger) — l'appelant le placera entre ses
        voisins. Lève si la fenêtre est trop courte pour contenir les mots.
        """

    def process(self, **kwargs) -> List[Optional[AlignedWord]]:
        """Point d'entrée métier générique (contrat commun) → délègue à align()."""
        return self.align(**kwargs)

    @abstractmethod
    def unload(self) -> None:
        """Libère le modèle."""
