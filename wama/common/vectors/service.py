"""
WAMA — service de VECTORISATION (FastAPI). Doc : `WAMA_MEMORY.md §7sexies`.

Le pendant du service TTS (`wama/common/tts/service.py`) pour les embeddings : un process à part, que Django,
les workers Celery et les outils appellent par `wama/common/vectors/service_client.py`. Il exécute
le moteur commun (`wama/common/vectors/engine.py`) sur des entrées DÉJÀ préparées par le client
(textes, images en base64) ; il ne lit aucun fichier et ne connaît pas Django.

Ce qu'il ne fait PAS, et pourquoi :
  • il ne tient aucun poids — c'est Ollama qui charge les modèles d'embedding. La VRAM se demande
    donc au gouverneur par le CLIENT, par espace (`service_client.reserve`), pas ici ;
  • il n'écoute que la boucle locale : il n'a pas d'authentification. Une médiathèque distante
    passe par WAMA (connecteur + tâche d'indexation), jamais par ce port.

Usage (depuis la racine du dépôt) :
    python -m uvicorn wama.common.vectors.service:app --host 127.0.0.1 --port 8002 --workers 1

Domicile depuis le 2026-10-28 : ce fichier était `vector_service.py`, à la racine du dépôt (module
`vector_service:app`) ; il a rejoint son paquet, à côté de son client et de son moteur, comme le
service TTS (`wama/common/tts/service.py`).
"""
import logging
import sys
from pathlib import Path
from typing import Optional

logging.basicConfig(level=logging.INFO, format="%(asctime)s [VECTORS] %(levelname)s %(message)s")
logger = logging.getLogger("vector_service")

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))   # racine du dépôt

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from wama.common.vectors import engine
from wama.common.vectors.spaces import SPACES, get

app = FastAPI(title="WAMA Vector Service", version="1.0")


class EmbedRequest(BaseModel):
    space: str
    #: Entrées préparées par le client (`engine.prepare`) : un texte, ou `{"image": <base64>}`.
    inputs: list
    timeout: float = engine.TIMEOUT_S
    keep_alive: Optional[str] = None


@app.get("/health")
def health():
    return {"status": "ok", "spaces": sorted(SPACES)}


@app.get("/spaces")
def spaces():
    """Les espaces déclarés — ce qu'un appelant peut demander."""
    return [{"key": s.key, "label": s.label, "modalities": list(s.modalities), "model": s.model,
             "model_key": s.model_key, "dims": s.dims} for s in SPACES.values()]


@app.post("/embed")
def embed(req: EmbedRequest):
    """Vectorise un lot. Fonction SYNCHRONE : uvicorn l'exécute dans son pool de threads, l'appel
    au fournisseur ne bloque pas la boucle. `vectors` vide = fournisseur indisponible (le client
    dégrade) ; une entrée mal formée est une erreur de l'appelant (422)."""
    try:
        space = get(req.space)
        engine.check_inputs(space, req.inputs)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    vectors = engine.embed_inputs(space, req.inputs, timeout=req.timeout,
                                  keep_alive=req.keep_alive)
    return {"space": space.key, "model": space.model, "dims": space.dims, "vectors": vectors}
