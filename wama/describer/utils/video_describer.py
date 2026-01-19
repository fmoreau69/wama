"""
Video description using frame extraction + BLIP + Whisper.
"""

import os
import logging
import tempfile
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)


def describe_video(description, set_progress, set_partial, console):
    """
    Describe video content: extract frames for visual description + audio transcript.

    Args:
        description: Description model instance
        set_progress: Function to update progress
        set_partial: Function to set partial result
        console: Function to log to console

    Returns:
        str: Video description/summary
    """
    user_id = description.user_id
    file_path = description.input_file.path
    output_format = description.output_format
    output_language = description.output_language
    max_length = description.max_length

    console(user_id, "Processing video file...")
    set_progress(description, 15)

    try:
        # Get video duration
        duration = get_video_duration(file_path)
        console(user_id, f"Video duration: {int(duration)}s")

        # Extract frames (1 frame every 10 seconds, max 18 frames for 3-minute video)
        frame_interval = 10
        max_frames = 18

        if duration > max_frames * frame_interval:
            frame_interval = int(duration / max_frames)

        console(user_id, f"Extracting frames (1 every {frame_interval}s)...")
        set_partial(description, "Extracting video frames...")
        set_progress(description, 20)

        frames = extract_frames(file_path, frame_interval, max_frames)
        console(user_id, f"Extracted {len(frames)} frames")

        # Describe frames with BLIP
        set_progress(description, 30)
        console(user_id, "Analyzing frames with AI...")
        set_partial(description, "Analyzing visual content...")

        frame_descriptions = describe_frames(frames, set_progress, console, user_id)

        # Cleanup temp frames
        for frame_path in frames:
            try:
                os.remove(frame_path)
            except:
                pass

        set_progress(description, 60)

        # Extract and transcribe audio
        audio_summary = ""
        if has_audio(file_path):
            console(user_id, "Processing audio track...")
            set_partial(description, "Transcribing audio...")

            audio_summary = process_audio_track(file_path, max_length // 2, console, user_id)
            set_progress(description, 75)

        # Combine visual and audio descriptions
        console(user_id, "Generating video summary...")
        set_partial(description, "Combining visual and audio analysis...")

        result = combine_descriptions(
            frame_descriptions,
            audio_summary,
            duration,
            output_format,
            max_length
        )

        set_progress(description, 90)
        console(user_id, "Video description generated successfully")

        # Translate if needed
        if output_language == 'fr':
            from .text_describer import translate_to_french
            result = translate_to_french(result, console, user_id)

        return result

    except Exception as e:
        logger.exception(f"Error describing video: {e}")
        raise


def get_video_duration(file_path: str) -> float:
    """Get video duration in seconds."""
    try:
        result = subprocess.run(
            ['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
             '-of', 'default=noprint_wrappers=1:nokey=1', file_path],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode == 0:
            return float(result.stdout.strip())
    except Exception as e:
        logger.warning(f"Could not get duration: {e}")

    return 60.0  # Default to 1 minute


def extract_frames(file_path: str, interval: int, max_frames: int) -> list:
    """Extract frames from video at specified interval."""
    frames = []
    temp_dir = tempfile.mkdtemp(prefix="describer_frames_")

    try:
        # Use ffmpeg to extract frames
        output_pattern = os.path.join(temp_dir, "frame_%04d.jpg")

        cmd = [
            'ffmpeg', '-i', file_path,
            '-vf', f'fps=1/{interval}',
            '-frames:v', str(max_frames),
            '-q:v', '2',
            output_pattern,
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


def describe_frames(frames: list, set_progress, console, user_id: int) -> list:
    """Describe each frame using BLIP."""
    if not frames:
        return []

    try:
        from .image_describer import get_blip_model
        from PIL import Image
        import torch

        processor, model = get_blip_model()
        device = "cuda" if torch.cuda.is_available() else "cpu"

        descriptions = []
        for i, frame_path in enumerate(frames):
            try:
                # Update progress
                progress = 30 + int((i / len(frames)) * 25)
                set_progress(None, progress) if set_progress else None

                # Load and process frame
                image = Image.open(frame_path).convert('RGB')
                inputs = processor(image, return_tensors="pt").to(device)

                out = model.generate(
                    **inputs,
                    max_new_tokens=50,
                    num_beams=3,
                )

                caption = processor.decode(out[0], skip_special_tokens=True)
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
        result = subprocess.run(
            ['ffprobe', '-v', 'error', '-select_streams', 'a',
             '-show_entries', 'stream=codec_type', '-of', 'csv=p=0', file_path],
            capture_output=True, text=True, timeout=10
        )
        return 'audio' in result.stdout.lower()
    except:
        return False


def process_audio_track(file_path: str, max_words: int, console, user_id: int) -> str:
    """Extract and transcribe audio from video."""
    temp_audio = None

    try:
        # Extract audio to temp file
        temp_audio = tempfile.mktemp(suffix='.wav')

        cmd = [
            'ffmpeg', '-i', file_path,
            '-vn', '-acodec', 'pcm_s16le',
            '-ar', '16000', '-ac', '1',
            temp_audio,
            '-y', '-hide_banner', '-loglevel', 'error'
        ]

        result = subprocess.run(cmd, capture_output=True, timeout=120)

        if result.returncode != 0:
            return ""

        # Transcribe
        from .audio_describer import transcribe_audio
        transcript = transcribe_audio(temp_audio, console, user_id)

        # Summarize if too long
        if transcript and len(transcript.split()) > max_words:
            from .text_describer import get_summarizer, sanitize_text_for_model

            clean_transcript = sanitize_text_for_model(transcript[:4000])
            summarizer = get_summarizer()
            summary = summarizer(
                clean_transcript,
                max_length=max_words,
                min_length=min(30, max_words // 2),
                do_sample=False,
                truncation=True
            )
            return summary[0]['summary_text']

        return transcript

    except Exception as e:
        logger.warning(f"Audio processing failed: {e}")
        return ""

    finally:
        if temp_audio and os.path.exists(temp_audio):
            try:
                os.remove(temp_audio)
            except:
                pass


def combine_descriptions(frame_descriptions: list, audio_summary: str,
                         duration: float, output_format: str, max_length: int) -> str:
    """Combine visual and audio descriptions into final result."""
    parts = []

    # Video info
    mins = int(duration // 60)
    secs = int(duration % 60)
    duration_str = f"{mins}:{secs:02d}"

    if output_format == 'scientific':
        parts.append(f"Video Analysis Report\n{'='*50}\n")
        parts.append(f"Duration: {duration_str}\n")
        parts.append(f"Frames analyzed: {len(frame_descriptions)}\n\n")

    # Visual description
    if frame_descriptions:
        if output_format == 'bullet_points':
            parts.append("Visual content:\n")
            for fd in frame_descriptions[:10]:  # Limit to 10 key frames
                parts.append(f"- [{fd['time']}s] {fd['description']}")
            parts.append("")
        elif output_format == 'scientific':
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
        if output_format == 'bullet_points':
            parts.append("Audio content:\n")
            sentences = audio_summary.split('. ')
            for s in sentences[:5]:
                if s.strip():
                    parts.append(f"- {s.strip()}")
        elif output_format == 'scientific':
            parts.append(f"Audio Transcript Summary:\n{audio_summary}")
        else:
            parts.append(f"Audio: {audio_summary}")

    # Final formatting
    result = '\n'.join(parts)

    # Ensure not too long
    if len(result.split()) > max_length:
        words = result.split()[:max_length]
        result = ' '.join(words) + '...'

    if output_format == 'scientific':
        result += f"\n\n---\nGenerated by WAMA Describer using AI-based video analysis."

    return result.strip()
