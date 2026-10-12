"""
Backend VIDÉO du describer — extraction d'images (ffmpeg) + légendes (BLIP par défaut, ou le
modèle de vision désigné) + transcription de la piste son (Whisper par défaut, ou le modèle
désigné). Les deux premières étapes sont aussi les process `frames` et `transcribe` du pipeline
(`caption_frames`, `transcribe_track`).

Contrat commun « texte » (voir `image_backend`) :
    callable(input_path, options=dict, progress_callback=fn, partial_callback=fn,
             console=fn) -> str

Traduit de `utils/video_describer.py` (2026-09-03, marche B1) — mêmes moteurs, signature
ORM-free. `extract_frames` garde son contrat `dest_dir` FOURNI PAR L'APPELANT (leçon
2026-08-25 : la fonction qui créait son mkdtemp ne le nettoyait jamais).
"""

import os
import logging
import subprocess
import tempfile

logger = logging.getLogger(__name__)


def _noop(*_a, **_k):
    return None


def caption_frames(input_path: str, options: dict = None, progress_callback=None,
                   partial_callback=None, console=None, duration: float = None) -> list:
    """Les légendes des images-clés d'une vidéo — l'étape `frames` du pipeline
    (`function_specs.PIPELINE`) : `[{frame, time, description}]`. Une image toutes les 10 s,
    18 au plus (l'intervalle s'allonge au-delà de 3 min), décrites par BLIP sous « auto » ou par
    le modèle de vision désigné (`options['vision_model']`)."""
    options = options or {}
    progress = progress_callback or _noop
    partial = partial_callback or _noop
    console = console or _noop
    if duration is None:
        duration = get_video_duration(input_path)

    # Extract frames (1 frame every 10 seconds, max 18 frames for 3-minute video)
    frame_interval = 10
    max_frames = 18

    if duration > max_frames * frame_interval:
        frame_interval = int(duration / max_frames)

    console(f"Extracting frames (1 every {frame_interval}s)...")
    partial("Extracting video frames...")
    progress(20)

    from .model_choice import BLIP, vision_for
    chosen = vision_for(options)

    # Brique COMMUNE `work_dir` : les images extraites ne survivent pas au bloc, et le
    # dossier part avec elles — y compris si l'analyse lève.
    from wama.common.utils.work_dir import work_dir
    with work_dir('describer_frames') as travail:
        frames = extract_frames(input_path, frame_interval, max_frames, dest_dir=str(travail))
        console(f"Extracted {len(frames)} frames")

        progress(30)
        console("Analyzing frames with AI...")
        partial("Analyzing visual content...")

        if chosen and chosen != BLIP:
            return describe_frames_with(chosen, frames, progress, console)
        return describe_frames(frames, progress, console)


