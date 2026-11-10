"""
WAMA — service TENSORFLOW (FastAPI) : les modèles TensorFlow, sur la carte, dans un seul processus.

Délimité par son MOTEUR (décision de Fabien, 2026-11-09), pas par le visage. Ce qui le justifie :
TensorFlow ne rend sa mémoire de carte qu'à la fin de son processus, et ne cohabite pas avec PyTorch
sur la carte (doctrine `USE_TF=0`, `scripts/wama_services.sh`). Ce processus charge donc TensorFlow
SEUL, jamais PyTorch. Premiers occupants : DeepFace et FER (`common/backends/`). Patron : le service
de confidentialité (`common/privacy/service.py`) ; le détail, `WAMA_MANIFEST_SPEC §7.1`.

LIBÉRER, C'EST S'ARRÊTER. Vider le cache de Keras ne rend rien à la carte (mesuré le 2026-11-08 :
compteur de TensorFlow à 0, carte toujours à +4,6 Go). Quand le gouverneur demande la carte et que le
service tient quelque chose dessus, il rend ses lignes au registre, note que l'arrêt est VOULU et
sort (`_stop_for_the_card`). La surveillance le relance à la demande du premier appelant
(`scripts/worker_watchdog.sh`, `common/utils/service_supervision.py`) ; d'ici là, l'appelant fait le
même travail chez lui, sur le processeur (`service_client`).

AU DÉMARRAGE il préchauffe l'expression seule ; l'âge et le genre viennent à la première demande
(décision du 2026-11-08). Relancé pendant qu'une tâche réclame la carte, il attend sans rien y
charger : l'état reste `loading` et les appelants font sans lui. `/health` dit l'état, `/run` répond
503 tant qu'il n'est pas prêt, ou quand la carte n'a pas la place d'un modèle à charger.

Usage (depuis la racine du dépôt) :
    python -m uvicorn wama.common.tensorflow_service.service:app --host 127.0.0.1 --port 8004 --workers 1

Boucle locale SEULE : aucune authentification, il voit des images de visages. `--workers 1` : deux
processus tiendraient deux fois les poids, sans jamais les rendre.
"""
import io
import json
import logging
import os
import sys
import threading
import time
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [TENSORFLOW] %(levelname)s %(message)s")
logger = logging.getLogger("tensorflow_service")

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))   # racine du dépôt
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'wama.settings')
os.environ.setdefault('USE_TF', '0')        # transformers n'importe pas TensorFlow de son côté

import django  # noqa: E402

django.setup()

from fastapi import Body, FastAPI, HTTPException, Query  # noqa: E402

from wama.common.backends.tensorflow_base import TENSORFLOW_SERVICE  # noqa: E402
from wama.common.tensorflow_service import engine, runtime  # noqa: E402

app = FastAPI(title="WAMA TensorFlow Service", version="1.0")

#: Ce que le service préchauffe : (tâche, moteur, modèle).
WARM_UP = ('face-analysis', 'deepface', 'deepface-expression')

#: Attente entre deux regards sur la carte, quand une demande de libération la tient.
CARD_POLL_S = 5.0
#: Le temps que l'acquittement parte (`resource_governor.serve_release_requests`) avant de sortir.
STOP_DELAY_S = 1.0

_ready = threading.Event()
_loading = threading.Event()
_stopping = threading.Event()
_running = 0
_running_lock = threading.Lock()


def _is_busy() -> bool:
    """Au travail : il charge, il répond, ou il a servi depuis moins d'une minute (un flux d'images
    continue, `resource_governor.busy_tenants`)."""
    if _loading.is_set() or _running > 0:
        return True
    from wama.common.services import resource_governor as gov
    return gov.tenant_id() in gov.busy_tenants()


def _on_card_backends() -> list:
    """Les backends chargés qui tiennent de la carte (FER, sur le processeur, n'en est pas)."""
    from wama.common.backends.base import _LIVE_BACKENDS
    return [b for b in list(_LIVE_BACKENDS) if b.is_loaded and b.recommended_vram_gb]


def _leave() -> None:
    """Le drapeau juste avant la sortie : posé plus tôt, un passage de la surveillance qui voit le
    processus encore vivant l'effacerait, et l'arrêt voulu se lirait comme une panne."""
    from wama.common.utils.service_supervision import note_stopped_on_purpose
    note_stopped_on_purpose(TENSORFLOW_SERVICE)
    os._exit(0)


