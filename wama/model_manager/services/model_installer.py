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


# Suffixe de nom de poids → sous-dossier de tâche YOLO (AI-models/models/vision/yolo/<task>/).
_YOLO_TASK_DIRS = {'-seg': 'segment', '-obb': 'obb', '-pose': 'pose', '-cls': 'classify'}


def pull_yolo_weights(name: str, timeout: int = 600, dry_run: bool = False):
    """
    Télécharge des poids YOLO OFFICIELS (assets GitHub Ultralytics, URL stable
    `releases/latest/download/<name>.pt`) DANS LE BON DOSSIER :
    `AI-models/models/vision/yolo/<task>/<name>.pt` — le sous-dossier de tâche est déduit
    du suffixe du nom (-seg/-obb/-pose/-cls, sinon detect), exactement l'arborescence que
    `model_registry` découvre au sync. Ouvre l'installation VISION du model_manager
    (l'endpoint prospect/install n'était qu'Ollama — phase 1).

    `dry_run` : ne télécharge pas, retourne la cible (valide la logique de chemin).
    Retourne {'ok': bool, 'path'|'target'|'error': …}. Idempotent : fichier déjà présent → ok.
    """
    import os
    import re
    import requests
    from django.conf import settings

    base = name[:-3] if name.endswith('.pt') else name
    # Noms officiels uniquement (yolo11s-seg, yolo26x, yolov12n-seg…) — pas d'URL arbitraire.
    if not re.fullmatch(r'yolo[a-z0-9._\-]+', base, re.IGNORECASE):
        return {'ok': False, 'error': f"nom de poids YOLO invalide: {name!r}"}
    task = next((d for suf, d in _YOLO_TASK_DIRS.items() if base.endswith(suf)), 'detect')
    target_dir = os.path.join(str(settings.AI_MODELS_DIR), 'models', 'vision', 'yolo', task)
    target = os.path.join(target_dir, f"{base}.pt")
    if dry_run:
        return {'ok': True, 'target': target, 'dry_run': True}
    if os.path.exists(target):
        return {'ok': True, 'path': target, 'already': True}

    os.makedirs(target_dir, exist_ok=True)
    url = f"https://github.com/ultralytics/assets/releases/latest/download/{base}.pt"
    tmp = target + '.part'
    try:
        with requests.get(url, stream=True, timeout=timeout, allow_redirects=True) as r:
            r.raise_for_status()
            with open(tmp, 'wb') as fh:
                for chunk in r.iter_content(chunk_size=1 << 20):
                    fh.write(chunk)
        # Garde-fou : une page d'erreur HTML ferait un .pt de quelques Ko.
        if os.path.getsize(tmp) < 1_000_000:
            os.remove(tmp)
            return {'ok': False, 'error': f"téléchargement suspect (<1 Mo) — poids inexistant ? {url}"}
        os.replace(tmp, target)
        return {'ok': True, 'path': target, 'url': url}
    except Exception as e:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except OSError:
            pass
        return {'ok': False, 'error': f"{type(e).__name__}: {e}"}


def register_after_install():
    """
    Re-synchronise le catalogue `AIModel` pour que le modèle fraîchement installé apparaisse.
    Réutilise `full_sync` (clean=False : ne touche pas aux autres sources). Retourne le résumé.
    """
    from .model_sync import ModelSyncService
    return ModelSyncService().full_sync()


