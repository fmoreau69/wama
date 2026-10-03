"""
Backend SheetSage2 — extraction de la partition ABC d'un audio (tâche `audio-to-score`).
(`transcribe` ci-dessous est l'API du modèle amont ; le vocabulaire WAMA est `extract_score`,
« transcribe » désignant déjà le transcriber et la parole.)

Écrit par le rôle `backend` de wama-dev-ai (Albert, 2026-10-03), revu avant validation.

Le moteur est `transformers-remote-code` : le code du modèle est livré DANS son dépôt
(`auto_map`) et exécuté par `trust_remote_code=True`. Le dépôt ne porte qu'un ADAPTATEUR ; son
parent `m-a-p/MERT-v2-FullSong` (composant `base` du catalogue) est chargé par ce code lui-même,
avec le `cache_dir` qu'on lui passe — il se range donc À CÔTÉ du modèle (`component_repos`).

⚠ Chargé par l'IDENTIFIANT du dépôt + `cache_dir` + révision, jamais par le chemin du snapshot :
avec un dossier local, transformers 4.57 ne recopie que les imports relatifs DIRECTS du code
distant (`chord_spelling_sheetsage2.py`, importé en second rang, manque — mesuré le 2026-10-03).
La branche « dépôt » les recopie tous ; `installed_snapshot` donne la révision installée.

Mesuré le 2026-10-03 (RTX 4090) : 2,7 Go de VRAM en float32, 7 s pour 1 min d'audio ; CPU 76 s
pour 18 s. Une note collée à la toute fin de l'audio fait lever le moteur (grille de sous-temps) :
l'erreur est rendue telle quelle, jamais une partition vide.
"""

import logging
from typing import Callable, Optional

from wama.common.utils.model_components import installed_snapshot

from .score_extraction_base import ScoreExtractionBackend

logger = logging.getLogger(__name__)

HF_ID = "m-a-p/SheetSage2"
MODEL_KEY = f"huggingface:{HF_ID}"

# Clé LITTÉRALE : l'inventaire la lit par AST — c'est elle qui départage ce backend d'Audio8, qui
# partage le moteur `transformers-remote-code`.
SUPPORTED_MODELS = {
    "m-a-p/SheetSage2": {
        "name": "SheetSage2",
        "description": "Audio → partition ABC (mélodie vocale et instrumentale, accords)",
        "vram": 2.7,
    }
}


class SheetSage2Backend(ScoreExtractionBackend):
    """SheetSage2 : un audio de morceau → sa partition ABC."""

    ENGINE = "transformers-remote-code"
    name = "sheetsage2"
    display_name = "SheetSage2"
    recommended_vram_gb = 2.7
    description = "Audio → partition (adaptateur SheetSage2 sur MERT-v2-FullSong)."
    REQUIRED_PACKAGES = ["transformers", "torch"]

    def __init__(self):
        super().__init__()
        self._model = None

    def load(self, model: Optional[str] = None) -> bool:
        if self._model is not None:
            return True
        import torch
        from transformers import AutoModel

        snapshot = installed_snapshot(MODEL_KEY)
        device = "cuda" if torch.cuda.is_available() else "cpu"
        # float32 : la seule précision mesurée (la sonde du 2026-10-03), 2,7 Go sur GPU.
        self._model = AutoModel.from_pretrained(
            HF_ID,
            revision=snapshot.name,
            cache_dir=str(snapshot.parent.parent.parent),
            trust_remote_code=True,
        ).to(device).eval()
        self._loaded = True
        self._current_model = HF_ID
        logger.info("[SheetSage2] chargé (révision %s, %s)", snapshot.name[:12], device)
        return True

    def unload(self) -> None:
        if self._model is None:
            return
        self._model = None
        self._loaded = False
        self._current_model = None
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:
            pass
        logger.info("[SheetSage2] déchargé")

    def extract_score(
        self,
        model_id: str,
        audio_path: str,
        output_dir: Optional[str] = None,
        melody_only: bool = True,
        progress_callback: Optional[Callable[[int], None]] = None,
    ) -> str:
        if self._model is None:
            self.load()
        if progress_callback:
            progress_callback(0)
        import torch
        with torch.inference_mode():
            result = self._model.transcribe(audio_path, output_dir=output_dir,
                                            melody_only=melody_only)
        abc = (result or {}).get("abc")
        if not abc:
            raise RuntimeError("SheetSage2 n'a produit aucune partition : "
                               f"{(result or {}).get('abc_error') or 'raison non donnée'}")
        if progress_callback:
            progress_callback(100)
        return abc
