"""
WAMA — service de CONFIDENTIALITÉ (FastAPI) : détecter les données personnelles d'un texte.

Le pendant des services TTS (`wama/common/tts/service.py`) et de vectorisation
(`wama/common/vectors/service.py`), né dans son paquet (2026-10-28, ROADMAP §16.4bis) : un process
à part, que Django, les workers et l'assistant appellent par `privacy/service_client.py`. Pourquoi
un service : les détecteurs de l'union sont des modèles (300 Mo à 1,2 Go chacun) que la porte de
l'assistant interroge à chaque envoi vers un modèle distant — les charger dans chaque process
gunicorn coûterait autant de fois la mémoire. Le premier appel paie le chargement (~30 s mesurés),
les suivants ~0,2 s.

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
from pathlib import Path
from typing import List, Optional

logging.basicConfig(level=logging.INFO, format="%(asctime)s [PRIVACY] %(levelname)s %(message)s")
logger = logging.getLogger("privacy_service")

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))   # racine du dépôt
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'wama.settings')

import django  # noqa: E402

django.setup()

from fastapi import FastAPI, HTTPException  # noqa: E402
from pydantic import BaseModel  # noqa: E402

from wama.common.privacy import engine  # noqa: E402

app = FastAPI(title="WAMA Privacy Service", version="1.0")


class DetectRequest(BaseModel):
    #: Le texte, en un ou plusieurs SEGMENTS (pages, paragraphes d'un document).
    segments: List[str]
    language: str = ''
    entities: Optional[List[str]] = None
    detectors: Optional[List[str]] = None
    threshold: Optional[float] = None


@app.get("/health")
def health():
    return {"status": "ok", "detectors": [key for key, _ in engine.installed_detectors()]}


@app.post("/detect")
def detect(req: DetectRequest):
    """Le document de détections des segments. Fonction SYNCHRONE : uvicorn l'exécute dans son
    pool de threads. Une erreur de détection est une ERREUR (500), jamais « rien trouvé »."""
    try:
        return engine.detect_segments(req.segments, req.language, entities=req.entities,
                                      detectors=req.detectors, threshold=req.threshold)
    except Exception as exc:
        logger.exception("détection en échec")
        raise HTTPException(status_code=500, detail=f"{type(exc).__name__}: {exc}")
