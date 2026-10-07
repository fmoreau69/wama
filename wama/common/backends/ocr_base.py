"""
Contrat des moteurs d'OCR — spécialisation de `BaseModelBackend` (2026-10-07).

POURQUOI UN CONTRAT. olmOCR, docTR et GLM-OCR avaient déjà la MÊME signature (`run(file_path,
mode, language, progress_cb, on_partial)`) sans qu'elle soit déclarée nulle part : rien ne la
disait au rôle `backend` qui écrit un nouveau moteur, et la résolution ne pouvait pas borner un
moteur partagé à sa tâche. Déclaré ici et dans `backend_inventory.TASK_CONTRACTS`, il sert trois
lecteurs, une seule table :
  • la RÉSOLUTION — un backend OCR sous un moteur qui sert plusieurs tâches (Ollama héberge le chat
    ET `glm-ocr`) n'y exécute que l'OCR ;
  • le rôle `backend` — la méthode à écrire pour un moteur OCR nouveau, lue par AST ;
  • la porte commune `manager.run_contract` — elle passe à `run` les réglages de l'élément PAR
    LEUR NOM : les arguments portent les noms des paramètres du schéma (`mode`, `language`).

Ce que le contrat NE fait pas : choisir le modèle. La clé de catalogue choisie arrive par
`catalogue_key` (contrat commun) ; un moteur qui sert plusieurs modèles la lit.
"""
from abc import abstractmethod
from typing import Callable, Optional

from wama.common.backends.base import BaseModelBackend


class OCRBackend(BaseModelBackend):
    """Un moteur d'OCR : un document (PDF ou image) → son texte."""

    @abstractmethod
    def run(
        self,
        file_path: str,
        mode: str = 'auto',
        language: str = '',
        progress_cb: Optional[Callable[[int, str], None]] = None,
        on_partial: Optional[Callable[[str], None]] = None,
    ) -> str:
        """Texte du document `file_path`.

        mode        : 'auto' | 'printed' | 'handwritten' — indication, que le moteur peut ignorer
                      (la capacité `params` du catalogue dit ceux qu'il LIT) ;
        language    : code de langue indicatif ('' = détection) ;
        progress_cb : `(pourcentage, message)` ;
        on_partial  : `(texte cumulé)` après chaque page — aperçu « pendant » (preview_utils).
        """

    def process(self, **kwargs) -> str:
        """Point d'entrée métier générique (contrat commun) → délègue à `run()`."""
        return self.run(**kwargs)
