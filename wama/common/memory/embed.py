"""
Embeddings de la mémoire — `qwen3-embedding:4b` via Ollama. Doc : `WAMA_MEMORY.md §7`.

POURQUOI qwen3-embedding:4b (bascule du 2026-10-19, décision de Fabien ; c'était `bge-m3`).
Mesuré au banc `mteb_fr_retrieval` (2026-09, `PROJECT_STATUS`) : Qwen3-Embedding-4B 70,0 (1ᵉʳ sur
116), bge-m3 61,5 (16ᵉ) — le corpus du Lescot est francophone, et un embedder faible y dégrade le rappel sans
jamais lever d'erreur : la panne est silencieuse et se mesure en pertinence, pas en logs (c'est
la même raison qui avait fait préférer bge-m3 à `nomic`, anglo-centré). Deux réglages le rendent
compatible avec ce poste et avec la colonne existante :
  • `dimensions=1024` : le modèle rend 2560 dimensions, entraîné pour être TRONQUÉ (Matryoshka) ;
    Ollama tronque et renormalise (norme 1, mesuré). La colonne pgvector `vector(1024)` et son
    index restent — une bascule à dimension égale est un réindex, pas une migration ;
  • `num_ctx=2048` : sans lui, Ollama réserve le contexte complet du modèle — 9,3 Go de VRAM
    MESURÉS, contre 3,8 Go à 2048 jetons. Les textes vectorisés font au plus ~1 000 caractères
    (fragments du RAG : `index.CHUNK_SIZE` = 800 ; souvenirs : 1 042 au plus, mesuré) : 2048
    jetons ne tronquent rien.
Les REQUÊTES portent une instruction (`QUERY_INSTRUCTION`), les documents non : c'est l'usage
prescrit par le modèle pour la recherche — une requête et le passage qui y répond ne se
ressemblent pas, l'instruction dit au modèle ce qu'on cherche.

RÈGLE D'INTÉGRATION — DÉGRADATION, JAMAIS ÉCHEC. Si Ollama est éteint, si le modèle n'est pas
tiré, si la requête expire : on rend `None` et l'appelant écrit quand même, `embedding=NULL`.
Une écriture perdue est irrécupérable (cf. `MemoryItem` : non re-dérivable) ; un vecteur manquant
se rattrape par un réindex. On ne troque jamais la première contre le second.

⚠ CE MODULE TOUCHE LE GPU DE L'HÔTE. Tout appel ici charge l'embedder côté Ollama. Sur ce poste,
l'hôte Windows a crashé le 2026-08-20 pendant une série d'appels d'embedding, et la règle
d'exploitation interdit les chargements Ollama enchaînés hors action explicite de l'utilisateur.
Deux conséquences, portées par le code et pas par la vigilance :
  1. `keep_alive='0'` sur chaque appel — le modèle est déchargé AUSSITÔT au lieu de résider 5 min
     (défaut Ollama), ce qui évite qu'une série d'écritures ne laisse la VRAM occupée entre-temps.
  2. L'appelant peut TOUJOURS écrire sans embarquer (`remember(..., embed=False)`) puis rattraper
     par `store.reindex()`. Aucun chemin d'écriture n'oblige à toucher le GPU.

DEPUIS LE 2026-10-19 (`WAMA_MEMORY.md §7sexies`) : ce module ne parle plus à Ollama lui-même. Le
modèle, ses dimensions, sa fenêtre et l'instruction de requête sont DÉCLARÉS par l'espace `text`
(`common/vectors/spaces.py`), l'appel passe par le service de vectorisation commun
(`common/vectors/service_client.py`), et la gouvernance VRAM aussi. Il garde ce qui est propre à la
mémoire : la règle de dégradation, la résidence courte du rappel, `vectorized_q`.
"""
from __future__ import annotations

import logging

from ..vectors import service_client as vectors
from ..vectors.spaces import TEXT

logger = logging.getLogger(__name__)

#: Modèle d'embedding de référence. Le nom est STOCKÉ par ligne (`Embedded.embedding_model`) :
#: une bascule devient un réindex explicite, au lieu de mélanger deux espaces vectoriels dans la
#: même colonne — ce qui transformerait les distances en bruit SANS erreur visible. Et une ligne
#: d'un autre modèle n'est jamais comparée à une requête de celui-ci (`vectorized_q`).
EMBEDDING_MODEL = TEXT.model

