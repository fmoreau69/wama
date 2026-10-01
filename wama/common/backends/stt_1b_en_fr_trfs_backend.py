"""
Backend Kyutai STT 1B (en/fr) – moteur : transformers.

Les poids sont déjà présents dans le catalogue :
`huggingface:kyutai/stt-1b-en_fr-trfs`.  
Le composant « model » pointe vers le fichier `model.safetensors`.  
Le répertoire contenant ce fichier regroupe également le tokenizer
(`tokenizer.json`, `processor` etc.) ; c’est ce répertoire qui est passé à
`from_pretrained` de `transformers`.

Limites :
- Pas de diarisation native.
- Pas de hot‑words.
- Les timestamps ne sont pas fournis par défaut ; le backend renvoie
  uniquement le texte complet.
- Le modèle accepte les audios 24 kHz (il n’effectue pas de resampling).

Moteur : `transformers` (classe `KyutaiSpeechToTextForConditionalGeneration`).
VRAM recommandée ≈ 3.2 Go (voir manifeste).
"""

import logging
from pathlib import Path

from .speech_to_text_base import SpeechToTextBackend, TranscriptionResult, TranscriptionSegment
from wama.common.utils.model_components import component_paths

logger = logging.getLogger(__name__)

# ----------------------------------------------------------------------
# Inventaire des modèles supportés par ce backend
# ----------------------------------------------------------------------
SUPPORTED_MODELS = {
    "kyutai/stt-1b-en_fr-trfs": {
        "name": "Kyutai STT 1B (en/fr)",
        "description": "Modèle de transcription streaming (anglais / français) : 1 B paramètres, 0.5 s de latence.",
        "vram": 3.2,
    }
}


class KyutaiSttBackend(SpeechToTextBackend):
    """
    Backend pour le modèle `kyutai/stt-1b-en_fr-trfs` utilisant la bibliothèque
    `transformers`.  Le modèle est chargé depuis le disque (pas de téléchargement
    réseau) grâce à la fonction utilitaire `component_paths`.
    """

    # ------------------------------------------------------------------
    # Métadonnées du backend (obligatoires)
    # ------------------------------------------------------------------
    ENGINE = "transformers"
    name = "kyutai_stt_1b"
    display_name = "Kyutai STT 1B (en/fr)"
    description = "Transcription streaming (anglais / français) – modèle 1 B paramètres."
    description_long = (
        "Modèle de reconnaissance de parole streaming basé sur Transformers. "
        "Fonctionne en mode offline ; aucune diarisation ni hot‑words. "
        "Utilise le tokenizer et le modèle fournis dans le catalogue HF."
    )

    # Capacités déclarées
    supports_diarization = False
    supports_timestamps = False
    supports_hotwords = False
    supports_streaming = False
    supports_vad_filter = False

    # Dépendances Python (import‑only)
    REQUIRED_PACKAGES = ["transformers", "torch", "soundfile", "numpy"]
    # Pas de paquet pip différent du nom d'import
    PIP_PACKAGES = None

    # Ressources
    min_vram_gb = 0
    recommended_vram_gb = 3.2
    max_audio_seconds = None  # pas de limitation connue

    def __init__(self):
        super().__init__()
        self._model = None
        self._processor = None
        self._device = None
        self.catalogue_key = "huggingface:kyutai/stt-1b-en_fr-trfs"

    # ------------------------------------------------------------------
    # Cycle de vie
    # ------------------------------------------------------------------
    def load(self, model_name: str = None) -> bool:
        """
        Charge le modèle et le processeur depuis le répertoire du catalogue.
        Le paramètre `model_name` est ignoré ; le backend ne supporte qu’un seul
        modèle (celui indiqué dans `self.catalogue_key`).
        """
        try:
            # 1️⃣ Récupérer le chemin du fichier poids
            paths = component_paths(self.catalogue_key)  # {role: Path}
            model_path: Path = paths["model"]
            root_dir = model_path.parent

            # 2️⃣ Imports lourds (dans la méthode, comme requis)
            import torch
            from transformers import (
                KyutaiSpeechToTextProcessor,
                KyutaiSpeechToTextForConditionalGeneration,
            )

            # 3️⃣ Sélection du device
            self._device = "cuda" if torch.cuda.is_available() else "cpu"
            logger.info(f"[Kyutai STT] Chargement sur device={self._device}")

            # 4️⃣ Charger le processeur et le modèle
            self._processor = KyutaiSpeechToTextProcessor.from_pretrained(str(root_dir))
            self._model = KyutaiSpeechToTextForConditionalGeneration.from_pretrained(
                str(root_dir),
                device_map=self._device,
                torch_dtype="auto",
            )

            self._loaded = True
            self._current_model = self.catalogue_key
            logger.info("[Kyutai STT] Modèle chargé avec succès")
            return True
        except Exception as exc:  # pragma: no cover – log et renvoie False
            logger.error(f"[Kyutai STT] Échec du chargement du modèle : {exc}")
            self._loaded = False
            return False

    def unload(self) -> None:
        """Libère le modèle et le processeur, puis vide le cache CUDA si besoin."""
        if self._model is not None:
            logger.info("[Kyutai STT] Déchargement du modèle")
            del self._model
            self._model = None
        if self._processor is not None:
            del self._processor
            self._processor = None
        try:
            import torch

            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:
            pass
        self._loaded = False
        self._current_model = None

    # ------------------------------------------------------------------
    # Transcription
    # ------------------------------------------------------------------
    def transcribe(
        self,
        audio_path: str,
        language: str = None,
        hotwords: str = None,
        **kwargs,
    ) -> TranscriptionResult:
        """
        Transcrit le fichier audio indiqué.

        Args:
            audio_path: Chemin vers le fichier audio (wav, mp3, …).
            language: Ignoré – le modèle détecte automatiquement la langue.
            hotwords: Non supporté par ce backend.
            **kwargs: Ignorés.

        Retourne:
            TranscriptionResult contenant le texte complet.
        """
        if not self.is_loaded:
            error_msg = "Modèle non chargé – appelez `load()` avant `transcribe()`."
            logger.error(f"[Kyutai STT] {error_msg}")
            return TranscriptionResult(success=False, text="", error=error_msg)

        try:
            # 1️⃣ Lecture audio
            import numpy as np
            import soundfile as sf

            audio, sr = sf.read(audio_path, dtype="float32")
            if audio.ndim > 1:  # garder le premier canal si stéréo
                audio = audio[:, 0]
            # Le modèle attend 24 kHz ; on prévient si le taux diffère
            if sr != 24000:
                logger.warning(
                    f"[Kyutai STT] Taux d'échantillonnage {sr} Hz ≠ 24000 Hz – le modèle peut dégrader la qualité."
                )

            # 2️⃣ Préparer les entrées avec le processeur
            inputs = self._processor(
                audio,
                sampling_rate=sr,
                return_tensors="pt",
                padding=True,
            )
            inputs = {k: v.to(self._device) for k, v in inputs.items()}

            # 3️⃣ Génération
            output_tokens = self._model.generate(**inputs)

            # 4️⃣ Décodage
            decoded = self._processor.batch_decode(output_tokens, skip_special_tokens=True)
            transcript = decoded[0] if decoded else ""

            return TranscriptionResult(
                success=True,
                text=transcript,
                language=language or "",
                segments=[],
            )
        except Exception as exc:  # pragma: no cover – log et renvoie l’erreur
            logger.error(f"[Kyutai STT] Erreur de transcription : {exc}")
            return TranscriptionResult(success=False, text="", error=str(exc))
