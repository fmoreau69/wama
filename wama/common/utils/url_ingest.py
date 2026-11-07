"""
url_ingest — Ingestion intelligente d'une URL vers un fichier local (COMMUN).

Décide page web vs média :
  - plateforme média (YouTube, Vimeo…) ou extension média → téléchargement du média
    (upload_media_from_url : yt_dlp / HTTP) ;
  - sinon, HEAD : une page web (Content-Type text/html) est gardée TELLE QUELLE en `.html`
    (décision de Fabien, 2026-10-13 : on garde l'original — 0,3 à 0,45 Mo mesurés pour une
    page GitHub ou Wikipedia —, et le texte se lit au traitement par `html_to_readable_text`) ;
  - sinon → téléchargement, avec reniflage HTML post-download de secours.

La même table de décision dit la NATURE d'une URL AVANT tout téléchargement (`url_nature`) :
une création de card la lit pour ne pas classer une vidéo YouTube en « document ».

Extrait du Describer (où la logique était dupliquée entre views.upload et
workers) pour réutilisation par toute app acceptant une entrée URL / un fichier
batch.
"""
import os
import re
import logging
from urllib.parse import unquote, urlparse

logger = logging.getLogger(__name__)

# Plateformes média (téléchargement direct, jamais traitées comme page web).
MEDIA_PLATFORM_DOMAINS = (
    'youtube.com', 'youtu.be', 'vimeo.com', 'dailymotion.com',
    'twitch.tv', 'soundcloud.com', 'bandcamp.com', 'mixcloud.com',
)
#: Parmi elles, celles qui servent un SON — leur page est un audio, pas une vidéo.
AUDIO_PLATFORM_DOMAINS = ('soundcloud.com', 'bandcamp.com', 'mixcloud.com')
#: Natures qu'on télécharge sans interroger l'en-tête (ni page web, ni document).
_MEDIA_NATURES = ('image', 'video', 'audio')
_BROWSER_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                  '(KHTML, like Gecko) Chrome/122 Safari/537.36',
    'Accept-Language': 'en-US,en;q=0.9',
}


def _host_in(url: str, domains) -> bool:
    """L'HÔTE de l'URL est-il l'un de ces domaines (ou un sous-domaine) ? Lu sur l'hôte et non
    sur la chaîne entière : `https://example.org/?ref=youtube.com` n'est pas YouTube."""
    host = (urlparse(str(url or '')).hostname or '').lower()
    return any(host == d or host.endswith('.' + d) for d in domains)


def is_media_platform(url: str) -> bool:
    """URL d'une plateforme média (vidéo ou son) — téléchargée par yt_dlp, jamais lue en page."""
    return _host_in(url, MEDIA_PLATFORM_DOMAINS)


#: Hôtes YouTube — dont l'adresse d'une vidéo se réduit à son identifiant (`canonical_media_url`).
_YOUTUBE_DOMAINS = ('youtube.com', 'youtu.be', 'youtube-nocookie.com')


