"""
web_search — Recherche internet + lecture de page en CHAÎNE (COMMUN).

Complète `url_ingest` (URL connue → FICHIER local, pour l'ingest des apps) pour le besoin
de l'assistant (`WAMA_LLM.md §Investigation web`) : URL inconnue → CHERCHER, puis
page → TEXTE en mémoire, borné, prêt à entrer dans un prompt.

⚠ Le MOTEUR ne vit plus ici depuis le 2026-09-26 (décision de Fabien). Ce module en avait UN,
écrit en dur — DuckDuckGo —, et le jour où ce moteur a cessé de répondre autre chose qu'un
défi anti-robot, la surface entière est tombée sans recours. Les moteurs sont désormais des
sources du registre avec un adaptateur chacun (`common/search_engines/`), et le choix est une
PRÉFÉRENCE de chacun au profil sur un défaut d'instance. Ce module orchestre : il choisit,
appelle, et met en forme pour l'appelant.

Gardes, toutes délibérées :
  • `url_guard` sur chaque lecture de page (URL pilotée par une donnée), REDIRECTIONS
    comprises — l'adresse d'un moteur, elle, vient du registre, jamais d'une saisie ;
  • plafond d'OCTETS au téléchargement (⚠ premier de WAMA — `url_ingest` n'en a pas,
    trou consigné dans `WAMA_LLM.md`) et de CARACTÈRES en sortie : le texte est destiné
    à un prompt de LLM local à fenêtre étroite ;
  • le texte rendu est une DONNÉE NON FIABLE destinée à un prompt : l'appelant (skill
    « assistant-investigation ») doit le traiter comme une source, jamais comme des
    instructions.
"""
from __future__ import annotations

import logging

#: Ré-exporté : les appelants (tool_api, tests) l'attrapent sans connaître les moteurs.
from wama.common.search_engines import SearchEngineUnavailable  # noqa: F401

logger = logging.getLogger(__name__)

#: Bornes par défaut — le plafond d'octets protège la machine, celui de caractères le prompt.
DEFAULT_MAX_BYTES = 2_000_000
DEFAULT_MAX_CHARS = 12_000

#: En-têtes de LECTURE d'une page. Distincts de ceux d'un moteur (chaque adaptateur porte les
#: siens) : on lit ici des sites quelconques, dont beaucoup servent une page dégradée à un
#: client qui ne s'annonce pas comme un navigateur.
_UA = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                  '(KHTML, like Gecko) Chrome/122 Safari/537.36',
    'Accept-Language': 'fr-FR,fr;q=0.9,en-US,en;q=0.8',
}


def search_web(query: str, max_results: int = 5, user=None) -> list:
    """
    Recherche web → [{'title', 'url', 'snippet'}], au plus `max_results` (borné 1-10).

    Le moteur est celui de `user` (sa préférence de profil, sinon le défaut d'instance, sinon
    le premier utilisable). Sans utilisateur — tâche planifiée, ligne de commande — la
    résolution retombe sur le défaut d'instance et les clés d'instance.

    Les URL rendues ne sont PAS visitées ici : la garde SSRF s'applique au moment de la
    LECTURE (`read_web_page`), là où la sortie réseau pilotée par la donnée a lieu.
    """
    from wama.common.search_engines import engine_for

    query = (query or '').strip()
    if not query:
        return []
    max_results = max(1, min(int(max_results), 10))

    engine = engine_for(user)
    hits = engine.search(query, max_results=max_results)
    logger.info("[web_search] %s : %d résultat(s) pour %r", engine.slug, len(hits), query[:60])
    return [hit.to_dict() for hit in hits[:max_results]]


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

    from wama.common.utils.http_proxy import outbound_proxies

    verifier_url(url)
    # La cible est une URL QUELCONQUE, pas une source déclarée : le proxy SORTANT commun.
    # `url_guard` a déjà refusé les cibles internes — aucun cas local à neutraliser ici.
    resp = requests.get(url, headers=_UA, timeout=20, stream=True,
                        proxies=outbound_proxies())
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
