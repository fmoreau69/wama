"""
Contrat de la tâche `pii-detection` — les DONNÉES PERSONNELLES d'un texte, par passage.

Écrit AVANT les backends (2026-10-28, ROADMAP §16.4bis), comme `score_extraction_base` : c'est le
contrat de tâche (`backend_inventory.TASK_CONTRACTS`) qui dit au rôle `backend` de wama-dev-ai
quelle méthode écrire, et c'est par lui qu'un détecteur entre dans l'union que Presidio orchestre
(`wama/common/privacy/`). Revue d'opus du 2026-10-17 : « recognizer Presidio plutôt que backend »
est un faux choix — le backend charge le modèle (catalogue, gouverneur, `cache_dir`), un fin
adaptateur le branche dans l'analyseur.

Un détecteur rend ses passages dans le VOCABULAIRE COMMUN (`privacy.entities.ENTITY_TYPES`) : il
déclare la correspondance de ses étiquettes (`ENTITY_MAP`) et TAIT celles qu'il ne déclare pas.
Les langues qu'il couvre sont celles de sa ligne de catalogue (`capabilities['languages']`), pas
une liste écrite ici.
"""
from abc import abstractmethod
from typing import List, Optional

from .base import BaseModelBackend


class PIIDetectionBackend(BaseModelBackend):
    """Repère les données personnelles d'un texte — un modèle `pii-detection` du catalogue.

    L'état de chargement vient d'ici, comme pour les autres contrats de tâche : un backend pose
    `self._loaded` dans `load()`/`unload()`."""

    #: étiquette du MODÈLE → type du vocabulaire commun. À déclarer par chaque backend.
    ENTITY_MAP: dict = {}

    def __init__(self):
        self._loaded = False
        self._current_model = None

    @property
    def is_loaded(self) -> bool:
        return self._loaded

    def process(self, **kwargs):
        """Point d'entrée générique (contrat commun) → délègue à `detect_entities()`."""
        return self.detect_entities(**kwargs)

    @abstractmethod
    def detect_entities(
        self,
        model_id: str,
        text: str,
        language: str,
        entities: Optional[List[str]] = None,
        threshold: Optional[float] = None,
    ) -> List[dict]:
        """Les passages personnels de `text`, chacun `{'start', 'end', 'entity', 'score'}`.

        `model_id`  : identifiant du modèle (dernier segment de sa clé de catalogue) ;
        `text`      : le texte entier — les positions rendues sont des index de CARACTÈRES dans
                      ce texte (`text[start:end]` est le passage), jamais dans un découpage interne ;
        `language`  : code ISO 639-1 du texte (`fr`, `en`…) ;
        `entities`  : types du vocabulaire commun à chercher (None = tous ceux que le modèle sait
                      rendre) ;
        `threshold` : score minimal (None = le défaut du modèle).

        `entity` appartient au vocabulaire commun ; `score` est entre 0 et 1 ; un passage vide
        ou hors du texte n'est jamais rendu. Un texte sans donnée personnelle rend `[]`."""
