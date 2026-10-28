"""
WAMA TTS Microservice - FastAPI
Standalone TTS service that keeps models preloaded in GPU memory.
Django and Celery workers call this service via HTTP.

Les moteurs (Coqui/XTTS, Bark, Higgs, Kokoro) sont des backends sous CONTRAT
COMMUN (`wama/synthesizer/backends/`, dérivés de `BaseModelBackend`) : c'est le
contrat qui mesure et publie leur empreinte VRAM au gouverneur (clé par modèle,
ex. `…CoquiBackend:<pid>#synthesizer:coqui-xtts`) et qui enregistre les
unloaders. Ce fichier ne garde que la POLITIQUE : bascule de moteur courant,
résidence de Kokoro, file HTTP. (La résolution des presets de voix l'a quitté le
2026-09-13 : elle est à Django, `common/tts/voice_refs.speaker_wav_for`.)

Usage (depuis la racine du dépôt) :
    python -m uvicorn wama.common.tts.service:app --host 0.0.0.0 --port 8001 --workers 1

Domicile depuis le 2026-10-28 : ce fichier était `tts_service.py`, à la racine du dépôt (module
`tts_service:app`). Il a rejoint son paquet de domaine, à côté de son client
(`service_client.py`) — demande de Fabien. Les motifs d'arrêt des scripts de démarrage
reconnaissent encore l'ancienne ligne de commande, le temps qu'aucun service lancé sous
l'ancien nom ne survive.
"""

import os
import logging
import threading
from pathlib import Path

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(level=logging.INFO, format="%(asctime)s [TTS] %(levelname)s %(message)s")
logger = logging.getLogger("tts_service")

# ---------------------------------------------------------------------------
# Project paths (sans importer Django — les chemins de POIDS vivent dans les backends)
# ---------------------------------------------------------------------------
#: Racine du dépôt (wama/common/tts/service.py → ../../..) : `sys.path` ci-dessous, pour que
#: `wama` s'importe même lancé hors de la racine.
PROJECT_DIR = Path(__file__).resolve().parents[3]

# ⚠ Le service ne connaît plus AUCUN dossier de voix (2026-09-13, MEDIA_STORAGE_TIERING §9.4
# marche 3) : `speaker_wav` arrive TOUJOURS résolu de Django (`common/tts/voice_refs.
# speaker_wav_for`, décidé par la capacité du moteur). Les deux constantes de dossier et le
# résolveur `_get_speaker_wav` qui vivaient ici recomposaient à la main ce que Django résout
# déjà — contre-épreuve avant retrait : 37 presets, 0 écart de fichier entre les deux.

# ---------------------------------------------------------------------------
# Bootstrap PROCESS (pas backend) : torch.load + plafond CUDA
# ---------------------------------------------------------------------------
import sys as _sys
_sys.path.insert(0, str(PROJECT_DIR))

import torch

DEVICE = "cuda" if torch.cuda.is_available() else "cpu"

# Patch torch.load for PyTorch 2.6+ (weights_only=True default breaks Bark AND the
# pickled Coqui checkpoints) — process-wide, must precede ANY backend load().
os.environ.setdefault("TORCH_FORCE_WEIGHTS_ONLY_LOAD", "0")
_original_torch_load = torch.load
def _patched_torch_load(*args, **kwargs):
    if "weights_only" not in kwargs:
        kwargs["weights_only"] = False
    return _original_torch_load(*args, **kwargs)
torch.load = _patched_torch_load


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import Response, StreamingResponse
from starlette.concurrency import run_in_threadpool
from pydantic import BaseModel
from typing import Optional

app = FastAPI(title="WAMA TTS Service", version="1.0")

# ---------------------------------------------------------------------------
# Backends sous contrat (singletons par moteur) + moteur COURANT
# ---------------------------------------------------------------------------
from wama.common.backends.manager import BackendManager
from wama.synthesizer.backends import ENGINE_BACKENDS, engine_for_model, local_model_name

# Registre + singletons keep_loaded : BRIQUE COMMUNE (pas de dict maison).
_manager = BackendManager('tts')
_manager.register_many(ENGINE_BACKENDS)

_current_engine = None        # "coqui", "bark", "higgs", or "kokoro"
_current_model_name = None    # e.g. "xtts_v2", "bark", "higgs_audio", "kokoro"

# Service readiness flag: False while models are loading at startup
_service_ready = False
_service_ready_lock = threading.Lock()

