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


def build_opener(source_key: str):
    """L'ouvreur urllib d'un connecteur, avec le proxy que la PORTÉE de sa source déclare.

    Jusqu'au 2026-09-21, chaque connecteur appelait `urllib.request.urlopen` directement.
    urllib lit bien `HTTP(S)_PROXY` dans l'environnement, mais IGNORE le réglage Django
    `WAMA_OUTBOUND_PROXY` que la brique commune honore (`common/utils/http_proxy.py`) : derrière
    le proxy de l'université, la médiathèque était la seule surface sortante à ne pas le suivre.

    Depuis le 2026-09-22 les connecteurs sont des sources du registre (`external_sources`,
    famille `media`) : le choix du proxy vient de `proxies_for(<clé>)`, comme pour toute source,
    au lieu d'être supposé ici. Traduction vers urllib, qui ne parle pas le format `requests` :
      • `None` (aucun proxy configuré) → AUCUN gestionnaire : urllib garde son comportement ;
      • des valeurs toutes `None` (portée LOCALE : proxy NEUTRALISÉ) → `ProxyHandler({})` — un
        dictionnaire à valeurs `None` passé tel quel ferait échouer urllib ;
      • sinon → les proxies déclarés.
    """
    from wama.common.external_sources import proxies_for
    proxies = proxies_for(source_key)
    if proxies is None:
        return urllib.request.build_opener()
    real = {scheme: url for scheme, url in proxies.items() if url}
    return urllib.request.build_opener(urllib.request.ProxyHandler(real))


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
        return build_opener(self.slug).open(req, timeout=timeout)

    def base_url(self) -> str:
        """L'adresse de base de ce connecteur, lue au REGISTRE des sources (sa clé = son slug).

        Plus de constante d'adresse dans les connecteurs depuis le 2026-09-22 : la garde
        `tests_external_sources` refuse toute recopie d'une adresse déclarée."""
        from wama.common.external_sources import base_url
        return base_url(self.slug)

    def download_bytes(self, download_url: str) -> bytes:
        """Télécharge le fichier et retourne ses octets. Override si besoin d'auth."""
        with self.open_url(download_url, timeout=60) as r:
            return r.read()
