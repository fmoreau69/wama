"""
Les ESPACES de vecteurs de WAMA — un par nature de média. Doc : `WAMA_MEMORY.md §7sexies`.

Un espace, c'est ce qui rend deux vecteurs COMPARABLES : le même modèle, les mêmes dimensions,
la même manière de poser une requête. Deux espaces ne se comparent jamais (la règle du §7 du RAG,
généralisée) : une recherche qui porte sur plusieurs natures de média vectorise sa requête dans
chaque espace concerné et fusionne les classements par rang.

Importable sans Django : le service de vectorisation (`common/vectors/service.py`) le lit aussi.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class VectorSpace:
    key: str
    label: str
    #: Natures d'entrée que le modèle de l'espace sait lire (`text`, `image`).
    modalities: tuple[str, ...]
    #: Nom du modèle chez le fournisseur (tag Ollama).
    model: str
    #: Clé du catalogue — ce que la route installe (`model_readiness.ensure_installed`), ce à
    #: quoi le gouverneur rattache une réservation, et la ligne qui porte l'EMPREINTE VRAM : un
    #: espace n'en déclare aucune (`service_client.need_gb` la lit au catalogue, où la mesure du
    #: chargement la rend — `ModelRegistry.measure_ollama_load`, 2026-10-20).
    model_key: str
    dims: int
    #: Demander `dimensions` au fournisseur : le modèle rend plus de dimensions et a été entraîné
    #: pour être TRONQUÉ (Matryoshka) ; Ollama tronque et renormalise.
    truncate: bool
    #: Fenêtre de contexte demandée — ce qui borne la VRAM (sans elle, Ollama réserve le contexte
    #: complet du modèle).
    num_ctx: int
    #: Préfixe des REQUÊTES (jamais des documents) — la forme de recherche prescrite par le modèle.
    query_prefix: str = ''
    #: Fournisseurs, dans l'ordre — des clés de `external_sources`. Un fournisseur DISTANT n'a sa
    #: place ici que s'il sert LE MÊME modèle aux mêmes dimensions : un autre modèle est un autre
    #: espace, pas un repli. Chacun parle l'API `/api/embed` d'Ollama.
    providers: tuple[str, ...] = ('ollama',)


#: Le texte — l'espace du RAG (`memory/embed.py` : pourquoi ce modèle, ces 1024 dimensions et cette
#: fenêtre).
TEXT = VectorSpace(
    key='text', label='Texte',
    modalities=('text',),
    model='qwen3-embedding:4b', model_key='ollama:qwen3-embedding:4b',
    dims=1024, truncate=True, num_ctx=2048,
    query_prefix=('Instruct: Given a question or keywords, retrieve the passages and memories '
                  'that answer it\nQuery: '),
)

#: Les médias — texte ET image dans un même espace : une requête écrite retrouve une image.
#: EmbeddingGemma-2, installé par la route et éprouvé le 2026-10-19 (`WAMA_MEMORY §7sexies`) :
#: « voiture » met la photo d'une voiture en tête. 768 dimensions, sans troncature (le RAG n'y
#: est pas : aucune colonne à épouser).
MEDIA = VectorSpace(
    key='media', label='Médias (texte et image)',
    modalities=('text', 'image'),
    model='embeddinggemma-2:latest', model_key='ollama:embeddinggemma-2:latest',
    dims=768, truncate=False, num_ctx=2048,
    query_prefix='task: search result | query: ',
)

SPACES: dict[str, VectorSpace] = {s.key: s for s in (TEXT, MEDIA)}

#: L'espace d'un DOCUMENT selon sa nature — le modèle qui va bien par type de média. Une
#: nature absente n'est pas encore vectorisée (vidéo, audio : `WAMA_MEMORY §7sexies`).
MODALITY_SPACE: dict[str, str] = {'text': 'text', 'image': 'media'}


def get(key: str) -> VectorSpace:
    try:
        return SPACES[key]
    except KeyError:
        raise ValueError(f"espace de vecteurs inconnu : {key!r} (connus : {', '.join(SPACES)})")


def space_for(modality: str) -> VectorSpace | None:
    """L'espace où se vectorise un document de cette nature, ou None si elle ne l'est pas."""
    key = MODALITY_SPACE.get(modality)
    return SPACES[key] if key else None