def install_from_spec(spec: dict) -> dict:
    """
    Point d'entrée UNIQUE d'installation — DESCRIPTEUR déclaratif au lieu de mécanismes
    hardcodés par type. Le spec peut être construit par l'UI, par la prospection, ou par
    l'ASSISTANT IA (pipeline cible : besoin utilisateur → modèle → librairie → app →
    install ; voir PROSPECTION_PIPELINE.md). Les `pull_*` existants deviennent les
    drivers derrière ce dispatcher.

    spec = {
      'kind': 'ollama' | 'hf' | 'yolo',        # driver d'installation
      'ref':  'qwen3:8b' | 'org/model' | 'yolo26s-seg',
      'category': 'diffusion' | 'speech' | …,  # hf : catégorie de dossier (model_locations)
      'family': 'qwen-image',                  # hf : sous-dossier famille (optionnel)
      'allow_patterns': ['*.safetensors'],     # hf : restreindre les fichiers (optionnel)
      'pip_dependencies': ['lib>=x'],          # optionnel — VALIDATION HUMAINE OBLIGATOIRE
      'human_validated': True,                 # requis si pip_dependencies non vide
      'note': 'pourquoi ce modèle',            # traçabilité (journalisée)
    }
    Retourne {'ok': bool, …} (mêmes clés que les drivers, + 'pip' si dépendances).
    """
    spec = spec or {}
    kind = spec.get('kind')
    ref = (spec.get('ref') or '').strip()
    if not ref:
        return {'ok': False, 'error': 'spec.ref requis'}
    deps = [d for d in (spec.get('pip_dependencies') or []) if d]
    # ⚠ Installer des paquets = surface de risque (cf. pip_install_packages) : le spec
    # doit porter la preuve d'une validation humaine explicite, jamais d'auto.
    if deps and not spec.get('human_validated'):
        return {'ok': False,
                'error': "pip_dependencies exige une validation humaine explicite "
                         "(spec.human_validated=true)"}
    if spec.get('note'):
        logger.info("install_from_spec %s:%s — %s", kind, ref, spec['note'])

    if kind == 'ollama':
        res = pull_ollama_model(ref)
    elif kind == 'yolo':
        res = pull_yolo_weights(ref)
    elif kind == 'hf':
        if not spec.get('category'):
            return {'ok': False, 'error': "spec.category requis pour kind='hf'"}
        res = pull_hf_model(ref, spec['category'], spec.get('family'),
                            allow_patterns=spec.get('allow_patterns'))
    else:
        return {'ok': False, 'error': f"spec.kind inconnu: {kind!r} (ollama|hf|yolo)"}

    if res.get('ok') and deps:
        res['pip'] = pip_install_packages(deps)
        if not res['pip'].get('ok'):
            res['ok'] = False
            res['error'] = "modèle téléchargé mais dépendances pip en échec (voir 'pip')"
    if res.get('ok'):
        try:
            register_after_install()
        except Exception:
            logger.warning("register_after_install a échoué (le sync périodique rattrapera)",
                           exc_info=True)
    return res


def pip_install_packages(packages, timeout: int = 1800) -> dict:
    """
    Installe des paquets pip dans le venv courant — pour rendre un backend disponible quand un
    nouveau modèle exige de nouvelles libs (jonction avec le contrat BaseModelBackend).

    ⚠️ Installer des paquets arbitraires est une surface de risque → à déclencher sur VALIDATION
    HUMAINE uniquement, jamais en auto. Retourne {ok, installed, error}.
    """
    import subprocess
    import sys

    pkgs = [p for p in (packages or []) if p]
    if not pkgs:
        return {'ok': True, 'installed': []}
    try:
        proc = subprocess.run(
            [sys.executable, '-m', 'pip', 'install', *pkgs],
            capture_output=True, text=True, timeout=timeout,
        )
        if proc.returncode == 0:
            return {'ok': True, 'installed': pkgs}
        return {'ok': False, 'installed': [], 'error': (proc.stderr or '')[-2000:]}
    except Exception as e:
        return {'ok': False, 'installed': [], 'error': f"{type(e).__name__}: {e}"}


def ensure_backend_deps(backend_cls, timeout: int = 1800) -> dict:
    """
    Installe les paquets manquants d'un backend (classe `BaseModelBackend`) si nécessaire.
    Lit `missing_packages()` (import) et `pip_install_spec()` (noms pip). No-op si déjà dispo.
    À appeler sur validation humaine (cf. pip_install_packages). Retourne {ok, installed, already}.
    """
    missing = backend_cls.missing_packages()
    if not missing:
        return {'ok': True, 'installed': [], 'already': True}
    res = pip_install_packages(backend_cls.pip_install_spec(), timeout=timeout)
    res['already'] = False
    return res
