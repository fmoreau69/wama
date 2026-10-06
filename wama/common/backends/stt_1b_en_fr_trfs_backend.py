"""
Backend Kyutai STT 1B (en/fr) – moteur : transformers.

Les poids sont déjà présents dans le catalogue :
`huggingface:kyutai/stt-1b-en_fr-trfs`.
Le composant « model » pointe vers le fichier `model.safetensors`.
Le répertoire contenant ce fichier regroupe également le tokenizer
(`tokenizer.json`, `processor` etc.) ; c’est ce répertoire qui est passé à
`from_pretrained` de `transformers`.

Limites :
- Pas de diarisation native.
- Pas de hot‑words.
- Le modèle travaille à 24 kHz : l'audio est décodé et rééchantillonné par la brique commune
  (`audio_decode`), jamais par torchcodec (cassé dans le venv).

Horodatage (corrigé le 2026-10-01, après le Valider) : le modèle émet UN jeton par trame audio
(80 ms), avec un retard fixe déclaré par son extracteur (`audio_delay_seconds`, 0,5 s). Le temps
d'un mot se lit donc sur la position de ses jetons ; les mots se regroupent en segments aux
pauses (`segments_from_words`, commun avec NeMo).

Moteur : `transformers` (classe `KyutaiSpeechToTextForConditionalGeneration`).
VRAM recommandée ≈ 3.2 Go (voir manifeste).
"""

import logging
from pathlib import Path

from .speech_to_text_base import SpeechToTextBackend, TranscriptionResult, segments_from_words
from wama.common.utils.model_components import component_paths

logger = logging.getLogger(__name__)

# ----------------------------------------------------------------------
# Inventaire des modèles supportés par ce backend
# ----------------------------------------------------------------------
# Le nom de sa ligne de catalogue, et RIEN d'autre : nom, description et VRAM sont au
# REGISTRE (l'inventaire ne lit que la clé) — 2026-10-06, `backend_proposals`.
SUPPORTED_MODELS = {
    "kyutai/stt-1b-en_fr-trfs": {"model_key": "huggingface:kyutai/stt-1b-en_fr-trfs"},
}

