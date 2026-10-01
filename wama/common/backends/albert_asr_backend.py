"""
Transcription DISTANTE par Albert API (DINUM) — premier moteur d'app exécuté chez un fournisseur.

POURQUOI (2026-09-30, demande de Fabien) : Albert sert `whisper-large-v3`, le même modèle que le
Whisper local. S'il se mesure équivalent, c'est un gain de GPU ; et une app qui sait appeler un
modèle distant peut ÉVALUER un modèle avant de l'intégrer — par la chaîne d'évaluation existante
(`asr_eval_corpus`, `result_evaluation`), sans rien d'autre.

LE LIEN MODÈLE ↔ BACKEND est celui de tout le parc : la ligne `albert:whisper-large-v3` porte
`composition.runtime.engine = 'albert'` (découverte `cloud_models.model_info_for`), ce backend
déclare le même `ENGINE`, et la résolution commune (`backend_for_model`) les relie. Le moteur
`albert` sert AUSSI le chat, les embeddings et l'OCR du fournisseur : c'est le contrat de tâche
(`SpeechToTextBackend`) qui réserve ce backend à la transcription (`backend_inventory`, filtre
des moteurs distants).

LE PROTOCOLE est celui d'OpenAI (`POST /audio/transcriptions`), déclaré sur la source
(`external_sources`, `protocol='openai'`). Un autre fournisseur qui le parle = une sous-classe qui
redéclare `ENGINE` ; rien d'autre ne dépend d'Albert ici.

CE QUE LE BACKEND NE DÉCIDE PAS : qui a le droit d'appeler, ni avec quelle clé. La clé est posée
par l'appelant (`authorize`), après la garde commune `cloud_models.cloud_access` (profil « 100 %
local », modèle ouvert par la clé de CET utilisateur). Un backend ne connaît pas l'utilisateur.

Mesuré le 2026-09-30 sur l'API réelle (clé d'instance) :
  • formats ACCEPTÉS : mp3 ou wav — d'où la conversion en wav 16 kHz mono (ce qu'un modèle de
    parole consomme de toute façon : rien de ce qu'il entend n'est perdu) ;
  • `verbose_json` rend langue, durée et segments horodatés ; `json` le texte seul ;
    `diarized_json` des locuteurs mais PAS la langue ; aucun horodatage par mot ;
  • 26 min de réunion (50 Mo en wav 16 kHz) transcrites en 7,5 s ; la limite de taille n'est pas
    documentée (erreur 413 prévue) — d'où `max_audio_seconds`, sous la plus longue mesure ;
  • ⚠ `language` n'IMPOSE pas la langue de l'audio : il TRADUIT la sortie vers cette langue. Il
    n'est donc passé que lorsque l'orchestration en impose une (réglage « une seule langue »).

LE FILTRE DE PAROLE (2026-10-01) : mesuré sur trois réunions SUMM-RE, Albert OMETTAIT 70 à 250
mots de plus que le Whisper local, avec des segments de 22 à 25 s couvrant tout l'audio — il ne
découpe pas la parole en amont. `vad_filter` fait donc ici ce que fait faster-whisper : le VAD
Silero repère les passages parlés, seuls ceux-ci sont envoyés (bout à bout), et les horodatages
rendus sont replacés sur l'audio d'origine (`SpeechTimestampsMap`). Même détecteur, mêmes
réglages par défaut que le local : la comparaison ne mesure que le moteur.
Mesuré le jour même (`WAMA_QUALITE §9bis`) : le filtre aide l'audio multilingue (FLEURS-CS
44,5 → 39,8 %) mais NE RÉDUIT PAS les omissions en réunion (31,6 → 31,7 %), pas plus qu'un envoi
par morceaux de ≤ 30 s (32,2 %, essayé puis retiré) : l'écart avec le local est dans le décodage
d'Albert, que son API ne règle pas.
"""

import logging
import os
import shutil
import tempfile
import time
from typing import Optional

from .speech_to_text_base import SpeechToTextBackend, TranscriptionResult, TranscriptionSegment

