"""
Backend : FrWhisper (transformers)

Ce backend charge les poids déjà présents dans le snapshot
``huggingface:aihpi/FrWhisper`` via la fonction utilitaire
``component_paths``.  Le moteur déclaré est **transformers** et le
modèle est un Whisper‑large‑v3 fine‑tuned pour le français.  La
transcription s’effectue avec le pipeline ``automatic-speech-recognition``
de 🤗 transformers ; les timestamps sont renvoyés sous forme de
segments.  Le modèle nécessite environ **7.4 Go VRAM**.

Limites :
- Pas de diarisation ni de hot‑words.
- Le pipeline impose la langue française (config generation fourni).
- Aucun streaming ; le fichier audio complet est traité en une passe.
"""

from pathlib import Path
import logging

from .speech_to_text_base import SpeechToTextBackend, TranscriptionResult, TranscriptionSegment
from wama.common.utils.model_components import component_paths

logger = logging.getLogger(__name__)

# ----------------------------------------------------------------------
# Inventaire des modèles supportés (module‑level)
# ----------------------------------------------------------------------
SUPPORTED_MODELS = {
    "aihpi/FrWhisper": {
        "name": "FrWhisper",
        "description": "Whisper large‑v3 fine‑tuned for French conversational speech",
        "vram": 7.4,
    }
}


class FrWhisperBackend(SpeechToTextBackend):
    """
    Backend de transcription français basé sur le modèle *FrWhisper*.
    Utilise le moteur ``transformers`` (pipeline ASR).
    """

    # ------------------------------------------------------------------
    # Métadonnées de classe (obligatoires)
    # ------------------------------------------------------------------
    ENGINE = "transformers"
    name = "frwhisper"
    display_name = "FrWhisper (transformers)"
    description = "Whisper large‑v3 fine‑tuned for French speech (transformers)."
    description_long = (
        "Modèle Whisper large‑v3 adapté au français conversationnel. "
        "Transcription multilingue, mais la langue est forcée en français "
        "par la configuration du modèle. Retourne les timestamps par segment."
    )

    # Capacités du backend
    supports_diarization = False
    supports_timestamps = True
    supports_hotwords = False
    supports_streaming = False
    supports_vad_filter = False

    # Dépendances Python (import name)
    REQUIRED_PACKAGES = ["transformers", "torch", "soundfile"]
    # Pas de paquet pip différent à déclarer
    PIP_PACKAGES = None

    # Ressources
    min_vram_gb = 0
    recommended_vram_gb = 7.4
    max_audio_seconds = None  # Whisper gère les longues séquences (chunking interne)

    def __init__(self):
        super().__init__()
        self._pipeline = None
        self._model_dir = None

    # ------------------------------------------------------------------
    # Chargement / déchargement
    # ------------------------------------------------------------------
    def load(self, model_name: str = None) -> bool:
        """
        Charge le modèle depuis le snapshot local.

        ``model_name`` n’est pas utilisé : le backend ne gère qu’un seul
        modèle (identifié par le catalogue ``huggingface:aihpi/FrWhisper``).
        """
        try:
            # 1️⃣ Récupérer le répertoire contenant les poids et les fichiers
            #    de configuration/tokenizer.
            paths = component_paths("huggingface:aihpi/FrWhisper")
            if "model" not in paths:
                logger.error("[FrWhisper] Aucun composant « model » trouvé dans le snapshot.")
                return False
            # Le répertoire parent contient l’ensemble des fichiers du modèle.
            self._model_dir = paths["model"].parent

            # 2️⃣ Importer le pipeline uniquement si le backend est réellement chargé.
            from transformers import pipeline

            # Sélection du device : CUDA si disponible, sinon CPU.
            device = -1
            try:
                import torch
                if torch.cuda.is_available():
                    device = 0
            except Exception:
                pass

            logger.info(f"[FrWhisper] Chargement du pipeline depuis {self._model_dir} (device={device})")
            self._pipeline = pipeline(
                "automatic-speech-recognition",
                model=str(self._model_dir),
                tokenizer=str(self._model_dir),
                device=device,
                chunk_length_s=30,          # même valeur que le README recommande
                return_timestamps=True,    # on veut les segments
            )
            self._loaded = True
            self._current_model = "aihpi/FrWhisper"
            return True
        except Exception as exc:
            logger.error(f"[FrWhisper] Échec du chargement du modèle : {exc}")
            self._loaded = False
            return False

    def unload(self) -> None:
        """Libère le pipeline et les ressources GPU éventuelles."""
        if self._pipeline is not None:
            logger.info("[FrWhisper] Déchargement du pipeline.")
            try:
                import torch
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
            except Exception:
                pass
            self._pipeline = None
        self._model_dir = None
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
            audio_path: Chemin vers le fichier audio (wav, mp3, …). Le pipeline
                accepte directement le chemin.
            language: Ignoré ; la langue est forcée en français par le modèle.
            hotwords: Non supporté ; le paramètre est simplement ignoré.
            **kwargs: Paramètres supplémentaires (non utilisés).

        Retourne:
            TranscriptionResult contenant le texte complet et, si disponible,
            la liste des segments avec timestamps.
        """
        if not self.is_loaded or self._pipeline is None:
            error_msg = "[FrWhisper] Backend non chargé – appel à load() requis."
            logger.error(error_msg)
            return TranscriptionResult(success=False, text="", error=error_msg)

        try:
            # Le pipeline accepte le chemin du fichier audio.
            result = self._pipeline(audio_path)

            # Texte complet
            text = result.get("text", "")

            # Langue – le modèle force le français, mais on récupère quand même
            # le champ éventuel.
            detected_language = result.get("language", "fr")

            # Construction des segments (chunks) si présents.
            segments = []
            chunks = result.get("chunks", [])
            for idx, chunk in enumerate(chunks):
                # Chaque chunk possède « timestamp » = [start, end] (en secondes)
                ts = chunk.get("timestamp", [0.0, 0.0])
                start, end = float(ts[0]), float(ts[1])
                seg = TranscriptionSegment(
                    speaker_id="0",          # pas de diarisation
                    start_time=start,
                    end_time=end,
                    text=chunk.get("text", ""),
                    confidence=None,        # non fourni par le pipeline
                )
                segments.append(seg)

            return TranscriptionResult(
                success=True,
                text=text,
                language=detected_language,
                segments=segments,
                error=None,
            )
        except Exception as exc:
            logger.error(f"[FrWhisper] Erreur pendant la transcription : {exc}")
            return TranscriptionResult(
                success=False,
                text="",
                language="",
                segments=[],
                error=str(exc),
            )
