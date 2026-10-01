"""
Qwen3-ASR Backend for Transcriber

Alibaba Qwen3-ASR — open-source ASR models with:
- Context biasing: hotwords passed as the official `context` of the prompt
- 30 languages with auto-detection (named in English by the runtime: "French")
- Noise robustness (RL-trained on noisy data)
- Low VRAM: 0.6B ≈ 2 GB, 1.7B ≈ 4 GB

Models (HuggingFace):
  - Qwen/Qwen3-ASR-0.6B   — fast, low VRAM
  - Qwen/Qwen3-ASR-1.7B   — best accuracy (default)

RUNTIME (réécrit le 2026-09-28). L'architecture `qwen3_asr` n'est pas dans transformers : elle est
fournie par le paquet officiel `qwen-asr`, qui l'ENREGISTRE auprès de transformers à l'import. La
version précédente de ce backend appelait une API de style Whisper (`forced_decoder_ids`, jetons
`<|0.00|>`) que ce modèle n'a pas — elle n'a jamais tourné (card #49 du 25/09 : « Transformers
does not recognize this architecture »).

INSTALLATION MESURÉE : `qwen-asr==0.0.6` épingle `accelerate==1.12.0` (que son code n'importe pas)
et des dépendances de démo et de langues (gradio, flask, vllm, soynlp, nagisa). En `--no-deps`, il
tourne avec NOTRE transformers 4.57.6 et accelerate 1.6.0 — un seul patch, `import nagisa`
rendu paresseux (`patches/apply_patches.py` n°7 ; tokenizer japonais, inutile ailleurs).
"""

import gc
import logging
from typing import Optional

from .speech_to_text_base import SpeechToTextBackend, TranscriptionResult, TranscriptionSegment

logger = logging.getLogger(__name__)

DEFAULT_MODEL = 'Qwen/Qwen3-ASR-1.7B'


