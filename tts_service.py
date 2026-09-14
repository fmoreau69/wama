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

Usage:
    python -m uvicorn tts_service:app --host 0.0.0.0 --port 8001 --workers 1
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
PROJECT_DIR = Path(__file__).parent

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
from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
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
    vivants = []
    for cle in ENGINE_BACKENDS:
        be = _manager.get_backend(cle)
        if be is not None and getattr(be, "keep_resident", False) and be.is_loaded:
            vivants.append(cle)
    return vivants


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


def _switch_model(model_name: str, engine_declare: str | None = None):
    """Switch to the requested model, unloading the current one first."""
    global _current_engine, _current_model_name

    if _current_model_name == model_name:
        logger.info(f"Model {model_name} already loaded, skipping")
        return

    _unload_current()

    engine = engine_for_model(model_name, engine_declare)
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
        "gpu_memory_gb": round(gpu_mem, 2),
    }


def _synthesize(be, req: "TTSRequest") -> str:
    """Contrat d'appel uniforme : chaque backend consomme ce qui le concerne. La voix de
    référence vient RÉSOLUE de Django (voir l'en-tête) ; Bark n'en consomme pas — son mapping
    preset → locuteur est dans son backend."""
    return be.synthesize(
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


@app.post("/tts")
def tts_endpoint(req: TTSRequest):
    """Generate audio from text. Returns raw WAV bytes."""
    # Refuse requests while the service is still initialising so the caller
    # can detect the "not ready" state and retry rather than blocking a GPU
    # worker for the full model-loading time.
    with _service_ready_lock:
        ready = _service_ready
    if not ready:
        raise HTTPException(
            status_code=503,
            detail={"status": "loading", "message": "TTS service is still loading, retry shortly"},
        )

    try:
        engine = engine_for_model(req.model, req.engine)
        # Un moteur lourd ATTEND le verrou ; un résident le prend seulement s'il est libre.
        tient = _engine_lock.acquire(blocking=not _keep_resident(engine))
        if tient:
            try:
                _switch_model(req.model, req.engine)
                wav_path = _synthesize(_backend(_current_engine), req)
            finally:
                _engine_lock.release()
        else:
            # Synthèse lourde en cours : le temps réel est servi sans bascule ni déchargement.
            be = _backend(engine)
            if not be.is_loaded:
                be.load(local_model_name(req.model))
            logger.info(f"{engine} servi pendant une synthèse lourde — moteur courant intact")
            wav_path = _synthesize(be, req)

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
    except Exception as exc:
        logger.warning(f"[TTS] gouverneur de ressources non initialisé : {exc}")

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
    # `wama/common/tests_hf_cache_routing.py`) ; la course d'imports `accelerate` venait d'un
    # thread lancé dans Django (cf. wama/views.py, note sous _get_kokoro), pas de ce service.
    # Ne pas réintroduire de préchargement dans un process multi-worker.
    if os.environ.get("TTS_SKIP_PRELOAD", "0") == "1":
        preload = []
    else:
        raw = os.environ.get("TTS_PRELOAD", "kokoro").strip().lower()
        preload = [] if raw in ("", "none", "0") else [p.strip() for p in raw.split(",") if p.strip()]

    if not preload:
        with _service_ready_lock:
            _service_ready = True
        logger.info("Aucun préchargement demandé — les modèles se chargeront à la 1re requête")
        return

    # Préchargement en tâche de fond pour qu'uvicorn serve /health immédiatement :
    # il répond {"status": "loading"} jusqu'à _service_ready = True.
    def _background_preload():
        global _service_ready
        for name in preload:
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
        with _service_ready_lock:
            _service_ready = True
        logger.info("Préchargement terminé — service prêt")

    t = threading.Thread(target=_background_preload, daemon=True, name="tts-preload")
    t.start()
    logger.info(f"Startup: préchargement en tâche de fond → {', '.join(preload)}")