def describe_video(input_path: str, options: dict = None,
                   progress_callback=None, partial_callback=None, console=None) -> str:
    """Décrit une vidéo (images-clés + piste audio) — contrat commun « texte ».

    `options['frame_captions']` et `options['transcript']` (2026-10-13) : ce que les process
    `frames` et `transcribe` ont déjà rendu — repris tels quels. Absents (appel du contrat seul,
    la jumelle), ils sont faits ici."""
    options = options or {}
    progress = progress_callback or _noop
    partial = partial_callback or _noop
    console = console or _noop

    output_style = options.get('output_style') or 'detailed'
    output_language = options.get('output_language') or 'fr'
    max_length = int(options.get('max_length') or 500)

    console("Processing video file...")
    progress(15)

    try:
        # Get video duration
        duration = get_video_duration(input_path)
        console(f"Video duration: {int(duration)}s")

        frame_descriptions = options.get('frame_captions')
        if frame_descriptions is None and output_style != 'meeting':
            frame_descriptions = caption_frames(input_path, options, progress, partial, console,
                                                duration=duration)
        frame_descriptions = frame_descriptions or []

        progress(60)

        # Select LLM model once for all downstream calls
        from .model_choice import llm_for
        llm_model, llm_provider = llm_for(options, 'video', output_style)
        console(f"Modèle LLM : {llm_model}")

        # Extract and transcribe audio
        audio_transcript = options.get('transcript')
        if audio_transcript is None:
            audio_transcript = ""
            if has_audio(input_path):
                console("Traitement de la piste audio…")
                partial("Transcription audio…")
                audio_transcript = transcribe_track(input_path, options.get('asr_model'), console)
        # For meeting format we need the full transcript (no summarization)
        if audio_transcript and output_style != 'meeting':
            audio_transcript = condense_transcript(
                audio_transcript, max_length // 2, output_language=output_language,
                llm_model=llm_model, llm_provider=llm_provider)
        progress(75)

        # Meeting compte-rendu: skip frame analysis, use LLM on transcript
        if output_style == 'meeting':
            console("Génération du compte-rendu de réunion (Ollama)…")
            partial("Rédaction du compte-rendu…")
            from wama.common.utils.llm_utils import generate_meeting_summary
            return generate_meeting_summary(audio_transcript, language=output_language,
                                            model=llm_model, provider=llm_provider)

        # Combine visual and audio descriptions
        console("Generating video summary...")
        partial("Combining visual and audio analysis...")

        result = combine_descriptions(
            frame_descriptions,
            audio_transcript,
            duration,
            output_style,
            max_length
        )

        progress(90)
        console("Video description generated successfully")

        # Translate if needed
        if output_language == 'fr':
            from .text_backend import translate_to_french
            result = translate_to_french(result, console)

        return result

    except Exception as e:
        logger.exception(f"Error describing video: {e}")
        raise


