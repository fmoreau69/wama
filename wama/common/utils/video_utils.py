"""
WAMA Common - Video & YouTube Utilities
Extraction audio depuis vidéos et téléchargement YouTube
"""

import os
import shutil
import subprocess
import logging
import requests
from pathlib import Path
from urllib.parse import urlparse
from typing import Optional, Tuple

import yt_dlp

from wama.anonymizer.utils.media_utils import get_unique_filename

logger = logging.getLogger(__name__)


def _get_ffmpeg_path():
    """DÉLÈGUE à la brique ffmpeg_utils (audit 2026-07-06 : cette copie locale n'avait
    ni test fonctionnel WSL2, ni fallback imageio, ni escape hatch FFMPEG_BINARY)."""
    from wama.common.utils.ffmpeg_utils import get_ffmpeg_exe
    return get_ffmpeg_exe()


def _js_runtimes():
    """Le moteur JavaScript que yt_dlp exige pour YouTube (`deno`, paquet pip du venv).

    Sans lui, YouTube ne livre plus que des formats dégradés. Son chemin est passé
    explicitement : un worker lancé par `venv_linux/bin/celery` n'a pas le `bin/` du venv
    dans son PATH, où yt_dlp le chercherait sinon.
    """
    try:
        from deno import find_deno_bin
        return {'deno': {'path': find_deno_bin()}}
    except Exception:
        return {'deno': {}}


def get_ffprobe_path():
    """DÉLÈGUE à la brique ffmpeg_utils (cf. _get_ffmpeg_path)."""
    from wama.common.utils.ffmpeg_utils import get_ffprobe_exe
    return get_ffprobe_exe()


