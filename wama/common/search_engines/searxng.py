"""SearXNG — méta-moteur AUTO-HÉBERGÉ (instance du labo), sans clé.

`GET /search?q=…&format=json`. ⚠ Le format JSON est DÉSACTIVÉ par défaut dans SearXNG : il
s'active dans `settings.yml` (`search.formats: [html, json]`). Une instance qui ne l'a pas
activé répond en HTML — le moteur le dit alors en clair plutôt que de rendre « aucun résultat ».

⚠⚠ Ce que SearXNG n'est PAS : un index. Il interroge les mêmes moteurs que tout le monde,
depuis l'IP de l'instance. Mesuré par des tiers en juillet 2026 sur une instance privée :
Google ne rend aucun résultat exploitable, Brave et Startpage suspendent l'instance, seul
DuckDuckGo répond. Il apporte la VIE PRIVÉE (aucune requête ne sort nominativement), pas la
fiabilité — et il ne contourne pas le défi anti-robot qui a mis notre accès direct à terre :
il le déplace sur l'IP du labo.
"""
from __future__ import annotations

from .base import BaseSearchEngine, SearchEngineUnavailable, SearchHit


class SearxngEngine(BaseSearchEngine):
    slug = 'searxng'

    def search(self, query: str, max_results: int = 5) -> list[SearchHit]:
        data = self.get_json('/search', {'q': query, 'format': 'json'})
        rows = data.get('results')
        if rows is None:
            raise SearchEngineUnavailable(
                "l'instance SearXNG n'a pas rendu de résultats JSON — activer le format dans "
                "son `settings.yml` (`search.formats: [html, json]`)")
        hits = []
        for row in rows:
            url = row.get('url') or ''
            if not url.startswith(('http://', 'https://')):
                continue
            hits.append(SearchHit(
                title=(row.get('title') or url).strip(),
                url=url,
                snippet=' '.join((row.get('content') or '').split()),
            ))
            if len(hits) >= max_results:
                break
        return hits
