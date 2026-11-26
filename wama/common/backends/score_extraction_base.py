"""
Contrat de la tâche `audio-to-score` — un audio → sa PARTITION (ABC), le maillon du COVER.

Écrit AVANT le backend (2026-10-03), parce que c'est le contrat de tâche
(`backend_inventory.TASK_CONTRACTS`) qui dit au rôle `backend` de wama-dev-ai quelle méthode
écrire : sans lui, le backend de YuE2 avait été proposé avec une méthode que le composer n'appelait
jamais (`music_generation_base`, 2026-10-01).

Nommé `extract_score`, pas « transcribe » (décision de Fabien, 2026-10-03) : ce verbe désigne
déjà le transcriber, la méthode des backends de parole et la tâche Whisper.

Le consommateur est le pipeline du composer : l'audio du morceau à reprendre (`work_audio`) devient
une partition, que le rendu (YuE2) suit dans le style de la consigne — la chaîne « audio source →
SheetSage2 → partition de la mélodie → YuE2 » que la documentation du moteur prescrit
(`vendor/yue/skills/yue2-music/references/models-and-setup.md:19-27`).
"""
from abc import abstractmethod
from typing import Callable, Optional

from .base import BaseModelBackend

#: Les PISTES d'un morceau qu'un moteur peut décoder en même temps que sa partition (2026-11-25,
#: `ROUTE §10.7.14 ㉑` — elles étaient jetées) : les clés sous lesquelles il les rend (`marks`),
#: et celles des pistes automatiques d'un audio que l'app du métier déclare (`media_marks`).
#: Toutes des segments sur le temps de l'audio (`start`, `end` en secondes) :
#:   `structure` — les parties (`label` : intro, verse, chorus, bridge…, tel que le moteur les nomme) ;
#:   `measures`  — les mesures, d'un temps fort au suivant (`number` : leur numéro dans la
#:                 partition de la même passe, depuis 1, une levée comprise ; `meter` « 4/4 » ;
#:                 `tempo` en temps par minute, mesuré sur la mesure, None si elle est incomplète) ;
#:   `tonality`  — les plages de tonalité (`key`) ;
#:   `chords`    — les accords (`chord`).
STRUCTURE, MEASURES, TONALITY, CHORDS = 'structure', 'measures', 'tonality', 'chords'
MUSIC_TRACKS = (STRUCTURE, MEASURES, TONALITY, CHORDS)


class ScoreExtractionBackend(BaseModelBackend):
    """Extrait la partition ABC d'un audio — un modèle `audio-to-score` du catalogue.

    L'état de chargement vient d'ici, comme pour les contrats de parole et d'image : un backend
    pose `self._loaded` dans `load()`/`unload()` et n'a rien d'autre à écrire.

    `marks` : ce que le DERNIER `extract_score` a décodé en plus de la partition, `{clé de
    MUSIC_TRACKS: lignes}` — posé AVANT qu'une partition impossible ne lève (la structure d'un
    morceau se lit même quand sa notation échoue) ; None pour un moteur qui n'en rend pas."""

    def __init__(self):
        self._loaded = False
        self._current_model = None
        self.marks: Optional[dict] = None

    @property
    def is_loaded(self) -> bool:
        return self._loaded

    def process(self, **kwargs):
        """Point d'entrée générique (contrat commun) → délègue à `extract_score()`."""
        return self.extract_score(**kwargs)

    @abstractmethod
    def extract_score(
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
                              partition complète (accords compris), pour éditer un morceau ;
        `progress_callback` : reçoit un pourcentage (0-100).

        Un audio dont aucune partition utilisable ne se construit (trop court, sans pulsation
        ni tonalité décodables) LÈVE en le disant — jamais une partition vide."""