def canonical_media_url(url: str) -> str:
    """L'adresse d'UNE vidéo de plateforme, débarrassée de ce qui n'est pas elle.

    Une vidéo ouverte DANS une playlist (`watch?v=<id>&list=<liste>&index=2`) porte l'état de
    lecture de la playlist : `list` la désigne, `index` est la position courante du lecteur — elle
    avance à chaque rechargement de la page, sans rapport avec la place de la vidéo dans la liste.
    Seul `v` dit la vidéo voulue (2026-11-07, Fabien : la 2ᵉ d'une playlist collée dans le Composer
    a importé la 5ᵉ — le téléchargement audio, sans `noplaylist`, tirait la liste entière et gardait
    un `.wav` au hasard). Rendue : `https://www.youtube.com/watch?v=<id>` (un temps de départ `t`
    n'est pas gardé : on télécharge le média entier). Hors YouTube, ou sans identifiant de vidéo
    (une playlist seule), l'adresse est rendue telle quelle — `ensure_single_media` la refusera."""
    from urllib.parse import parse_qs
    text = str(url or '').strip()
    if not _host_in(text, _YOUTUBE_DOMAINS):
        return text
    parsed = urlparse(text)
    host = (parsed.hostname or '').lower()
    video_id = ''
    if host == 'youtu.be' or host.endswith('.youtu.be'):
        video_id = parsed.path.strip('/').split('/')[0]
    else:
        video_id = (parse_qs(parsed.query).get('v') or [''])[0]
        if not video_id:
            parts = [p for p in parsed.path.split('/') if p]
            # /shorts/<id>, /live/<id>, /embed/<id> : l'identifiant est le segment qui suit.
            if len(parts) >= 2 and parts[0] in ('shorts', 'live', 'embed', 'v'):
                video_id = parts[1]
    video_id = re.sub(r'[^\w\-]', '', video_id)
    return f'https://www.youtube.com/watch?v={video_id}' if video_id else text


class PlaylistNotAMedia(ValueError):
    """Une adresse de playlist là où l'on attend UN média — un refus, pas un échec à retenter
    par un autre téléchargeur."""


def ensure_single_media(info: dict, url: str) -> dict:
    """Le résultat de yt_dlp est-il UN média ? Une playlist seule (adresse sans vidéo désignée)
    rendrait N fichiers pour une card qui n'en prend qu'un : refusée, en le disant — jamais un
    fichier pris au hasard parmi eux."""
    if isinstance(info, dict) and (info.get('_type') == 'playlist' or info.get('entries') is not None):
        raise PlaylistNotAMedia(
            "Cette adresse désigne une playlist, pas une vidéo : ouvrez la vidéo voulue et "
            f"collez son adresse ({url}).")
    return info


def url_nature(url: str) -> str:
    """Nature d'une URL connaissable AVANT de la télécharger, dans le vocabulaire commun
    (`app_registry.category_of_path`) — ou '' quand seul le téléchargement le dira.

      - plateforme média → 'video' ('audio' pour une plateforme de son) ;
      - chemin à extension → la catégorie de l'extension (`.mp4` → 'video', `.html` → 'document') ;
      - sans extension (`github.com/turgu1/uPDF`) → '' : une page ou un fichier, l'en-tête le dira.
    """
    if is_media_platform(url):
        return 'audio' if _host_in(url, AUDIO_PLATFORM_DOMAINS) else 'video'
    ext = os.path.splitext(unquote(urlparse(str(url or '')).path))[1].lower()
    if not ext:
        return ''
    from wama.common.app_registry import category_of_path
    return category_of_path('x' + ext)


