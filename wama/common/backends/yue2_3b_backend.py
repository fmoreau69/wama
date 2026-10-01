"""
Backend YuE2‑3B – moteur « yue ».

Les poids du modèle sont déjà installés ; on les récupère via
`component_paths('huggingface:m-a-p/YuE2-3B')` (rôle « model ») et le VAE via
`component_repos('huggingface:m-a-p/YuE2-3B')` (rôle « vae »).  
Le moteur est fourni sous forme de paquet vendorisé : le code se trouve dans
`settings.BACKEND_VENDOR_DIR/yue/` et s’importe avec
`self.import_vendored('<paquet>.<module>', subdir='src')`.  
Le backend charge une instance de `YuE2Pipeline` (vendored) et l’utilise pour
générer le fichier audio demandé. Le moteur ne supporte pas le paramètre
`melody_path` ; il ne contrôle pas directement la durée, on le signale dans le
log. La VRAM du processus est libérée à `unload()` via
`torch.cuda.set_per_process_memory_fraction(1.0)`.
"""

import logging
import os
from pathlib import Path
from typing import Callable, Optional

from .music_generation_base import MusicGenerationBackend, split_caption_lyrics

logger = logging.getLogger(__name__)

# ----------------------------------------------------------------------
# Inventaire des modèles supportés (module‑level)
# ----------------------------------------------------------------------
SUPPORTED_MODELS = {
    "m-a-p/YuE2-3B": {
        "name": "YuE2‑3B",
        "description": "Frontier music generation model (text‑to‑music) with editable scores.",
        "vram": 8.8,
    },
}


class YuE2Backend(MusicGenerationBackend):
    """Backend pour le modèle YuE2‑3B (moteur « yue »)."""

    # ── métadonnées requises par le contrat commun ───────────────────────
    ENGINE = "yue"
    REQUIRED_PACKAGES = ["torch", "soundfile"]
    name = "YuE2-3B"
    display_name = "YuE2‑3B – Text‑to‑Music"
    recommended_vram_gb = 8.8
    description = "YuE2‑3B – génération musicale à partir de texte, via le moteur yue."
    VENDORED = True

    # ------------------------------------------------------------------
    # Gestion du cycle de vie
    # ------------------------------------------------------------------
    def __init__(self):
        self._pipeline = None
        self._warm = False

    @property
    def is_loaded(self) -> bool:
        return self._warm

    def load(self, model: Optional[str] = None) -> bool:
        """
        Initialise le pipeline YuE2.

        Le paramètre *model* n’est pas utilisé ; le backend charge toujours le
        modèle déclaré dans le catalogue « huggingface:m-a-p/YuE2-3B ».
        """
        # Import du code vendorisé
        pipeline_mod = self.import_vendored("yue2.pipeline", subdir="src")
        YuE2Pipeline = getattr(pipeline_mod, "YuE2Pipeline")

        # Chemins des poids du modèle principal
        from wama.common.utils.model_components import component_paths, component_repos

        model_paths = component_paths("huggingface:m-a-p/YuE2-3B")
        if "model" not in model_paths:
            raise RuntimeError("Composant « model » introuvable pour YuE2‑3B")
        model_dir = model_paths["model"].parent

        # Chemins du VAE (déclaré comme dépôt séparé)
        repos = component_repos("huggingface:m-a-p/YuE2-3B")
        vae_info = repos.get("vae")
        if not vae_info:
            raise RuntimeError("Composant « vae » introuvable pour YuE2‑3B")
        vae_repo, vae_cache = vae_info

        # Instanciation du pipeline – on désactive le progress bar interne
        self._pipeline = YuE2Pipeline.from_pretrained(
            model=model_dir,
            vae=vae_repo,
            cache_dir=str(vae_cache),
            progress=False,
        )
        self._warm = True
        return True

    def unload(self) -> None:
        """Libère le pipeline et réinitialise la limite de VRAM du processus."""
        self._pipeline = None
        self._warm = False
        try:
            import torch

            if torch.cuda.is_available():
                torch.cuda.set_per_process_memory_fraction(1.0)
                torch.cuda.empty_cache()
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Génération
    # ------------------------------------------------------------------
    def generate(
        self,
        model_id: str,
        prompt: str,
        duration: float,
        output_path: str,
        melody_path: Optional[str] = None,
        progress_callback: Optional[Callable[[int], None]] = None,
        on_audio: Optional[Callable] = None,
    ) -> str:
        """
        Génère un fichier audio à partir du *prompt*.

        - *model_id* : ignoré (le backend ne gère qu’un seul modèle : YuE2‑3B).
        - *prompt* : texte complet fourni par le compositeur ; on le découpe en
          style (caption) et paroles via :func:`split_caption_lyrics`.
        - *duration* : le moteur ne contrôle pas la durée ; on le consigne dans le log.
        - *melody_path* : non supporté ; une exception est levée si fourni.
        - *progress_callback* : reçoit 0 → 100 % approximatif.
        - *on_audio* : callback ``(numpy.ndarray, int)`` appelé une fois que le
          tableau audio final est disponible.
        """
        if melody_path is not None:
            raise ValueError("YuE2‑3B ne supporte pas le paramètre melody_path")

        # Chargement paresseux si nécessaire
        if not self.is_loaded:
            self.load()

        # Découpage du prompt
        style, lyrics = split_caption_lyrics(prompt)

        # Le moteur ne gère pas explicitement la durée ; on le loggue.
        logger.info(
            "[YuE2Backend] durée demandée %.2f s – le moteur ne la contraint pas, il la traite comme borne",
            duration,
        )

        # Progression initiale
        if progress_callback:
            progress_callback(0)

        # Génération via le pipeline vendorisé
        # Le pipeline expose un appel direct (voir README du moteur) :
        #   pipe(style=..., lyrics=..., cot="full", seed=...)
        # On utilise un seed fixe (0) si le compositeur n’en fournit pas.
        seed = 0
        try:
            # Le pipeline accepte les arguments *style* et *lyrics*.
            song_result = self._pipeline(
                style=style,
                lyrics=lyrics,
                cot="full",
                seed=seed,
            )
        except Exception as exc:
            logger.exception("Échec de la génération YuE2‑3B")
            raise RuntimeError(f"YuE2 generation failed: {exc}") from exc

        if progress_callback:
            progress_callback(80)

        # Sauvegarde du fichier audio
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        saved_path = song_result.save(output_path)

        # Callback audio (tableau numpy, fréquence d’échantillonnage)
        if on_audio:
            try:
                on_audio(song_result.audio, song_result.sample_rate)
            except Exception:
                logger.exception("Erreur dans le callback on_audio")

        if progress_callback:
            progress_callback(100)

        return str(saved_path)
