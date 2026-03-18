"""
Audio description using Whisper transcription + summarization.

Transcription is delegated to wama.common.utils.whisper_utils (faster-whisper,
large-v3 by default) so that Transcriber and Describer share the same engine.
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
        # Transcribe audio with shared whisper_utils (faster-whisper, large-v3)
        console(user_id, "Transcription audio avec Whisper (large-v3)…")
        set_partial(description, "Chargement du modèle Whisper…")

        from wama.common.utils.whisper_utils import transcribe_audio as _transcribe
        _result = _transcribe(file_path, model_name='large-v3')
        transcript = _result.text

        if not transcript or not transcript.strip():
            return "Aucune parole détectée dans le fichier audio."

        word_count = len(transcript.split())
        console(user_id, f"{word_count} mots transcrits")

        set_progress(description, 60)
        set_partial(description, transcript[:300] + "..." if len(transcript) > 300 else transcript)

        # Meeting compte-rendu: use heavy LLM directly
        if output_format == 'meeting':
            console(user_id, "Génération du compte-rendu de réunion (Ollama)…")
            set_partial(description, "Rédaction du compte-rendu…")
            from wama.common.utils.llm_utils import generate_meeting_summary, get_describer_model
            _model = get_describer_model('audio', 'meeting')
            console(user_id, f"Modèle LLM : {_model}")
            return generate_meeting_summary(transcript, language=output_language, model=_model)

        # If short, just format the transcript
        if word_count <= max_length:
            console(user_id, "Transcript is short, using directly...")
            result = format_audio_result(transcript, output_format, is_summary=False)
            return result

        # Long transcript: summarize with Ollama (replaces legacy BART pipeline)
        console(user_id, "Résumé du transcript (Ollama)…")
        set_partial(description, "Génération du résumé en cours…")
        set_progress(description, 70)

        from wama.common.utils.llm_utils import generate_structured_summary, get_describer_model
        _model = get_describer_model('audio', output_format)
        console(user_id, f"Modèle LLM : {_model}")

        try:
            summary_data = generate_structured_summary(
                transcript, content_hint='audio',
                language=output_language or 'fr',
                model=_model,
            )
            set_progress(description, 85)

            if output_format == 'bullet_points' and summary_data['key_points']:
                result = '\n'.join(f"- {p}" for p in summary_data['key_points'])
            elif output_format == 'scientific':
                parts = [summary_data['summary']]
                if summary_data['key_points']:
                    parts += ['', 'Key points:'] + [f"- {p}" for p in summary_data['key_points']]
                result = '\n'.join(parts)
            elif output_format == 'detailed':
                parts = [summary_data['summary']]
                if summary_data['key_points']:
                    parts += ['', 'Points clés :'] + [f"- {p}" for p in summary_data['key_points']]
                result = '\n'.join(parts)
            else:
                result = summary_data['summary']

        except Exception as llm_err:
            console(user_id, f"Avertissement: Ollama indisponible ({llm_err}), transcript tronqué")
            logger.warning(f"Ollama summarization failed: {llm_err}")
            words = transcript.split()[:max_length]
            result = ' '.join(words) + ('…' if len(transcript.split()) > max_length else '')

        if not result:
            result = format_audio_result(transcript, output_format, is_summary=False)

        set_progress(description, 90)

        console(user_id, "Audio description generated successfully")
        return result

    except Exception as e:
        logger.exception(f"Error describing audio: {e}")
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
