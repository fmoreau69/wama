"""
Sonde vision via Ollama — décrire une image avec un modèle multimodal local (gemma4:12b, e4b…).
Sert au bench (d) : comparer des modèles candidats sur de vraies images WAMA, en français.

API LOCALE officielle Ollama `/api/chat` (champ `images` base64). Aucun scraping.
"""
from __future__ import annotations

import base64
import os


def describe_image_ollama(image_path: str, model: str = 'gemma4:12b',
                          prompt: str | None = None, timeout: int = 180):
    """Décrit une image via un modèle vision Ollama LOCAL. Retourne {'ok', 'description'|'error'}."""
    from django.conf import settings
    import requests

    if not os.path.exists(image_path):
        return {'ok': False, 'error': f"image introuvable : {image_path}"}
    try:
        with open(image_path, 'rb') as f:
            b64 = base64.b64encode(f.read()).decode()
    except OSError as e:
        return {'ok': False, 'error': f"lecture image : {e}"}

    base = getattr(settings, 'OLLAMA_HOST', 'http://127.0.0.1:11434').rstrip('/')
    prompt = prompt or "Décris cette image en français, de façon précise et concise."
    try:
        r = requests.post(f"{base}/api/chat", json={
            'model': model, 'stream': False,
            'messages': [{'role': 'user', 'content': prompt, 'images': [b64]}],
        }, timeout=timeout)
        r.raise_for_status()
        msg = (r.json().get('message') or {})
        return {'ok': True, 'description': (msg.get('content') or '').strip()}
    except Exception as e:
        return {'ok': False, 'error': f"{type(e).__name__}: {e}"}
