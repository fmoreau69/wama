"""
Le MOTEUR de vectorisation — la seule écriture de l'appel au modèle d'embedding.
Doc : `WAMA_MEMORY.md §7sexies`.

Sans Django : le service (`vector_service.py`) l'exécute, et le client (`service_client.py`)
l'exécute lui-même quand le service n'est pas joignable. Un seul chemin de code dans les deux cas.

RÈGLE D'INTÉGRATION — DÉGRADATION, JAMAIS ÉCHEC (celle du RAG, `memory/embed.py`) : fournisseur
éteint, modèle absent, délai dépassé ⇒ `[]`, et l'appelant décide (écrire sans vecteur, réessayer
plus tard). Une entrée MAL FORMÉE, elle, est une erreur de programmation : `ValueError`.

⚠ Tout appel charge le modèle côté Ollama, sur le GPU de l'hôte : `KEEP_ALIVE` le décharge
aussitôt par défaut (`memory/embed.py` §5bis : l'hôte a crashé le 2026-08-20 pendant une série
de chargements). Une résidence plus longue se demande au gouverneur (`service_client`).
"""
from __future__ import annotations

import base64
import io
import logging

from .spaces import VectorSpace, get

logger = logging.getLogger(__name__)

#: Délai par défaut — un embedding est souvent sur le chemin d'une écriture ou d'un rappel
#: interactif : mieux vaut dégrader en quelques secondes que faire attendre.
TIMEOUT_S = 20.0

#: Résidence du modèle APRÈS la réponse : '0' = déchargement immédiat (défaut Ollama : 5 min).
KEEP_ALIVE = '0'

#: Plus grand côté d'une image envoyée. Le projecteur d'EmbeddingGemma-2 travaille en 224 px :
#: 768 garde la marge et borne la requête (~100 Ko) — c'est la taille de la mesure du 2026-10-19.
MAX_IMAGE_SIDE = 768


def _image_b64(source) -> str:
    """Une image (chemin ou octets) en JPEG base64, réduite à `MAX_IMAGE_SIDE`."""
    from PIL import Image

    image = Image.open(io.BytesIO(source) if isinstance(source, (bytes, bytearray)) else source)
    image = image.convert('RGB')
    image.thumbnail((MAX_IMAGE_SIDE, MAX_IMAGE_SIDE))
    buf = io.BytesIO()
    image.save(buf, 'JPEG', quality=90)
    return base64.b64encode(buf.getvalue()).decode('ascii')


def prepare(space: VectorSpace, items, *, query: bool = False) -> list:
    """Les entrées du fournisseur, dans l'ordre de `items`.

    Un item est un texte (`str` ou `{'text': …}`) ou une image (`{'image': chemin | octets}`).
    Le texte d'une REQUÊTE reçoit le préfixe de l'espace ; un document reste nu. L'image part en
    `{'image': <base64>}`, la seule forme qu'Ollama vectorise (mesuré le 2026-10-19 : un champ
    `images` voisin ou `{'type': 'image'}` rendent un vecteur vide ou un 400)."""
    inputs = []
    for item in items:
        if isinstance(item, dict) and 'image' in item:
            if 'image' not in space.modalities:
                raise ValueError(f"l'espace {space.key!r} ne lit pas les images")
            inputs.append({'image': _image_b64(item['image'])})
            continue
        text = item.get('text') if isinstance(item, dict) else item
        if not isinstance(text, str) or not text.strip():
            raise ValueError(f'entrée vide ou inconnue : {item!r}')
        inputs.append((space.query_prefix + text) if query else text)
    return inputs


def check_inputs(space: VectorSpace, inputs) -> None:
    """Contrôle des entrées DÉJÀ préparées (ce que le service reçoit du client)."""
    for value in inputs:
        if isinstance(value, str) and value.strip():
            continue
        if (isinstance(value, dict) and set(value) == {'image'} and isinstance(value['image'], str)
                and 'image' in space.modalities):
            continue
        raise ValueError(f"entrée non préparée pour l'espace {space.key!r}")


