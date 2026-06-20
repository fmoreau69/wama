"""
Prospection de modèles — version DÉTERMINISTE (sans LLM, sans scraping).

Interroge l'API officielle `huggingface_hub` pour lister les modèles notables d'une tâche
(triés par téléchargements) et signale ceux que WAMA possède déjà. C'est le socle factuel :
la couche multi-agents (lecture de benchmarks, confrontation d'avis, score de confiance)
viendra PAR-DESSUS ce signal, et toute intégration reste soumise à acceptation admin.

Mapping app WAMA → tâche HF dans `APP_TASKS`.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# Tâche HuggingFace par défaut pour chaque app WAMA (point de départ de la prospection).
APP_TASKS = {
    'imager':       'text-to-image',
    'video':        'text-to-video',
    'transcriber':  'automatic-speech-recognition',
    'synthesizer':  'text-to-speech',
    'describer':    'image-text-to-text',
    'anonymizer':   'object-detection',
    'enhancer':     'image-to-image',
}

# Tâche HF → ModelType valide (cf. models.ModelType).
_TASK_MODEL_TYPE = {
    'text-to-image':                 'diffusion',
    'text-to-video':                 'diffusion',
    'image-to-image':                'upscaling',
    'automatic-speech-recognition':  'speech',
    'text-to-speech':                'speech',
    'image-text-to-text':            'vlm',
    'object-detection':              'vision',
}


def prospect_hf(task: str, limit: int = 15, library: str | None = None, min_downloads: int = 0):
    """
    Top modèles HF d'une `task` (par téléchargements), avec flag « déjà dans WAMA ».
    Retourne {'ok': True, 'task': str, 'candidates': [...]} ou {'ok': False, 'error': str}.
    """
    try:
        from huggingface_hub import HfApi
    except ImportError:
        return {'ok': False, 'error': "huggingface_hub non installé (pip install huggingface_hub)"}

    from wama.model_manager.models import AIModel
    have = {(m.hf_id or '').lower() for m in AIModel.objects.exclude(hf_id='')}

    api = HfApi()
    # huggingface_hub 1.x : filtrage par tâche = `pipeline_tag` (pas `task`), librairie via `filter`.
    kwargs = {'pipeline_tag': task, 'sort': 'downloads', 'limit': limit,
              'expand': ['downloads', 'likes', 'lastModified', 'pipeline_tag']}
    if library:
        kwargs['filter'] = library
    try:
        models = list(api.list_models(**kwargs))
    except Exception as e:
        # Repli si `expand` non supporté/incompatible avec ce filtre.
        kwargs.pop('expand', None)
        try:
            models = list(api.list_models(**kwargs))
        except Exception as e2:
            return {'ok': False, 'error': f"{type(e2).__name__}: {e2}"}
    # Garantir l'ordre décroissant par téléchargements quel que soit le défaut de l'API.
    models.sort(key=lambda m: getattr(m, 'downloads', 0) or 0, reverse=True)

    candidates = []
    for m in models:
        dl = getattr(m, 'downloads', 0) or 0
        if dl < min_downloads:
            continue
        lm = getattr(m, 'last_modified', None)
        candidates.append({
            'hf_id': m.id,
            'downloads': dl,
            'likes': getattr(m, 'likes', 0) or 0,
            'pipeline_tag': getattr(m, 'pipeline_tag', None) or task,
            'last_modified': lm.isoformat() if hasattr(lm, 'isoformat') else (lm or None),
            'have': m.id.lower() in have,
        })
    return {'ok': True, 'task': task, 'candidates': candidates}


def apply_recommendations(candidates, source: str, task: str):
    """
    Crée/maj des entrées `recommended` dans le catalogue pour les candidats NOUVEAUX (pas déjà
    dans WAMA). Non téléchargées, non disponibles, préfixe model_id `rec-` (distinctes des
    modèles découverts). Le flag `extra_info['recommended']` est préservé par le sync. Retourne
    le nombre d'entrées écrites. L'installation effective reste une action admin (HF à venir).
    """
    import re
    from datetime import datetime, timezone
    from wama.model_manager.models import AIModel

    mt = _TASK_MODEL_TYPE.get(task, 'llm')
    now = datetime.now(timezone.utc).isoformat()
    n = 0
    for c in candidates:
        if c.get('have'):
            continue
        hf_id = c['hf_id']
        model_id = 'rec-' + re.sub(r'[^a-z0-9.-]+', '-', hf_id.lower()).strip('-')
        AIModel.objects.update_or_create(
            model_key=f"{source}:{model_id}",
            defaults={
                'name': hf_id.split('/')[-1],
                'source': source,
                'model_type': mt,
                'hf_id': hf_id,
                'description': f"(Recommandé · prospection) {task} — {c['downloads']} téléchargements, {c['likes']} ♥",
                'is_downloaded': False,
                'is_available': False,
                'extra_info': {'recommended': {
                    'task': task,
                    'downloads': c['downloads'],
                    'likes': c['likes'],
                    'pipeline_tag': c.get('pipeline_tag'),
                    'prospected_at': now,
                }},
            },
        )
        n += 1
    return n
