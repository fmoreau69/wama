"""Exa — recherche NEURONALE (classement par le sens, pas par mots-clés).

Protocole mesuré le 2026-09-26 : `POST /search`, clé dans l'en-tête `x-api-key`, corps
`{query, numResults, type, contents}` ; réponse `{results: [{title, url, text, …}]}`.
`type='auto'` laisse Exa arbitrer entre neuronal et mots-clés — c'est ce qu'il recommande
quand la requête peut être de l'une ou l'autre nature, et l'assistant pose les deux.

`contents.text.maxCharacters` : on demande un EXTRAIT court, pas la page. Lire la page est un
geste séparé (`read_web_page`), borné et gardé (SSRF) — le mélanger ici ferait entrer des
pages entières dans un prompt à fenêtre étroite.
"""
from __future__ import annotations

from .base import BaseSearchEngine, SearchHit

#: Longueur de l'extrait demandé par résultat — de quoi juger la pertinence, pas de quoi
#: répondre : c'est `read_web_page` qui rapporte le contenu, après que l'assistant a choisi.
SNIPPET_CHARS = 400


class ExaEngine(BaseSearchEngine):
    slug = 'exa'

    def search(self, query: str, max_results: int = 5) -> list[SearchHit]:
        data = self.post_json('/search', {
            'query': query,
            'numResults': max_results,
            'type': 'auto',
            'contents': {'text': {'maxCharacters': SNIPPET_CHARS}},
        }, headers={'x-api-key': self.api_key})
        hits = []
        for row in (data.get('results') or []):
            url = row.get('url') or ''
            if not url.startswith(('http://', 'https://')):
                continue
            hits.append(SearchHit(
                title=(row.get('title') or url).strip(),
                url=url,
                snippet=' '.join((row.get('text') or '').split())[:SNIPPET_CHARS],
            ))
            if len(hits) >= max_results:
                break
        return hits
