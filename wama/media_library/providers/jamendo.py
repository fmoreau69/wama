"""
WAMA Media Library — Jamendo provider
Clé API gratuite (Client ID) : https://devportal.jamendo.com/
"""

import json
import urllib.parse
import urllib.request

from .base import BaseProvider, SearchResult


class JamendoProvider(BaseProvider):
    slug             = 'jamendo'
    name             = 'Jamendo'
    supported_types  = ['audio_music']
    requires_api_key = True

    _BASE = 'https://api.jamendo.com/v3.0'
    _UA   = 'WAMA/1.0 (media library)'

    def search(self, query: str, asset_type: str, page: int = 1, per_page: int = 20) -> dict:
        if not self.api_key:
            return {'results': [], 'total': 0, 'has_more': False,
                    'error': 'Clé API Jamendo (Client ID) manquante — ajoutez-la dans votre profil'}

        if asset_type not in self.supported_types:
            return {'results': [], 'total': 0, 'has_more': False}

        params = {
            'client_id':   self.api_key,
            'format':      'json',
            'limit':       per_page,
            'offset':      (page - 1) * per_page,
            'search':      query,
            'include':     'musicinfo',
            'imagesize':   '200',
            'audioformat': 'mp31',   # MP3 128 kbps
        }
        url = f"{self._BASE}/tracks/?{urllib.parse.urlencode(params)}"

        try:
            req = urllib.request.Request(url, headers={'User-Agent': self._UA})
            with urllib.request.urlopen(req, timeout=15) as r:
                data = json.loads(r.read())
        except Exception as exc:
            return {'results': [], 'total': 0, 'has_more': False, 'error': str(exc)}

        results = []
        for t in data.get('results', []):
            try:
                duration = float(t.get('duration', 0) or 0)
            except (ValueError, TypeError):
                duration = 0.0

            music_info = t.get('musicinfo', {}) or {}
            tag_dict   = music_info.get('tags', {}) or {}
            tag_list   = (tag_dict.get('genres') or []) + (tag_dict.get('instruments') or [])
            tags       = ', '.join(tag_list[:10])

            results.append(SearchResult(
                provider_id  = str(t.get('id', '')),
                title        = t.get('name', '') or f'Track {t.get("id")}',
                preview_url  = t.get('image', ''),
                download_url = t.get('audio', ''),   # direct MP3 stream link
                asset_type   = 'audio_music',
                license      = t.get('license_ccurl', 'CC'),
                author       = t.get('artist_name', ''),
                duration     = duration,
                tags         = tags,
            ))

        try:
            total = int(data.get('headers', {}).get('results_fullcount', len(results)))
        except (ValueError, TypeError):
            total = len(results)

        has_more = (page * per_page) < total
        return {'results': results, 'total': total, 'has_more': has_more}
