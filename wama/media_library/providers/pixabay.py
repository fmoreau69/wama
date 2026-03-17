"""
WAMA Media Library — Pixabay provider
Clé API gratuite : https://pixabay.com/api/docs/
"""

import json
import urllib.parse
import urllib.request

from .base import BaseProvider, SearchResult


class PixabayProvider(BaseProvider):
    slug             = 'pixabay'
    name             = 'Pixabay'
    supported_types  = ['image', 'video']
    requires_api_key = True

    _IMAGE_API = 'https://pixabay.com/api/'
    _VIDEO_API = 'https://pixabay.com/api/videos/'
    _UA        = 'WAMA/1.0 (media library)'

    def search(self, query: str, asset_type: str, page: int = 1, per_page: int = 20) -> dict:
        if not self.api_key:
            return {'results': [], 'total': 0, 'has_more': False,
                    'error': 'Clé API Pixabay manquante — ajoutez-la dans votre profil'}

        if asset_type == 'image':
            base_url = self._IMAGE_API
            params = {
                'key':        self.api_key,
                'q':          query,
                'image_type': 'photo',
                'per_page':   per_page,
                'page':       page,
                'safesearch': 'true',
            }
        elif asset_type == 'video':
            base_url = self._VIDEO_API
            params = {
                'key':      self.api_key,
                'q':        query,
                'per_page': per_page,
                'page':     page,
            }
        else:
            return {'results': [], 'total': 0, 'has_more': False}

        url = f"{base_url}?{urllib.parse.urlencode(params)}"
        try:
            req = urllib.request.Request(url, headers={'User-Agent': self._UA})
            with urllib.request.urlopen(req, timeout=15) as r:
                data = json.loads(r.read())
        except Exception as exc:
            return {'results': [], 'total': 0, 'has_more': False, 'error': str(exc)}

        hits    = data.get('hits', [])
        total   = data.get('totalHits', 0)
        results = []

        for h in hits:
            if asset_type == 'image':
                results.append(SearchResult(
                    provider_id  = str(h.get('id', '')),
                    title        = (h.get('tags', '') or '').split(',')[0].strip() or f'Image {h.get("id")}',
                    preview_url  = h.get('previewURL', ''),
                    download_url = h.get('largeImageURL', h.get('webformatURL', '')),
                    asset_type   = 'image',
                    license      = 'CC0',
                    author       = h.get('user', ''),
                    width        = h.get('imageWidth', 0),
                    height       = h.get('imageHeight', 0),
                    file_size    = h.get('imageSize', 0),
                    tags         = h.get('tags', ''),
                ))
            elif asset_type == 'video':
                videos = h.get('videos', {})
                best   = videos.get('medium') or videos.get('small') or {}
                pic_id = h.get('picture_id', '')
                thumb  = f'https://i.vimeocdn.com/video/{pic_id}_295x166.jpg' if pic_id else ''
                results.append(SearchResult(
                    provider_id  = str(h.get('id', '')),
                    title        = (h.get('tags', '') or '').split(',')[0].strip() or f'Video {h.get("id")}',
                    preview_url  = thumb,
                    download_url = best.get('url', ''),
                    asset_type   = 'video',
                    license      = 'CC0',
                    author       = h.get('user', ''),
                    width        = best.get('width', 0),
                    height       = best.get('height', 0),
                    file_size    = best.get('size', 0),
                    tags         = h.get('tags', ''),
                    duration     = h.get('duration', 0),
                ))

        has_more = page * per_page < total
        return {'results': results, 'total': total, 'has_more': has_more}