def _url(key: str, path: str) -> str:
    """Adresse d'un fournisseur (`external_sources.effective_url` : Ollama par son résolveur,
    réécriture WSL2 → hôte Windows) suivie de `path`."""
    from wama.common.external_sources import effective_url
    return f'{effective_url(key).rstrip("/")}{path}'


def _post(key: str, path: str, payload: dict, timeout: float):
    import requests

    from wama.common.external_sources import proxies_for
    # `proxies` dérivés de la PORTÉE déclarée de la source : neutralisés pour un service local
    # (le proxy UGE de `.env` répondrait sa page d'erreur), empruntés pour un distant.
    return requests.post(_url(key, path), json=payload, proxies=proxies_for(key), timeout=timeout)


def embed_inputs(space: VectorSpace, inputs, *, timeout: float = TIMEOUT_S,
                 keep_alive: str | None = None) -> list:
    """Les vecteurs d'entrées préparées (même ordre), ou `[]` si aucun fournisseur n'a répondu.

    Le lot part en UN appel : Ollama rechargerait sinon le modèle à chaque requête."""
    if not inputs:
        return []
    payload = {'model': space.model, 'input': list(inputs),
               'options': {'num_ctx': space.num_ctx},
               'keep_alive': KEEP_ALIVE if keep_alive is None else keep_alive}
    if space.truncate:
        payload['dimensions'] = space.dims
    for provider in space.providers:
        try:
            resp = _post(provider, '/api/embed', payload, timeout)
        except Exception:
            logger.warning('[vectors] %s injoignable pour %s', provider, space.key, exc_info=True)
            continue
        if resp.status_code != 200:
            logger.warning('[vectors] %s HTTP %s pour %s (%s)', provider, resp.status_code,
                           space.key, resp.text[:160])
            continue
        vectors = resp.json().get('embeddings') or []
        if len(vectors) != len(inputs):
            logger.warning('[vectors] %s : %s vecteurs pour %s entrées — lot ignoré',
                           provider, len(vectors), len(inputs))
            continue
        bad = next((len(v) for v in vectors if len(v) != space.dims), None)
        if bad is not None:
            logger.error('[vectors] %s : dimension %s ≠ %s attendue pour %s — lot ignoré',
                         provider, bad, space.dims, space.model)
            continue
        return vectors
    return []


def embed(space_key: str, items, *, query: bool = False, timeout: float = TIMEOUT_S,
          keep_alive: str | None = None) -> list:
    """`prepare` puis `embed_inputs` — l'appel complet, dans ce process."""
    space = get(space_key)
    return embed_inputs(space, prepare(space, items, query=query), timeout=timeout,
                        keep_alive=keep_alive)


def unload(space_key: str) -> bool:
    """Décharge tout de suite le modèle de l'espace (appel vide à `keep_alive` '0', la forme
    documentée par Ollama). True si un fournisseur a répondu."""
    space = get(space_key)
    for provider in space.providers:
        try:
            if _post(provider, '/api/embed', {'model': space.model, 'input': [],
                                              'keep_alive': '0'}, 10.0).status_code == 200:
                return True
        except Exception:
            logger.debug('[vectors] déchargement impossible chez %s', provider, exc_info=True)
    return False


def available(space_key: str) -> bool:
    """Le modèle de l'espace est-il présent chez un fournisseur — SANS le charger. Distingue
    « pas installé » de « fournisseur éteint », que l'appel d'embedding confondrait en `[]`."""
    import requests

    from wama.common.external_sources import proxies_for
    from wama.common.utils.ollama_host import full_tag
    space = get(space_key)
    # Ollama nomme `x:latest` ce qu'on demande sous `x` ; un AUTRE tag de la même famille
    # (`x:270m`) n'est pas le modèle de l'espace.
    wanted = {space.model, full_tag(space.model)}
    for provider in space.providers:
        try:
            resp = requests.get(_url(provider, '/api/tags'), proxies=proxies_for(provider),
                                timeout=5.0)
            names = {m.get('name', '') for m in (resp.json().get('models') or [])}
        except Exception:
            continue
        if wanted & names:
            return True
    return False
