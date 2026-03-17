"""
WAMA Media Library — Wikimedia Commons provider
Aucune clé API requise. Utilise l'API MediaWiki publique.
"""

import json
import re
import urllib.parse
import urllib.request

from .base import BaseProvider, SearchResult


class WikimediaProvider(BaseProvider):
    slug             = 'wikimedia'
    name             = 'Wikimedia Commons'
    supported_types  = ['image', 'video']
    requires_api_key = False

    _API = 'https://commons.wikimedia.org/w/api.php'
    _UA  = 'WAMA/1.0 (media library; +https://github.com/wama)'

    # MIME types acceptés par type d'asset
    _MIME_FILTER = {
        'image': 'filetype:bitmap',
        'video': 'filetype:video',
    }

    def search(self, query: str, asset_type: str, page: int = 1, per_page: int = 20) -> dict:
        if asset_type not in self.supported_types:
            return {'results': [], 'total': 0, 'has_more': False}

        mime_filter = self._MIME_FILTER.get(asset_type, '')
        gsrsearch   = f'{mime_filter} {query}'.strip()
        offset      = (page - 1) * per_page

        params = {
            'action':       'query',
            'format':       'json',
            'generator':    'search',
            'gsrnamespace': '6',        # File namespace
            'gsrsearch':    gsrsearch,
            'gsrlimit':     per_page,
            'gsroffset':    offset,
            'prop':         'imageinfo',
            'iiprop':       'url|size|mime|extmetadata',
            'iiurlwidth':   320,
        }
        url = f"{self._API}?{urllib.parse.urlencode(params)}"

        try:
            req = urllib.request.Request(url, headers={'User-Agent': self._UA})
            with urllib.request.urlopen(req, timeout=15) as r:
                data = json.loads(r.read())
        except Exception as exc:
            return {'results': [], 'total': 0, 'has_more': False, 'error': str(exc)}

        pages   = data.get('query', {}).get('pages', {})
        results = []

        for p in pages.values():
            if p.get('missing'):
                continue
            ii = (p.get('imageinfo') or [{}])[0]
            if not ii.get('url'):
                continue

            # filter by MIME
            mime = ii.get('mime', '')
            if asset_type == 'image' and not mime.startswith('image/'):
                continue
            if asset_type == 'video' and not mime.startswith('video/'):
                continue

            meta   = ii.get('extmetadata', {})
            lic    = meta.get('LicenseShortName', {}).get('value', '')
            author = re.sub(r'<[^>]+>', '', meta.get('Artist', {}).get('value', ''))[:100]

            results.append(SearchResult(
                provider_id  = str(p.get('pageid', '')),
                title        = p.get('title', '').replace('File:', ''),
                preview_url  = ii.get('thumburl', ii.get('url', '')),
                download_url = ii.get('url', ''),
                asset_type   = asset_type,
                license      = lic,
                author       = author,
                width        = ii.get('width', 0),
                height       = ii.get('height', 0),
                file_size    = ii.get('size', 0),
            ))

        total    = data.get('query', {}).get('searchinfo', {}).get('totalhits', len(results))
        has_more = offset + len(results) < total

        return {'results': results, 'total': total, 'has_more': has_more}