#: Kyutai émet ses mots avec un retard VARIABLE (jusqu'à ~1,5 s mesuré le 2026-10-01) : l'écart
#: entre deux mots ne mesure pas un silence. Les segments se coupent sur SA ponctuation ; la pause
#: n'est plus qu'un filet large.
SENTENCE_ENDS = '.?!…'
PAUSE_SECONDS = 2.0


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
    display_name = "Kyutai STT 1B (en/fr)"
    description = "Transcription streaming (anglais / français) – modèle 1 B paramètres."
    description_long = (
        "Modèle de reconnaissance de parole streaming basé sur Transformers. "
        "Fonctionne en mode offline ; aucune diarisation ni hot‑words. "
        "Horodatage par mot déduit des trames audio (80 ms)."
    )

    # Capacités déclarées
    supports_diarization = False
    supports_timestamps = True
    supports_hotwords = False
    supports_streaming = False
    supports_vad_filter = False

    # Dépendances Python (import‑only) — le décodage passe par la brique commune.
    REQUIRED_PACKAGES = ["transformers", "torch"]
    # Pas de paquet pip différent du nom d'import
    PIP_PACKAGES = None

    # Ressources
    min_vram_gb = 0
    recommended_vram_gb = 3.2
    #: Une passe au plus : la fenêtre d'attention du modèle est de 375 trames (30 s), glissante ;
    #: mesuré sans défaut à 75 s le 2026-10-01. Au-delà, la découpe commune du worker.
    max_audio_seconds = 300

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
        Le paramètre `model_name` est ignoré ; le backend ne supporte qu’un seul
        modèle (celui indiqué dans `self.catalogue_key`).

        Déjà chargé → réutilisé. Le worker GPU ne décharge pas entre deux cards : recharger à
        chaque card EMPILAIT une copie du modèle sur la précédente, jusqu'au manque de mémoire
        (campagne du 2026-10-02, 19:53 et 20:18). Même règle que NeMo.
        """
        if self._loaded and self._model is not None:
            logger.info("[Kyutai STT] déjà chargé — réutilisé")
            return True
        if self._model is not None:
            self.unload()
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
                dtype="auto",
            )

            self._loaded = True
            self._current_model = self.catalogue_key
            logger.info("[Kyutai STT] Modèle chargé avec succès")
            return True
        except Exception as exc:  # pragma: no cover – log et renvoie False
            logger.error(f"[Kyutai STT] Échec du chargement du modèle : {exc}")
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
    def _words(self, token_ids, frame_seconds: float, delay_seconds: float) -> list:
        """Mots horodatés depuis la sortie : un jeton par trame, un mot commence à chaque pièce
        préfixée de `▁` (SentencePiece). Les jetons de remplissage et spéciaux ne portent rien."""
        tokenizer = self._processor.tokenizer
        silent = set(tokenizer.all_special_ids) | {self._model.config.pad_token_id,
                                                  self._model.config.bos_token_id}
        words, pieces = [], []

        def close():
            text = tokenizer.convert_tokens_to_string([p for _, p in pieces]).strip()
            if text:
                words.append({'word': text, 'start': round(pieces[0][0], 2),
                              'end': round(pieces[-1][0] + frame_seconds, 2)})

        for index, token_id in enumerate(token_ids):
            if token_id in silent:
                continue
            piece = tokenizer.convert_ids_to_tokens(token_id)
            if piece is None:
                continue
            at = max(0.0, index * frame_seconds - delay_seconds)
            if piece.startswith('▁') and pieces:
                close()
                pieces = []
            pieces.append((at, piece))
        if pieces:
            close()
        return words

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
            TranscriptionResult : texte complet et segments horodatés.
        """
        if not self.is_loaded:
            error_msg = "Modèle non chargé – appelez `load()` avant `transcribe()`."
            logger.error(f"[Kyutai STT] {error_msg}")
            return TranscriptionResult(success=False, text="", error=error_msg)

        try:
            from wama.common.utils.audio_decode import decode_audio_at

            extractor = self._processor.feature_extractor
            # 1️⃣ Lecture audio, au taux du modèle (24 kHz) GARANTI : `decode_audio` laisse un
            #    WAV à sa fréquence native, et le processeur ne la vérifie pas (essai du
            #    2026-10-01 : un 16 kHz pris pour du 24 kHz, accéléré de moitié).
            audio, sr = decode_audio_at(audio_path, target_sr=extractor.sampling_rate)

            # 2️⃣ Préparer les entrées — `audio=` NOMMÉ : en position, le processeur le lit
            #    comme une image et rend un dict vide (constaté le 2026-10-01).
            inputs = self._processor(audio=audio, return_tensors="pt")
            inputs = {k: v.to(self._device) for k, v in inputs.items()}

            # 3️⃣ Génération, en `inference_mode` : dans le worker GPU (2026-10-02, campagne
            #    d'évaluation), la 1ʳᵉ carte Kyutai après LinTO et FrWhisper a échoué sur « Inplace
            #    update to inference tensor outside InferenceMode » — non reproduit seul ni après
            #    l'un ou l'autre. Une mise à jour en place d'un tel tenseur est permise DANS ce mode.
            import torch
            with torch.inference_mode():
                output_tokens = self._model.generate(**inputs)

            # 4️⃣ Décodage
            decoded = self._processor.batch_decode(output_tokens, skip_special_tokens=True)
            transcript = decoded[0].strip() if decoded else ""
            frame_seconds = self._model.config.codec_config.frame_size / sr
            words = self._words(output_tokens[0].tolist(), frame_seconds,
                                float(getattr(extractor, 'audio_delay_seconds', 0.0) or 0.0))

            return TranscriptionResult(
                success=True,
                text=transcript,
                language=language or "",
                segments=segments_from_words(words, pause_seconds=PAUSE_SECONDS,
                                             sentence_ends=SENTENCE_ENDS),
            )
        except Exception as exc:  # pragma: no cover – log et renvoie l’erreur
            logger.exception(f"[Kyutai STT] Erreur de transcription : {exc}")
            return TranscriptionResult(success=False, text="", error=str(exc))
