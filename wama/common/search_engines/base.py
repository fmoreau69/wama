"""Moteurs de recherche web — contrat COMMUN d'un moteur.

Même forme que les connecteurs de la médiathèque (`media_library/providers/`), et pour les
mêmes raisons : chaque moteur a son protocole, aucun n'a le droit d'avoir son adresse, son
proxy ni sa clé à lui. Ce qui est déclaré vit au registre des sources (`external_sources`,
famille `recherche`) ; ce qui est PROPRE à un moteur — le corps de la requête et la forme de
sa réponse — vit dans sa classe, et nulle part ailleurs.

Né le 2026-09-26 (décision de Fabien) : la recherche web de l'assistant était câblée en dur sur
DuckDuckGo, qui a cessé de répondre à autre chose qu'un défi anti-robot. Un moteur unique écrit
dans la brique est un point de panne que rien ne contourne.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class SearchHit:
    """Un résultat, indépendant du moteur — ce que l'assistant reçoit."""
    title: str
    url: str
    snippet: str = ''

    def to_dict(self):
        return {'title': self.title, 'url': self.url, 'snippet': self.snippet}


class SearchEngineUnavailable(RuntimeError):
    """Le moteur a répondu, mais pas avec des résultats (défi anti-robot, clé refusée…).

    ⚠ Distinct d'une recherche SANS RÉSULTAT, qui est une réponse légitime. Mesuré le
    2026-09-26 : DuckDuckGo rend un HTTP 200 de 14 Ko contenant « Unfortunately, bots use
    DuckDuckGo too. Please complete the following challenge » — la requête réussit, le parsing
    ne trouve rien, et la recherche rendait une liste VIDE. L'assistant concluait alors « je
    n'ai rien trouvé » sur une recherche qui n'avait jamais eu lieu.
    *Un échec qui emprunte la forme d'un succès est pire qu'une erreur : il se croit.*
    """


class BaseSearchEngine(ABC):
    """Un moteur : son protocole, et rien d'autre.

    `slug` est la clé de sa source au registre — c'est par elle que viennent son adresse
    (`base_url`), son proxy (`proxies_for`) et la clé de l'utilisateur.
    """

    slug: str = ''
    #: Le moteur exige-t-il une clé ? (dérivé du registre par `requires_key()`, surchargeable)
    timeout_s: float = 15.0

    def __init__(self, api_key: str = ''):
        self.api_key = api_key

    # ── Ce que chaque moteur implémente ──────────────────────────────────────────────────
    @abstractmethod
    def search(self, query: str, max_results: int = 5) -> list[SearchHit]:
        """Rend au plus `max_results` résultats. Lève `SearchEngineUnavailable` si le moteur
        a répondu autre chose que des résultats (un défi, une clé refusée)."""
        ...

    # ── Ce qu'aucun moteur ne réécrit ────────────────────────────────────────────────────
    @property
    def label(self) -> str:
        from wama.common.external_sources import get
        return get(self.slug).label

    def base_url(self) -> str:
        """L'adresse de ce moteur, lue au REGISTRE (sa clé = son slug) — jamais une constante
        d'adresse dans la classe : une garde le vérifie (`tests_external_sources`)."""
        from wama.common.external_sources import base_url
        return base_url(self.slug)

    def proxies(self):
        """Le proxy que la PORTÉE déclarée de la source impose — neutralisé pour une instance
        locale (SearXNG du labo), emprunté pour un service Internet."""
        from wama.common.external_sources import proxies_for
        return proxies_for(self.slug)

    def post_json(self, path: str, payload: dict, headers: dict | None = None) -> dict:
        """POST JSON → JSON. TOUTE sortie réseau d'un moteur passe par ici ou par `get_json`."""
        import requests
        resp = requests.post(self.base_url().rstrip('/') + path, json=payload,
                             headers={'Content-Type': 'application/json', **(headers or {})},
                             timeout=self.timeout_s, proxies=self.proxies())
        return self._read(resp)

    def get_json(self, path: str, params: dict, headers: dict | None = None) -> dict:
        import requests
        resp = requests.get(self.base_url().rstrip('/') + path, params=params,
                            headers=headers or {}, timeout=self.timeout_s,
                            proxies=self.proxies())
        return self._read(resp)

    def _read(self, resp) -> dict:
        """Statut et corps — une clé refusée est dite EN CLAIR, pas rendue comme « rien trouvé »."""
        if resp.status_code in (401, 403):
            raise SearchEngineUnavailable(
                f"{self.label} a refusé la clé d'API (HTTP {resp.status_code}) — "
                f"vérifier celle posée au profil")
        if resp.status_code == 429:
            raise SearchEngineUnavailable(f"{self.label} : quota atteint (HTTP 429)")
        resp.raise_for_status()
        try:
            return resp.json()
        except ValueError as exc:
            raise SearchEngineUnavailable(
                f"{self.label} n'a pas répondu en JSON — {exc}") from exc