#: Doit correspondre à `common.models.EMBEDDING_DIMS`. DEMANDÉE à Ollama (`dimensions`) : le
#: modèle en rend 2560, tronquées à la source (cf. en-tête). Le moteur refuse un lot d'une autre
#: dimension plutôt que d'écrire une ligne que pgvector rejetterait avec un message obscur.
EXPECTED_DIMS = TEXT.dims

#: Fenêtre de contexte demandée à Ollama — ce qui borne la VRAM (cf. en-tête : 3,8 Go mesurés au
#: lieu de 9,3). À relever si l'on vectorise un jour des textes plus longs que ~1 500 caractères.
NUM_CTX = TEXT.num_ctx

#: Instruction des REQUÊTES (rappel), jamais des documents — forme prescrite par Qwen3-Embedding
#: (`Instruct: <tâche>\nQuery: <requête>`), en anglais comme le recommande le modèle même pour une
#: requête en français. Posée par le moteur (`query=True`).
QUERY_INSTRUCTION = TEXT.query_prefix


def vectorized_q():
    """Les lignes VECTORISÉES par l'embedder COURANT — la seule définition de « vectorisé » : la
    recherche vectorielle (`store._by_vector`), le réindex (ce qui reste à faire) et les compteurs
    (« Mon RAG », corpus des docs) la lisent. Un vecteur d'un autre modèle n'en est pas un : il
    vit dans un autre espace, sa distance à une requête de celui-ci ne veut rien dire."""
    from django.db.models import Q
    return Q(embedding__isnull=False, embedding_model=EMBEDDING_MODEL)

#: Court volontairement. Un embedding est sur le chemin d'une écriture ou d'un rappel interactif :
#: mieux vaut dégrader en quelques secondes que faire attendre. Le réindex, lui, n'est pas pressé.
TIMEOUT_S = vectors.TIMEOUT_S

# La résidence APRÈS la réponse est celle du moteur (`vectors.engine.KEEP_ALIVE`, '0' :
# déchargement immédiat) — le surcoût d'un rechargement par appel est le prix de l'innocuité ; le
# réindex par LOT (`store.reindex`) l'amortit en demandant une résidence courte au gouverneur.


#: Résidence demandée pour un rappel — courte. Le gouverneur peut refuser, auquel cas chaque
#: rappel recharge le modèle (~5 s au lieu de ~300 ms) : lent, jamais concurrent.
RESIDENCE_RAPPEL = '5m'

#: La même, en secondes, pour que la RÉSERVATION expire avec la résidence qu'elle déclare.
#: Sans elle, la ligne survivait une heure (TTL du registre) à un modèle qu'Ollama décharge au
#: bout de 5 min — et aucun appelant du rappel ne la libérait (mesuré le 2026-09-14).
RESIDENCE_RAPPEL_S = 300


def embed_text(text: str, *, timeout: float = TIMEOUT_S, resident: bool = False,
               query: bool = False):
    """
    Rend le vecteur de `text`, ou `None` si l'embedder est indisponible.

    `None` est un retour NORMAL, pas une anomalie — voir la règle de dégradation ci-dessus.

    `resident=True` : DEMANDE au gouverneur de garder l'embedder chargé après l'appel. Sans
    cela, un rappel sémantique repaie le chargement complet à chaque fois — mesuré le
    2026-08-21 : 5,3 s par appel, y compris le second enchaîné. C'est ce qui rendait
    l'arbitrage « hybride pour `memory_recall` » creux : la qualité y gagnait, la latence non.
    Le gouverneur reste seul juge — refus ⇒ déchargement immédiat, comme avant.

    `query=True` : le texte est une REQUÊTE (`embed_query`).
    """
    keep_alive = None
    if resident:
        allowed, _ = residency_allowed()
        if allowed:
            reserve(expires_in_s=RESIDENCE_RAPPEL_S)
            keep_alive = RESIDENCE_RAPPEL
    vecs = embed_batch([text], timeout=timeout, keep_alive=keep_alive, query=query)
    return vecs[0] if vecs else None