def get_video_duration(file_path: str) -> float:
    """Get video duration in seconds."""
    try:
        from wama.common.utils.ffmpeg_utils import get_ffprobe_exe, adapt_path_for_ffmpeg
        _fp = get_ffprobe_exe()
        result = subprocess.run(
            [_fp, '-v', 'error', '-show_entries', 'format=duration',
             '-of', 'default=noprint_wrappers=1:nokey=1', adapt_path_for_ffmpeg(file_path, _fp)],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode == 0:
            return float(result.stdout.strip())
    except Exception as e:
        logger.warning(f"Could not get duration: {e}")

    return 60.0  # Default to 1 minute


def extract_frames(file_path: str, interval: int, max_frames: int, dest_dir: str = None) -> list:
    """Extrait des images du film, une toutes les `interval` secondes, dans `dest_dir`.

    ⚠ `dest_dir` est FOURNI PAR L'APPELANT depuis le 2026-08-25. Auparavant la fonction
    créait son propre `mkdtemp` et ne le nettoyait pas — sans même annoncer de contrat.
    L'appelant retirait les FICHIERS un à un mais JAMAIS le dossier : chaque description de
    vidéo laissait un `describer_frames_*` vide dans le temporaire du système, définitivement.
    Et si l'analyse des images levait, rien n'était nettoyé du tout — ni fichiers, ni dossier.
    ⚠ Autre fuite du même bloc : quand ffmpeg sortait en erreur, les images DÉJÀ écrites
    n'étaient pas collectées (la boucle ne tourne que sur `returncode == 0`) — donc jamais
    supprimées non plus.
    """
    frames = []
    temp_dir = dest_dir or tempfile.mkdtemp(prefix="describer_frames_")

    try:
        # Use ffmpeg to extract frames
        output_pattern = os.path.join(temp_dir, "frame_%04d.jpg")

        from wama.common.utils.ffmpeg_utils import get_ffmpeg_exe, adapt_path_for_ffmpeg
        _ff = get_ffmpeg_exe()
        cmd = [
            _ff, '-i', adapt_path_for_ffmpeg(file_path, _ff),
            '-vf', f'fps=1/{interval}',
            '-frames:v', str(max_frames),
            '-q:v', '2',
            adapt_path_for_ffmpeg(output_pattern, _ff),
            '-y', '-hide_banner', '-loglevel', 'error'
        ]

        result = subprocess.run(cmd, capture_output=True, timeout=120)

        if result.returncode == 0:
            # Collect extracted frames
            for i in range(1, max_frames + 1):
                frame_path = os.path.join(temp_dir, f"frame_{i:04d}.jpg")
                if os.path.exists(frame_path):
                    frames.append(frame_path)

    except Exception as e:
        logger.warning(f"Frame extraction failed: {e}")

    return frames


def describe_frames(frames: list, progress=None, console=None) -> list:
    """Describe each frame using BLIP."""
    if not frames:
        return []
    progress = progress or _noop
    console = console or _noop

    try:
        from . import get_blip
        from PIL import Image

        blip = get_blip()
        blip.load()

        descriptions = []
        for i, frame_path in enumerate(frames):
            try:
                # Update progress
                progress(30 + int((i / len(frames)) * 25))

                # Load and process frame
                image = Image.open(frame_path).convert('RGB')
                caption = blip.process(image=image, max_new_tokens=50, num_beams=3)
                descriptions.append({
                    'frame': i + 1,
                    'time': i * 10,  # Approximate time in seconds
                    'description': caption.strip()
                })

            except Exception as e:
                logger.warning(f"Error describing frame {i}: {e}")
                continue

        return descriptions

    except Exception as e:
        logger.exception(f"Error in frame description: {e}")
        return []


def has_audio(file_path: str) -> bool:
    """Check if video has audio track."""
    try:
        from wama.common.utils.ffmpeg_utils import get_ffprobe_exe, adapt_path_for_ffmpeg
        _fp = get_ffprobe_exe()
        result = subprocess.run(
            [_fp, '-v', 'error', '-select_streams', 'a',
             '-show_entries', 'stream=codec_type', '-of', 'csv=p=0', adapt_path_for_ffmpeg(file_path, _fp)],
            capture_output=True, text=True, timeout=10
        )
        return 'audio' in result.stdout.lower()
    except Exception:
        return False


def describe_frames_with(model: str, frames: list, progress=None, console=None) -> list:
    """Légende chaque image-clé avec le modèle de vision Ollama DÉSIGNÉ — même forme que
    `describe_frames` (BLIP). Une image sans réponse est sautée, comme BLIP ; aucune réponse du
    tout est une erreur dite (un modèle désigné n'est jamais remplacé en silence)."""
    if not frames:
        return []
    progress = progress or _noop
    console = console or _noop
    from .image_backend import _describe_with_ollama_vision, _vision_prompt
    # Légendes BRÈVES en anglais, comme celles de BLIP : la rédaction et la traduction en aval
    # les traitent de la même façon.
    prompt = _vision_prompt('brief', 'en', model)
    console(f"Images-clés décrites par {model} (Ollama)…")
    descriptions = []
    for i, frame_path in enumerate(frames):
        progress(30 + int((i / len(frames)) * 25))
        caption = _describe_with_ollama_vision(model, frame_path, prompt)
        if not caption:
            logger.warning(f"{model} : aucune légende pour l'image {i}")
            continue
        descriptions.append({'frame': i + 1, 'time': i * 10, 'description': caption.strip()})
    if not descriptions:
        raise RuntimeError(f"Le modèle de vision désigné « {model} » n'a décrit aucune image "
                           "(Ollama joignable ? modèle installé ?).")
    return descriptions


def transcribe_track(file_path: str, asr_model: str = None, console=None, user=None) -> str:
    """Le texte parlé de la piste son d'une vidéo — l'étape `transcribe` du pipeline pour une
    vidéo. La piste est extraite (16 kHz mono), puis transcrite par le modèle retenu
    (`audio_backend.transcribe_speech`). Une piste illisible ou une transcription en échec rend
    '' : la description se fait alors sans le son, comme avant le pipeline."""
    console = console or _noop
    temp_audio = None

    try:
        # Extract audio to temp file
        temp_audio = tempfile.mktemp(suffix='.wav')

        from wama.common.utils.ffmpeg_utils import get_ffmpeg_exe, adapt_path_for_ffmpeg
        _ff = get_ffmpeg_exe()
        cmd = [
            _ff, '-i', adapt_path_for_ffmpeg(file_path, _ff),
            '-vn', '-acodec', 'pcm_s16le',
            '-ar', '16000', '-ac', '1',
            adapt_path_for_ffmpeg(temp_audio, _ff),
            '-y', '-hide_banner', '-loglevel', 'error'
        ]

        result = subprocess.run(cmd, capture_output=True, timeout=120)

        if result.returncode != 0:
            return ""

        from .audio_backend import transcribe_speech
        return transcribe_speech(temp_audio, asr_model, user=user, console=console,
                                 duration=get_video_duration(file_path))

    except Exception as e:
        logger.warning(f"Audio processing failed: {e}")
        console(f"Avertissement : piste son non transcrite ({e})")
        return ""

    finally:
        if temp_audio and os.path.exists(temp_audio):
            try:
                os.remove(temp_audio)
            except Exception:
                pass


def condense_transcript(transcript: str, max_words: int, output_language: str = 'fr',
                        llm_model: str = '', llm_provider: str = None) -> str:
    """La piste son, telle que la description d'une vidéo la cite : un transcript trop long pour
    elle (`max_words`) est résumé par le LLM, tronqué si le LLM ne répond pas.

    `llm_model` : l'appelant réel passe toujours le modèle résolu (`model_choice.llm_for`). Vide →
    résolution `modele_par_defaut()` — plus JAMAIS de nom en dur ici (l'ancien défaut
    `qwen3.5:9b` a survécu au refactor du 04/08 puis désigné un modèle retiré le 26/08)."""
    if not transcript or len(transcript.split()) <= max_words:
        return transcript
    if not llm_model:
        from wama.common.utils.llm_utils import modele_par_defaut
        llm_model = modele_par_defaut()
    try:
        from wama.common.utils.llm_utils import generate_structured_summary
        summary_data = generate_structured_summary(
            transcript, content_hint='audio',
            language=output_language, model=llm_model, provider=llm_provider,
        )
        return summary_data['summary']
    except Exception as e:
        logger.warning(f"Ollama summarization failed, using truncated transcript: {e}")
        words = transcript.split()[:max_words]
        return ' '.join(words) + '…'


def combine_descriptions(frame_descriptions: list, audio_summary: str,
                         duration: float, output_style: str, max_length: int) -> str:
    """Combine visual and audio descriptions into final result."""
    parts = []

    # Video info
    mins = int(duration // 60)
    secs = int(duration % 60)
    duration_str = f"{mins}:{secs:02d}"

    if output_style == 'scientific':
        parts.append(f"Video Analysis Report\n{'='*50}\n")
        parts.append(f"Duration: {duration_str}\n")
        parts.append(f"Frames analyzed: {len(frame_descriptions)}\n\n")

    # Visual description
    if frame_descriptions:
        if output_style == 'bullet_points':
            parts.append("Visual content:\n")
            for fd in frame_descriptions[:10]:  # Limit to 10 key frames
                parts.append(f"- [{fd['time']}s] {fd['description']}")
            parts.append("")
        elif output_style == 'scientific':
            parts.append("Visual Content Analysis:\n")
            for fd in frame_descriptions:
                parts.append(f"  Frame {fd['frame']} ({fd['time']}s): {fd['description']}")
            parts.append("")
        else:
            # Summarize frame descriptions
            unique_descriptions = list(set(fd['description'] for fd in frame_descriptions))
            visual_summary = '. '.join(unique_descriptions[:5])
            parts.append(f"Visual content: {visual_summary}")
            parts.append("")

    # Audio description
    if audio_summary:
        if output_style == 'bullet_points':
            parts.append("Audio content:\n")
            sentences = audio_summary.split('. ')
            for s in sentences[:5]:
                if s.strip():
                    parts.append(f"- {s.strip()}")
        elif output_style == 'scientific':
            parts.append(f"Audio Transcript Summary:\n{audio_summary}")
        else:
            parts.append(f"Audio: {audio_summary}")

    # Final formatting
    result = '\n'.join(parts)

    # Ensure not too long
    if len(result.split()) > max_length:
        words = result.split()[:max_length]
        result = ' '.join(words) + '...'

    if output_style == 'scientific':
        result += f"\n\n---\nGenerated by WAMA Describer using AI-based video analysis."

    return result.strip()