def html_to_readable_text(html: str) -> str:
    """Convert HTML to readable plain text using BeautifulSoup + lxml."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, 'lxml')

    # Get page title
    title_tag = soup.find('title')
    title_text = title_tag.get_text(strip=True) if title_tag else ''

    # Remove non-content elements
    for tag in soup(['script', 'style', 'nav', 'footer', 'aside',
                     'noscript', 'meta', 'link', 'button', 'svg', 'form',
                     'iframe', 'template', 'header']):
        tag.decompose()

    # Find main content area.
    # Specific content containers are preferred over generic <main> (which on GitHub
    # includes the full page — file tree, navigation, sidebar — not just the README).
    main = (
        soup.find(id='readme') or          # GitHub README
        soup.find(class_='markdown-body') or  # GitHub/GitLab markdown render
        soup.find('article') or
        soup.find(attrs={'role': 'main'}) or
        soup.find('main') or
        soup.find(id='content') or
        soup.find(class_='content') or
        soup.body or
        soup
    )

    text = main.get_text(separator='\n', strip=True)
    text = re.sub(r'\n{3,}', '\n\n', text)

    if title_text:
        text = f"# {title_text}\n\n{text}"

    return text.strip()


def _page_basename(url: str) -> str:
    """Nom de fichier d'une page, tiré des deux derniers segments de son chemin
    (`github.com/turgu1/uPDF` → `turgu1_uPDF`), `page` à défaut."""
    parts = [p for p in urlparse(url).path.split('/') if p]
    base = '_'.join(parts[-2:]) if len(parts) >= 2 else (parts[-1] if parts else 'page')
    return re.sub(r'[^\w\-]', '_', base)[:60] or 'page'


def _get_page(url: str):
    """GET d'une page sous la garde de sortie : l'URL saisie AVANT la requête, puis chaque
    REDIRECTION suivie — une cible publique peut rediriger vers une adresse interne, et ne
    valider que l'URL saisie laisserait passer exactement ce qu'on cherche à empêcher."""
    import requests
    from wama.common.utils.url_guard import guarded_request
    # Chaque saut est jugé AVANT d'être envoyé (`guarded_request`, 2026-11-06).
    resp = guarded_request('GET', url, headers=_BROWSER_HEADERS, timeout=20)
    resp.raise_for_status()
    return resp


def fetch_html_page(url: str, dest_dir: str) -> str:
    """Enregistre une page web TELLE QUELLE (`<nom>.html`, octets d'origine — l'encodage déclaré
    par la page reste valable) et rend son chemin."""
    resp = _get_page(url)
    save_path = os.path.join(dest_dir, f"{_page_basename(url)}.html")
    with open(save_path, 'wb') as f:
        f.write(resp.content)
    return save_path


def _sniff_downloaded(path: str, url: str) -> str:
    """Un téléchargement sans extension (ou en `.html`) qui EST une page reçoit l'extension
    `.html` ; sans extension et non-HTML, `.txt` (comportement conservé depuis describer.upload :
    le fichier reste identifiable et exportable). Rend le chemin final."""
    name = os.path.basename(path)
    ext = name.rsplit('.', 1)[-1].lower() if '.' in name else ''
    if ext and ext not in ('html', 'htm'):
        return path
    try:
        with open(path, 'rb') as fh:
            sample = fh.read(2048).lower()
        if b'<html' in sample or b'<!doctype' in sample:
            if ext:
                return path
            new_path = os.path.join(os.path.dirname(path), f"{_page_basename(url)}.html")
        elif not ext:
            new_path = path + '.txt'
        else:
            return path
        os.rename(path, new_path)
        return new_path
    except Exception as ex:
        logger.warning(f"[url_ingest] Post-download sniff failed: {ex}")
        return path


def fetch_url_content(url: str, dest_dir: str) -> str:
    """URL -> chemin de fichier local sous dest_dir.

    Page web -> `.html` gardé tel quel ; média -> fichier téléchargé. Réutilise
    upload_media_from_url (plateformes/HTTP) + reniflage HTML post-download.
    """
    from wama.common.utils.video_utils import upload_media_from_url
    from wama.common.utils.url_guard import UrlRefusee, guarded_request, verifier_url

    # Validée ICI aussi, et pas seulement dans les appelés : le `requests.head` ci-dessous est
    # une sortie réseau à part entière — c'est déjà une sonde exploitable.
    verifier_url(url)

    is_html_page = False
    if url_nature(url) not in _MEDIA_NATURES:
        try:
            import requests
            # Ce HEAD suit les redirections : chaque saut est jugé AVANT d'être envoyé
            # (`guarded_request`) — et le refus doit SORTIR du try, pas être avalé.
            head = guarded_request('HEAD', url, timeout=10,
                                   headers={'User-Agent': 'Mozilla/5.0'})
            is_html_page = 'text/html' in head.headers.get('Content-Type', '')
        except UrlRefusee:
            raise
        except Exception:
            pass

    if is_html_page:
        return fetch_html_page(url, dest_dir)
    return _sniff_downloaded(upload_media_from_url(url, dest_dir), url)
