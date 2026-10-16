"""
Contrat de la tâche `audio-to-midi` — un audio → un MIDI à une piste PAR INSTRUMENT.

Écrit le 2026-10-16, avant son premier backend (MuScriptor), pour la même raison que
`score_extraction_base` : c'est le contrat de tâche (`backend_inventory.TASK_CONTRACTS`) qui dit au
rôle `backend` de wama-dev-ai quelle méthode écrire.

Distinct d'`audio-to-score` (`ScoreExtractionBackend`) : celui-ci rend la grille mélodie + accords
qu'un COVER suit ; celui-là rend toutes les parties entendues — la « Partition complète » du
composer, montrée et lue sur la page d'édition, jamais donnée au rendu. Nommé `extract_midi`, pas
« transcribe » (ce verbe est celui du transcriber, décision de Fabien du 2026-10-03).

La mise en NOTATION (MIDI → ABC lisible) n'est pas du ressort du moteur : c'est la brique commune
`common/utils/midi_score.py`, la même pour tout moteur de cette tâche.
"""
from abc import abstractmethod
from typing import Callable, Optional

from .base import BaseModelBackend


class MidiExtractionBackend(BaseModelBackend):
    """Extrait le MIDI multi-instrument d'un audio — un modèle `audio-to-midi` du catalogue.

    L'état de chargement vient d'ici, comme pour les autres contrats : un backend pose
    `self._loaded` dans `load()`/`unload()` et n'a rien d'autre à écrire."""

    def __init__(self):
        self._loaded = False
        self._current_model = None

    @property
    def is_loaded(self) -> bool:
        return self._loaded

    def process(self, **kwargs):
        """Point d'entrée générique (contrat commun) → délègue à `extract_midi()`."""
        return self.extract_midi(**kwargs)

    @abstractmethod
    def extract_midi(
        self,
        model_id: str,
        audio_path: str,
        output_dir: Optional[str] = None,
        progress_callback: Optional[Callable[[int], None]] = None,
    ) -> bytes:
        """Rend les OCTETS d'un fichier MIDI de `audio_path` : une piste par instrument, nommée
        (son instrument), la batterie sur le canal de percussion ; tempo et métrique écrits quand
        le moteur les détecte, la mesure 1 commençant au temps 0.

        `model_id`          : identifiant du modèle (dernier segment de sa clé de catalogue) ;
        `audio_path`        : chemin absolu de l'audio (tout format que `audio_decode` lit) ;
        `output_dir`        : dossier où le moteur peut ranger ses fichiers annexes — facultatif ;
        `progress_callback` : reçoit un pourcentage (0-100).

        Un audio dont rien n'est transcrit LÈVE en le disant — jamais un MIDI vide."""