logger = logging.getLogger(__name__)


class _Refused(Exception):
    """Albert a refusé un envoi (HTTP ≠ 200, limite de débit persistante) — message prêt."""


class AlbertTranscriptionBackend(SpeechToTextBackend):
    """Reconnaissance de parole chez Albert API — aucun poids local, aucune VRAM."""

    #: Moteur piloté (contrat commun) : la SOURCE distante, comme le déclare le modèle.
    ENGINE = 'albert'
    name = 'albert'
    display_name = 'Albert API (DINUM)'
    description = "Transcription distante chez Albert (État) — aucune VRAM locale."
    description_long = (
        "Modèles de reconnaissance de parole servis par Albert API (DINUM), hébergement "
        "SecNumCloud. L'audio QUITTE la machine : réservé aux profils qui autorisent le cloud et "
        "aux clés Albert qui ouvrent le modèle. Horodatage par segment, pas par mot ; pas de "
        "diarisation dans ce mode."
    )

    supports_diarization = False
    supports_timestamps = True
    supports_hotwords = False
    supports_streaming = False
    supports_vad_filter = True

    REQUIRED_PACKAGES = ['requests']
    min_vram_gb = 0
    recommended_vram_gb = 0

    #: Sous la plus longue durée MESURÉE (1565 s) : au-delà, l'orchestration découpe.
    max_audio_seconds = 1500
    #: Délai d'une requête : 26 min d'audio ont pris 7,5 s ; la marge couvre une file chargée.
    REQUEST_TIMEOUT_S = 600
    #: Albert plafonne à 10 requêtes par minute (429 au-delà, mesuré le 2026-09-29) : un lot de
    #: cards, ou un long audio que l'orchestration découpe, attend et recommence au lieu d'échouer.
    RATE_LIMIT_WAIT_S = 7.0
    RATE_LIMIT_RETRIES = 6

    def __init__(self):
        super().__init__()
        self._api_key = ''

    def authorize(self, api_key: str) -> None:
        """Clé de l'appel suivant — posée par l'appelant APRÈS la garde commune."""
        self._api_key = api_key or ''

    def load(self, model_name: str = None) -> bool:
        """Rien à charger : retient seulement l'identifiant du modèle chez le fournisseur."""
        if not model_name:
            logger.error("[Albert ASR] aucun modèle nommé — un modèle distant se désigne toujours")
            return False
        self._current_model = model_name
        self._loaded = True
        return True

    def unload(self) -> None:
        self._current_model = None
        self._loaded = False

    def _upload_path(self, audio_path: str, tmp_dir: str) -> str:
        """Le fichier ENVOYÉ : l'original s'il est déjà du wav 16 kHz mono, sinon sa conversion."""
        try:
            import soundfile as sf
            info = sf.info(audio_path)
            if (audio_path.lower().endswith('.wav') and info.samplerate == 16000
                    and info.channels == 1):
                return audio_path
        except Exception:
            pass
        from wama.common.utils.audio_decode import transcode_to_wav
        return transcode_to_wav(audio_path, os.path.join(tmp_dir, 'albert_upload.wav'))

    @staticmethod
    def _speech_only(wav_path: str, tmp_dir: str):
        """Les seuls passages parlés de `wav_path` (wav 16 kHz mono), bout à bout, selon le VAD
        de faster-whisper → (chemin du wav envoyé, carte des temps) ; (None, None) sans parole.
        La carte replace un temps de l'audio envoyé sur l'audio d'origine."""
        import soundfile as sf
        from faster_whisper.vad import (SpeechTimestampsMap, VadOptions, collect_chunks,
                                        get_speech_timestamps)
        wave, sr = sf.read(wav_path, dtype='float32')
        spans = get_speech_timestamps(wave, VadOptions(), sampling_rate=sr)
        if not spans:
            return None, None
        chunks, _ = collect_chunks(wave, spans, sampling_rate=sr)
        out = os.path.join(tmp_dir, 'albert_speech.wav')
        sf.write(out, chunks[0], sr, subtype='PCM_16')
        logger.info(f"[Albert ASR] filtre de parole : {len(spans)} passages, "
                    f"{len(chunks[0]) / max(len(wave), 1):.0%} de l'audio envoyé")
        return out, SpeechTimestampsMap(spans, sr)

    def _post(self, path: str, data: dict) -> dict:
        """Un envoi ; attend et recommence sur la limite de débit (HTTP 429). Lève `_Refused`."""
        import requests
        from wama.common import external_sources
        for attempt in range(self.RATE_LIMIT_RETRIES + 1):
            with open(path, 'rb') as fh:
                response = requests.post(
                    f"{external_sources.base_url(self.ENGINE)}/audio/transcriptions",
                    headers={'Authorization': f'Bearer {self._api_key}'},
                    files={'file': (os.path.basename(path), fh, 'audio/wav')},
                    data=data, timeout=self.REQUEST_TIMEOUT_S)
            if response.status_code == 429 and attempt < self.RATE_LIMIT_RETRIES:
                wait = response.headers.get('Retry-After') if response.headers else None
                time.sleep(float(wait) if wait and str(wait).replace('.', '', 1).isdigit()
                           else self.RATE_LIMIT_WAIT_S)
                continue
            if response.status_code != 200:
                try:
                    detail = response.json().get('detail') or response.text
                except ValueError:
                    detail = response.text
                raise _Refused(f"Albert a refusé la transcription (HTTP {response.status_code}) : "
                               f"{str(detail)[:300]}")
            return response.json()
        raise _Refused("Albert : limite de débit toujours atteinte")

    def transcribe(self, audio_path: str, language: str = None, hotwords: str = None,
                   **kwargs) -> TranscriptionResult:
        import requests

        if not self._loaded or not self._current_model:
            return TranscriptionResult(success=False, text='', error="modèle distant non chargé")
        if not self._api_key:
            return TranscriptionResult(success=False, text='',
                                       error="aucune clé Albert posée pour cet appel")
        tmp_dir = tempfile.mkdtemp(prefix='wama_albert_')
        time_map = None
        data = {'model': self._current_model, 'response_format': 'verbose_json'}
        if language:
            data['language'] = language
        t0 = time.time()
        try:
            upload = self._upload_path(audio_path, tmp_dir)
            # Filtre de parole : défaut FAUX ici — c'est l'orchestration qui décide (`vad_mode`
            # de la card, sonde du champ lointain), comme elle le fait pour Whisper.
            if kwargs.get('vad_filter', False):
                upload, time_map = self._speech_only(upload, tmp_dir)
                if upload is None:
                    return TranscriptionResult(success=True, text='', language=language or '',
                                               segments=[])
            payload = self._post(upload, data)
        except _Refused as e:
            return TranscriptionResult(success=False, text='', error=str(e))
        except requests.RequestException as e:
            return TranscriptionResult(success=False, text='', error=f"Albert injoignable : {e}")
        except Exception as e:
            logger.error(f"[Albert ASR] échec : {e}", exc_info=True)
            return TranscriptionResult(success=False, text='', error=str(e))
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

        def _original(seconds, is_end=False):
            seconds = float(seconds or 0.0)
            return time_map.get_original_time(seconds, is_end=is_end) if time_map else seconds

        detected = payload.get('language') or language or ''
        segments = [
            TranscriptionSegment(
                speaker_id='',
                start_time=_original(seg.get('start')),
                end_time=_original(seg.get('end'), is_end=True),
                text=(seg.get('text') or '').strip(),
                language=detected or None,
            )
            for seg in (payload.get('segments') or []) if (seg.get('text') or '').strip()
        ]
        text = (payload.get('text') or '').strip()
        logger.info(f"[Albert ASR] {self._current_model} : {len(text)} caractères, "
                    f"{len(segments)} segments, langue={detected} en {time.time() - t0:.1f} s")
        progress = kwargs.get('progress_callback')
        if progress:
            try:
                progress(1.0)
            except Exception:
                pass
        return TranscriptionResult(success=True, text=text, language=detected, segments=segments)
