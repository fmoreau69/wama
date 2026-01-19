"""
Audio description using Whisper transcription + summarization.
"""

import os
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def describe_audio(description, set_progress, set_partial, console):
    """
    Describe audio content: transcribe with Whisper, then summarize.

    Args:
        description: Description model instance
        set_progress: Function to update progress
        set_partial: Function to set partial result
        console: Function to log to console

    Returns:
        str: Audio description/summary
    """
    user_id = description.user_id
    file_path = description.input_file.path
    output_format = description.output_format
    output_language = description.output_language
    max_length = description.max_length

    console(user_id, "Processing audio file...")
    set_progress(description, 20)

    try:
        # Transcribe audio
        console(user_id, "Transcribing audio with Whisper...")
        set_partial(description, "Loading Whisper model...")

        transcript = transcribe_audio(file_path, console, user_id)

        if not transcript or not transcript.strip():
            return "No speech detected in the audio file."

        word_count = len(transcript.split())
        console(user_id, f"Transcribed {word_count} words")

        set_progress(description, 60)
        set_partial(description, transcript[:300] + "..." if len(transcript) > 300 else transcript)

        # If short, just format the transcript
        if word_count <= max_length:
            console(user_id, "Transcript is short, using directly...")
            result = format_audio_result(transcript, output_format, is_summary=False)
            return result

        # Summarize the transcript
        console(user_id, "Summarizing transcript...")
        set_partial(description, "Generating summary...")

        from .text_describer import get_summarizer, chunk_text, sanitize_text_for_model, reset_cuda

        summarizer = get_summarizer()

        set_progress(description, 70)

        # Chunk and summarize
        chunks = chunk_text(transcript, max_tokens=1024)
        summaries = []
        cuda_failed = False

        for i, chunk in enumerate(chunks):
            if len(chunk.split()) < 50:
                continue

            progress = 70 + int((i / len(chunks)) * 15)
            set_progress(description, progress)

            try:
                # Sanitize chunk to prevent tokenization errors
                clean_chunk = sanitize_text_for_model(chunk)
                if not clean_chunk or len(clean_chunk.split()) < 30:
                    continue

                if cuda_failed:
                    summarizer = get_summarizer(force_cpu=True)

                summary = summarizer(
                    clean_chunk,
                    max_length=150,
                    min_length=50,
                    do_sample=False,
                    truncation=True
                )
                summaries.append(summary[0]['summary_text'])

            except RuntimeError as e:
                error_str = str(e)
                if 'CUDA' in error_str or 'device-side assert' in error_str:
                    logger.warning(f"CUDA error on chunk {i}, switching to CPU: {e}")
                    reset_cuda()
                    cuda_failed = True

                    # Retry on CPU
                    try:
                        summarizer = get_summarizer(force_cpu=True)
                        clean_chunk = sanitize_text_for_model(chunk)
                        if clean_chunk and len(clean_chunk.split()) >= 30:
                            summary = summarizer(
                                clean_chunk,
                                max_length=150,
                                min_length=50,
                                do_sample=False,
                                truncation=True
                            )
                            summaries.append(summary[0]['summary_text'])
                            console(user_id, f"Chunk {i+1} processed on CPU (fallback)")
                    except Exception as cpu_error:
                        logger.warning(f"CPU fallback also failed for chunk {i}: {cpu_error}")
                else:
                    logger.warning(f"Error summarizing chunk {i}: {e}")

            except IndexError as e:
                # "index out of range in self" - tokenizer issue
                logger.warning(f"Tokenizer error on chunk {i}: {e}")
                continue

            except Exception as e:
                logger.warning(f"Error summarizing chunk {i}: {e}")
                continue

        if not summaries:
            # Fallback to transcript
            result = format_audio_result(transcript, output_format, is_summary=False)
        else:
            combined = ' '.join(summaries)

            # Final summarization if needed
            if len(combined.split()) > max_length * 2:
                try:
                    clean_combined = sanitize_text_for_model(combined)
                    if cuda_failed:
                        summarizer = get_summarizer(force_cpu=True)

                    final = summarizer(
                        clean_combined,
                        max_length=max_length,
                        min_length=min(50, max_length // 2),
                        do_sample=False,
                        truncation=True
                    )
                    combined = final[0]['summary_text']
                except RuntimeError as e:
                    if 'CUDA' in str(e) or 'device-side assert' in str(e):
                        logger.warning(f"CUDA error in final summary, trying CPU: {e}")
                        reset_cuda()
                        try:
                            summarizer = get_summarizer(force_cpu=True)
                            clean_combined = sanitize_text_for_model(combined)
                            final = summarizer(
                                clean_combined,
                                max_length=max_length,
                                min_length=min(50, max_length // 2),
                                do_sample=False,
                                truncation=True
                            )
                            combined = final[0]['summary_text']
                        except:
                            words = combined.split()[:max_length]
                            combined = ' '.join(words) + '...'
                    else:
                        words = combined.split()[:max_length]
                        combined = ' '.join(words) + '...'
                except:
                    words = combined.split()[:max_length]
                    combined = ' '.join(words) + '...'

            result = format_audio_result(combined, output_format, is_summary=True)

        set_progress(description, 90)

        # Translate if needed - summarizers typically output English
        if output_language == 'fr':
            detected = detect_language(result)
            console(user_id, f"Language detected: {detected}, requested: {output_language}")

            if detected != 'fr':
                console(user_id, "Translating to French...")
                from .text_describer import translate_to_french
                result = translate_to_french(result, console, user_id)

        console(user_id, "Audio description generated successfully")
        return result

    except Exception as e:
        logger.exception(f"Error describing audio: {e}")
        raise


def transcribe_audio(file_path: str, console, user_id: int) -> str:
    """Transcribe audio using Whisper."""
    try:
        # Try faster-whisper first
        try:
            from faster_whisper import WhisperModel

            console(user_id, "Using faster-whisper...")
            model = WhisperModel("base", device="auto", compute_type="auto")
            segments, info = model.transcribe(file_path)

            transcript = ' '.join([segment.text for segment in segments])
            return transcript.strip()

        except ImportError:
            pass

        # Fall back to openai-whisper
        try:
            import whisper

            console(user_id, "Using openai-whisper...")
            model = whisper.load_model("base")
            result = model.transcribe(file_path)

            return result["text"].strip()

        except ImportError:
            pass

        # Try using Transcriber module if available
        try:
            console(user_id, "Using Transcriber module...")
            # This assumes the transcriber workers are available
            from wama.transcriber.utils import transcribe_file
            return transcribe_file(file_path)
        except ImportError:
            pass

        raise ImportError(
            "No Whisper implementation available. "
            "Install: pip install faster-whisper or pip install openai-whisper"
        )

    except Exception as e:
        logger.exception(f"Transcription failed: {e}")
        raise


def format_audio_result(text: str, output_format: str, is_summary: bool) -> str:
    """Format audio description result."""
    text = text.strip()

    prefix = "Summary of audio content:" if is_summary else "Audio transcript:"

    if output_format == 'bullet_points':
        import re
        sentences = re.split(r'(?<=[.!?])\s+', text)
        bullets = []
        for s in sentences:
            s = s.strip()
            if s:
                if not s.endswith('.'):
                    s += '.'
                bullets.append(f"- {s}")
        return f"{prefix}\n\n" + '\n'.join(bullets)

    elif output_format == 'scientific':
        content_type = "summary" if is_summary else "transcript"
        return f"Audio Content Analysis:\n\n{text}\n\n---\nThis {content_type} was generated using automatic speech recognition."

    elif output_format == 'summary':
        if len(text) > 500:
            text = text[:497] + '...'
        return text

    else:  # detailed
        return f"{prefix}\n\n{text}"


def detect_language(text: str) -> str:
    """Simple language detection."""
    # Common French words
    french_words = ['le', 'la', 'les', 'de', 'du', 'des', 'un', 'une', 'est', 'sont', 'avec', 'pour', 'dans', 'sur']
    # Common English words
    english_words = ['the', 'a', 'an', 'is', 'are', 'with', 'for', 'in', 'on', 'at', 'to', 'of']

    words = text.lower().split()[:100]  # Check first 100 words

    french_count = sum(1 for w in words if w in french_words)
    english_count = sum(1 for w in words if w in english_words)

    if french_count > english_count:
        return 'fr'
    return 'en'
