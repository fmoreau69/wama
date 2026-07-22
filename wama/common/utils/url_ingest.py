"""
url_ingest — Ingestion intelligente d'une URL vers un fichier local (COMMUN).

Décide page web vs média :
  - page web (Content-Type text/html, hors plateforme média / hors extension
    média) -> extraction du TEXTE LISIBLE complet (BeautifulSoup) dans un .txt ;
  - sinon -> téléchargement du média (upload_media_from_url : YouTube yt_dlp / HTTP),
    avec sniff HTML post-download de secours.

Extrait du Describer (où la logique était dupliquée entre views.upload et
workers) pour réutilisation par toute app acceptant une entrée URL / un fichier
batch. NE PERD RIEN : la lecture de page web complète est conservée ici.
"""
import os
import re
import logging

logger = logging.getLogger(__name__)

# Plateformes média (téléchargement direct, jamais traitées comme page web).
MEDIA_PLATFORM_DOMAINS = (
    'youtube.com', 'youtu.be', 'vimeo.com', 'dailymotion.com',
    'twitch.tv', 'soundcloud.com', 'bandcamp.com', 'mixcloud.com',
)
MEDIA_EXTS = ('.mp4', '.webm', '.mkv', '.avi', '.mov',
              '.mp3', '.wav', '.flac', '.ogg', '.m4a',
              '.jpg', '.jpeg', '.png', '.gif', '.webp')


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




def fetch_html_as_text(url: str, temp_dir: str) -> str:
    """
    Fetch a web page and save its readable text content as a .txt file.
    Uses BeautifulSoup + lxml to strip markup and extract meaningful content.
    Returns the path to the saved .txt file.
    """
    import re
    import requests
    from urllib.parse import urlparse
    from bs4 import BeautifulSoup

    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                      '(KHTML, like Gecko) Chrome/122 Safari/537.36',
        'Accept-Language': 'en-US,en;q=0.9',
    }
    resp = requests.get(url, headers=headers, timeout=20)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, 'lxml')

    title_tag = soup.find('title')
    title_text = title_tag.get_text(strip=True) if title_tag else ''

    for tag in soup(['script', 'style', 'nav', 'footer', 'aside',
                     'noscript', 'meta', 'link', 'button', 'svg', 'form',
                     'iframe', 'template', 'header']):
        tag.decompose()

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

    # Build a clean filename from the URL path
    parsed = urlparse(url)
    path_parts = [p for p in parsed.path.split('/') if p]
    base = '_'.join(path_parts[-2:]) if len(path_parts) >= 2 else (path_parts[-1] if path_parts else 'page')
    base = re.sub(r'[^\w\-]', '_', base)[:60] or 'page'
    save_path = os.path.join(temp_dir, f"{base}.txt")

    with open(save_path, 'w', encoding='utf-8') as f:
        f.write(text)

    return save_path

logger = logging.getLogger(__name__)




def fetch_url_content(url: str, dest_dir: str) -> str:
    """URL -> chemin de fichier local sous dest_dir.

    Page web -> .txt (texte lisible) ; média -> fichier téléchargé. Réutilise
    upload_media_from_url (YouTube/HTTP) + sniff HTML post-download.
    """
    from wama.common.utils.video_utils import upload_media_from_url

    is_media_platform = any(d in url for d in MEDIA_PLATFORM_DOMAINS)
    has_media_ext = url.lower().split('?')[0].endswith(MEDIA_EXTS)

    is_html_page = False
    if not is_media_platform and not has_media_ext:
        try:
            import requests
            head = requests.head(url, timeout=10, allow_redirects=True,
                                 headers={'User-Agent': 'Mozilla/5.0'})
            is_html_page = 'text/html' in head.headers.get('Content-Type', '')
        except Exception:
            pass

    if is_html_page:
        return fetch_html_as_text(url, dest_dir)

    downloaded_path = upload_media_from_url(url, dest_dir)
    name = os.path.basename(downloaded_path)
    ext = name.rsplit('.', 1)[-1].lower() if '.' in name else ''
    if not ext or ext in ('html', 'htm'):
        try:
            with open(downloaded_path, 'rb') as fh:
                sample = fh.read(2048).lower()
            if b'<html' in sample or b'<!doctype' in sample:
                with open(downloaded_path, 'r', encoding='utf-8', errors='replace') as fh:
                    html = fh.read()
                text = html_to_readable_text(html)
                from urllib.parse import urlparse
                parts = [p for p in urlparse(url).path.split('/') if p]
                base = '_'.join(parts[-2:]) if len(parts) >= 2 else (parts[-1] if parts else 'page')
                base = re.sub(r'[^\w\-]', '_', base)[:60] or 'page'
                new_path = os.path.join(dest_dir, f"{base}.txt")
                with open(new_path, 'w', encoding='utf-8') as fh:
                    fh.write(text)
                os.remove(downloaded_path)
                downloaded_path = new_path
            elif not ext:
                # Fichier téléchargé sans extension et non-HTML : nommer .txt
                # pour qu'il reste identifiable/exportable (comportement conservé
                # depuis describer.upload).
                new_path = downloaded_path + '.txt'
                os.rename(downloaded_path, new_path)
                downloaded_path = new_path
        except Exception as ex:
            logger.warning(f"[url_ingest] Post-download sniff failed: {ex}")

    return downloaded_path
