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


# ModelType (catalogue) → catégorie de dossier (model_locations.model_dir).
_TYPE_CATEGORY = {
    'diffusion': 'diffusion',
    'speech':    'speech',
    'vlm':       'vlm',
    'vision':    'detect',
    'upscaling': 'enhance',
    'ocr':       'ocr',
    'music':     'music',
    'llm':       'llm',
}


def pull_hf_model(hf_id: str, category: str, family: str | None = None,
                  dry_run: bool = False, allow_patterns=None, progress=None):
    """
    Télécharge un modèle HuggingFace DANS LE BON DOSSIER (catégorie WAMA) via l'API officielle
    `snapshot_download(cache_dir=…)` — on catégorise par `cache_dir`, SANS muter `HF_HUB_CACHE`
    global (cause de dispersion/doublons quand plusieurs threads le mutent en concurrence).

    `dry_run` : ne télécharge pas, retourne juste le dossier cible (valide la logique de chemin).
    Retourne {'ok': bool, 'path'|'target'|'error': …}.

    NB : « téléchargé + catalogué » ≠ « utilisable dans l'app » — l'usage requiert un backend qui
    sache charger ce modèle (problème du chargeur générique, séparé).
    """
    import os
    try:
        from wama.common.utils.model_locations import model_dir
        target = str(model_dir(category, family or hf_id.split('/')[-1]))
    except Exception as e:
        return {'ok': False, 'error': f"résolution dossier: {type(e).__name__}: {e}"}

    if dry_run:
        return {'ok': True, 'target': target, 'dry_run': True}

    os.makedirs(target, exist_ok=True)
    try:
        from huggingface_hub import snapshot_download
        path = snapshot_download(repo_id=hf_id, cache_dir=target, allow_patterns=allow_patterns)
        return {'ok': True, 'path': path, 'target': target}
    except Exception as e:
        return {'ok': False, 'error': f"{type(e).__name__}: {e}"}


def register_after_install():
    """
    Re-synchronise le catalogue `AIModel` pour que le modèle fraîchement installé apparaisse.
    Réutilise `full_sync` (clean=False : ne touche pas aux autres sources). Retourne le résumé.
    """
    from .model_sync import ModelSyncService
    return ModelSyncService().full_sync()