def get_media_info(file_path: str) -> dict:
    """
    Extract metadata from an image or video file.

    Args:
        file_path: Path to the media file

    Returns:
        dict with keys:
            - media_type: 'image' or 'video'
            - width: int
            - height: int
            - fps: float (1 for images)
            - duration: float in seconds (0 for images)
            - file_size: int in bytes
            - properties: str formatted as "WxH (fps)"

    Raises:
        FileNotFoundError: If file does not exist
        ValueError: If file cannot be opened or analyzed
    """
    import cv2
    from PIL import Image
    import mimetypes

    if not os.path.exists(file_path):
        raise FileNotFoundError(f"File does not exist: {file_path}")

    file_size = os.path.getsize(file_path)
    mime_type, _ = mimetypes.guess_type(file_path)

    result = {
        'media_type': None,
        'width': 0,
        'height': 0,
        'fps': 0,
        'duration': 0,
        'file_size': file_size,
        'properties': '',
    }

    # Check if it's an image
    if mime_type and mime_type.startswith("image/"):
        try:
            with Image.open(file_path) as img:
                result['width'], result['height'] = img.size
            result['media_type'] = 'image'
            result['fps'] = 1
            result['duration'] = 0
            result['properties'] = f"{result['width']}x{result['height']} (1fps)"
            logger.info(f"Image analyzed: {result['width']}x{result['height']}")
            return result
        except Exception as e:
            raise ValueError(f"Error opening image: {e}")

    # Assume it's a video
    vid = None
    try:
        vid = cv2.VideoCapture(file_path)
        if not vid.isOpened():
            raise ValueError(f"Could not open video file: {file_path}")

        fps = vid.get(cv2.CAP_PROP_FPS)
        if not fps or fps <= 0:
            fps = 25  # Default fallback

        width = int(vid.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(vid.get(cv2.CAP_PROP_FRAME_HEIGHT))
        total_frames = vid.get(cv2.CAP_PROP_FRAME_COUNT)
        duration = total_frames / fps if fps > 0 else 0

        result['media_type'] = 'video'
        result['width'] = width
        result['height'] = height
        result['fps'] = fps
        result['duration'] = duration
        result['properties'] = f"{width}x{height} ({fps:.2f}fps)"

        logger.info(f"Video analyzed: {width}x{height}, fps={fps:.2f}, duration={duration:.2f}s")
        return result

    except Exception as e:
        raise ValueError(f"Error analyzing video: {e}")
    finally:
        if vid is not None:
            vid.release()


def _filename_from_response(url, response):
    """Nom de fichier fiable pour un download HTTP générique.

    Priorité : en-tête Content-Disposition (filename*/filename) → basename de
    l'URL → nom générique + extension déduite du Content-Type. Évite le fallback
    trompeur 'video.mp4' pour les documents/pages servis sans nom de fichier
    (pdf, docx, contenu via redirection…).
    """
    import re
    import mimetypes
    from urllib.parse import unquote

    # 1) Content-Disposition (filename*=UTF-8''… prioritaire sur filename="…")
    cd = response.headers.get('Content-Disposition', '') if response is not None else ''
    if cd:
        m = re.search(r"filename\*=(?:UTF-8'')?([^;]+)", cd, flags=re.IGNORECASE) \
            or re.search(r'filename="?([^";]+)"?', cd, flags=re.IGNORECASE)
        if m:
            name = os.path.basename(unquote(m.group(1).strip().strip('"')))
            if name:
                return name

    # 2) basename de l'URL — DÉCODÉ (unquote AVANT basename : un %2F redevient '/' et
    # tombe au basename). Sans ça, un lien type Wikipédia enregistrait le fichier avec
    # ses %C3%A9 dans le NOM, que l'inspecteur affichait tel quel (constat Fabien 17/08 —
    # « Au_th%C3%A9%C3%A2tre_… ») ; les items déjà ingérés gardent leur ancien nom.
    name = os.path.basename(unquote(urlparse(url).path))

    # 3) extension déduite du Content-Type si le nom n'en a pas
    if not os.path.splitext(name)[1]:
        ct = (response.headers.get('Content-Type', '') if response is not None else '').split(';')[0].strip()
        guessed = mimetypes.guess_extension(ct) if ct else None
        name = name or 'download'
        if guessed and not name.endswith(guessed):
            name = name + guessed
    return name or 'download'


def _download_one(ydl, url: str) -> dict:
    """UN média par yt_dlp : les informations lues d'abord (rien n'est téléchargé), refusées si
    elles désignent une playlist (`url_ingest.ensure_single_media`), puis le téléchargement — sur
    ces mêmes informations, sans seconde extraction (`process_ie_result`, le geste de
    `download_with_info_file`). Rend les informations du média téléchargé."""
    from wama.common.utils.url_ingest import ensure_single_media
    info = ensure_single_media(ydl.extract_info(url, download=False), url)
    return ydl.process_ie_result(info, download=True)


def _downloaded_path(ydl, info: dict, ext: str = '') -> str:
    """Le fichier que yt_dlp a ÉCRIT pour ce média, post-traitements compris (extraction audio,
    conversion) : lu sur ses informations (`requested_downloads[].filepath`), jamais deviné parmi
    les fichiers du dossier. `ext` : l'extension que le post-traitement pose, quand l'information
    manque (version ancienne de yt_dlp)."""
    for download in (info or {}).get('requested_downloads') or ():
        path = download.get('filepath') or download.get('_filename')
        if path and os.path.exists(path):
            return path
    path = ydl.prepare_filename(info)
    if ext:
        path = os.path.splitext(path)[0] + ext
    if not os.path.exists(path):
        raise RuntimeError(f"Fichier téléchargé introuvable ({os.path.basename(path)})")
    return path


def upload_media_from_url(url, output_path, *, with_title=False):
    """Download a media file from a URL using yt_dlp (with robust options) or direct HTTP.

    For YouTube URLs, try yt_dlp with youtube-specific extractor args and proper headers. If that
    fails, fallback to pytube. For generic HTTP URLs, stream with a desktop-like User-Agent.

    `with_title` : rend `(chemin, titre)` — le titre du média sur sa plateforme, '' pour un
    fichier servi en HTTP — au lieu du seul chemin. C'est ce que lit l'ingest commun pour nommer
    l'entrée (`source_ingest._download`), dans les trois modes, comme le téléchargement audio.

    ⚠ Point d'entrée de TÉLÉCHARGEMENT piloté par une saisie utilisateur (champ URL, fichier de
    lot, ingest déclaratif) : la cible est validée AVANT toute sortie réseau — sans quoi le
    serveur interroge le réseau interne avec ses droits à lui (SSRF, cf. `url_guard`).
    """
    def done(path, title=''):
        return (path, title or '') if with_title else path

    from wama.common.utils.url_guard import UrlRefusee, guarded_request, verifier_url
    from wama.common.utils.url_ingest import PlaylistNotAMedia, canonical_media_url, is_media_platform
    verifier_url(url)
    # La vidéo désignée, jamais l'état de lecture de sa playlist (`list`, `index`).
    url = canonical_media_url(url)
    try:
        # Plateformes média : la MÊME table que la décision page/média (`url_ingest`) — une
        # URL Vimeo ou SoundCloud partait jusque-là au GET générique, qui rendait sa page HTML.
        if is_media_platform(url):
            ydl_opts = {
                # La meilleure qualité LISIBLE par nos traitements : H.264 (YouTube s'y arrête
                # à 1080p). Le « meilleur » brut est de l'AV1 4K, qu'OpenCV ne décode pas
                # (mesuré le 2026-10-14 : 244 Mo illisibles, contre 84 Mo lus en 1080p).
                'format': ('bestvideo[vcodec^=avc1]+bestaudio[ext=m4a]/best[vcodec^=avc1]'
                           '/bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio/best'),
                'merge_output_format': 'mp4',
                'outtmpl': os.path.join(output_path, '%(title)s.%(ext)s'),
                'noplaylist': True,
                'quiet': False,  # Show progress for debugging
                'retries': 5,
                'fragment_retries': 5,
                'sleep_interval_requests': 2,
                'http_headers': {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122 Safari/537.36',
                    'Accept-Language': 'en-US,en;q=0.9',
                    'Referer': 'https://www.youtube.com/',
                },
                # Clients du lecteur YouTube : ceux que yt_dlp choisit. Les forcer à
                # `android, web` ne laissait plus que le format 18 (360p) — mesuré le 2026-10-14.
                'js_runtimes': _js_runtimes(),
                'nocheckcertificate': True,
                'overwrites': False,
                'concurrent_fragment_downloads': 4,  # Speed up download with more threads
                # Post-processing to ensure best quality
                'postprocessors': [{
                    'key': 'FFmpegVideoConvertor',
                    'preferedformat': 'mp4',
                }],
            }
            try:
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = _download_one(ydl, url)
                    # Le fichier tel que yt_dlp l'a nommé (le titre). Il n'est plus renommé : le
                    # « nom unique » cherché ici voyait ce fichier lui-même et lui ajoutait un
                    # suffixe aléatoire à chaque fois (`Titre_df521730.mp4`, 2026-11-07) — le
                    # dossier est celui du téléchargement, aucun autre fichier n'y entre en conflit.
                    return done(_downloaded_path(ydl, info, '.mp4'), (info or {}).get('title'))
            except PlaylistNotAMedia:
                raise                    # un refus : aucun autre téléchargeur n'y changerait rien
            except Exception as yerr:
                # Repli pytube : YouTube seulement (pytube ne connaît pas les autres plateformes).
                if not ('youtube.com' in url or 'youtu.be' in url):
                    raise ValueError(f"Platform download failed (yt_dlp): {yerr}")
                try:
                    from pytube import YouTube
                    print(f"[YouTube Download] yt_dlp failed, trying pytube fallback: {yerr}")
                    yt = YouTube(url)

                    # Try to get the highest resolution stream (adaptive or progressive)
                    # First try: highest resolution adaptive video stream
                    stream = yt.streams.filter(adaptive=True, file_extension='mp4').order_by('resolution').desc().first()

                    if stream is None:
                        # Second try: progressive streams (lower quality but has audio)
                        print("[YouTube Download] No adaptive stream found, trying progressive...")
                        stream = (
                            yt.streams
                            .filter(progressive=True, file_extension='mp4')
                            .order_by('resolution')
                            .desc()
                            .first()
                        )

                    if stream is None:
                        # Last resort: any mp4 stream
                        print("[YouTube Download] No progressive stream found, trying any mp4...")
                        stream = yt.streams.filter(file_extension='mp4').first()

                    if stream is None:
                        raise ValueError("No suitable stream found (mp4)")

                    print(f"[YouTube Download] Using stream: {stream.resolution} - {stream.mime_type}")
                    temp_filename = stream.default_filename or 'video.mp4'
                    unique_filename = get_unique_filename(output_path, temp_filename)
                    save_path = os.path.join(output_path, unique_filename)
                    stream.download(output_path=output_path, filename=unique_filename)
                    print(f"[YouTube Download] Downloaded successfully: {save_path}")
                    return done(save_path, getattr(yt, 'title', ''))
                except Exception as pterr:
                    raise ValueError(f"YouTube download failed (yt_dlp: {yerr}); fallback pytube failed: {pterr}")

        # Generic HTTP download
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122 Safari/537.36',
            'Accept': '*/*',
            'Referer': url,
        }
        # Chaque saut de redirection est jugé AVANT d'être envoyé (`guarded_request`,
        # 2026-11-06) — sinon une adresse publique mène le serveur sur son réseau interne. Le
        # refus remonte TEL QUEL (pas emballé en « Download failed »).
        response = guarded_request('GET', url, stream=True, timeout=20, headers=headers)
        response.raise_for_status()
        filename = _filename_from_response(url, response)
        unique_filename = get_unique_filename(output_path, filename)
        save_path = os.path.join(output_path, unique_filename)

        with open(save_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
        return done(save_path)

    except (UrlRefusee, PlaylistNotAMedia):
        raise
    except Exception as e:
        raise ValueError(f"Download failed: {e}")


def extract_audio_from_video(video_path: str, output_audio_path: Optional[str] = None) -> str:
    """
    Extrait l'audio d'un fichier vidéo.

    Args:
        video_path: Chemin vers le fichier vidéo
        output_audio_path: Chemin de sortie (optionnel, sinon auto-généré)

    Returns:
        str: Chemin vers le fichier audio extrait

    Raises:
        RuntimeError: Si ffmpeg n'est pas trouvé ou si l'extraction échoue
    """
    ffmpeg = _get_ffmpeg_path()
    if not ffmpeg:
        raise RuntimeError(
            "ffmpeg not found. Please install ffmpeg to extract audio from videos."
        )

    if not os.path.exists(video_path):
        raise FileNotFoundError(f"Video file not found: {video_path}")

    # Générer le chemin de sortie si non fourni
    if output_audio_path is None:
        video_dir = os.path.dirname(video_path)
        video_name = Path(video_path).stem
        output_audio_path = os.path.join(video_dir, f"{video_name}_audio.wav")

    try:
        # Extraire l'audio avec ffmpeg
        # -vn: pas de vidéo
        # -acodec pcm_s16le: codec audio WAV
        # -ar 16000: sample rate 16kHz (optimal pour Whisper)
        # -ac 1: mono
        cmd = [
            ffmpeg,
            "-i", video_path,
            "-vn",  # Pas de vidéo
            "-acodec", "pcm_s16le",  # WAV PCM
            "-ar", "16000",  # 16kHz
            "-ac", "1",  # Mono
            "-y",  # Overwrite output
            output_audio_path
        ]

        logger.info(f"Extracting audio from video: {video_path}")
        result = subprocess.run(
            cmd,
            check=True,
            capture_output=True,
            text=True
        )

        if not os.path.exists(output_audio_path):
            raise RuntimeError("Audio extraction failed: output file not created")

        logger.info(f"Audio extracted successfully to: {output_audio_path}")
        return output_audio_path

    except subprocess.CalledProcessError as e:
        error_msg = f"ffmpeg failed: {e.stderr}"
        logger.error(error_msg)
        raise RuntimeError(error_msg)
    except Exception as e:
        logger.error(f"Audio extraction error: {e}")
        raise


def download_youtube_audio(youtube_url: str, output_dir: str) -> Tuple[str, str]:
    """
    Télécharge l'audio d'une vidéo YouTube.

    Args:
        youtube_url: URL de la vidéo YouTube
        output_dir: Dossier de destination

    Returns:
        Tuple[str, str]: (chemin_audio, titre_video)

    Raises:
        RuntimeError: Si le téléchargement échoue ; `PlaylistNotAMedia` (une `ValueError`) si
        l'adresse désigne une playlist sans vidéo.

    Une vidéo ouverte dans une playlist est téléchargée SEULE (`canonical_media_url` +
    `noplaylist`) : jusqu'au 2026-11-07, ce téléchargement tirait la playlist entière et rendait
    le premier `.wav` récent du dossier — la 5ᵉ chanson pour la 2ᵉ demandée. Le fichier rendu est
    celui que yt_dlp dit avoir écrit (`_downloaded_path`), le titre celui de la vidéo.
    """
    from wama.common.utils.url_guard import verifier_url
    from wama.common.utils.url_ingest import PlaylistNotAMedia, canonical_media_url
    verifier_url(youtube_url)
    youtube_url = canonical_media_url(youtube_url)
    os.makedirs(output_dir, exist_ok=True)

    try:
        # Options avancées pour contourner les restrictions YouTube
        ydl_opts = {
            'noplaylist': True,
            'format': 'bestaudio/best',
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'wav',
                'preferredquality': '192',
            }],
            'outtmpl': os.path.join(output_dir, '%(title)s.%(ext)s'),
            'quiet': False,
            'no_warnings': False,
            # Options pour contourner les restrictions
            'nocheckcertificate': True,
            'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'referer': 'https://www.youtube.com/',
            'http_headers': {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'Accept-Language': 'en-us,en;q=0.5',
                'Sec-Fetch-Mode': 'navigate',
            },
            # Clients du lecteur : ceux de yt_dlp, comme `upload_media_from_url`.
            'js_runtimes': _js_runtimes(),
            'age_limit': None,
            'socket_timeout': 30,
            'retries': 10,
            'fragment_retries': 10,
            'skip_unavailable_fragments': True,
        }

        logger.info(f"Downloading audio from YouTube: {youtube_url}")

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = _download_one(ydl, youtube_url)
            audio_path = _downloaded_path(ydl, info, '.wav')
            video_title = (info or {}).get('title') or os.path.splitext(
                os.path.basename(audio_path))[0]
            logger.info(f"YouTube audio downloaded successfully: {audio_path}")
            return audio_path, video_title

    except PlaylistNotAMedia:
        raise
    except Exception as e:
        error_msg = f"YouTube download failed: {str(e)}"
        logger.error(error_msg)

        # Messages d'erreur plus explicites
        if "403" in str(e) or "Forbidden" in str(e):
            error_msg += "\n\nSolution: Essayez de mettre à jour yt-dlp avec: pip install --upgrade yt-dlp"
        elif "unable to download" in str(e).lower():
            error_msg += "\n\nLa vidéo pourrait être restreinte géographiquement ou privée."

        raise RuntimeError(error_msg)