#: Synthèses EN COURS (B1, 2026-09-20) — ce que le service DÉCLARE au gouverneur comme
#: « occupé » : tant qu'une voix est produite, il ne se décharge pas pour une demande de
#: libération, il le dit (le requérant attend). Le verrou `_engine_lock` ne suffit pas : un
#: résident est servi SANS le prendre (cf. `/tts`).
_synth_depth = 0
_synth_depth_lock = threading.Lock()
#: Moteurs préchargés au démarrage — ce que le service RESTAURE après s'être déchargé pour une
#: demande de libération (mêmes règles que le préchargement : seuls les `keep_resident`).
_PRELOAD: list = []


def _synth_begin():
    global _synth_depth
    with _synth_depth_lock:
        _synth_depth += 1
    try:
        from wama.common.services.resource_governor import mark_busy
        mark_busy()
    except Exception:
        pass


def _synth_end():
    global _synth_depth
    with _synth_depth_lock:
        _synth_depth = max(0, _synth_depth - 1)
        idle = _synth_depth == 0
    if idle:
        try:
            from wama.common.services.resource_governor import clear_busy
            clear_busy()
        except Exception:
            pass


def _is_busy() -> bool:
    with _synth_depth_lock:
        return _synth_depth > 0


def _unload_all_engines() -> int:
    """Se DÉCHARGER pour une demande de libération : TOUS les moteurs, résidents compris —
    c'est le seul chemin qui passe outre `keep_resident`, et il n'est emprunté que sur l'accord
    explicite d'un utilisateur transmis par le gouverneur. Rend le nombre de moteurs déchargés."""
    global _current_engine, _current_model_name
    from wama.common.backends.base import unload_live_backends
    with _engine_lock:
        n = unload_live_backends()
        _current_engine = None
        _current_model_name = None
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
    return n


def _preload_engines(names) -> None:
    """Précharge `names` (règles du démarrage) — appelé au démarrage ET pour la restauration."""
    for name in names:
        try:
            if _keep_resident(name):
                # Moteur temps réel : il reste résident (cf. _unload_current) et ne
                # devient PAS _current_engine — il coexiste avec le moteur courant.
                _backend(name).load()
                logger.info(f"{name} préchargé et résident")
            else:
                with _engine_lock:
                    _switch_model(name)
                logger.info(f"{name} préchargé")
        except Exception as e:
            logger.warning(
                f"Préchargement de {name} échoué — il sera chargé à la 1re demande : {e}",
                exc_info=True,
            )


def _restore_residents() -> None:
    """Après une libération : les moteurs temps réel déclarés reviennent (Kokoro pour
    l'assistant) ; un moteur lourd revient à la prochaine demande, comme d'habitude."""
    _preload_engines([n for n in _PRELOAD if _keep_resident(n)])

#: Verrou des MOTEURS (2026-09-14) — il englobe BASCULE + SYNTHÈSE. `/tts` est une fonction
#: synchrone qu'uvicorn exécute dans un pool de threads : sans lui, une requête qui basculait de
#: moteur déchargeait celui qu'une autre requête était en train d'utiliser (XTTS vidé en pleine
#: synthèse par une vocalisation de l'assistant — `_unload_current` ne garde que les résidents).
#: ⚠ Un moteur RÉSIDENT (temps réel, Kokoro) ne doit pas ATTENDRE derrière une longue synthèse
#: lourde : le client expirerait et Django retomberait sur son Kokoro en-process. S'il trouve le
#: verrou pris, il est servi SANS toucher au moteur courant ; s'il le trouve libre, il le prend
#: et garde le comportement historique (la bascule décharge le moteur lourd, la VRAM est rendue).
#: RLock : `_switch_model` peut être rappelé sous le verrou.
_engine_lock = threading.RLock()


def _backend(engine: str):
    """Instance singleton du backend d'un moteur (BackendManager commun)."""
    return _manager.get_backend(engine)


# ---------------------------------------------------------------------------
# Déclaration de VRAM au gouverneur de ressources
# ---------------------------------------------------------------------------
# Ce service est un PROCESS SÉPARÉ : son empreinte VRAM est invisible des workers
# Celery. La DÉCLARATION est désormais celle du contrat commun (enveloppes
# load/unload de BaseModelBackend : empreinte MESURÉE, une ligne par modèle) —
# l'ancienne ligne agrégée "tts-service" est REMPLACÉE, pas doublée. Ce qui reste
# ici est le BATTEMENT : une réservation expire (TTL 1 h, garde-fou anti process
# mort) alors que Kokoro est résident SANS LIMITE de durée — sans rafraîchissement,
# sa ligne disparaîtrait et le gouverneur recroirait cette VRAM libre.
# Depuis le 2026-09-14 le battement est la brique COMMUNE
# `base.start_reservation_heartbeat` : les workers Celery, qui n'en avaient pas, la
# partagent (leurs résidents sortaient du registre au bout d'une heure).


