"""
Contrat de la tâche `image-to-score` — une PAGE de partition imprimée (image ou PDF) → sa partition.

Écrit le 2026-11-06, avant son premier backend (copisteria, `PROSPECTION_PIPELINE`, veille du
2026-11-06), pour la même raison que `score_extraction_base` et `midi_extraction_base` : c'est le
contrat de tâche (`backend_inventory.TASK_CONTRACTS`) qui dit au rôle `backend` de wama-dev-ai quelle
méthode écrire. Le consommateur visé est le Reader (« l'utilisateur scanne une partition, la
partition est rendue typographiée et éditable », Fabien).

Le moteur rend du MUSICXML, l'échange standard que ces moteurs écrivent (copisteria, homr,
Audiveris) et le fichier qu'on télécharge tel quel. La mise en ABC — ce que la page d'édition et
le composer lisent — n'est pas de son ressort : une brique commune, la même pour tout moteur de la
tâche (patron d'`audio-to-midi`, que `midi_score` note).

Les noms suivent les conventions des autres contrats : le fichier arrive sous le nom de son PORT
(`work_file`, celui de l'OCR et de `TASK_DEFAULT_INPUTS`), la progression sous `progress_callback`.
"""
from abc import abstractmethod
from typing import Callable, Optional

from .base import BaseModelBackend


class ScoreReadingBackend(BaseModelBackend):
    """Lit la partition d'une page imprimée — un modèle `image-to-score` du catalogue.

    L'état de chargement vient d'ici, comme pour les autres contrats : un backend pose
    `self._loaded` dans `load()`/`unload()` et n'a rien d'autre à écrire."""

    def __init__(self):
        self._loaded = False
        self._current_model = None

    @property
    def is_loaded(self) -> bool:
        return self._loaded

    def process(self, **kwargs):
        """Point d'entrée générique (contrat commun) → délègue à `read_score()`."""
        return self.read_score(**kwargs)

    @abstractmethod
    def read_score(
        self,
        model_id: str,
        work_file: str,
        output_dir: Optional[str] = None,
        progress_callback: Optional[Callable[[int], None]] = None,
        page_texts: Optional[list] = None,
    ) -> str:
        """Rend le TEXTE MusicXML de la partition de `work_file` — ses pages à la suite, une
        partition unique.

        `model_id`          : identifiant du modèle (dernier segment de sa clé de catalogue) ;
        `work_file`         : chemin absolu d'une image (PNG, JPEG…) ou d'un PDF ;
        `output_dir`        : dossier où le moteur peut ranger ses fichiers de travail (pages
                              rasterisées, caches) — facultatif, le texte rendu fait foi ;
        `progress_callback` : reçoit un pourcentage (0-100) ;
        `page_texts`        : le TEXTE de chaque page avec sa place et son RÔLE (2026-11-08) — une
                              entrée par page, la page de `OCRBackend.read_lines` (`width`,
                              `height`, `lines`) dont chaque ligne porte un `role` de
                              `score_page.TEXT_ROLES` (titre, compositeur, numéro de page, nombre
                              de reprises…). Facultatif : sans lui la musique se lit pareil, sans
                              titre ni mots. Un moteur qui ne lit pas le texte l'ignore.

        Une page où aucune portée ne se lit LÈVE en le disant — jamais une partition vide."""
