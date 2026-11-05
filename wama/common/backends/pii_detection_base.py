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
import threading
from abc import abstractmethod
from typing import List, Optional

from .base import BaseModelBackend

#: Le service de confidentialité, par sa clé au registre des sources (`external_sources.SOURCES`) :
#: le nom sous lequel il se déclare tenant (`common/privacy/service.py`) et le `SERVED_BY` des
#: détecteurs, qu'il charge pour tous.
PRIVACY_SERVICE = 'privacy_service'


class PIIDetectionBackend(BaseModelBackend):
    """Repère les données personnelles d'un texte — un modèle `pii-detection` du catalogue.

    L'état de chargement vient d'ici, comme pour les autres contrats de tâche : un backend pose
    `self._loaded` dans `load()`/`unload()`."""

    #: étiquette du MODÈLE → type du vocabulaire commun. À déclarer par chaque backend.
    ENTITY_MAP: dict = {}

    #: Les détecteurs se chargent dans le service de confidentialité, pour tous.
    SERVED_BY = PRIVACY_SERVICE

    def __init__(self):
        self._loaded = False
        self._current_model = None
        self._load_lock = threading.Lock()

    @property
    def is_loaded(self) -> bool:
        return self._loaded

    def ensure_loaded(self, model_id: str = None) -> None:
        """Le modèle chargé UNE fois, quels que soient les appels simultanés — ce que
        `detect_entities` appelle avant de travailler. Mesuré le 2026-11-02 au service de
        confidentialité : trois premières requêtes concurrentes chargeaient chaque détecteur trois
        fois sur la carte (`[bardsai PII] chargé` ×3 dans la même milliseconde)."""
        if self._loaded:
            return
        with self._load_lock:
            if not self._loaded:
                self.load(model_id)

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