def embed_query(text: str, *, resident: bool = False):
    """Le vecteur d'une REQUÊTE de rappel : le moteur la précède de `QUERY_INSTRUCTION` (les
    documents, eux, se vectorisent nus — `embed_text`, `embed_batch`). `None` si indisponible."""
    if not (text or '').strip():
        return None
    return embed_text(text, resident=resident, query=True)


def embed_batch(texts, *, timeout: float = TIMEOUT_S, keep_alive: str = None,
                query: bool = False):
    """
    Rend la liste des vecteurs (même ordre que `texts`), ou `[]` si l'embedder est indisponible.

    Le lot est traité en UN appel (service de vectorisation, espace `text`) : Ollama recharge
    sinon le modèle à chaque requête, ce qui dominerait le coût d'une indexation de médiathèque.

    `keep_alive` : résidence VRAM APRÈS la réponse. `None` = celle du moteur ('0', déchargement
    immédiat), le bon défaut pour une écriture interactive isolée.

    ⚠ MAIS PAS POUR UN RÉINDEX. Sur 940 éléments en lots de 64, décharger entre chaque lot
    impose ~15 cycles charge/décharge — or c'est un ENCHAÎNEMENT de chargements Ollama qui a
    précédé le crash hôte du 2026-08-20 (§5bis). `store.reindex()` passe donc une résidence
    courte et décharge UNE fois à la fin : 1 cycle au lieu de 15. Moins de cycles, pas plus de
    résidence — les deux vont dans le même sens ici.
    """
    kept = [t for t in (texts or []) if t and t.strip()]
    if not kept:
        return []
    try:
        vecs = vectors.embed(TEXT.key, kept, query=query, timeout=timeout,
                                 keep_alive=keep_alive)
    except Exception:
        logger.warning("[memory.embed] vectorisation impossible — écriture sans vecteur",
                       exc_info=True)
        return []
    if not vecs:
        logger.warning("[memory.embed] embedder indisponible — écriture sans vecteur")
    return vecs


#: L'empreinte VRAM de l'embedder n'est plus déclarée ici (`VRAM_GB`, retiré le 2026-10-20) : elle
#: se lit au catalogue, mesurée au chargement (`vectors.need_gb`). La fenêtre de contexte en fait
#: varier le triple — d'où une mesure, jamais la taille du fichier.

#: Détenteur déclaré au gouverneur — celui de l'espace (`vectors.owner`).
OWNER = vectors.owner(TEXT)


def residency_allowed() -> tuple[bool, str]:
    """
    Demande au GOUVERNEUR s'il y a de la place pour garder l'embedder résident
    (`vectors.residency_allowed`). Une résidence écrite en dur (`keep_alive='5m'`) ignorerait les
    réservations des autres process et garderait l'embedder en VRAM pendant leur chargement —
    exactement le motif d'enchaînement qui a précédé le crash du 2026-08-20.
    """
    return vectors.residency_allowed(TEXT.key)


def reserve(*, expires_in_s: float = None) -> bool:
    """Déclare la résidence au gouverneur. `expires_in_s` : la ligne expire avec la résidence
    qu'elle déclare (rappel : 5 min, sans libération explicite). Le réindex, lui, la libère en fin
    d'opération (`release`)."""
    return vectors.reserve(TEXT.key, expires_in_s=expires_in_s)


def release() -> bool:
    """Libère la réservation. ⚠ COMPTABILITÉ SEULEMENT — le déchargement réel, c'est `unload()` ;
    les deux vont toujours ensemble."""
    return vectors.release(TEXT.key)


def unload() -> bool:
    """
    Décharge le modèle d'embedding de la VRAM, tout de suite. Rend True si la demande a abouti.

    Sert de POINT FINAL au réindex : la résidence tenue pendant l'opération ne doit pas lui
    survivre, sinon on aurait juste déplacé le problème d'un enchaînement de cycles vers un squat
    de VRAM.
    """
    return vectors.unload(TEXT.key)


def embedder_available() -> bool:
    """
    Dit si le modèle d'embedding est tiré côté Ollama — SANS le charger.

    Utilisé par les diagnostics et le réindex pour distinguer « pas encore tiré » (action :
    `manage.py pull_model ollama:qwen3-embedding:4b`) de « serveur éteint » (action : démarrer
    Ollama). Les deux se présentent autrement comme le même `None`.
    """
    return vectors.available(TEXT.key)
