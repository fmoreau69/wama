"""
WAMA Media Library — BaseProvider
Interface abstraite pour tous les connecteurs de sources media externes.
"""

import urllib.request
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

#: User-Agent par défaut (téléchargement). Chaque connecteur garde le sien pour ses recherches :
#: le proxy est la seule chose que le 2026-09-21 a changée, à dessein.
USER_AGENT = 'WAMA/1.0 (media library; +https://github.com/wama)'


def build_opener():
    """L'ouvreur urllib de TOUS les connecteurs, avec le proxy sortant de WAMA.

    Jusqu'au 2026-09-21, chaque connecteur appelait `urllib.request.urlopen` directement.
    urllib lit bien `HTTP(S)_PROXY` dans l'environnement, mais IGNORE le réglage Django
    `WAMA_OUTBOUND_PROXY` que la brique commune honore (`common/utils/http_proxy.py`) : derrière
    le proxy de l'université, la médiathèque était la seule surface sortante à ne pas le suivre.
    `outbound_proxies()` résout le réglage puis l'environnement ; quand aucun des deux n'est
    posé, on ne passe AUCUN gestionnaire et urllib garde exactement son comportement d'avant.
    """
    from wama.common.utils.http_proxy import outbound_proxies
    proxies = outbound_proxies()
    return urllib.request.build_opener(
        *([urllib.request.ProxyHandler(proxies)] if proxies else []))


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

    def open_url(self, url: str, timeout: float, headers: dict | None = None):
        """TOUTE requête sortante d'un connecteur passe ici — recherche comme téléchargement.

        Une garde le tient (`tests_providers.py`) : un connecteur qui rappellerait `urlopen`
        lui-même contournerait de nouveau le proxy, sans la moindre erreur.
        """
        req = urllib.request.Request(url, headers={'User-Agent': USER_AGENT, **(headers or {})})
        return build_opener().open(req, timeout=timeout)

    def download_bytes(self, download_url: str) -> bytes:
        """Télécharge le fichier et retourne ses octets. Override si besoin d'auth."""
        with self.open_url(download_url, timeout=60) as r:
            return r.read()