def _stop_for_the_card() -> int:
    """Le déchargement du tenant : rend ses lignes et sort. Rien sur la carte, rien à faire."""
    held = _on_card_backends()
    if not held:
        return 0
    _stopping.set()
    # La boucle commune : un déchargement qui échoue n'arrête ni les suivants ni la sortie du processus
    # (« stopping » à vie, la surveillance le verrait vivant et ne le relancerait pas).
    from wama.common.backends.base import unload_live_backends
    unload_live_backends()
    logger.info('Arrêt demandé par le gouverneur : %d modèle(s) sur la carte', len(held))
    threading.Timer(STOP_DELAY_S, _leave).start()
    return len(held)


def _card_can_take(backend) -> bool:
    """Le modèle tient-il sur ce que la carte a de libre ? Sa place est déclarée (recalée sur la mesure,
    `recommended_vram_gb`), moins ce que les modèles déjà chargés ont réservé : TensorFlow garde une
    réserve commune, que le suivant réutilise. Carte illisible, on ne bloque pas."""
    from wama.common.services.resource_governor import card_free_gb
    free = card_free_gb()
    held = sum(loaded.recommended_vram_gb for loaded in _on_card_backends())
    return free is None or free >= (backend.recommended_vram_gb or 0) - held


def _release_requested() -> bool:
    """Une tâche réclame-t-elle la carte en ce moment ? (Hors demandes ciblées sur un modèle.)"""
    from wama.common.services import resource_governor as gov
    return any(not line.get('models') for line in gov.pending_release_requests().values())


def _warm_up() -> None:
    try:
        runtime.tensorflow()
        task, name, model_id = WARM_UP
        backend = engine.backend(task, name, model_id)
        while runtime.on_the_card() and (_release_requested() or not _card_can_take(backend)):
            time.sleep(CARD_POLL_S)
        _loading.set()
        backend.ensure_loaded(model_id)
        logger.info('Préchauffage terminé — service prêt')
    except Exception:
        logger.exception('Préchauffage en échec — chaque demande dira ce qui manque')
    finally:
        _loading.clear()
        _ready.set()


@app.on_event("startup")
def _startup() -> None:
    runtime.use_the_card()
    # En tâche de fond, pour qu'uvicorn serve /health aussitôt (« loading » jusque-là).
    threading.Thread(target=_warm_up, daemon=True, name='tensorflow-warm-up').start()
    try:
        from wama.common.services.resource_governor import Tenant, start_release_listener
        start_release_listener(Tenant(TENSORFLOW_SERVICE, unload=_stop_for_the_card, is_busy=_is_busy,
                                      unload_model=lambda _key: _stop_for_the_card() > 0))
    except Exception:
        logger.warning('gouverneur de ressources non initialisé', exc_info=True)


def _status() -> str:
    if _stopping.is_set():
        return 'stopping'
    return 'ok' if _ready.is_set() else 'loading'


@app.get("/health")
def health():
    return {'status': _status(), 'on_card': runtime.on_the_card(),
            'torch_loaded': 'torch' in sys.modules}


def _unavailable(status: str, message: str) -> HTTPException:
    return HTTPException(status_code=503, detail={'status': status, 'message': message})


@app.post("/run")
def run(params: str = Query(...), body: bytes = Body(..., media_type='application/octet-stream')):
    """Une demande : `params` en JSON (`task`, `engine`, `models`, `options`), l'image en `.npy`.
    Fonction SYNCHRONE : uvicorn l'exécute dans son pool de threads. 503 = fais-le sans moi, l'appelant
    se replie ; une erreur d'analyse est une ERREUR (500), jamais « pas de visage »."""
    import numpy as np
    global _running
    status = _status()
    if status != 'ok':
        raise _unavailable(status, 'service TensorFlow indisponible pour le moment')
    request = json.loads(params)
    task, name, models = request['task'], request['engine'], request['models']
    with _running_lock:
        _running += 1
    try:
        if runtime.on_the_card():
            for model_id in models:
                backend = engine.backend(task, name, model_id)
                if not backend.is_loaded and not _card_can_take(backend):
                    raise _unavailable('no_room', f'la carte n\'a pas la place de « {model_id} »')
        image = np.load(io.BytesIO(body), allow_pickle=False)
        return {'result': engine.run(task, name, models, image, request.get('options'))}
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception('demande en échec')
        raise HTTPException(status_code=500, detail=f'{type(exc).__name__}: {exc}')
    finally:
        with _running_lock:
            _running -= 1
