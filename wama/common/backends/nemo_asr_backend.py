"""
NVIDIA NeMo ASR Backend for Transcriber — Canary 1B v2 and Parakeet TDT 0.6B v3.

POURQUOI CES DEUX-LÀ (2026-09-28). Banc Open ASR français (moyenne FLEURS/MCV/MLS, en cache dans
WAMA) : canary-1b-v2 4,79 %, parakeet-tdt-0.6b-v3 5,38 % — les deux meilleurs modèles OUVERTS qui
tiennent sur la carte, devant Qwen3-ASR (5,68 %) et Whisper large-v3 (6,24 %). Leurs poids étaient
installés depuis septembre (une archive `.nemo` chacun) sans aucun moteur pour les exécuter.

RUNTIME MESURÉ : `nemo_toolkit[asr]==3.0.0` épingle des versions qui RÉTROGRADERAIENT des paquets
partagés du venv (lightning 2.6.1 → 2.4.0, protobuf 7 → 6, fsspec — `pip install --dry-run`).
En `--no-deps`, avec ses 28 dépendances NOUVELLES seulement (liste exhaustive ci-dessous), il tourne
avec NOS versions — un seul patch (`apply_patches.py` n°8 : une signature de télémétrie). Preuve
hors venv, sur CPU : parakeet a transcrit un extrait français sans faute, horodaté au mot.

Deux familles, un moteur : Canary est un modèle MULTITÂCHE (AED) qui exige sa langue
(`source_lang`/`target_lang`) ; Parakeet (TDT) détecte la sienne. Les capacités propres à chacun
(langue exigée, durée maximale d'une passe) sont DÉCLARÉES dans `SUPPORTED_MODELS`.
"""

import gc
import logging
from pathlib import Path
from typing import List, Optional

from .speech_to_text_base import SpeechToTextBackend, TranscriptionResult, TranscriptionSegment

logger = logging.getLogger(__name__)

DEFAULT_MODEL = 'parakeet-tdt-0.6b-v3'

#: Les 25 langues européennes des deux cartes — la vérité du MOTEUR ; le catalogue du transcriber
#: la lit (`model_config.NEMO_LANGUAGES`) au lieu d'en tenir une copie.
NEMO_LANGUAGES = ('bg', 'hr', 'cs', 'da', 'nl', 'en', 'et', 'fi', 'fr', 'de', 'el', 'hu', 'it',
                  'lv', 'lt', 'mt', 'pl', 'pt', 'ro', 'sk', 'sl', 'es', 'sv', 'ru', 'uk')


