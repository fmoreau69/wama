"""Staan — l'index de recherche EUROPÉEN (coentreprise Qwant + Ecosia, Paris).

Protocole mesuré le 2026-09-26 sur la documentation publique : base `https://api.staan.ai/v2`
(déclarée au registre), jeton `Authorization: Bearer …`, 1 000 requêtes/mois offertes puis
2 €/1 000. Trois surfaces annoncées — recherche web, recherche « pour l'IA » (RAG/agents) et
une API de réponse rédigée. WAMA appelle la RECHERCHE : l'assistant rédige lui-même, avec ses
propres modèles et son propre cadre ; déléguer la rédaction à la source rendrait une réponse
qu'aucun de nos garde-fous n'aurait vue.

Intérêt pour un labo public : les données restent sous juridiction UE, et l'index est
indépendant de Google et de Bing.
"""
from __future__ import annotations

from .base import BaseSearchEngine, SearchHit

#: L'API rend le champ de description sous l'un de ces noms selon la surface interrogée —
#: on lit le premier présent plutôt que d'en supposer un seul.
_SNIPPET_KEYS = ('snippet', 'description', 'content', 'text')
_TITLE_KEYS = ('title', 'name')


class StaanEngine(BaseSearchEngine):
    slug = 'staan'

    def search(self, query: str, max_results: int = 5) -> list[SearchHit]:
        data = self.get_json('/search', {'q': query, 'count': max_results},
                             headers={'Authorization': f'Bearer {self.api_key}'})
        hits = []
        for row in _rows(data):
            url = row.get('url') or ''
            if not url.startswith(('http://', 'https://')):
                continue
            hits.append(SearchHit(
                title=_first(row, _TITLE_KEYS) or url,
                url=url,
                snippet=' '.join(_first(row, _SNIPPET_KEYS).split()),
            ))
            if len(hits) >= max_results:
                break
        return hits


def _rows(data: dict) -> list:
    """Les résultats, quelle que soit l'enveloppe.

    ⚠ Écrit TOLÉRANT à dessein : la documentation décrit trois surfaces et WAMA n'a pas de clé
    pour mesurer la forme exacte du corps. On lit `results` (le nom le plus courant), sinon
    `web.results`, sinon `data` — et si rien ne correspond, on rend zéro résultat plutôt que
    de lever : l'appelant distingue déjà « pas de résultat » d'un moteur indisponible.
    """
    for candidate in (data.get('results'), (data.get('web') or {}).get('results'),
                      data.get('data')):
        if isinstance(candidate, list):
            return candidate
    return []


def _first(row: dict, keys: tuple) -> str:
    for key in keys:
        value = row.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ''