def _keep_resident(engine: str) -> bool:
    """Le moteur DÉCLARE-t-il servir le temps réel (→ jamais déchargé aux bascules) ?

    La politique était écrite ici en littéral (`_current_engine == "kokoro"`) : un
    second moteur temps réel — `kokoro-onnx`, mêmes poids servis par onnxruntime —
    aurait été déchargé à chaque bascule sans que rien ne le signale. Elle est
    désormais DÉCLARÉE par le backend (`TTSBackend.keep_resident`) et seulement LUE
    ici. Même geste que `composition` : la politique se déclare, le service l'exécute.
    """
    be = _manager.get_backend(engine) if engine else None
    return bool(getattr(be, "keep_resident", False))


def _resident_engines() -> list:
    """Moteurs déclarés résidents ET effectivement chargés (pour /health)."""
    loaded = []
    for key in ENGINE_BACKENDS:
        be = _manager.get_backend(key)
        if be is not None and getattr(be, "keep_resident", False) and be.is_loaded:
            loaded.append(key)
    return loaded


def _unload_current():
    """Unload whatever model is currently loaded and free GPU memory."""
    global _current_engine, _current_model_name

    if _keep_resident(_current_engine):
        # Moteur temps réel (Kokoro .pt/.onnx : ~82M) : on le GARDE résident pour
        # éviter le rechargement (thrash) à chaque bascule synthesizer↔assistant →
        # vocalisation instantanée. POLITIQUE du service : le backend `unload()`
        # décharge réellement, on ne l'appelle simplement pas.
        logger.info(f"{_current_engine} reste résident (warm) — pas de déchargement")
    elif _current_engine is not None:
        be = _manager.get_backend(_current_engine)
        if be is not None and be.is_loaded:
            logger.info(f"Unloading {_current_engine} model: {_current_model_name}")
            be.unload()   # l'enveloppe du contrat rend la ligne de registre VRAM

    _current_engine = None
    _current_model_name = None

    if torch.cuda.is_available():
        torch.cuda.empty_cache()
        logger.info("GPU cache cleared")


def _switch_model(model_name: str, declared_engine: str | None = None):
    """Switch to the requested model, unloading the current one first."""
    global _current_engine, _current_model_name

    if _current_model_name == model_name:
        logger.info(f"Model {model_name} already loaded, skipping")
        return

    _unload_current()

    engine = engine_for_model(model_name, declared_engine)
    # Le backend reçoit le nom LOCAL (sans le préfixe de source) : depuis la route F4b ②
    # (2026-09-01) l'app envoie la clé catalogue entière (`synthesizer:coqui-xtts`), que
    # `COQUI_MODEL_MAPPING` ne connaît pas — elle serait tombée dans le repli et Coqui aurait
    # reçu un identifiant inexistant. On conserve la clé ENTIÈRE dans `_current_model_name`
    # (c'est l'identité rapportée par /status et comparée à la demande suivante).
    _backend(engine).load(local_model_name(model_name))
    _current_engine = engine
    _current_model_name = model_name


# ---------------------------------------------------------------------------
# Request/Response models
# ---------------------------------------------------------------------------
class TTSRequest(BaseModel):
    text: str
    # ⚠ Le défaut était `"xtts_v2"`, un identifiant MORT depuis le renommage du 2026-08-18
    # (xtts_v2 → coqui-xtts) : une requête sans `model` demandait un moteur inexistant.
    model: str = "synthesizer:coqui-xtts"
    language: str = "fr"
    voice_preset: str = "default"
    speaker_wav: Optional[str] = None
    multi_speaker: bool = False
    scene_description: str = ""
    options: dict = {}
    #: Moteur DÉCLARÉ du modèle (`composition.runtime.engine` au catalogue), résolu côté
    #: Django et passé ici. C'est ce qui permet d'exécuter un modèle qu'aucune app ne déclare :
    #: son nom (`onnx-community/Kokoro-82M-v1.0-ONNX`) ne ressemble à aucun moteur, seul le
    #: catalogue sait que son moteur est `kokoro-onnx`. Ce service n'a pas Django — il ne peut
    #: pas aller le chercher lui-même. Absent → routage par le nom, comme avant.
    engine: Optional[str] = None


