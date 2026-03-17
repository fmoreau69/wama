"""
WAMA Media Library — Pexels provider
Clé API gratuite : https://www.pexels.com/api/
"""

import json
import urllib.parse
import urllib.request

from .base import BaseProvider, SearchResult


class PexelsProvider(BaseProvider):
    slug             = 'pexels'
    name             = 'Pexels'
    supported_types  = ['image', 'video']
    requires_api_key = True

    _IMAGE_API = 'https://api.pexels.com/v1/search'
    _VIDEO_API = 'https://api.pexels.com/videos/search'
    _UA        = 'WAMA/1.0 (media library)'

    def search(self, query: str, asset_type: str, page: int = 1, per_page: int = 20) -> dict:
        if not self.api_key:
            return {'results': [], 'total': 0, 'has_more': False,
                    'error': 'Clé API Pexels manquante — ajoutez-la dans votre profil'}

        if asset_type not in self.supported_types:
            return {'results': [], 'total': 0, 'has_more': False}

        base_url = self._IMAGE_API if asset_type == 'image' else self._VIDEO_API
        params   = {'query': query, 'page': page, 'per_page': per_page}
        url      = f"{base_url}?{urllib.parse.urlencode(params)}"

        try:
            req = urllib.request.Request(url, headers={
                'User-Agent': self._UA,
                'Authorization': self.api_key,
            })
            with urllib.request.urlopen(req, timeout=15) as r:
                data = json.loads(r.read())
        except Exception as exc:
            return {'results': [], 'total': 0, 'has_more': False, 'error': str(exc)}

        results = []
        if asset_type == 'image':
            for p in data.get('photos', []):
                src = p.get('src', {})
                results.append(SearchResult(
                    provider_id  = str(p.get('id', '')),
                    title        = p.get('alt', '') or f'Photo {p.get("id")}',
                    preview_url  = src.get('medium', ''),
                    download_url = src.get('large2x', src.get('original', '')),
                    asset_type   = 'image',
                    license      = 'Pexels License',
                    author       = p.get('photographer', ''),
                    width        = p.get('width', 0),
                    height       = p.get('height', 0),
                ))
        elif asset_type == 'video':
            for v in data.get('videos', []):
                files = sorted(
                    [f for f in v.get('video_files', []) if f.get('link')],
                    key=lambda x: x.get('height', 0), reverse=True,
                )
                best  = next((f for f in files if f.get('quality') == 'hd'), files[0] if files else {})
                results.append(SearchResult(
                    provider_id  = str(v.get('id', '')),
                    title        = f'Pexels Video {v.get("id")}',
                    preview_url  = v.get('image', ''),
                    download_url = best.get('link', ''),
                    asset_type   = 'video',
                    license      = 'Pexels License',
                    author       = (v.get('user') or {}).get('name', ''),
                    width        = best.get('width', 0),
                    height       = best.get('height', 0),
                    duration     = v.get('duration', 0),
                ))

        total    = data.get('total_results', len(results))
        has_more = bool(data.get('next_page'))
        return {'results': results, 'total': total, 'has_more': has_more}
