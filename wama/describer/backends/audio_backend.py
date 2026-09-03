"""
Backend AUDIO du describer — transcription Whisper + résumé LLM.

Contrat commun « texte » (voir `image_backend`) :
    callable(input_path, options=dict, progress_callback=fn, partial_callback=fn,
             console=fn) -> str

Traduit de `utils/audio_describer.py` (2026-09-03, marche B1) — mêmes moteurs
(whisper_utils partagé avec le Transcriber), signature ORM-free.
"""

import logging

logger = logging.getLogger(__name__)


def _noop(*_a, **_k):
    return None


def describe_audio(input_path: str, options: dict = None,
                   progress_callback=None, partial_callback=None, console=None) -> str:
    """Décrit un contenu audio (transcription puis résumé) — contrat commun « texte »."""
    options = options or {}
    progress = progress_callback or _noop
    partial = partial_callback or _noop
    console = console or _noop

    output_style = options.get('output_style') or 'detailed'
    output_language = options.get('output_language') or 'fr'
    max_length = int(options.get('max_length') or 500)

    console("Processing audio file...")
    progress(20)

    try:
        # Transcribe audio with shared whisper_utils (faster-whisper, large-v3)
        console("Transcription audio avec Whisper (large-v3)…")
        partial("Chargement du modèle Whisper…")

        from wama.common.utils.whisper_utils import transcribe_audio as _transcribe
        _result = _transcribe(input_path, model_name='large-v3')
        transcript = _result.text

        if not transcript or not transcript.strip():
            return "Aucune parole détectée dans le fichier audio."

        word_count = len(transcript.split())
        console(f"{word_count} mots transcrits")

        progress(60)
        partial(transcript[:300] + "..." if len(transcript) > 300 else transcript)

        # Meeting compte-rendu: use heavy LLM directly
        if output_style == 'meeting':
            console("Génération du compte-rendu de réunion (Ollama)…")
            partial("Rédaction du compte-rendu…")
            from wama.common.utils.llm_utils import generate_meeting_summary, get_describer_model
            _model = get_describer_model('audio', 'meeting')
            console(f"Modèle LLM : {_model}")
            return generate_meeting_summary(transcript, language=output_language, model=_model)

        # If short, just format the transcript
        if word_count <= max_length:
            console("Transcript is short, using directly...")
            result = format_audio_result(transcript, output_style, is_summary=False)
            return result

        # Long transcript: summarize with Ollama (replaces legacy BART pipeline)
        console("Résumé du transcript (Ollama)…")
        partial("Génération du résumé en cours…")
        progress(70)

        from wama.common.utils.llm_utils import generate_structured_summary, get_describer_model
        _model = get_describer_model('audio', output_style)
        console(f"Modèle LLM : {_model}")

        try:
            summary_data = generate_structured_summary(
                transcript, content_hint='audio',
                language=output_language or 'fr',
                model=_model,
            )
            progress(85)

            if output_style == 'bullet_points' and summary_data['key_points']:
                result = '\n'.join(f"- {p}" for p in summary_data['key_points'])
            elif output_style == 'scientific':
                parts = [summary_data['summary']]
                if summary_data['key_points']:
                    parts += ['', 'Key points:'] + [f"- {p}" for p in summary_data['key_points']]
                result = '\n'.join(parts)
            elif output_style == 'detailed':
                parts = [summary_data['summary']]
                if summary_data['key_points']:
                    parts += ['', 'Points clés :'] + [f"- {p}" for p in summary_data['key_points']]
                result = '\n'.join(parts)
            else:
                result = summary_data['summary']

        except Exception as llm_err:
            console(f"Avertissement: Ollama indisponible ({llm_err}), transcript tronqué")
            logger.warning(f"Ollama summarization failed: {llm_err}")
            words = transcript.split()[:max_length]
            result = ' '.join(words) + ('…' if len(transcript.split()) > max_length else '')

        if not result:
            result = format_audio_result(transcript, output_style, is_summary=False)

        progress(90)

        console("Audio description generated successfully")
        return result

    except Exception as e:
        logger.exception(f"Error describing audio: {e}")
        raise


def format_audio_result(text: str, output_style: str, is_summary: bool) -> str:
    """Format audio description result."""
    text = text.strip()

    prefix = "Summary of audio content:" if is_summary else "Audio transcript:"

    if output_style == 'bullet_points':
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

    elif output_style == 'scientific':
        content_type = "summary" if is_summary else "transcript"
        return f"Audio Content Analysis:\n\n{text}\n\n---\nThis {content_type} was generated using automatic speech recognition."

    elif output_style == 'summary':
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
