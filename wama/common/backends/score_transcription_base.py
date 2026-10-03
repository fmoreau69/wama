"""
Contrat de la tâche `audio-to-score` — un audio → sa PARTITION (ABC), le maillon du COVER.

Écrit AVANT le backend (2026-10-03), parce que c'est le contrat de tâche
(`backend_inventory.TASK_CONTRACTS`) qui dit au rôle `backend` de wama-dev-ai quelle méthode
écrire : sans lui, le backend de YuE2 avait été proposé avec une méthode que le composer n'appelait
jamais (`music_generation_base`, 2026-10-01).

Le consommateur est le pipeline du composer : l'audio du morceau à reprendre (`work_audio`) devient
une partition, que le rendu (YuE2) suit dans le style de la consigne — la chaîne « audio source →
SheetSage2 → partition de la mélodie → YuE2 » que la documentation du moteur prescrit
(`vendor/yue/skills/yue2-music/references/models-and-setup.md:19-27`).
"""
from abc import abstractmethod
from typing import Callable, Optional

from .base import BaseModelBackend


class ScoreTranscriptionBackend(BaseModelBackend):
    """Transcrit un audio en partition ABC — un modèle `audio-to-score` du catalogue.

    L'état de chargement vient d'ici, comme pour les contrats de parole et d'image : un backend
    pose `self._loaded` dans `load()`/`unload()` et n'a rien d'autre à écrire."""

    def __init__(self):
        self._loaded = False
        self._current_model = None

    @property
    def is_loaded(self) -> bool:
        return self._loaded

    def process(self, **kwargs):
        """Point d'entrée générique (contrat commun) → délègue à `transcribe_score()`."""
        return self.transcribe_score(**kwargs)

    @abstractmethod
    def transcribe_score(
        self,
        model_id: str,
        audio_path: str,
        output_dir: Optional[str] = None,
        melody_only: bool = True,
        progress_callback: Optional[Callable[[int], None]] = None,
    ) -> str:
        """Rend le TEXTE ABC de la partition de `audio_path`.

        `model_id`          : identifiant du modèle (dernier segment de sa clé de catalogue) ;
        `audio_path`        : chemin absolu de l'audio (tout format que le moteur décode) ;
        `output_dir`        : dossier où le moteur peut ranger ses fichiers annexes (MIDI,
                              annotations) — facultatif, le texte rendu fait foi ;
        `melody_only`       : True = la MÉLODIE seule, sans accords — la forme qu'un COVER
                              reprend (la consigne de rendu redonne le style) ; False = la
                              transcription complète (accords compris), pour éditer un morceau ;
        `progress_callback` : reçoit un pourcentage (0-100).

        Un audio dont aucune partition utilisable ne se construit (trop court, sans pulsation
        ni tonalité décodables) LÈVE en le disant — jamais une partition vide."""
