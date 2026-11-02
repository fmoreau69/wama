"""
WAMA — service de CONFIDENTIALITÉ (FastAPI) : détecter les données personnelles d'un texte.

Le pendant des services TTS (`wama/common/tts/service.py`) et de vectorisation
(`wama/common/vectors/service.py`), né dans son paquet (2026-10-28, ROADMAP §16.4bis) : un process
à part, que Django, les workers et l'assistant appellent par `privacy/service_client.py`. Pourquoi
un service : les détecteurs de l'union sont des modèles (300 Mo à 1,2 Go chacun) que la porte de
l'assistant interroge à chaque envoi vers un modèle distant — les charger dans chaque process
gunicorn coûterait autant de fois la mémoire. Les appels ~0,2 s une fois chargé.

PRÉCHAUFFÉ AU DÉMARRAGE (2026-11-02) : le premier appel payait le chargement — « ~30 s » le
28/10, 3 min mesurées le 2026-11-02 sur le premier document de l'Anonymizer après une relance
(import de Presidio 125 s à froid sur `/mnt/d`, dont ~45 s de TensorFlow, puis les détecteurs sur la
carte) : le client abandonnait à 180 s et la tâche échouait. Comme le service de voix : les
analyseurs des langues de base et leurs détecteurs se chargent en tâche de fond au démarrage,
`/health` dit « loading » jusque-là, `/detect` répond 503 « loading » — le client le dit
(`PrivacyServiceLoading`), une tâche ATTEND (`ServiceNotReady`), la porte de l'assistant refuse.
`USE_TF=0` à l'amorce : la pile de détection n'emploie pas TensorFlow, que `transformers` importe
dès qu'il est installé (import de Presidio 80 s au lieu de 125, mesuré).

À la différence de ses deux aînés, ce service INITIALISE Django : l'union se compose au CATALOGUE
(les modèles `pii-detection` installés et leurs langues) et chaque détecteur se charge par la porte
commune `backend_instance_for_key` — qui déclare son empreinte au gouverneur. L'occultation n'a
aucun modèle : le client la fait sur place.

Usage (depuis la racine du dépôt) :
    python -m uvicorn wama.common.privacy.service:app --host 127.0.0.1 --port 8003 --workers 1

Boucle locale SEULE : le service n'a pas d'authentification — il voit des textes personnels.
`--workers 1` : les détecteurs restent chargés dans UN process.
"""
import logging
import os
import sys
import threading
from pathlib import Path
from typing import List, Optional

logging.basicConfig(level=logging.INFO, format="%(asctime)s [PRIVACY] %(levelname)s %(message)s")
logger = logging.getLogger("privacy_service")

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))   # racine du dépôt
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'wama.settings')
os.environ.setdefault('USE_TF', '0')        # avant tout import de `transformers` (voir l'en-tête)

import django  # noqa: E402

django.setup()

from fastapi import FastAPI, HTTPException  # noqa: E402
from pydantic import BaseModel  # noqa: E402

from wama.common.privacy import engine  # noqa: E402

app = FastAPI(title="WAMA Privacy Service", version="1.0")

#: Posé quand le préchauffage est fini (réussi ou non : un détecteur qui ne se charge pas est NOMMÉ
#: à chaque détection, `unavailable`, il ne bloque pas le service).
_ready = threading.Event()


def _warm_up() -> None:
    """Les analyseurs des langues de base, leurs détecteurs CHARGÉS : une phrase témoin par
    langue, l'une après l'autre (jamais deux chargements d'un même modèle en même temps)."""
    try:
        for language in engine.BASE_LANGUAGES:
            engine.detect_segments(['WAMA'], language)
        logger.info("Préchauffage terminé — service prêt")
    except Exception:
        logger.exception("Préchauffage en échec — les détections diront ce qui manque")
    finally:
        _ready.set()


@app.on_event("startup")
def _startup() -> None:
    # En tâche de fond, pour qu'uvicorn serve /health aussitôt (« loading » jusque-là).
    threading.Thread(target=_warm_up, daemon=True, name='privacy-warm-up').start()


class DetectRequest(BaseModel):
    #: Le texte, en un ou plusieurs SEGMENTS (pages, paragraphes d'un document).
    segments: List[str]
    language: str = ''
    entities: Optional[List[str]] = None
    detectors: Optional[List[str]] = None
    threshold: Optional[float] = None


@app.get("/health")
def health():
    return {"status": "ok" if _ready.is_set() else "loading",
            "detectors": [key for key, _ in engine.installed_detectors()]}


@app.post("/detect")
def detect(req: DetectRequest):
    """Le document de détections des segments. Fonction SYNCHRONE : uvicorn l'exécute dans son
    pool de threads. Une erreur de détection est une ERREUR (500), jamais « rien trouvé » ; pendant le
    préchauffage, 503 « loading » (l'appelant attend ou refuse, il ne bloque pas 3 min)."""
    if not _ready.is_set():
        raise HTTPException(status_code=503, detail={"status": "loading",
                                                     "message": "service de confidentialité en chargement"})
    try:
        return engine.detect_segments(req.segments, req.language, entities=req.entities,
                                      detectors=req.detectors, threshold=req.threshold)
    except Exception as exc:
        logger.exception("détection en échec")
        raise HTTPException(status_code=500, detail=f"{type(exc).__name__}: {exc}")
