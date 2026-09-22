"""
WAMA Media Library — Freesound provider
Clé API gratuite : https://freesound.org/apiv2/apply/
"""

import json
import urllib.parse

from .base import BaseProvider, SearchResult


class FreesoundProvider(BaseProvider):
    slug             = 'freesound'
    name             = 'Freesound'
    supported_types  = ['voice', 'audio_sfx']
    requires_api_key = True

    _UA   = 'WAMA/1.0 (media library)'

    def search(self, query: str, asset_type: str, page: int = 1, per_page: int = 20) -> dict:
        if not self.api_key:
            return {'results': [], 'total': 0, 'has_more': False,
                    'error': 'Clé API Freesound manquante — ajoutez-la dans votre profil'}

        if asset_type not in self.supported_types:
            return {'results': [], 'total': 0, 'has_more': False}

        # Pour les bruitages : clips plus courts ; pour les voix : durée modérée
        max_dur = '15' if asset_type == 'audio_sfx' else '30'
        params = {
            'query':     query,
            'token':     self.api_key,
            'page':      page,
            'page_size': per_page,
            'fields':    'id,name,previews,duration,filesize,license,username,tags',
            'filter':    f'duration:[0.1 TO {max_dur}]',
        }
        url = f"{self.base_url()}/search/text/?{urllib.parse.urlencode(params)}"

        try:
            with self.open_url(url, timeout=15, headers={'User-Agent': self._UA}) as r:
                data = json.loads(r.read())
        except Exception as exc:
            return {'results': [], 'total': 0, 'has_more': False, 'error': str(exc)}

        results = []
        for h in data.get('results', []):
            previews    = h.get('previews', {})
            preview_url = (previews.get('preview-hq-mp3')
                           or previews.get('preview-lq-mp3', ''))
            tags = ', '.join((h.get('tags') or [])[:10])
            results.append(SearchResult(
                provider_id  = str(h.get('id', '')),
                title        = h.get('name', ''),
                preview_url  = preview_url,
                download_url = preview_url,   # preview MP3 = fichier téléchargeable
                # Le rôle DEMANDÉ, pas `'voice'` en dur : la recherche est déjà filtrée par lui
                # (durée plus courte pour un bruitage), et `supported_types` promet les deux.
                # Jusqu'au 2026-09-21, un bruitage cherché ici entrait en médiathèque comme VOIX.
                asset_type   = asset_type,
                license      = h.get('license', ''),
                author       = h.get('username', ''),
                duration     = h.get('duration', 0),
                file_size    = h.get('filesize', 0),
                tags         = tags,
            ))

        total    = data.get('count', 0)
        has_more = data.get('next') is not None
        return {'results': results, 'total': total, 'has_more': has_more}
