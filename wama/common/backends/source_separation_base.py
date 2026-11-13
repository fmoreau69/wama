"""
Contrat de la tâche `audio-source-separation` — un audio → une PISTE par source (voix, batterie…).

Écrit le 2026-11-12 avec son premier backend (Demucs v4), pour la raison des autres contrats de
tâche (`midi_extraction_base`, `score_reading_base`) : c'est lui que `backend_inventory.
TASK_CONTRACTS` désigne au rôle `backend` de wama-dev-ai, et lui qui borne la résolution (LIANT).

Le besoin (demande de Fabien) : découper l'audio d'une card du composer en pistes, pour transcrire
chacune SEULE — une partition d'un instrument isolé est plus juste que celle du mélange. Ce que le
contrat rend, ce sont des FICHIERS ; ce qu'on en fait (des cards, un lot) n'est pas son affaire :
c'est la brique commune `common/utils/derived_cards.py`.

Les pistes qu'un modèle rend sont une CAPACITÉ déclarée au catalogue (`capabilities.stems`) —
jamais déduites du nom du modèle —, nommées par leur moteur (les noms de Demucs, standard du
domaine : MUSDB18 pour `vocals`, `drums`, `bass`, `other`). Leur libellé affiché est celui de tout
instrument (`midi_score.instrument_label`, une seule table).
"""
from abc import abstractmethod
from typing import Callable, Dict, Optional

from .base import BaseModelBackend


class SourceSeparationBackend(BaseModelBackend):
    """Sépare un audio en pistes — un modèle `audio-source-separation` du catalogue.

    L'état de chargement vient d'ici, comme pour les autres contrats : un backend pose
    `self._loaded` dans `load()`/`unload()` et n'a rien d'autre à écrire."""

    def __init__(self):
        self._loaded = False
        self._current_model = None

    @property
    def is_loaded(self) -> bool:
        return self._loaded

    def process(self, **kwargs):
        """Point d'entrée générique (contrat commun) → délègue à `separate_sources()`."""
        return self.separate_sources(**kwargs)

    @abstractmethod
    def separate_sources(
        self,
        model_id: str,
        audio_path: str,
        output_dir: str,
        progress_callback: Optional[Callable[[int], None]] = None,
    ) -> Dict[str, str]:
        """Écrit une piste WAV par source de `audio_path` dans `output_dir` et rend
        `{piste: chemin absolu}`, dans l'ordre du modèle (`vocals`, `drums`…).

        `model_id`          : identifiant du modèle (dernier segment de sa clé de catalogue) ;
        `audio_path`        : chemin absolu de l'audio (tout format que `audio_decode` lit) ;
        `output_dir`        : dossier existant où écrire les pistes ;
        `progress_callback` : reçoit un pourcentage (0-100).

        Les pistes gardent la fréquence d'échantillonnage du modèle et sont en stéréo. Un audio
        illisible LÈVE en le disant — jamais une liste vide."""
