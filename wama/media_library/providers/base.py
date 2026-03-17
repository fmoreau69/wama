"""
WAMA Media Library — BaseProvider
Interface abstraite pour tous les connecteurs de sources media externes.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class SearchResult:
    """Résultat de recherche normalisé, indépendant du provider."""
    provider_id:  str           # ID interne au provider
    title:        str
    preview_url:  str           # URL miniature/aperçu (publique)
    download_url: str           # URL de téléchargement direct
    asset_type:   str           # 'image', 'video', 'voice', …
    license:      str  = ''
    author:       str  = ''
    duration:     float = 0.0   # secondes
    width:        int  = 0
    height:       int  = 0
    file_size:    int  = 0      # bytes
    tags:         str  = ''     # CSV

    def to_dict(self):
        return {
            'provider_id':  self.provider_id,
            'title':        self.title,
            'preview_url':  self.preview_url,
            '_download_url': self.download_url,  # prefixed _ : CDN URL, not an API secret
            'asset_type':   self.asset_type,
            'license':      self.license,
            'author':       self.author,
            'duration':     self.duration,
            'width':        self.width,
            'height':       self.height,
            'file_size':    self.file_size,
            'tags':         self.tags,
        }


class BaseProvider(ABC):
    """
    Interface abstraite pour un connecteur de source media.
    Toutes les clés API restent côté serveur — jamais exposées au JS.
    """
    slug:             str  = ''
    name:             str  = ''
    supported_types:  list = []
    requires_api_key: bool = True

    def __init__(self, api_key: str = ''):
        self.api_key = api_key

    @abstractmethod
    def search(self, query: str, asset_type: str, page: int = 1, per_page: int = 20) -> dict:
        """
        Returns:
            {
                'results':  [SearchResult],
                'total':    int,
                'has_more': bool,
                'error':    str | None,   # présent uniquement en cas d'erreur
            }
        """
        ...

    def download_bytes(self, download_url: str) -> bytes:
        """Télécharge le fichier et retourne ses octets. Override si besoin d'auth."""
        import urllib.request
        req = urllib.request.Request(
            download_url,
            headers={'User-Agent': 'WAMA/1.0 (media library; +https://github.com/wama)'},
        )
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.read()
