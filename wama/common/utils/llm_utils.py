"""
WAMA Common — LLM utilities
Shared Ollama client for use in Celery workers (transcriber, describer, ...).
"""

import json
import logging
import re
from typing import Optional

logger = logging.getLogger(__name__)


def ollama_chat(messages: list, model: str = 'qwen3:14b-q8_0') -> tuple[Optional[str], Optional[str]]:
    """
    Send a chat request to the local Ollama server.

    Args:
        messages: List of {"role": ..., "content": ...} dicts.
        model:    Ollama model name.

    Returns:
        (text, None)  on success
        (None, error) on failure
    """
    import httpx
    from django.conf import settings

    host = getattr(settings, 'OLLAMA_HOST', 'http://127.0.0.1:11434').rstrip('/')
    url = f"{host}/api/chat"

    try:
        with httpx.Client(timeout=180.0, trust_env=False) as client:
            resp = client.post(url, json={
                "model": model,
                "messages": messages,
                "options": {"temperature": 0.3, "num_predict": 2048},
                "stream": False,
            })
        if resp.status_code != 200:
            return None, f"Ollama HTTP {resp.status_code}: {resp.text[:200]}"
        text = resp.json().get("message", {}).get("content", "")
        return text.strip(), None
    except Exception as e:
        logger.error(f"[llm_utils] Ollama error: {e}")
        return None, str(e)


