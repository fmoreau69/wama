"""
WAMA Media Library — Openverse provider
API publique sans clé requise : https://api.openverse.org/v1/
Clé optionnelle (quota plus élevé) : https://api.openverse.org/v1/auth_tokens/register/
"""

import json
import urllib.parse
import urllib.request

from .base import BaseProvider, SearchResult


class OpenverseProvider(BaseProvider):
    slug             = 'openverse'
    name             = 'Openverse'
    supported_types  = ['image', 'audio_music']
    requires_api_key = False

    _BASE = 'https://api.openverse.org/v1'
    _UA   = 'WAMA/1.0 (media library)'

    def search(self, query: str, asset_type: str, page: int = 1, per_page: int = 20) -> dict:
        if asset_type == 'image':
            endpoint = f'{self._BASE}/images/'
        elif asset_type == 'audio_music':
            endpoint = f'{self._BASE}/audio/'
        else:
            return {'results': [], 'total': 0, 'has_more': False}

        params = {
            'q':            query,
            'page':         page,
            'page_size':    per_page,
            'license_type': 'commercial',
        }
        url = f"{endpoint}?{urllib.parse.urlencode(params)}"

        headers = {'User-Agent': self._UA, 'Accept': 'application/json'}
        if self.api_key:
            headers['Authorization'] = f'Bearer {self.api_key}'

        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=15) as r:
                data = json.loads(r.read())
        except Exception as exc:
            return {'results': [], 'total': 0, 'has_more': False, 'error': str(exc)}

        results = []
        for item in data.get('results', []):
            tags = ', '.join(t.get('name', '') for t in (item.get('tags') or [])[:10])
            if asset_type == 'image':
                results.append(SearchResult(
                    provider_id  = item.get('id', ''),
                    title        = item.get('title', '') or f'Image {item.get("id", "")}',
                    preview_url  = item.get('thumbnail', ''),
                    download_url = item.get('url', ''),
                    asset_type   = 'image',
                    license      = item.get('license', ''),
                    author       = item.get('creator', ''),
                    width        = item.get('width') or 0,
                    height       = item.get('height') or 0,
                    tags         = tags,
                ))
            else:
                results.append(SearchResult(
                    provider_id  = item.get('id', ''),
                    title        = item.get('title', '') or f'Audio {item.get("id", "")}',
                    preview_url  = item.get('thumbnail', ''),
                    download_url = item.get('url', ''),
                    asset_type   = 'audio_music',
                    license      = item.get('license', ''),
                    author       = item.get('creator', ''),
                    duration     = item.get('duration') or 0,
                    file_size    = item.get('filesize') or 0,
                    tags         = tags,
                ))

        total    = data.get('result_count', 0)
        has_more = data.get('page_count', 1) > page
        return {'results': results, 'total': total, 'has_more': has_more}