class NemoASRBackend(SpeechToTextBackend):
    """Speech-to-text with NVIDIA NeMo (Canary / Parakeet), word-level timestamps included."""

    #: Moteur piloté (contrat commun) — la librairie qui exécute réellement le modèle.
    ENGINE = 'nemo'

    #: Modèles du catalogue servis (clés = `model_id` du catalogue, segment après `transcriber:`).
    #: `settings_key` = dossier de famille dans `MODEL_PATHS['speech']` ; `multitask` = exige sa
    #: langue (Canary) ; `max_audio_seconds` = une passe sûre (Canary est entraîné sur des
    #: segments ≤ 40 s ; Parakeet tient ~24 min en attention pleine, 10 min laisse de la marge).
    SUPPORTED_MODELS = {
        'canary-1b-v2': {'hf_id': 'nvidia/canary-1b-v2', 'settings_key': 'canary',
                         'multitask': True, 'max_audio_seconds': 30},
        'parakeet-tdt-0.6b-v3': {'hf_id': 'nvidia/parakeet-tdt-0.6b-v3', 'settings_key': 'parakeet',
                                 'multitask': False, 'max_audio_seconds': 600},
    }
    name = "nemo"
    display_name = "NVIDIA NeMo (Canary / Parakeet)"
    description = "NVIDIA NeMo — Canary 1B v2 / Parakeet TDT v3, 25 langues européennes, heure au mot."
    description_long = (
        "Moteurs ASR NVIDIA : Canary 1B v2 (le plus précis en français parmi les modèles ouverts, "
        "langue à préciser) et Parakeet TDT 0.6B v3 (très rapide, langue détectée). 25 langues "
        "européennes, horodatage au mot natif. Diarisation via pyannote. ~3–8 Go VRAM."
    )

    supports_diarization = False   # pyannote post-processing in workers.py
    supports_timestamps  = True    # word + segment timestamps from the decoder
    supports_hotwords    = False
    supports_streaming   = False

    #: Borne de la passe AVANT `load()` (le défaut le plus prudent) ; `load()` pose celle du
    #: modèle chargé sur l'instance — c'est elle que lit le découpage commun du worker.
    max_audio_seconds = 30

    REQUIRED_PACKAGES = ['nemo', 'lhotse', 'soundfile', 'librosa']
    #: `--no-deps` OBLIGATOIRE : honorer les pins de nemo_toolkit rétrograderait lightning,
    #: protobuf et fsspec. En contrepartie, la liste est EXHAUSTIVE — les 28 paquets que NeMo
    #: exige et que le venv n'a pas (relevé `pip install --dry-run --report`, 2026-09-28).
    PIP_PACKAGES = [
        'nemo-toolkit==3.0.0', 'lhotse==1.33.0', 'cytoolz==1.1.0', 'intervaltree==3.2.1',
        'nv-one-logger-core==2.3.1', 'overrides==7.7.0', 'StrEnum==0.4.15', 'toml==0.10.2',
        'nv-one-logger-pytorch-lightning-integration==2.3.1',
        'nv-one-logger-training-telemetry==2.3.1', 'toolz==1.1.0', 'webdataset==1.0.2',
        'aistore==1.26.0', 'braceexpand==0.1.7', 'humanize==4.16.0', 'msgspec==0.21.1',
        'tenacity==9.1.4', 'cuda-bindings==13.4.3', 'cuda-pathfinder==1.8.2', 'kaldialign==0.12.0',
        'sacrebleu==2.6.0', 'colorama==0.4.6', 'text-unidecode==1.3', 'wandb==0.30.0',
        'opentelemetry-exporter-http-transport==0.66b0',
        'opentelemetry-exporter-otlp-common==0.66b0', 'whisper_normalizer==0.1.15',
        'indic_numtowords==1.1.0', 'text2num==3.1.0',
    ]
    PIP_NO_DEPS = True

    min_vram_gb         = 3
    recommended_vram_gb = 8

    def __init__(self):
        super().__init__()
        self._model = None
        self._model_id = None

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @classmethod
    def model_id_for(cls, model_name: Optional[str]) -> str:
        """Id du catalogue d'une demande (id, ou dépôt HF d'un modèle servi) ; rien → le défaut."""
        if not model_name:
            return DEFAULT_MODEL
        name = str(model_name).split(':', 1)[-1].lower()
        if name in cls.SUPPORTED_MODELS:
            return name
        for model_id, spec in cls.SUPPORTED_MODELS.items():
            if spec['hf_id'].lower() == name:
                return model_id
        return DEFAULT_MODEL

    @staticmethod
    def _family_dir(settings_key: str) -> Path:
        from django.conf import settings
        return Path(settings.MODEL_PATHS['speech'][settings_key])

    #: En dessous, la langue détectée d'un passage est INCERTAINE : on lui préfère le repli.
    UNSURE_PROBABILITY = 0.5

    @staticmethod
    def _spoken_language(audio, fallback: str = None) -> str:
        """Langue PARLÉE, détectée quand l'élément n'en donne pas (`spoken_language`). ⚠ Jamais
        la langue du site : c'était le repli du premier passage, et `LANGUAGE_CODE = 'en-us'` a
        fait TRADUIRE un extrait français en anglais par Canary (2026-09-28).

        `fallback` (2026-09-29) : la langue du passage PRÉCÉDENT, ou celle de la sonde du worker.
        Un passage dont la détection est hors des langues du moteur, ou incertaine, la prend —
        vécu sur FLEURS-CS (#904) : un passage de 30 s détecté « la » (latin, p = 0,40) faisait
        échouer TOUTE la card. Sans repli, le refus d'avant reste (jamais de langue devinée)."""
        from wama.common.utils.spoken_language import detect_spoken_language
        try:
            language, probability = detect_spoken_language(audio, supported=NEMO_LANGUAGES)
        except ValueError as exc:
            if fallback:
                logger.info(f"[NeMo] {exc} — langue du repli : {fallback}")
                return fallback
            raise
        if fallback and language != fallback and probability < NemoASRBackend.UNSURE_PROBABILITY:
            logger.info(f"[NeMo] « {language} » incertaine (p={probability:.2f}) — repli : {fallback}")
            return fallback
        return language

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def load(self, model_name: str = None) -> bool:
        """Load a NeMo ASR model — catalogue id or HF id, default parakeet-tdt-0.6b-v3."""
        model_id = self.model_id_for(model_name)
        spec = self.SUPPORTED_MODELS[model_id]
        if self._loaded and self._model_id == model_id:
            logger.info(f"[NeMo] '{model_id}' already loaded — reusing")
            return True
        try:
            if self._model is not None:
                self.unload()
            import torch

            # Levier B de `hf_weights` : l'archive `.nemo` se charge par CHEMIN ; on la tire DANS
            # le dossier de famille (motif : l'archive seule, pas le reste du dépôt).
            from wama.common.utils.hf_weights import poids_locaux
            snapshot = Path(poids_locaux(spec['hf_id'], self._family_dir(spec['settings_key']),
                                         patterns=['*.nemo']))
            archive = next(iter(sorted(snapshot.glob('*.nemo'))), None)
            if archive is None:
                raise FileNotFoundError(f"aucune archive .nemo dans {snapshot}")

            import nemo.collections.asr as nemo_asr
            device = 'cuda' if torch.cuda.is_available() else 'cpu'
            logger.info(f"[NeMo] Loading '{model_id}' on {device} from {archive}")
            self._model = nemo_asr.models.ASRModel.restore_from(str(archive), map_location=device)
            self._model.eval()

            self._model_id = model_id
            self._loaded = True
            self._current_model = spec['hf_id']            # lu par `catalogue_key_for`
            self.max_audio_seconds = spec['max_audio_seconds']
            logger.info(f"[NeMo] '{model_id}' loaded ✓ ({type(self._model).__name__})")
            return True
        except Exception as e:
            logger.error(f"[NeMo] Failed to load '{model_id}': {e}", exc_info=True)
            self._model = None
            self._loaded = False
            return False

    def unload(self) -> None:
        if self._model is not None:
            logger.info("[NeMo] Unloading model…")
            del self._model
            self._model = None
            try:
                import torch
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
            except Exception:
                pass
            gc.collect()
            self._loaded = False
            self._model_id = None
            self._current_model = None

    # ------------------------------------------------------------------
    # Transcription
    # ------------------------------------------------------------------

    def _load_audio(self, audio_path: str):
        """Mono float32 at 16 kHz, whatever the container (m4a/aac/mp3/video): common decoder."""
        import numpy as np

        from wama.common.utils.audio_decode import decode_audio
        audio, sr = decode_audio(audio_path, target_sr=16000, mono=True)
        if sr != 16000:
            import librosa
            audio = librosa.resample(audio, orig_sr=sr, target_sr=16000)
        return np.asarray(audio, dtype=np.float32)

    @staticmethod
    def _segments_of(hypothesis, duration: float) -> List[TranscriptionSegment]:
        """NeMo stamps → common segments, each with its words ({word, start, end, probability} —
        the same shape as Whisper's). No segment stamps → one segment over the whole chunk."""
        text = (getattr(hypothesis, 'text', '') or '').strip()
        stamps = getattr(hypothesis, 'timestamp', None) or {}
        words = [{'word': w.get('word', ''), 'start': float(w.get('start', 0.0)),
                  'end': float(w.get('end', 0.0)), 'probability': None}
                 for w in (stamps.get('word') or [])]
        segments = []
        for s in stamps.get('segment') or []:
            start, end = float(s.get('start', 0.0)), float(s.get('end', 0.0))
            inside = [w for w in words if start - 0.01 <= w['start'] and w['end'] <= end + 0.01]
            segments.append(TranscriptionSegment(speaker_id='', start_time=start, end_time=end,
                                                 text=(s.get('segment') or '').strip(),
                                                 words=inside or None))
        if not segments and text:
            segments = [TranscriptionSegment(speaker_id='', start_time=0.0,
                                             end_time=round(duration, 2), text=text,
                                             words=words or None)]
        return segments

    def transcribe(self, audio_path: str, language: str = None, **kwargs) -> TranscriptionResult:
        """Transcribe one audio file (≤ `max_audio_seconds`; the common chunking cuts longer ones)."""
        if not self._loaded or self._model is None:
            if not self.load():
                return TranscriptionResult(success=False, text='', error="Failed to load NeMo model")
        try:
            audio = self._load_audio(audio_path)
            options = {'timestamps': True}
            # Langue : donnée, sinon ENTENDUE — pour Canary qui l'exige, et pour tous parce que
            # le résultat la porte (l'aligneur acoustique est choisi par elle).
            lang = (language or '').split('-')[0].lower() or self._spoken_language(
                audio, fallback=kwargs.get('fallback_language'))
            if self.SUPPORTED_MODELS[self._model_id]['multitask']:
                # Canary : transcription = MÊME langue en entrée et en sortie (sinon il traduit).
                options.update(source_lang=lang, target_lang=lang, pnc='yes')
            hypothesis = self._model.transcribe([audio], **options)[0]
            if isinstance(hypothesis, (list, tuple)):      # certains décodeurs rendent (meilleures, toutes)
                hypothesis = hypothesis[0]
            text = (getattr(hypothesis, 'text', '') or '').strip()
            segments = self._segments_of(hypothesis, len(audio) / 16000)
            logger.info(f"[NeMo] Done — {len(text)} chars, {len(segments)} segment(s)")
            return TranscriptionResult(success=True, text=text, language=lang, segments=segments)
        except Exception as e:
            logger.error(f"[NeMo] Transcription failed: {e}", exc_info=True)
            return TranscriptionResult(success=False, text='', error=str(e))