def extract_json_from_llm(text: str) -> Optional[dict]:
    """
    Extract the first JSON object from an LLM response.
    Handles reasoning tags (<think>...</think>) and surrounding prose.
    """
    # Strip thinking blocks
    clean = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL).strip()
    match = re.search(r'\{.*\}', clean, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass
    return None


def generate_meeting_summary(
    text: str,
    language: str = 'fr',
    speakers: Optional[list] = None,
    model: str = 'qwen3:14b-q8_0',
) -> str:
    """
    Generate a structured meeting summary (compte-rendu de réunion) using Ollama.

    Args:
        text:     Transcript or meeting text (truncated to ~8000 chars).
        language: 'fr' | 'en'
        speakers: Optional list of speaker IDs from diarization.
        model:    Ollama model to use.

    Returns:
        Formatted meeting summary as a markdown string.
        Falls back to truncated input on failure.
    """
    lang_label = "en français" if language == 'fr' else "in English"
    participants_hint = (
        f"\nParticipants identifiés par la diarisation : {', '.join(speakers)}"
        if speakers else ""
    )

    truncated = text[:8000] + ('…' if len(text) > 8000 else '')

    messages = [
        {
            "role": "system",
            "content": (
                "Tu es un assistant spécialisé dans la rédaction de comptes-rendus de réunion. "
                f"Réponds toujours {lang_label} avec un JSON valide et rien d'autre."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Génère un compte-rendu structuré de cette réunion.{participants_hint}\n\n"
                "Retourne un JSON avec ces clés :\n"
                '- "summary": résumé exécutif en 2-4 phrases\n'
                '- "topics": liste des sujets abordés (strings)\n'
                '- "decisions": liste des décisions prises (strings, peut être vide)\n'
                '- "action_items": liste des actions à mener avec responsable si identifiable (strings)\n'
                '- "participants": liste des participants identifiés (strings, peut être vide)\n\n'
                f"Transcription :\n{truncated}\n\n"
                "Réponds UNIQUEMENT avec le JSON."
            ),
        },
    ]

    result_text, error = ollama_chat(messages, model=model)

    if error or not result_text:
        logger.warning(f"[llm_utils] generate_meeting_summary failed: {error}")
        return truncated

    data = extract_json_from_llm(result_text)
    if not data:
        logger.warning("[llm_utils] Could not parse JSON from meeting summary response")
        return truncated

    # Render as structured markdown
    lines: list[str] = []
    if language == 'fr':
        lines.append("## Compte-rendu de réunion\n")
        if data.get("summary"):
            lines += ["### Résumé exécutif", data["summary"], ""]
        if data.get("participants"):
            lines += ["### Participants"] + [f"- {p}" for p in data["participants"]] + [""]
        if data.get("topics"):
            lines += ["### Points abordés"] + [f"- {t}" for t in data["topics"]] + [""]
        if data.get("decisions"):
            lines += ["### Décisions prises"] + [f"- {d}" for d in data["decisions"]] + [""]
        if data.get("action_items"):
            lines += ["### Actions à mener"] + [f"- {a}" for a in data["action_items"]]
    else:
        lines.append("## Meeting Summary\n")
        if data.get("summary"):
            lines += ["### Executive Summary", data["summary"], ""]
        if data.get("participants"):
            lines += ["### Participants"] + [f"- {p}" for p in data["participants"]] + [""]
        if data.get("topics"):
            lines += ["### Topics Discussed"] + [f"- {t}" for t in data["topics"]] + [""]
        if data.get("decisions"):
            lines += ["### Decisions Made"] + [f"- {d}" for d in data["decisions"]] + [""]
        if data.get("action_items"):
            lines += ["### Action Items"] + [f"- {a}" for a in data["action_items"]]

    return '\n'.join(lines)


def verify_text_coherence(
    text: str,
    content_hint: str = 'transcription',
    language: str = 'fr',
    model: str = 'qwen3:14b-q8_0',
) -> dict:
    """
    Verify text coherence and suggest corrections using Ollama.

    Args:
        text:         Source text to verify (truncated to ~6000 chars).
        content_hint: 'transcription' | 'description' | 'audio' | 'video' | 'image' | 'text'
        language:     'fr' | 'en'
        model:        Ollama model to use.

    Returns:
        {
            "score":      int (0-100),
            "notes":      [str, ...],   # detected issues (empty list if none)
            "suggestion": str,          # corrected text (identical to input if score >= 85)
        }
    """
    content_labels = {
        'transcription': 'transcription audio',
        'description':   'description de contenu',
        'audio':         'contenu audio',
        'video':         'contenu vidéo',
        'image':         "description d'image",
        'text':          'texte',
        'meeting':       'compte-rendu de réunion',
    }
    label = content_labels.get(content_hint, 'texte')
    lang_label = "en français" if language == 'fr' else "in English"

    truncated = text[:6000] + ('…' if len(text) > 6000 else '')

    messages = [
        {
            "role": "system",
            "content": (
                "Tu es un expert en contrôle qualité de textes issus de l'IA. "
                f"Réponds toujours {lang_label} avec un JSON valide et rien d'autre."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Analyse la cohérence et la qualité de cette {label}.\n\n"
                "Retourne un JSON avec ces clés :\n"
                '- "score": note de qualité de 0 à 100 (100 = parfait, sans aucun défaut)\n'
                '- "notes": liste des problèmes détectés : répétitions ASR, phrases tronquées ou '
                'incomplètes, hallucinations, incohérences sémantiques, changements de langue '
                'inattendus (liste de strings, vide si aucun problème)\n'
                '- "suggestion": version corrigée du texte. Si score >= 85 et aucun problème '
                "majeur, retourner le texte original inchangé.\n\n"
                f"Texte à analyser :\n{truncated}\n\n"
                "Réponds UNIQUEMENT avec le JSON."
            ),
        },
    ]

    result_text, error = ollama_chat(messages, model=model)

    if error or not result_text:
        logger.warning(f"[llm_utils] verify_text_coherence failed: {error}")
        raise RuntimeError(error or "No response from Ollama")

    data = extract_json_from_llm(result_text)
    if not data:
        logger.warning("[llm_utils] Could not parse JSON from coherence check response")
        raise RuntimeError("Could not parse JSON response from Ollama")

    return {
        "score":      max(0, min(100, int(data.get("score", 0)))),
        "notes":      [str(n) for n in data.get("notes", []) if n],
        "suggestion": str(data.get("suggestion", text)),
    }


def generate_structured_summary(
    text: str,
    content_hint: str = 'transcription',
    language: str = 'fr',
    model: str = 'qwen3:14b-q8_0',
) -> dict:
    """
    Generate a structured summary (summary, key_points, action_items) using Ollama.

    Args:
        text:         Source text to summarize (will be truncated to ~8000 chars).
        content_hint: 'transcription' | 'description' | 'audio' | 'video'
        language:     'fr' | 'en'
        model:        Ollama model to use.

    Returns:
        {
            "summary":      str,
            "key_points":   [str, ...],
            "action_items": [str, ...],
        }
        Empty strings / lists on failure.
    """
    lang_label = "en français" if language == 'fr' else "in English"
    content_type_label = {
        'transcription': 'réunion ou entretien',
        'description':   'document ou média',
        'audio':         'contenu audio',
        'video':         'contenu vidéo',
    }.get(content_hint, 'document')

    truncated = text[:8000] + ('…' if len(text) > 8000 else '')

    messages = [
        {
            "role": "system",
            "content": (
                f"Tu es un assistant d'analyse documentaire. "
                f"Réponds toujours {lang_label} avec un JSON valide et rien d'autre."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Analyse ce contenu ({content_type_label}) et retourne un JSON avec ces clés :\n"
                f'- "summary": résumé en 2-3 phrases\n'
                f'- "key_points": liste de 3-5 points clés (strings)\n'
                f'- "action_items": liste d\'actions identifiées (strings, peut être vide)\n\n'
                f"Contenu :\n{truncated}\n\n"
                f"Réponds UNIQUEMENT avec le JSON, sans texte avant ou après."
            ),
        },
    ]

    result_text, error = ollama_chat(messages, model=model)

    if error or not result_text:
        logger.warning(f"[llm_utils] generate_structured_summary failed: {error}")
        raise RuntimeError(error or "No response from Ollama")

    data = extract_json_from_llm(result_text)
    if not data:
        logger.warning("[llm_utils] Could not parse JSON from LLM response")
        raise RuntimeError("Could not parse JSON response from Ollama")

    return {
        "summary":      str(data.get("summary", "")),
        "key_points":   [str(p) for p in data.get("key_points", []) if p],
        "action_items": [str(a) for a in data.get("action_items", []) if a],
    }