class QwenASRBackend(SpeechToTextBackend):
    """
    Speech-to-text backend using Alibaba Qwen3-ASR (official `qwen_asr` runtime).

    Key differentiator: native context biasing — domain terms passed as the prompt context
    are favoured during transcription.

    Diarization is handled externally by pyannote_diarizer (same as Whisper).
    """

    #: Moteur piloté (contrat commun) — voir BaseModelBackend.ENGINE.
    ENGINE = 'transformers'

    #: Modèles du catalogue que CE backend sert — le lien FIN, déclaré le 2026-09-06.
    #: `ENGINE` ne suffit pas comme clé : `transformers` est piloté par 4 backends de 4 apps
    #: différentes, donc résoudre par moteur seul serait indécidable. Cette liste tranche.
    #: Les clés sont les `model_id` du catalogue (segment après `<source>:`), vocabulaire
    #: PARTAGÉ avec `SUPPORTED_MODELS` des backends imager — une graphie différente rouvrirait
    #: le trou qu'on ferme.
    #: La valeur porte le dépôt HF : c'est ce que `load()` charge quand le worker lui passe l'id
    #: du catalogue (`TranscriberBackendManager.model_for_request`, 2026-09-28).
    SUPPORTED_MODELS = {'qwen3-asr-0.6b': {'hf_id': 'Qwen/Qwen3-ASR-0.6B'},
                        'qwen3-asr-1.7b': {'hf_id': 'Qwen/Qwen3-ASR-1.7B'}}
    name = "qwen_asr"
    display_name = "Qwen3-ASR (Alibaba)"
    description = "Qwen3-ASR — multilingue, context biasing des mots-clés. Diarisation via pyannote."
    description_long = (
        "Qwen3-ASR (Alibaba) : transcription multilingue (30 langues, dont le français) avec "
        "context biasing natif — les mots-clés fournis entrent dans le contexte du modèle pour "
        "mieux reconnaître le vocabulaire métier. Pas de diarisation native (pyannote en "
        "post-traitement) ; segments de 30 s, l'heure de chaque mot vient de l'alignement "
        "acoustique. ~2–4 Go VRAM."
    )

    supports_diarization = False   # pyannote post-processing in workers.py
    #: Horodatage au SEGMENT (le vocabulaire commun dit « mot/segment ») : les segments sont datés
    #: par le DÉCOUPAGE commun (`max_audio_seconds` ci-dessous). Pas d'heure par MOT — le runtime
    #: ne la donne qu'avec son aligneur dédié, non intégré ; l'alignement acoustique la fournit.
    supports_timestamps  = True
    supports_hotwords    = True    # context biasing via the official prompt context
    supports_streaming   = False

    #: Découpage COMMUN (`workers._transcribe_maybe_chunked`) : chaque morceau devient un segment
    #: daté par son décalage. 30 s = la fenêtre qu'un lecteur corrige d'un coup d'œil ; le modèle
    #: accepterait 20 min d'une traite, mais sans aucune heure intermédiaire.
    max_audio_seconds = 30

    # Dépendances (contrat commun) — le téléchargement du modèle, lui, est fait dans load().
    REQUIRED_PACKAGES = ['transformers', 'soundfile', 'librosa', 'qwen_asr']
    #: `--no-deps` OBLIGATOIRE (cf. l'en-tête) : honorer le pin `accelerate==1.12.0` déplacerait
    #: une dépendance PARTAGÉE du venv pour rien. Tout le reste du chemin transformers est déjà là.
    PIP_PACKAGES = ['qwen-asr==0.0.6']
    PIP_NO_DEPS = True

    min_vram_gb         = 2
    recommended_vram_gb = 4

    MODEL_VRAM = {
        'Qwen/Qwen3-ASR-0.6B': 2,
        'Qwen/Qwen3-ASR-1.7B': 4,
    }

    def __init__(self):
        super().__init__()
        self._model  = None
        self._device = None
        self._dtype  = None

    # ------------------------------------------------------------------
    # Availability
    # ------------------------------------------------------------------

    @classmethod
    def is_available(cls) -> bool:
        """Disponible quand le runtime officiel `qwen_asr` est installé (contrat commun :
        `missing_packages`, par `find_spec` sur des RACINES — aucun import lourd).

        ⚠⚠ **`find_spec` d'un nom POINTÉ IMPORTE ses paquets parents** — la version du 25/09
        testait `transformers.models.qwen3_asr` et payait **34,1 s** à chaque expiration du cache
        de la page (le scénario nocturne « Envoyer vers » du transcriber sautait sur ce délai).
        Les racines seules restent à 0,00 s. *Une promesse de légèreté n'est pas une mesure.*
        """
        return not cls.missing_packages()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_device_and_dtype(self):
        """Auto-select device and torch dtype — bfloat16 on CUDA when supported (the dtype of the
        official examples; float16 overflows more easily on Qwen3 activations)."""
        try:
            import torch
            if torch.cuda.is_available():
                return 'cuda', (torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float16)
        except ImportError:
            pass
        return 'cpu', None

    def _get_cache_dir(self) -> str:
        """Dossier de famille des poids (`settings.MODEL_PATHS['speech']['qwen_asr']`)."""
        from django.conf import settings
        return str(settings.MODEL_PATHS.get('speech', {}).get('qwen_asr')
                   or settings.AI_MODELS_DIR / 'models' / 'speech' / 'qwen_asr')

    def _load_audio(self, audio_path: str):
        """Load audio as a mono float32 numpy array at 16 kHz → (array, 16000) — common decoder,
        so a compressed container (mp3/m4a) reads too (soundfile alone did not)."""
        from wama.common.utils.audio_decode import decode_audio_at
        return decode_audio_at(audio_path, target_sr=16000)

    @staticmethod
    def _runtime_language(language: Optional[str]) -> Optional[str]:
        """Code WAMA (`fr`) → nom attendu par le runtime (`French`), None si inconnu de lui
        (détection automatique plutôt qu'un refus). Table générique `LANGUAGE_NAMES_EN`."""
        if not language:
            return None
        from qwen_asr.inference.utils import SUPPORTED_LANGUAGES

        from wama.common.tts.constants import LANGUAGE_NAMES_EN
        name = LANGUAGE_NAMES_EN.get(str(language).lower())
        return name if name in SUPPORTED_LANGUAGES else None

    @staticmethod
    def _wama_language(runtime_name: str) -> str:
        """Nom du runtime (`French`, ou `French,English` fusionné) → code WAMA du premier."""
        from wama.common.tts.constants import LANGUAGE_NAMES_EN
        first = (runtime_name or '').split(',')[0].strip()
        return next((code for code, name in LANGUAGE_NAMES_EN.items() if name == first), '')

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    @classmethod
    def hf_id_for(cls, model_name: Optional[str]) -> str:
        """Dépôt HF d'une demande : id du catalogue (`qwen3-asr-0.6b`) → son dépôt déclaré ; un
        dépôt HF passe tel quel ; rien → le défaut."""
        if not model_name:
            return DEFAULT_MODEL
        declared = cls.SUPPORTED_MODELS.get(str(model_name).lower())
        return declared['hf_id'] if declared else model_name

    def load(self, model_name: str = None) -> bool:
        """Load a Qwen3-ASR model — catalogue id or HuggingFace id, default Qwen/Qwen3-ASR-1.7B."""
        model_id = self.hf_id_for(model_name)

        if self._loaded and self._current_model == model_id:
            logger.info(f"[QwenASR] '{model_id}' already loaded — reusing")
            return True

        try:
            if self._model is not None:
                self.unload()

            self._device, self._dtype = self._get_device_and_dtype()

            # Levier B de `hf_weights` (chemin local) : le runtime transmet `cache_dir` au MODÈLE
            # mais pas à son PROCESSEUR (`Qwen3ASRModel.from_pretrained`, qwen3_asr.py:208) — ses
            # fichiers seraient partis au cache partagé. On télécharge DANS le dossier de famille
            # et on charge par CHEMIN : tout est lu là, aucune variable d'environnement touchée.
            from wama.common.utils.hf_weights import poids_locaux
            local = poids_locaux(model_id, self._get_cache_dir())

            from qwen_asr import Qwen3ASRModel   # enregistre l'architecture qwen3_asr

            logger.info(f"[QwenASR] Loading '{model_id}' on {self._device} from {local}")
            kwargs = {}
            if self._dtype is not None:
                kwargs['dtype'] = self._dtype
            if self._device == 'cuda':
                kwargs['device_map'] = 'cuda:0'
            self._model = Qwen3ASRModel.from_pretrained(
                local, max_inference_batch_size=1, max_new_tokens=512, **kwargs)

            self._loaded        = True
            self._current_model = model_id
            vram = self.MODEL_VRAM.get(model_id, self.recommended_vram_gb)
            logger.info(f"[QwenASR] '{model_id}' loaded ✓ (≈{vram} GB VRAM)")
            return True

        except Exception as e:
            logger.error(f"[QwenASR] Failed to load '{model_id}': {e}")
            self._model  = None
            self._loaded = False
            return False

    def unload(self) -> None:
        """Unload model and free VRAM."""
        if self._model is not None:
            logger.info("[QwenASR] Unloading model…")
            del self._model
            self._model = None
            try:
                import torch
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
            except Exception:
                pass
            gc.collect()
            self._loaded        = False
            self._current_model = None
            logger.info("[QwenASR] Model unloaded")

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
        Transcribe an audio file (≤ `max_audio_seconds` — the common chunking cuts longer ones).

        Args:
            audio_path:  Path to the audio file.
            language:    WAMA code (e.g. 'fr', 'en') or None for auto-detect.
            hotwords:    Comma-separated domain terms, passed as the prompt context.

        Returns:
            TranscriptionResult — one segment spanning the chunk; empty speaker_id (filled by
            pyannote post-processing in workers.py if diarization is enabled).
        """
        if not self._loaded or self._model is None:
            if not self.load():
                return TranscriptionResult(success=False, text='',
                                           error="Failed to load Qwen3-ASR model")
        try:
            audio, sr = self._load_audio(audio_path)
            context = (hotwords or '').strip()
            if context:
                logger.info(f"[QwenASR] Context biasing active: {context[:80]}…")
            result = self._model.transcribe(audio=(audio, sr), context=context,
                                            language=self._runtime_language(language))[0]
            text = (result.text or '').strip()
            detected = self._wama_language(result.language) or (language or '')
            segments = [TranscriptionSegment(speaker_id='', start_time=0.0,
                                             end_time=round(len(audio) / sr, 2), text=text)] if text else []
            logger.info(f"[QwenASR] Done — {len(text)} chars, language={detected or '?'}")
            return TranscriptionResult(success=True, text=text, language=detected, segments=segments)

        except Exception as e:
            logger.error(f"[QwenASR] Transcription failed: {e}", exc_info=True)
            return TranscriptionResult(success=False, text='', error=str(e))
