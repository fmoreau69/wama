"""
Sonde vision via Ollama — décrire une image avec un modèle multimodal local (gemma4:12b, e4b…).
Sert au bench (d) : comparer des modèles candidats sur de vraies images WAMA, en français.

API LOCALE officielle Ollama `/api/chat` (champ `images` base64). Aucun scraping.
"""
from __future__ import annotations

import base64
import os


def describe_image_ollama(image_path: str, model: str = 'gemma4:12b',
                          prompt: str | None = None, timeout: int = 180,
                          keep_alive: str | None = None):
    """Décrit une image via un modèle vision Ollama LOCAL. Retourne {'ok', 'description'|'error'}.

    `keep_alive` : résidence VRAM après réponse (défaut Ollama : 5 min). Une valeur courte
    ('120s') laisse s'enchaîner un LOT d'images sans repayer le chargement des poids, puis
    libère ; '0' décharge tout de suite. Cf. [[llm_utils]], même réglage côté texte.
    """
    from django.conf import settings
    import requests

    if not os.path.exists(image_path):
        return {'ok': False, 'error': f"image introuvable : {image_path}"}
    try:
        with open(image_path, 'rb') as f:
            b64 = base64.b64encode(f.read()).decode()
    except OSError as e:
        return {'ok': False, 'error': f"lecture image : {e}"}

    # Résolution via la brique (réécriture passerelle sous WSL2) ; le contournement du proxy
    # reste assuré par le `trust_env = False` posé plus bas sur la session.
    from wama.common.utils.ollama_host import ollama_base
    base = ollama_base()
    prompt = prompt or "Décris cette image en français, de façon précise et concise."
    try:
        payload = {
            'model': model, 'stream': False,
            'messages': [{'role': 'user', 'content': prompt, 'images': [b64]}],
        }
        if keep_alive is not None:
            payload['keep_alive'] = keep_alive
        # `trust_env=False` : Ollama est LOCAL. Sans ça, requests honore HTTP(S)_PROXY et
        # envoie l'appel dans le proxy UGE, qui répond 504 (constaté 2026-07-31 depuis le
        # smoke UI). Même précaution que llm_utils.ollama_chat, qui pose déjà trust_env=False.
        with requests.Session() as s:
            s.trust_env = False
            r = s.post(f"{base}/api/chat", json=payload, timeout=timeout)
        r.raise_for_status()
        msg = (r.json().get('message') or {})
        return {'ok': True, 'description': (msg.get('content') or '').strip()}
    except Exception as e:
        return {'ok': False, 'error': f"{type(e).__name__}: {e}"}
