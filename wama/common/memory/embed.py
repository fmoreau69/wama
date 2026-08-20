"""
Embeddings de la mémoire — `bge-m3` via Ollama. Doc : `WAMA_MEMORY.md §7`.

POURQUOI bge-m3 ET PAS nomic-embed-text. `nomic` est anglo-centré ; le corpus du Lescot est en
français, et un embedder anglophone y dégrade le rappel sans jamais lever d'erreur — la panne est
silencieuse et se mesure en pertinence, pas en logs. Le quick-win était déjà identifié
(ROADMAP §16.1) ; la mémoire est son premier consommateur.

RÈGLE D'INTÉGRATION — DÉGRADATION, JAMAIS ÉCHEC. Si Ollama est éteint, si le modèle n'est pas
tiré, si la requête expire : on rend `None` et l'appelant écrit quand même, `embedding=NULL`.
Une écriture perdue est irrécupérable (cf. `MemoryItem` : non re-dérivable) ; un vecteur manquant
se rattrape par un réindex. On ne troque jamais la première contre le second.

⚠ CE MODULE TOUCHE LE GPU DE L'HÔTE. Tout appel ici charge `bge-m3` côté Ollama. Sur ce poste,
l'hôte Windows a crashé le 2026-08-20 pendant une série d'appels d'embedding, et la règle
d'exploitation interdit les chargements Ollama enchaînés hors action explicite de l'utilisateur.
Deux conséquences, portées par le code et pas par la vigilance :
  1. `keep_alive='0'` sur chaque appel — le modèle est déchargé AUSSITÔT au lieu de résider 5 min
     (défaut Ollama), ce qui évite qu'une série d'écritures ne laisse la VRAM occupée entre-temps.
  2. L'appelant peut TOUJOURS écrire sans embarquer (`remember(..., embed=False)`) puis rattraper
     par `store.reindex()`. Aucun chemin d'écriture n'oblige à toucher le GPU.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

#: Modèle d'embedding de référence. Le nom est STOCKÉ par ligne (`Embedded.embedding_model`) :
#: une bascule devient un réindex explicite, au lieu de mélanger deux espaces vectoriels dans la
#: même colonne — ce qui transformerait les distances en bruit SANS erreur visible.
EMBEDDING_MODEL = 'bge-m3'

#: Doit correspondre à `common.models.EMBEDDING_DIMS`. Un écart est une erreur de programmation,
#: pas un cas d'usage : on refuse le vecteur plutôt que d'écrire une ligne que pgvector rejettera
#: de toute façon, mais avec un message incompréhensible.
EXPECTED_DIMS = 1024

#: Court volontairement. Un embedding est sur le chemin d'une écriture ou d'un rappel interactif :
#: mieux vaut dégrader en quelques secondes que faire attendre. Le réindex, lui, n'est pas pressé.
TIMEOUT_S = 20.0

#: Résidence VRAM du modèle APRÈS la réponse. '0' = déchargement immédiat, à l'inverse du défaut
#: Ollama (5 min). Même précaution que `llm_utils.ollama_chat` pour les passes courtes qui
#: précèdent un gros chargement GPU : sans ça, une série d'écritures mémoire laisserait bge-m3
#: squatter la VRAM entre deux appels, en concurrence avec un traitement utilisateur.
#: Le surcoût est un rechargement par appel — négligeable pour 567 M, et c'est le prix de
#: l'innocuité. Le réindex par LOT (`store.reindex`) amortit ça en un seul appel.
KEEP_ALIVE = '0'


def embed_text(text: str, *, model: str = '', timeout: float = TIMEOUT_S):
    """
    Rend le vecteur de `text`, ou `None` si l'embedder est indisponible.

    `None` est un retour NORMAL, pas une anomalie — voir la règle de dégradation ci-dessus.
    """
    vectors = embed_batch([text], model=model, timeout=timeout)
    return vectors[0] if vectors else None


def embed_batch(texts, *, model: str = '', timeout: float = TIMEOUT_S):
    """
    Rend la liste des vecteurs (même ordre que `texts`), ou `[]` si l'embedder est indisponible.

    Le lot est traité en UN appel : Ollama recharge sinon le modèle à chaque requête, ce qui
    dominerait le coût d'une indexation de médiathèque.
    """
    textes = [t for t in (texts or []) if t and t.strip()]
    if not textes:
        return []

    import httpx

    from ..utils.ollama_host import ollama_base

    model = model or EMBEDDING_MODEL
    # `trust_env=False` : même précaution que `llm_utils.ollama_chat` — le proxy UGE est configuré
    # au niveau système et intercepterait un appel qui doit rester local.
    try:
        with httpx.Client(timeout=timeout, trust_env=False) as client:
            resp = client.post(f"{ollama_base()}/api/embed",
                               json={"model": model, "input": textes,
                                     "keep_alive": KEEP_ALIVE})
        if resp.status_code != 200:
            logger.warning("[memory.embed] Ollama HTTP %s (%s) — écriture sans vecteur",
                           resp.status_code, resp.text[:160])
            return []
        vecteurs = resp.json().get('embeddings') or []
    except Exception:
        logger.warning("[memory.embed] embedder injoignable — écriture sans vecteur", exc_info=True)
        return []

    if len(vecteurs) != len(textes):
        logger.warning("[memory.embed] %s vecteurs pour %s textes — lot ignoré",
                       len(vecteurs), len(textes))
        return []
    for v in vecteurs:
        if len(v) != EXPECTED_DIMS:
            logger.error("[memory.embed] dimension %s ≠ %s attendue pour %s — lot ignoré. "
                         "Un changement d'embedder impose une MIGRATION de la colonne pgvector.",
                         len(v), EXPECTED_DIMS, model)
            return []
    return vecteurs


def embedder_disponible(model: str = '') -> bool:
    """
    Dit si le modèle d'embedding est tiré côté Ollama — SANS le charger.

    Utilisé par les diagnostics et le réindex pour distinguer « pas encore tiré » (action :
    `ollama pull bge-m3`) de « serveur éteint » (action : démarrer Ollama). Les deux se
    présentent autrement comme le même `None`.
    """
    import httpx

    from ..utils.ollama_host import ollama_base

    model = model or EMBEDDING_MODEL
    try:
        with httpx.Client(timeout=5.0, trust_env=False) as client:
            resp = client.get(f"{ollama_base()}/api/tags")
        if resp.status_code != 200:
            return False
        noms = [m.get('name', '') for m in (resp.json().get('models') or [])]
    except Exception:
        return False
    # Ollama nomme `bge-m3:latest` ce qu'on demande sous `bge-m3` — comparer sur le préfixe.
    return any(n == model or n.startswith(model + ':') for n in noms)
