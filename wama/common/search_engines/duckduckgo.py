"""DuckDuckGo (endpoint HTML, sans clé) — le moteur historique, ⚠ HORS SERVICE.

Il n'y a ici aucune API : on POSTe une requête et on parse la page de résultats. C'était le
choix du 2026-08-29 (aucune clé à demander, aucun compte à créer) et il a tenu un mois.

⚠ **Mesuré le 2026-09-26** : le moteur répond HTTP 200 avec 14 Ko de « Unfortunately, bots use
DuckDuckGo too. Please complete the following challenge » — un défi anti-robot à la place des
résultats. Le code reste, parce qu'il est correct et qu'un moteur peut redevenir accessible ;
mais il DIT son indisponibilité au lieu de rendre une liste vide.
"""
from __future__ import annotations

from .base import BaseSearchEngine, SearchEngineUnavailable, SearchHit

_UA = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                  '(KHTML, like Gecko) Chrome/122 Safari/537.36',
    'Accept-Language': 'fr-FR,fr;q=0.9,en-US,en;q=0.8',
}
#: Marqueurs d'une page de DÉFI plutôt que de résultats. Deux conditions réunies (aucun
#: résultat parsé ET un de ces mots) : un seul des deux se déclencherait à tort — une recherche
#: légitime sur le mot « challenge » rendrait des résultats, donc ne lèvera pas.
_CHALLENGE_MARKERS = ('anomaly', 'challenge', 'captcha', 'unusual traffic')


def _decode_href(href: str) -> str:
    """DuckDuckGo enrobe les liens (`//duckduckgo.com/l/?uddg=<url>`) — rendre l'URL réelle."""
    from urllib.parse import parse_qs, urlparse

    if href.startswith('//'):
        href = 'https:' + href
    parts = urlparse(href)
    if parts.netloc.endswith('duckduckgo.com') and parts.path.startswith('/l/'):
        # parse_qs décode déjà le percent-encoding — ne PAS ré-unquoter.
        return parse_qs(parts.query).get('uddg', [''])[0] or href
    return href


class DuckDuckGoEngine(BaseSearchEngine):
    slug = 'duckduckgo'

    def search(self, query: str, max_results: int = 5) -> list[SearchHit]:
        import requests
        from bs4 import BeautifulSoup

        resp = requests.post(self.base_url(), data={'q': query}, headers=_UA,
                             timeout=self.timeout_s, proxies=self.proxies())
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, 'lxml')
        hits = []
        for block in soup.select('div.result'):
            if 'result--ad' in ' '.join(block.get('class') or []):
                continue
            link = block.select_one('a.result__a')
            if not link or not link.get('href'):
                continue
            url = _decode_href(link['href'])
            if not url.startswith(('http://', 'https://')):
                continue
            snippet = block.select_one('.result__snippet')
            hits.append(SearchHit(title=link.get_text(strip=True), url=url,
                                  snippet=snippet.get_text(strip=True) if snippet else ''))
            if len(hits) >= max_results:
                break
        if not hits:
            low = resp.text.lower()
            marker = next((m for m in _CHALLENGE_MARKERS if m in low), '')
            if marker:
                raise SearchEngineUnavailable(
                    f"{self.label} a répondu par un défi anti-robot (« {marker} ») au lieu de "
                    f"résultats — choisir un autre moteur au profil")
        return hits
