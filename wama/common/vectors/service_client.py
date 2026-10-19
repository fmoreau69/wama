"""
Client COMMUN du service de vectorisation (`vector_service.py`, FastAPI, uvicorn 127.0.0.1:8002).
Doc : `WAMA_MEMORY.md §7sexies`. Même patron que `common/tts/service_client.py` : tout le monde
vectorise par ici — le RAG (`memory/embed.py`), l'indexation des médias, le Describer.

Ce qui se passe à l'appel : les entrées sont PRÉPARÉES ici (une image devient un JPEG réduit en
base64, la requête reçoit le préfixe de son espace), puis envoyées au service. Service éteint
(pas encore relancé, arrêté) ⇒ le MÊME moteur s'exécute dans ce process : rien ne casse, on perd
seulement le déport. Délai dépassé ⇒ `[]` (dégrader, jamais échouer : `engine`).

La VRAM se demande ICI, au gouverneur, par espace — le service ne tient aucun poids (Ollama les
tient), il n'a donc rien à déclarer lui-même.

Importable sans Django initialisé : l'adresse du service est résolue à l'appel.
"""
from __future__ import annotations

import logging

from . import engine
from .spaces import VectorSpace, get

logger = logging.getLogger(__name__)

TIMEOUT_S = engine.TIMEOUT_S


def service_url() -> str:
    from wama.common.external_sources import base_url
    return base_url('vector_service')


def embed(space_key: str, items, *, query: bool = False, timeout: float = TIMEOUT_S,
          keep_alive: str | None = None) -> list:
    """Les vecteurs de `items` dans l'espace `space_key` (même ordre), ou `[]` si indisponible.

    Un item est un texte (`str`, `{'text': …}`) ou une image (`{'image': chemin | octets}`) ;
    `query=True` vectorise une REQUÊTE (préfixe de l'espace), sinon un document."""
    import requests

    from wama.common.external_sources import proxies_for

    space = get(space_key)
    inputs = engine.prepare(space, items, query=query)
    if not inputs:
        return []
    try:
        resp = requests.post(f'{service_url()}/embed',
                             json={'space': space.key, 'inputs': inputs,
                                   'timeout': timeout, 'keep_alive': keep_alive},
                             proxies=proxies_for('vector_service'),
                             timeout=(2, timeout + 5))       # (connexion, lecture)
    except requests.ConnectionError:
        logger.info('[vectors] service injoignable à %s — moteur exécuté dans ce process',
                    service_url())
        return engine.embed_inputs(space, inputs, timeout=timeout, keep_alive=keep_alive)
    except requests.Timeout:
        logger.warning('[vectors] service : délai dépassé (%s s) pour %s', timeout, space.key)
        return []
    if resp.status_code != 200:
        logger.warning('[vectors] service HTTP %s pour %s (%s)', resp.status_code, space.key,
                       resp.text[:160])
        return []
    return resp.json().get('vectors') or []


# ── Gouvernance de la VRAM, par espace ───────────────────────────────────────────────────

def owner(space: VectorSpace) -> str:
    """Détenteur déclaré au gouverneur. Convention `<qui>#<clé catalogue>` (`OWNER_MODEL_SEP`) :
    c'est ce qui permet à `resident_models()` de rattacher la réservation au modèle du catalogue."""
    return f'vectors-{space.key}#{space.model_key}'


def residency_allowed(space_key: str) -> tuple[bool, str]:
    """Demande au GOUVERNEUR s'il y a de la place pour garder le modèle de l'espace chargé.

    C'est lui qui arbitre : `effective_free_gb()` déduit ce que les AUTRES process ont réservé
    sans l'avoir encore alloué — un job imager qui s'apprête à prendre 16 Go est vu AVANT qu'il
    n'alloue. Gouverneur indisponible ⇒ refus : l'incertitude ne se résout jamais en occupant."""
    space = get(space_key)
    try:
        from wama.common.services.resource_governor import effective_free_gb

        free = effective_free_gb(exclude=owner(space))
    except Exception:
        return False, 'gouverneur indisponible'
    if free <= 0:
        return False, 'VRAM libre inconnue ou nulle'
    # Marge : rester résident ne doit jamais être la raison pour laquelle un traitement
    # utilisateur échoue à charger.
    if free < space.vram_gb * 3:
        return False, f'{free:.1f} Go libres — insuffisant pour {space.vram_gb:.1f} Go avec marge'
    return True, f'{free:.1f} Go libres'


def reserve(space_key: str, *, expires_in_s: float = None) -> bool:
    """Déclare la résidence au gouverneur, pour que les AUTRES process la voient. `expires_in_s` :
    la ligne expire avec la résidence qu'elle déclare, sans libération explicite."""
    space = get(space_key)
    try:
        from wama.common.services.resource_governor import mark_used, reserve_vram

        ok = reserve_vram(owner(space), space.vram_gb, expires_in_s=expires_in_s)
        mark_used(owner(space))   # horodate : `idle_models()` peut réclamer la place plus tard
        return ok
    except Exception:
        return False


def release(space_key: str) -> bool:
    """Retire la réservation. ⚠ COMPTABILITÉ SEULEMENT — toujours avec `unload` : libérer sans
    décharger laisserait le modèle en VRAM sans que personne ne le sache."""
    try:
        from wama.common.services.resource_governor import release_reservation

        return release_reservation(owner(get(space_key)))
    except Exception:
        return False


def unload(space_key: str) -> bool:
    """Décharge le modèle de l'espace tout de suite (`engine.unload`)."""
    return engine.unload(space_key)


def available(space_key: str) -> bool:
    """Le modèle de l'espace est-il installé chez un fournisseur — sans le charger."""
    return engine.available(space_key)
