"""
WAMA Transcriber - Video & YouTube Utilities
Extraction audio depuis vidéos et téléchargement YouTube
"""

import os
import shutil
import subprocess
import logging
from pathlib import Path
from typing import Optional, Tuple

logger = logging.getLogger(__name__)


def _get_ffmpeg_path() -> Optional[str]:
    """Trouve le chemin vers ffmpeg."""
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg:
        return ffmpeg

    candidates = [
        r"C:\ffmpeg\bin\ffmpeg.exe",
        r"C:\Program Files\ffmpeg\bin\ffmpeg.exe",
        r"C:\Program Files (x86)\ffmpeg\bin\ffmpeg.exe",
        "/usr/bin/ffmpeg",
        "/usr/local/bin/ffmpeg",
        "/opt/homebrew/bin/ffmpeg",
        "/mnt/c/ffmpeg/bin/ffmpeg.exe",
        "/mnt/c/Program Files/ffmpeg/bin/ffmpeg.exe",
    ]

    for candidate in candidates:
        if os.path.exists(candidate):
            return candidate
    return None


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
        RuntimeError: Si yt-dlp n'est pas installé ou si le téléchargement échoue
    """
    # Vérifier si yt-dlp est installé
    ytdlp = shutil.which("yt-dlp")
    if not ytdlp:
        try:
            import yt_dlp
            ytdlp = "yt_dlp"  # Utiliser le module Python
        except ImportError:
            raise RuntimeError(
                "yt-dlp not found. Please install it with: pip install yt-dlp"
            )

    os.makedirs(output_dir, exist_ok=True)

    try:
        # Configuration yt-dlp pour télécharger seulement l'audio
        import yt_dlp

        # Options avancées pour contourner les restrictions YouTube
        ydl_opts = {
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
            # Options supplémentaires
            'extractor_args': {
                'youtube': {
                    'player_client': ['android', 'web'],
                    'player_skip': ['webpage', 'configs'],
                }
            },
            'age_limit': None,
            'socket_timeout': 30,
            'retries': 10,
            'fragment_retries': 10,
            'skip_unavailable_fragments': True,
        }

        logger.info(f"Downloading audio from YouTube: {youtube_url}")

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            # Récupérer les informations de la vidéo
            try:
                info = ydl.extract_info(youtube_url, download=False)
                video_title = info.get('title', 'youtube_audio')
            except Exception as e:
                logger.warning(f"Could not extract info without download: {e}")
                # Fallback: télécharger directement et récupérer le titre après
                video_title = "youtube_audio"

            # Télécharger
            result = ydl.extract_info(youtube_url, download=True)

            # Mettre à jour le titre si disponible
            if result and result.get('title'):
                video_title = result['title']

            # Construire le chemin du fichier audio
            safe_title = "".join(c for c in video_title if c.isalnum() or c in (' ', '-', '_')).strip()
            if not safe_title:
                safe_title = "youtube_audio"

            audio_path = os.path.join(output_dir, f"{safe_title}.wav")

            # Chercher le fichier (yt-dlp peut modifier le nom)
            for file in os.listdir(output_dir):
                if file.endswith('.wav'):
                    # Vérifier si c'est notre fichier
                    file_path = os.path.join(output_dir, file)
                    if safe_title in file or os.path.getmtime(file_path) > (os.path.getmtime(output_dir) - 60):
                        audio_path = file_path
                        break

            if not os.path.exists(audio_path):
                # Chercher n'importe quel fichier WAV récent
                wav_files = [f for f in os.listdir(output_dir) if f.endswith('.wav')]
                if wav_files:
                    # Prendre le plus récent
                    wav_files.sort(key=lambda x: os.path.getmtime(os.path.join(output_dir, x)), reverse=True)
                    audio_path = os.path.join(output_dir, wav_files[0])

            if not os.path.exists(audio_path):
                raise RuntimeError("Audio file not found after download")

            logger.info(f"YouTube audio downloaded successfully: {audio_path}")
            return audio_path, video_title

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