def is_video_file(filename: str) -> bool:
    """Vérifie si un fichier est une vidéo basé sur son extension."""
    video_extensions = {
        '.mp4', '.avi', '.mkv', '.mov', '.wmv', '.flv',
        '.webm', '.m4v', '.mpg', '.mpeg', '.3gp'
    }
    ext = os.path.splitext(filename)[1].lower()
    return ext in video_extensions


def is_audio_file(filename: str) -> bool:
    """Vérifie si un fichier est un audio basé sur son extension."""
    audio_extensions = {
        '.mp3', '.wav', '.flac', '.m4a', '.aac',
        '.ogg', '.wma', '.opus', '.aiff'
    }
    ext = os.path.splitext(filename)[1].lower()
    return ext in audio_extensions


def is_image_file(filename: str) -> bool:
    """Vérifie si un fichier est une image basé sur son extension."""
    image_extensions = {
        '.jpg', '.jpeg', '.png', '.bmp', '.gif',
        '.webp', '.tif', '.tiff', '.heic', '.heif',
    }
    ext = os.path.splitext(filename)[1].lower()
    return ext in image_extensions


# Alias for the standalone anonymizer's `is_image()` API, kept for callers
# that still use the historical name.
is_image = is_image_file


def convert_video_to_web_compatible(input_path: str, output_path: Optional[str] = None) -> str:
    """
    Convertit une vidéo en format compatible web (H.264/AAC dans conteneur MP4).

    Cette fonction est nécessaire car OpenCV écrit des vidéos avec le codec mp4v
    qui n'est pas lisible directement dans les navigateurs web.

    Args:
        input_path: Chemin vers la vidéo source
        output_path: Chemin de sortie (optionnel, sinon remplace le fichier source)

    Returns:
        str: Chemin vers la vidéo convertie

    Raises:
        RuntimeError: Si ffmpeg n'est pas trouvé ou si la conversion échoue
    """
    ffmpeg = _get_ffmpeg_path()
    if not ffmpeg:
        logger.warning("ffmpeg not found - video may not play in browser")
        return input_path

    if not os.path.exists(input_path):
        raise FileNotFoundError(f"Video file not found: {input_path}")

    # Si pas de chemin de sortie, créer un fichier temporaire puis remplacer
    replace_original = output_path is None
    if replace_original:
        output_path = input_path.replace('.mp4', '_web.mp4')

    try:
        # Convertir en H.264 avec AAC audio
        # -c:v libx264: codec vidéo H.264
        # -preset fast: bon compromis vitesse/qualité
        # -crf 23: qualité (18-28, plus bas = meilleure qualité)
        # -c:a aac: codec audio AAC
        # -movflags +faststart: permet le streaming progressif
        cmd = [
            ffmpeg,
            "-i", input_path,
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "23",
            "-c:a", "aac",
            "-b:a", "128k",
            "-movflags", "+faststart",
            "-y",  # Overwrite output
            output_path
        ]

        logger.info(f"Converting video to web-compatible format: {input_path}")
        result = subprocess.run(
            cmd,
            check=True,
            capture_output=True,
            text=True
        )

        if not os.path.exists(output_path):
            raise RuntimeError("Video conversion failed: output file not created")

        # Si on remplace l'original, supprimer l'ancien et renommer le nouveau
        if replace_original:
            os.remove(input_path)
            os.rename(output_path, input_path)
            output_path = input_path

        logger.info(f"Video converted successfully: {output_path}")
        return output_path

    except subprocess.CalledProcessError as e:
        error_msg = f"ffmpeg conversion failed: {e.stderr}"
        logger.error(error_msg)
        # Ne pas lever d'exception, retourner le fichier original
        logger.warning("Returning original video file")
        return input_path
    except Exception as e:
        logger.error(f"Video conversion error: {e}")
        return input_path