class LoadModelRequest(BaseModel):
    model: str
    engine: Optional[str] = None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@app.get("/health")
def health():
    gpu_mem = 0.0
    if torch.cuda.is_available():
        gpu_mem = torch.cuda.memory_allocated() / 1024**3

    with _service_ready_lock:
        ready = _service_ready

    kokoro = _manager.get_backend("kokoro")
    return {
        "status": "ok" if ready else "loading",
        "device": DEVICE,
        "loaded_model": _current_model_name,
        "engine": _current_engine,
        # Kokoro vit HORS de _current_engine : il est résident en permanence une fois
        # chargé (cf. _unload_current) et n'est donc pas « le modèle courant ». Sans
        # ce champ, /health affichait loaded_model=null alors que Kokoro était chaud —
        # impossible de vérifier le préchargement depuis l'extérieur.
        "kokoro_resident": kokoro.resident_langs() if kokoro else [],
        # Généralisation (2026-08-31) : `kokoro_resident` ne parlait que du moteur .pt
        # et de SES langues ; depuis que la résidence est DÉCLARÉE, plusieurs moteurs
        # peuvent être chauds (kokoro, kokoro-onnx…). Champ conservé pour ne rien
        # casser, complété par la vue générale.
        "resident_engines": _resident_engines(),
        # Reconnaissance de la parole (conversation de l'assistant) : chargée à la 1re phrase.
        "stt_model": _stt._current_model if (_stt is not None and _stt.is_loaded) else None,
        "gpu_memory_gb": round(gpu_mem, 2),
    }


def _synthesis_kwargs(req: "TTSRequest") -> dict:
    """Contrat d'appel uniforme : chaque backend consomme ce qui le concerne. La voix de
    référence vient RÉSOLUE de Django (voir l'en-tête) ; Bark n'en consomme pas — son mapping
    preset → locuteur est dans son backend. Le même pour le fichier entier et pour le flux."""
    return dict(
        text=req.text,
        # Nom LOCAL, comme au chargement — `CoquiBackend.process` réindexe
        # `COQUI_MODEL_MAPPING` avec cette valeur.
        model=local_model_name(req.model),
        language=req.language,
        voice_preset=req.voice_preset,
        speaker_wav=req.speaker_wav or None,
        multi_speaker=req.multi_speaker,
        scene_description=req.scene_description,
        options=req.options,
    )


def _synthesize(be, req: "TTSRequest") -> str:
    return be.synthesize(**_synthesis_kwargs(req))


def _require_ready() -> None:
    """Refuse requests while the service is still initialising so the caller can detect the
    "not ready" state and retry rather than blocking a GPU worker for the full model-loading time."""
    with _service_ready_lock:
        ready = _service_ready
    if not ready:
        raise HTTPException(
            status_code=503,
            detail={"status": "loading", "message": "TTS service is still loading, retry shortly"},
        )


def _take_engine(req: "TTSRequest"):
    """Le moteur qui dira la demande, et si le verrou des moteurs est TENU (l'appelant le rend après
    le dernier échantillon). Un moteur lourd ATTEND le verrou ; un résident le prend seulement s'il
    est libre — sinon, une synthèse lourde est en cours et le temps réel est servi sans bascule ni
    déchargement. Le même geste pour `/tts` et `/tts/stream`."""
    engine = engine_for_model(req.model, req.engine)
    holds_lock = _engine_lock.acquire(blocking=not _keep_resident(engine))
    try:
        if holds_lock:
            _switch_model(req.model, req.engine)
            return _backend(_current_engine), True
        be = _backend(engine)
        if not be.is_loaded:
            be.load(local_model_name(req.model))
        logger.info(f"{engine} servi pendant une synthèse lourde — moteur courant intact")
        return be, False
    except Exception:
        if holds_lock:
            _engine_lock.release()
        raise


