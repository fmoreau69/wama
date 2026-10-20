"""
Client COMMUN du service de vectorisation (`vector_service.py`, FastAPI, uvicorn 127.0.0.1:8002).
Doc : `WAMA_MEMORY.md §7sexies`. Même patron que `common/tts/service_client.py` : tout le monde
vectorise par ici — le RAG (`memory/embed.py`), l'indexation des médias, le Describer.

Ce qui se passe à l'appel : les entrées sont PRÉPARÉES ici (une image devient un JPEG réduit en
base64, la requête reçoit le préfixe de son espace), puis envoyées au service. Service éteint
(pas encore relancé, arrêté) ⇒ le MÊME moteur s'exécute dans ce process : rien ne casse, on perd
seulement le déport. Délai dépassé ⇒ `[]` (dégrader, jamais échouer : `engine`).

La VRAM se demande ICI, au gouverneur, par espace — le service ne tient aucun poids (Ollama les
tient), il n'a donc rien à déclarer lui-même. Le besoin se lit au CATALOGUE (`need_gb`), et c'est
ici aussi qu'un chargement se MESURE pour l'y rendre (`_measured`) : le service n'a pas Django.

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
    space = get(space_key)
    inputs = engine.prepare(space, items, query=query)
    if not inputs:
        return []
    return _measured(space, keep_alive,
                     lambda: _embed_prepared(space, inputs, timeout=timeout, keep_alive=keep_alive))


def _measured(space: VectorSpace, keep_alive, call):
    """`call()`, sous la mesure du chargement d'Ollama (`ollama_host.measured_load`) — c'est ainsi
    que l'empreinte d'un espace atteint le catalogue (`need_gb`).

    La mesure reçoit la résidence EFFECTIVE de l'appel (celle du moteur quand l'appelant n'en
    pose pas) : à '0', Ollama a rendu le modèle avant qu'on relève, elle n'observe rien. Seul
    l'Ollama de cette machine se mesure."""
    if space.providers[:1] != ('ollama',):
        return call()
    from wama.common.utils.ollama_host import measured_load
    return measured_load(space.model, call,
                         keep_alive=engine.KEEP_ALIVE if keep_alive is None else keep_alive)


def _embed_prepared(space: VectorSpace, inputs, *, timeout: float, keep_alive) -> list:
    """L'appel au service, ou au même moteur dans ce process s'il ne répond pas."""
    import requests

    from wama.common.external_sources import proxies_for
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
    """Détenteur déclaré au gouverneur : la ligne de RÉSIDENCE de l'Ollama hôte pour ce modèle
    (`ollama_host_owner`), celle que `refresh_ollama_residency` rafraîchit et que
    `MemoryManager.unload_model` retire. Le modèle n'occupe la carte qu'une fois, où qu'on le
    demande : jusqu'au 2026-10-20 l'espace annonçait sous `vectors-<espace>#…`, et le même modèle
    comptait DEUX fois — dans la VRAM libre des autres, dans les résidents, dans les inactifs (et
    décharger l'un laissait l'autre en fantôme jusqu'à son expiration)."""
    from wama.common.services.resource_governor import ollama_host_owner
    from wama.common.utils.ollama_host import full_tag
    return ollama_host_owner(full_tag(space.model))


def need_gb(space: VectorSpace) -> float | None:
    """L'empreinte VRAM du modèle de l'espace, lue au CATALOGUE par la cascade commune
    (`auto_model.vram_needed_gb` : mesurée → source → déclarée → preset), ou None si personne ne
    sait. Un espace ne porte plus de chiffre : jusqu'au 2026-10-20 il déclarait sa mesure à côté
    de l'heuristique du catalogue (3,8 et 2,3 Go contre 2,5 et 1,3) ; la mesure du chargement
    (`_measured`) la rend désormais à la ligne de son modèle."""
    try:
        from wama.common.utils.auto_model import vram_needed_gb
    except Exception:
        return None
    return vram_needed_gb(space.model_key)


def residency_allowed(space_key: str) -> tuple[bool, str]:
    """Demande au GOUVERNEUR s'il y a de la place pour garder le modèle de l'espace chargé.

    C'est lui qui arbitre : `effective_free_gb()` déduit ce que les AUTRES process ont réservé
    sans l'avoir encore alloué — un job imager qui s'apprête à prendre 16 Go est vu AVANT qu'il
    n'alloue. Gouverneur indisponible, ou empreinte inconnue au catalogue ⇒ refus : l'incertitude
    ne se résout jamais en occupant."""
    space = get(space_key)
    need = need_gb(space)
    if not need:
        return False, f'empreinte de {space.model_key} inconnue au catalogue'
    try:
        from wama.common.services.resource_governor import effective_free_gb

        free = effective_free_gb(exclude=owner(space))
    except Exception:
        return False, 'gouverneur indisponible'
    if free <= 0:
        return False, 'VRAM libre inconnue ou nulle'
    # Marge : rester résident ne doit jamais être la raison pour laquelle un traitement
    # utilisateur échoue à charger.
    if free < need * 3:
        return False, f'{free:.1f} Go libres — insuffisant pour {need:.1f} Go avec marge'
    return True, f'{free:.1f} Go libres'


def reserve(space_key: str, *, expires_in_s: float = None) -> bool:
    """Déclare la résidence au gouverneur, pour que les AUTRES process la voient. `expires_in_s` :
    la ligne expire avec la résidence qu'elle déclare, sans libération explicite. Empreinte
    inconnue au catalogue ⇒ rien de déclaré (False) : `residency_allowed` a déjà refusé."""
    space = get(space_key)
    need = need_gb(space)
    if not need:
        return False
    try:
        from wama.common.services.resource_governor import mark_used, reserve_vram

        ok = reserve_vram(owner(space), need, expires_in_s=expires_in_s)
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
