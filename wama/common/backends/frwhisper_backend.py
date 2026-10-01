"""
Backend : FrWhisper (transformers)

Ce backend charge les poids déjà présents dans le snapshot
``huggingface:aihpi/FrWhisper`` via la fonction utilitaire
``component_paths``.  Le moteur déclaré est **transformers** et le
modèle est un Whisper‑large‑v3 fine‑tuned pour le français.  La
transcription s’effectue par ``generate`` (transcription longue séquentielle
de Whisper) ; les timestamps sont renvoyés sous forme de segments.  Le modèle nécessite environ **7.4 Go VRAM**.

Limites :
- Pas de diarisation ni de hot‑words.
- Aucun streaming ; le fichier audio complet est traité en une passe.

Corrigé le 2026-10-01, après le Valider (essai réel) :
- PLUS de `pipeline` : il importe torchcodec quelle que soit l'entrée, et torchcodec est cassé
  dans le venv. Le modèle et son processeur sont appelés directement, l'audio décodé par la
  brique commune (`audio_decode`) ;
- transcription longue SÉQUENTIELLE de Whisper (pas de `chunk_length_s`, que transformers
  déclare expérimental pour un seq2seq) ;
- la langue demandée est passée au décodage ; float16 sur GPU.
- ⚠ Horodatage GROSSIER : ce fine-tune émet rarement ses jetons de temps, un segment couvre
  souvent une fenêtre de 30 s — la diarisation en pâtit, pas le texte.
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

#: Taux d'entrée de Whisper.
SAMPLING_RATE = 16000


class FrWhisperBackend(SpeechToTextBackend):
    """
    Backend de transcription français basé sur le modèle *FrWhisper*.
    Utilise le moteur ``transformers`` (``WhisperForConditionalGeneration``).
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
        "La langue demandée est passée au décodage ; à défaut, Whisper la détecte. "
        "Retourne les timestamps par segment."
    )

    # Capacités du backend
    supports_diarization = False
    supports_timestamps = True
    supports_hotwords = False
    supports_streaming = False
    supports_vad_filter = False

    # Dépendances Python (import name) — le décodage passe par la brique commune.
    REQUIRED_PACKAGES = ["transformers", "torch"]
    # Pas de paquet pip différent à déclarer
    PIP_PACKAGES = None

    # Ressources
    min_vram_gb = 0
    recommended_vram_gb = 7.4
    max_audio_seconds = None  # transcription longue séquentielle de Whisper

    def __init__(self):
        super().__init__()
        self._model = None
        self._processor = None
        self._device = None
        self._dtype = None

    # ------------------------------------------------------------------
    # Chargement / déchargement
    # ------------------------------------------------------------------
    def load(self, model_name: str = None) -> bool:
        """
        Charge le modèle depuis le snapshot local.

        ``model_name`` n’est pas utilisé : le backend ne gère qu’un seul
        modèle (identifié par le catalogue ``huggingface:aihpi/FrWhisper``).
        """
        try:
            # 1️⃣ Le répertoire du composant « model » porte aussi config et tokenizer.
            paths = component_paths("huggingface:aihpi/FrWhisper")
            if "model" not in paths:
                logger.error("[FrWhisper] Aucun composant « model » trouvé dans le snapshot.")
                return False
            model_dir = paths["model"].parent

            # 2️⃣ Imports lourds seulement au chargement. PAS de `pipeline` : il importe torchcodec
            #    quelle que soit l'entrée, et torchcodec est cassé dans le venv (2026-10-01).
            import torch
            from transformers import WhisperForConditionalGeneration, WhisperProcessor

            self._device = "cuda" if torch.cuda.is_available() else "cpu"
            self._dtype = torch.float16 if self._device == "cuda" else torch.float32
            logger.info(f"[FrWhisper] Chargement depuis {model_dir} ({self._device})")
            self._processor = WhisperProcessor.from_pretrained(str(model_dir))
            self._model = WhisperForConditionalGeneration.from_pretrained(
                str(model_dir), dtype=self._dtype).to(self._device)
            self._loaded = True
            self._current_model = "aihpi/FrWhisper"
            return True
        except Exception as exc:
            logger.error(f"[FrWhisper] Échec du chargement du modèle : {exc}")
            self._loaded = False
            return False

    def unload(self) -> None:
        """Libère le modèle et les ressources GPU éventuelles."""
        if self._model is not None:
            logger.info("[FrWhisper] Déchargement du modèle.")
            self._model = None
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
            audio_path: Chemin vers le fichier audio (wav, mp3, …), décodé par la brique commune.
            language: Langue imposée au décodage (code ISO), sinon détectée par Whisper.
            hotwords: Non supporté ; le paramètre est simplement ignoré.
            **kwargs: Paramètres supplémentaires (non utilisés).

        Retourne:
            TranscriptionResult contenant le texte complet et, si disponible,
            la liste des segments avec timestamps.
        """
        if not self.is_loaded or self._model is None:
            error_msg = "[FrWhisper] Backend non chargé – appel à load() requis."
            logger.error(error_msg)
            return TranscriptionResult(success=False, text="", error=error_msg)

        try:
            from wama.common.utils.audio_decode import decode_audio_at

            audio, sr = decode_audio_at(audio_path, target_sr=SAMPLING_RATE)
            # Plus de 30 s : transcription longue SÉQUENTIELLE de Whisper (caractéristiques non
            # tronquées) ; sinon la forme courte, complétée à 30 s.
            inputs = self._processor(audio, sampling_rate=sr, return_tensors="pt", truncation=False,
                                     padding="longest", return_attention_mask=True)
            if inputs.input_features.shape[-1] < 3000:
                inputs = self._processor(audio, sampling_rate=sr, return_tensors="pt",
                                         return_attention_mask=True)
            inputs = inputs.to(self._device, self._dtype)
            options = {"return_timestamps": True, "return_segments": True, "task": "transcribe"}
            if language:
                options["language"] = language.split("-")[0].lower()
            output = self._model.generate(**inputs, **options)

            # ⚠ Ce fine-tune émet rarement ses jetons d'horodatage : un segment couvre souvent
            # toute une fenêtre de 30 s (mesuré le 2026-10-01). Le texte, lui, est complet.
            segments = []
            for part in output["segments"][0]:
                text = self._processor.decode(part["tokens"], skip_special_tokens=True).strip()
                if text:
                    segments.append(TranscriptionSegment(
                        speaker_id="",               # pas de diarisation
                        start_time=round(float(part["start"]), 2),
                        end_time=round(float(part["end"]), 2),
                        text=text,
                    ))

            return TranscriptionResult(
                success=True,
                # Les fenêtres se recollent par une espace : décodées d'un bloc, elles se
                # soudaient (« un peuje crois »).
                text=" ".join(s.text for s in segments),
                language=language or "",
                segments=segments,
                error=None,
            )
        except Exception as exc:
            logger.error(f"[FrWhisper] Erreur pendant la transcription : {exc}")
            return TranscriptionResult(
                success=False,
                text="",
                language="",
                segments=[],
                error=str(exc),
            )