@app.post("/tts")
def tts_endpoint(req: TTSRequest):
    """Generate audio from text. Returns raw WAV bytes."""
    _require_ready()

    try:
        _synth_begin()                    # occupé, déclaré au gouverneur (B1)
        try:
            be, holds_lock = _take_engine(req)
            try:
                wav_path = _synthesize(be, req)
            finally:
                if holds_lock:
                    _engine_lock.release()
        finally:
            _synth_end()

        # Read and return WAV bytes
        with open(wav_path, "rb") as f:
            wav_bytes = f.read()

        # Cleanup temp file
        try:
            os.remove(wav_path)
        except OSError:
            pass

        return Response(content=wav_bytes, media_type="audio/wav")

    except Exception as e:
        logger.error(f"TTS generation error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/tts/stream")
def tts_stream_endpoint(req: TTSRequest):
    """La même demande, rendue AU FIL DE L'EAU (2026-10-28, voix de l'assistant) : PCM 16 bits mono
    little-endian, la fréquence dans l'en-tête `X-Sample-Rate`. Le premier son est calculé AVANT
    la réponse (`TTSBackend.synthesize_stream`) — une erreur du moteur reste donc une erreur HTTP ;
    la suite part à mesure. Mêmes règles d'occupation que `/tts` : le verrou du moteur et l'état
    « occupé » déclaré au gouverneur sont tenus jusqu'au dernier morceau, ou jusqu'à l'abandon du
    flux par l'appelant (qui arrête le calcul)."""
    from wama.common.backends.tts_base import to_int16
    _require_ready()
    _synth_begin()
    holds_lock = False
    try:
        be, holds_lock = _take_engine(req)
        rate, chunks = be.synthesize_stream(**_synthesis_kwargs(req))
    except Exception as e:
        if holds_lock:
            _engine_lock.release()
        _synth_end()
        logger.error(f"TTS stream error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

    def pcm16():
        try:
            for chunk in chunks:
                yield to_int16(chunk).astype("<i2", copy=False).tobytes()
        except Exception as e:                # la réponse est partie : le flux s'arrête, dit ici
            logger.error(f"TTS stream interrompu : {e}", exc_info=True)
        finally:
            close = getattr(chunks, "close", None)
            if close:
                close()
            if holds_lock:
                _engine_lock.release()
            _synth_end()

    return StreamingResponse(pcm16(), media_type="audio/L16",
                             headers={"X-Sample-Rate": str(rate)})


# ---------------------------------------------------------------------------
# Reconnaissance de la parole — la CONVERSATION VOCALE de l'assistant (2026-10-10)
# ---------------------------------------------------------------------------
# Le service fait parler l'assistant ; il l'ÉCOUTE aussi, pour la même raison : un modèle
# chaud dans un process dédié, joint en quelques dixièmes de seconde. Une tâche Celery
# attendrait derrière le traitement GPU en cours (minutes), et un chargement dans gunicorn
# mettrait un Whisper par worker web. Whisper est chargé à la PREMIÈRE phrase entendue puis
# reste chaud ; une demande de libération du gouverneur le décharge comme les voix
# (`unload_live_backends` : c'est un backend sous contrat), et il revient à la phrase suivante.
_stt = None
#: Une transcription à la fois : CTranslate2 sur un seul modèle, et l'ordre des phrases compte.
_stt_lock = threading.Lock()
#: Inactivité après laquelle Whisper rend la carte. ⚠ MESURÉ le 2026-10-10 : large-v3 occupe
#: 4,1 Go réels, mais le gouverneur en RÉSERVE 10 (`WhisperBackend.recommended_vram_gb`, valeur
#: de repli : CTranslate2 alloue hors de PyTorch). Resté chargé, il ferait croire 10 Go pris aux
#: traitements lourds. Une conversation vient par rafales : on le garde chaud pendant, pas après.
STT_IDLE_UNLOAD_S = int(os.environ.get("WAMA_STT_IDLE_UNLOAD_S", "600"))
_stt_last_use = 0.0


def _stt_backend():
    global _stt
    if _stt is None:
        from wama.common.backends.whisper_backend import WhisperBackend
        _stt = WhisperBackend()
    return _stt


def _stt_idle_watch():
    """Décharge Whisper après `STT_IDLE_UNLOAD_S` sans transcription (thread de fond)."""
    import time
    while True:
        time.sleep(60)
        if _stt is None or not _stt.is_loaded or STT_IDLE_UNLOAD_S <= 0:
            continue
        if time.time() - _stt_last_use < STT_IDLE_UNLOAD_S:
            continue
        with _stt_lock:
            if _stt.is_loaded and time.time() - _stt_last_use >= STT_IDLE_UNLOAD_S:
                logger.info("Whisper inactif — déchargé (rend la carte)")
                _stt.unload()       # l'enveloppe du contrat rend la ligne de réservation VRAM


def _transcribe_clip(audio: bytes, suffix: str, language: str, model: str) -> dict:
    import tempfile
    import time
    global _stt_last_use
    _stt_last_use = time.time()
    tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
    try:
        tmp.write(audio)
        tmp.close()
        _synth_begin()                    # occupé, déclaré au gouverneur (même sens que /tts)
        try:
            with _stt_lock:
                be = _stt_backend()
                if not be.load(model):
                    raise RuntimeError(f"Whisper « {model} » ne se charge pas")
                # Filtre de parole ACTIF : sur un extrait sans voix, Whisper invente des phrases
                # (« Sous-titres réalisés par… ») ; le filtre les retire avant le décodage.
                result = be.transcribe(tmp.name, language=language or None,
                                       vad_filter=True, enable_timestamps=False)
        finally:
            _synth_end()
        _stt_last_use = time.time()
        if not result.success:
            raise RuntimeError(result.error or "transcription échouée")
        return {"text": result.text, "language": result.language}
    finally:
        try:
            os.remove(tmp.name)
        except OSError:
            pass


@app.post("/stt")
async def stt_endpoint(request: Request, language: str = "", model: str = "large-v3"):
    """Transcrit un extrait court (le CORPS de la requête : WAV, WebM…) → {text, language}.
    Corps brut plutôt qu'un formulaire : aucune dépendance de plus au service."""
    audio = await request.body()
    if not audio:
        raise HTTPException(status_code=400, detail="audio vide")
    content_type = (request.headers.get("content-type") or "").lower()
    suffix = ".webm" if "webm" in content_type else ".ogg" if "ogg" in content_type else ".wav"
    try:
        return await run_in_threadpool(_transcribe_clip, audio, suffix, language, model)
    except Exception as e:
        logger.error(f"STT error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


def _speech_only_clip(audio: bytes, suffix: str) -> bytes:
    """Les seuls passages PARLÉS de l'extrait (WAV 16 kHz mono), b'' s'il n'y en a aucun.

    Pour l'écoute par un modèle DISTANT (2026-10-11) : Silero tourne ici, sur le processeur,
    parce qu'importer `faster_whisper` coûte 52 à 66 s (mesuré : `ctranslate2` importe
    `transformers`, lu depuis /mnt/d), payées une fois par ce service au lieu d'une fois par
    worker gunicorn. Même détecteur, mêmes réglages que le filtre d'Albert : c'est SA méthode.
    """
    import shutil
    import tempfile
    from wama.common.backends.albert_asr_backend import AlbertTranscriptionBackend
    tmp_dir = tempfile.mkdtemp(prefix="wama_vad_")
    try:
        src = os.path.join(tmp_dir, "clip" + suffix)
        with open(src, "wb") as fh:
            fh.write(audio)
        backend = AlbertTranscriptionBackend()
        speech, _ = backend._speech_only(backend._upload_path(src, tmp_dir), tmp_dir)
        if speech is None:
            return b""
        with open(speech, "rb") as fh:
            return fh.read()
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def _vad_warm_up():
    """Importe le filtre de parole au démarrage (fond) : la 1ʳᵉ phrase distante n'attend pas.
    Et l'extracteur de la fin de tour : son premier avis arriverait sinon après la pause."""
    try:
        import faster_whisper.vad  # noqa: F401
        logger.info("Filtre de parole (Silero) prêt")
    except Exception as exc:
        logger.warning(f"Filtre de parole indisponible : {exc}")
    try:
        _turn_features()
    except Exception as exc:
        logger.warning(f"Fin de tour indisponible : {exc}")


# ── Fin de tour (Smart Turn, 2026-10-28) ─────────────────────────────────────
# La personne a-t-elle FINI sa phrase ? Juge sur les 8 dernières secondes, sur le processeur
# (aucune VRAM, ~12 ms selon l'éditeur). Django donne le chemin du modèle installé par la route
# (`wama/common/tts/end_of_turn.py`) ; le service ne cherche dans aucun dossier.
TURN_SECONDS = 8
_turn_sessions = {}
_turn_extractor = None
_turn_lock = threading.Lock()


def _turn_features():
    global _turn_extractor
    if _turn_extractor is None:
        from transformers import WhisperFeatureExtractor
        _turn_extractor = WhisperFeatureExtractor(chunk_length=TURN_SECONDS)
    return _turn_extractor


def _turn_session(model_path: str):
    with _turn_lock:
        session = _turn_sessions.get(model_path)
        if session is None:
            import onnxruntime as ort
            from wama.common.utils.onnx_utils import onnx_providers
            options = ort.SessionOptions()
            options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
            options.inter_op_num_threads = 1
            options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
            # Processeur SEUL : la variante int8 est faite pour lui, et la carte reste à la voix.
            session = ort.InferenceSession(model_path, sess_options=options,
                                           providers=onnx_providers(cpu_only=True))
            _turn_sessions[model_path] = session
        return session


def _end_of_turn_clip(audio: bytes, model_path: str) -> float:
    """Probabilité que le tour soit FINI — la recette de l'éditeur (`inference.py` du dépôt
    pipecat-ai/smart-turn) : la FIN de l'extrait gardée, complétée par du silence au début."""
    import io
    import numpy as np
    import soundfile as sf
    wave, rate = sf.read(io.BytesIO(audio), dtype="float32")
    if wave.ndim > 1:
        wave = wave.mean(axis=1)
    if rate != 16000:
        raise ValueError(f"extrait à {rate} Hz, 16 000 attendus")
    size = TURN_SECONDS * 16000
    wave = wave[-size:]
    if len(wave) < size:
        wave = np.pad(wave, (size - len(wave), 0))
    features = _turn_features()(wave, sampling_rate=16000, return_tensors="np",
                                padding="max_length", max_length=size, truncation=True,
                                do_normalize=True)
    inputs = features.input_features.squeeze(0).astype(np.float32)[None, ...]
    outputs = _turn_session(model_path).run(None, {"input_features": inputs})
    return float(outputs[0].reshape(-1)[0])


@app.post("/end-of-turn")
async def end_of_turn_endpoint(request: Request, model_path: str = ""):
    """Corps : la phrase dite jusqu'ici (WAV 16 kHz mono) → {probability} du tour FINI."""
    audio = await request.body()
    if not audio or not model_path:
        raise HTTPException(status_code=400, detail="audio ou modèle manquant")
    if not os.path.isfile(model_path):
        raise HTTPException(status_code=404, detail="modèle de fin de tour absent")
    try:
        probability = await run_in_threadpool(_end_of_turn_clip, audio, model_path)
    except Exception as e:
        logger.error(f"Fin de tour : {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
    return {"probability": probability}


@app.post("/speech-only")
async def speech_only_endpoint(request: Request):
    """Corps : un extrait audio → corps : ses passages parlés en WAV ; 204 s'il n'y en a pas."""
    audio = await request.body()
    if not audio:
        raise HTTPException(status_code=400, detail="audio vide")
    content_type = (request.headers.get("content-type") or "").lower()
    suffix = ".webm" if "webm" in content_type else ".ogg" if "ogg" in content_type else ".wav"
    try:
        speech = await run_in_threadpool(_speech_only_clip, audio, suffix)
    except Exception as e:
        logger.error(f"VAD error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
    if not speech:
        return Response(status_code=204)
    return Response(content=speech, media_type="audio/wav")


@app.post("/load-model")
def load_model_endpoint(req: LoadModelRequest):
    """Pre-load a model (for warming up)."""
    try:
        with _engine_lock:
            _switch_model(req.model, req.engine)
        return {
            "status": "loaded",
            "model": _current_model_name,
            "engine": _current_engine,
        }
    except Exception as e:
        logger.error(f"Model load error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# Startup – préchargement sélectif
# ---------------------------------------------------------------------------
@app.on_event("startup")
async def startup():
    global _service_ready

    logger.info("=== TTS Service starting ===")
    logger.info(f"Device: {DEVICE}")

    # Gouverneur de ressources — ce service est un process SÉPARÉ (uvicorn:8001)
    # qui détient de la VRAM hors du verrou Celery `gpu`. Sans ce câblage il
    # restait l'angle mort du dispositif : ni plafonné, ni visible du reclaim
    # inter-app (constat du 29/07/2026).
    try:
        from wama.common.services.resource_governor import configure_cuda_process
        configure_cuda_process()
        # `configure_cuda_process` BORNE ce process ; la déclaration d'empreinte est
        # celle du contrat de backend (une ligne par modèle, mesurée au chargement).
        # Le battement maintient ces lignes vivantes malgré le TTL — sans quoi un
        # modèle résident redeviendrait invisible au bout d'une heure.
        from wama.common.backends.base import start_reservation_heartbeat
        start_reservation_heartbeat()
        # Le service se DÉCLARE tenant (B1, 2026-09-20) : occupé tant qu'il synthétise, se
        # décharge — résidents compris — pour une demande de libération accordée par un
        # utilisateur, restaure ses temps réel une fois la demande close. Le service n'a
        # toujours aucun endpoint de déchargement : c'est le gouverneur qui parle, par Redis.
        from wama.common.services.resource_governor import Tenant, start_release_listener
        start_release_listener(Tenant("tts-service", unload=_unload_all_engines,
                                      restore=_restore_residents, is_busy=_is_busy))
    except Exception as exc:
        logger.warning(f"[TTS] gouverneur de ressources non initialisé : {exc}")

    # Whisper de la conversation vocale : rendu à la carte après inactivité (voir `/stt`).
    threading.Thread(target=_stt_idle_watch, daemon=True, name="stt-idle").start()
    # Filtre de parole de l'écoute distante (`/speech-only`) : son import est long, on le paie ici.
    threading.Thread(target=_vad_warm_up, daemon=True, name="vad-warm-up").start()

    # ── Préchargement SÉLECTIF ────────────────────────────────────────────────
    # TTS_PRELOAD = liste d'engines séparés par des virgules (défaut : "kokoro").
    #   kokoro-onnx → MÊMES poids que kokoro, servis par onnxruntime. **Chargement
    #             MESURÉ à 3,3 s** (session ONNX + voix, imports compris) : c'est lui
    #             qu'on précharge depuis le 2026-08-31 (doctrine inférence-first).
    #   kokoro  → 82M .pt. ⚠ « quasi instantané / coût de démarrage nul » était FAUX,
    #             et personne ne l'avait mesuré : le journal du service du 2026-08-31
    #             donne **87,9 s** entre « préchargement en tâche de fond → kokoro »
    #             (15:39:49,918) et « Kokoro (FR) préchargé et résident » (15:41:17,844)
    #             — un coût que `start_wama_prod.sh` ATTEND (il boucle sur /health).
    #   xtts_v2 → plusieurs Go et des dizaines de secondes : VOLONTAIREMENT hors du
    #             chemin de démarrage, il se charge à la 1re demande explicite.
    #   vide / "none" → aucun préchargement.
    # TTS_SKIP_PRELOAD=1 reste honoré (== TTS_PRELOAD=none) pour le développement.
    #
    # ⚠ Ce préchargement n'a sa place ICI que parce que ce service est un process
    # UNIQUE (uvicorn --workers 1). Raisons RE-VÉRIFIÉES le 2026-09-14 : N workers
    # préchargeraient N fois, le « moteur courant » et sa bascule n'existent qu'à l'intérieur
    # d'un process (N moteurs lourds possibles sur la même carte), et les verrous
    # (`_engine_lock`, génération Higgs) ne sérialisent rien entre process. La cause autrefois
    # citée ici — `HF_HUB_CACHE` muté en concurrence — n'existe plus (0 mutation,
    # `wama/common/tests/tests_hf_cache_routing.py`) ; la course d'imports `accelerate` venait d'un
    # thread lancé dans Django (cf. wama/views.py, note sous _get_kokoro), pas de ce service.
    # Ne pas réintroduire de préchargement dans un process multi-worker.
    if os.environ.get("TTS_SKIP_PRELOAD", "0") == "1":
        preload = []
    else:
        raw = os.environ.get("TTS_PRELOAD", "kokoro").strip().lower()
        preload = [] if raw in ("", "none", "0") else [p.strip() for p in raw.split(",") if p.strip()]

    _PRELOAD[:] = preload             # ce que la restauration après libération recharge
    if not preload:
        with _service_ready_lock:
            _service_ready = True
        logger.info("Aucun préchargement demandé — les modèles se chargeront à la 1re requête")
        return

    # Préchargement en tâche de fond pour qu'uvicorn serve /health immédiatement :
    # il répond {"status": "loading"} jusqu'à _service_ready = True.
    def _background_preload():
        global _service_ready
        _preload_engines(preload)
        with _service_ready_lock:
            _service_ready = True
        logger.info("Préchargement terminé — service prêt")

    t = threading.Thread(target=_background_preload, daemon=True, name="tts-preload")
    t.start()
    logger.info(f"Startup: préchargement en tâche de fond → {', '.join(preload)}")
