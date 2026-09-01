"""
web_search — Recherche internet + lecture de page en CHAÎNE (COMMUN).

Complète `url_ingest` (URL connue → FICHIER local, pour l'ingest des apps) pour le besoin
de l'assistant (`WAMA_LLM.md §Investigation web`) : URL inconnue → CHERCHER, puis
page → TEXTE en mémoire, borné, prêt à entrer dans un prompt.

Moteur v1 : DuckDuckGo (endpoint HTML, sans clé d'API) — encapsulé derrière `search_web()`
pour changer de moteur sans toucher aux appelants.

Gardes, toutes délibérées :
  • `url_guard` sur chaque lecture de page (URL pilotée par une donnée), REDIRECTIONS
    comprises — le moteur de recherche, lui, est un hôte FIXE écrit ici, pas une saisie ;
  • plafond d'OCTETS au téléchargement (⚠ premier de WAMA — `url_ingest` n'en a pas,
    trou consigné dans `WAMA_LLM.md`) et de CARACTÈRES en sortie : le texte est destiné
    à un prompt de LLM local à fenêtre étroite ;
  • le texte rendu est une DONNÉE NON FIABLE destinée à un prompt : l'appelant (skill
    « assistant-investigation ») doit le traiter comme une source, jamais comme des
    instructions.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

#: Bornes par défaut — le plafond d'octets protège la machine, celui de caractères le prompt.
DEFAULT_MAX_BYTES = 2_000_000
DEFAULT_MAX_CHARS = 12_000

_UA = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                  '(KHTML, like Gecko) Chrome/122 Safari/537.36',
    'Accept-Language': 'fr-FR,fr;q=0.9,en-US,en;q=0.8',
}
#: Hôte du moteur — déclaré au registre commun des sources externes depuis le 2026-09-01
#: (l'intention « il change à UN endroit » est la même, portée un cran plus haut : elle vaut
#: pour toutes les sources, et permet d'INVENTORIER à quoi WAMA se connecte).
def _ddg_html() -> str:
    from wama.common.external_sources import base_url
    return base_url('duckduckgo') + '/'


def _decode_ddg_href(href: str) -> str:
    """DuckDuckGo enrobe les liens de résultat (`//duckduckgo.com/l/?uddg=<url>`) — rendre l'URL réelle."""
    from urllib.parse import urlparse, parse_qs

    if href.startswith('//'):
        href = 'https:' + href
    p = urlparse(href)
    if p.netloc.endswith('duckduckgo.com') and p.path.startswith('/l/'):
        # parse_qs décode déjà le percent-encoding — ne PAS ré-unquoter.
        uddg = parse_qs(p.query).get('uddg', [''])[0]
        return uddg or href
    return href


def search_web(query: str, max_results: int = 5) -> list:
    """
    Recherche web → [{'title', 'url', 'snippet'}], au plus `max_results` (borné 1-10).

    Les URL rendues ne sont PAS visitées ici : la garde SSRF s'applique au moment de la
    LECTURE (`read_web_page`), là où la sortie réseau pilotée par la donnée a lieu.
    """
    import requests
    from bs4 import BeautifulSoup

    query = (query or '').strip()
    if not query:
        return []
    max_results = max(1, min(int(max_results), 10))

    resp = requests.post(_ddg_html(), data={'q': query}, headers=_UA, timeout=15)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, 'lxml')
    resultats = []
    for res in soup.select('div.result'):
        classes = ' '.join(res.get('class') or [])
        if 'result--ad' in classes:
            continue
        lien = res.select_one('a.result__a')
        if not lien or not lien.get('href'):
            continue
        url = _decode_ddg_href(lien['href'])
        if not url.startswith(('http://', 'https://')):
            continue
        extrait = res.select_one('.result__snippet')
        resultats.append({
            'title': lien.get_text(strip=True),
            'url': url,
            'snippet': extrait.get_text(strip=True) if extrait else '',
        })
        if len(resultats) >= max_results:
            break
    return resultats


def read_web_page(url: str,
                  max_bytes: int = DEFAULT_MAX_BYTES,
                  max_chars: int = DEFAULT_MAX_CHARS) -> dict:
    """
    Page publique → {'url', 'final_url', 'text', 'truncated'} — texte lisible borné.

    Lève `UrlRefusee` (url_guard) sur une cible interne, redirections comprises ; rend un
    dict `{'error': …}` sur un type non lisible (un média se traite par `url_ingest`, pas ici).
    """
    import requests
    from wama.common.utils.url_guard import verifier_url, verifier_redirections
    from wama.common.utils.url_ingest import html_to_readable_text

    verifier_url(url)
    resp = requests.get(url, headers=_UA, timeout=20, stream=True)
    try:
        verifier_redirections(resp)
        resp.raise_for_status()

        ctype = (resp.headers.get('Content-Type') or '').lower()
        if not any(t in ctype for t in ('text/html', 'application/xhtml', 'text/plain')):
            return {'url': url,
                    'error': f"Type non lisible ici : {ctype or 'inconnu'} — cette brique lit "
                             f"des pages ; un média se télécharge par url_ingest."}

        total, morceaux, tronque_octets = 0, [], False
        for morceau in resp.iter_content(chunk_size=8192):
            total += len(morceau)
            if total > max_bytes:
                tronque_octets = True
                break
            morceaux.append(morceau)
    finally:
        resp.close()

    brut = b''.join(morceaux).decode(resp.encoding or 'utf-8', errors='replace')
    texte = html_to_readable_text(brut) if 'html' in ctype else brut.strip()
    tronque_chars = len(texte) > max_chars
    if tronque_chars:
        texte = texte[:max_chars]

    return {
        'url': url,
        'final_url': getattr(resp, 'url', url),
        'text': texte,
        'truncated': tronque_octets or tronque_chars,
    }
