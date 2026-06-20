"""
Pipeline accept→download→register — installation de modèles dans WAMA.

Étape 2 du système d'auto-maintenance : une fois un modèle ACCEPTÉ (par l'admin, ou plus tard
par la prospection validée), on le télécharge AU BON ENDROIT puis on l'enregistre dans le
catalogue `AIModel` pour qu'il devienne visible/sélectionnable.

Ollama d'abord : `POST /api/pull` sur le démon LOCAL = API officielle (le démon parle au
registre, pas nous → aucun scraping). HF viendra ensuite (règle CLAUDE.md : path→env→import).
"""
from __future__ import annotations

import json
import logging

logger = logging.getLogger(__name__)


def pull_ollama_model(name: str, timeout: int = 1800, progress=None):
    """
    Télécharge un modèle Ollama via le démon LOCAL (`POST /api/pull`, stream).

    `progress` : callback optionnel(status:str) pour remonter l'avancement.
    Retourne {'ok': bool, 'status': str} ou {'ok': False, 'error': str}.
    """
    from django.conf import settings
    import requests

    base = getattr(settings, 'OLLAMA_HOST', 'http://127.0.0.1:11434').rstrip('/')
    last = None
    try:
        with requests.post(f"{base}/api/pull", json={"name": name, "stream": True},
                           stream=True, timeout=timeout) as r:
            r.raise_for_status()
            for line in r.iter_lines():
                if not line:
                    continue
                try:
                    data = json.loads(line)
                except (ValueError, TypeError):
                    continue
                if data.get('error'):
                    return {'ok': False, 'error': data['error']}
                status = data.get('status')
                if status and status != last:
                    last = status
                    if progress:
                        progress(status)
        return {'ok': True, 'status': last or 'success'}
    except Exception as e:
        return {'ok': False, 'error': f"{type(e).__name__}: {e}"}


def register_after_install():
    """
    Re-synchronise le catalogue `AIModel` pour que le modèle fraîchement installé apparaisse.
    Réutilise `full_sync` (clean=False : ne touche pas aux autres sources). Retourne le résumé.
    """
    from .model_sync import ModelSyncService
    return ModelSyncService().full_sync()
