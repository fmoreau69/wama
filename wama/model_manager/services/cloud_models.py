"""
Modèles DISTANTS au catalogue — découverte par la clé d'un UTILISATEUR (ROADMAP §8d Phase 3, 4b).

LE VERROU LEVÉ : `AIModel` ne savait décrire que des modèles LOCAUX. Un modèle distant y entre
désormais comme les autres (le modèle porte son moteur, le fournisseur se DÉRIVE) : ligne
`<source>:<id>`, `execution='cloud'`, moteur = la source `external_sources` qui porte adresse et clé.

DÉCOUVERTE PAR LES CLÉS DES UTILISATEURS (Fabien, 15/09) : à l'enregistrement d'une clé, WAMA lit
les modèles ouverts à CE compte (`GET /models`) et les garde avec la clé ; le catalogue porte
l'UNION. Chaque utilisateur ne choisit que ce que SA clé ouvre.
⚠ Une clé qui ne voit plus un modèle ne prouve pas qu'il a disparu (il peut être fermé à ce seul
compte) : la découverte AJOUTE et MET À JOUR, elle ne retire rien du catalogue.

NON-RÉGRESSION : ces lignes n'entrent au tirage que par `select_model(cloud_keys=…)`, que
`allowed_cloud_keys` calcule d'après le niveau cloud du profil.
"""
from __future__ import annotations

import logging

from wama.common import external_sources

logger = logging.getLogger(__name__)

#: Vocabulaire propre au serveur d'inférence du FOURNISSEUR, ni nôtre ni HuggingFace : Albert sert
#: ses embeddings par Text Embeddings Inference. Traduit vers le tag HF équivalent, puis le
#: vocabulaire commun (`canonical_task`) prend le relais.
_PROVIDER_TYPE_TO_HF_TAG = {'text-embeddings-inference': 'feature-extraction'}

#: Capacités qu'une TÂCHE distante garantit — celles que la sélection exige (`requires`).
#: `completion` : ce que `llm_utils._llm_par_catalogue` demande à un modèle de chat.
_TASK_ABILITIES = {
    'text-generation': {'completion': True},
    'captioning': {'completion': True, 'vision': True},
}


class CloudDiscoveryError(RuntimeError):
    """Découverte impossible — message lisible par l'utilisateur, jamais la clé."""


def task_and_type(remote_type: str):
    """(tâche NÔTRE, model_type) d'un type annoncé par le fournisseur, ou (None, None).

    Aucune devinette : un type qu'aucun vocabulaire ne connaît (le reranking d'Albert,
    `text-classification`) n'entre pas au catalogue plutôt que d'y entrer mal rangé.
    """
    from wama.model_manager.models import canonical_task, model_type_for_task
    from .prospector import hf_task_to_wama

    tag = _PROVIDER_TYPE_TO_HF_TAG.get(remote_type, remote_type or '')
    task = canonical_task(tag)
    model_type = model_type_for_task(task)
    if model_type:
        return task, model_type
    task, model_type = hf_task_to_wama(tag)
    return (task, model_type) if task else (None, None)


def list_remote_models(source: str, api_key: str, timeout: float = 20.0) -> list:
    """Modèles ouverts à `api_key` chez `source` : [{id, type, aliases}]."""
    import requests

    label = external_sources.get(source).label
    try:
        r = requests.get(f"{external_sources.base_url(source)}/models",
                         headers={'Authorization': f'Bearer {api_key}'},
                         proxies=external_sources.proxies_for(source), timeout=timeout)
    except requests.RequestException as exc:
        raise CloudDiscoveryError(f"{label} injoignable ({type(exc).__name__})") from exc
    if r.status_code in (401, 403):
        raise CloudDiscoveryError(f"clé refusée par {label} (HTTP {r.status_code})")
    if not r.ok:
        raise CloudDiscoveryError(f"{label} : HTTP {r.status_code}")
    return [{'id': m['id'], 'type': m.get('type') or '', 'aliases': m.get('aliases') or []}
            for m in (r.json().get('data') or []) if m.get('id')]


def upsert_catalog(source: str, remote: list) -> list:
    """Écrit (ou met à jour) une ligne de catalogue par modèle distant rangeable ; rend leurs clés."""
    from wama.model_manager.models import AIModel, EXECUTION_CLOUD

    src = external_sources.get(source)
    keys = []
    for m in remote:
        task, model_type = task_and_type(m['type'])
        if not model_type:
            continue
        key = f"{source}:{m['id']}"
        AIModel.objects.update_or_create(model_key=key, defaults={
            'name': m['id'],
            'model_type': model_type,
            'source': source,
            'execution': EXECUTION_CLOUD,
            'cost_tier': src.cost_tier,
            'description': f"{src.label} — modèle distant ({m['type']})",
            'hf_id': next((a for a in m['aliases'] if '/' in a), ''),
            'is_downloaded': False,
            'is_available': True,
            'vram_gb': 0,
            'backend_ref': source,
            # Le MOTEUR est le fournisseur (inventaire `external_sources.llm_engine_inventory`).
            'composition': {'runtime': {'engine': source}},
            'capabilities': {'task': task, **_TASK_ABILITIES.get(task, {})},
            'extra_info': {'remote_type': m['type'], 'aliases': m['aliases'],
                           'hosting': src.hosting},
        })
        keys.append(key)
    return keys


def refresh_key(row) -> tuple:
    """Relit chez le fournisseur les modèles ouverts à la clé `row` (`accounts.UserApiKey`).

    Rend (nombre de modèles, message d'erreur ou ''). Une erreur est GARDÉE sur la ligne et la
    liste précédente conservée : un fournisseur injoignable ne ferme rien à l'utilisateur.
    """
    from django.utils import timezone

    try:
        remote = list_remote_models(row.source, row.api_key)
    except CloudDiscoveryError as exc:
        row.discovery_error = str(exc)[:255]
        row.save(update_fields=['discovery_error'])
        logger.warning("[cloud_models] découverte %s pour %s : %s", row.source, row.user_id, exc)
        return 0, row.discovery_error
    row.open_models = upsert_catalog(row.source, remote)
    row.discovered_at = timezone.now()
    row.discovery_error = ''
    row.save(update_fields=['open_models', 'discovered_at', 'discovery_error'])
    return len(row.open_models), ''


def allowed_cloud_keys(user, automatic: bool = True) -> set:
    """`model_key` des modèles distants que `user` autorise — à passer à `select_model(cloud_keys=…)`.

    Les 3 niveaux du profil (Fabien, 15/09) :
    - « 100 % local » → rien, ni en automatique ni au choix manuel ;
    - « cloud si WAMA est saturé » → le choix MANUEL s'ouvre ; le tirage AUTOMATIQUE n'ouvre le
      distant que sur saturation, signal que porte le chantier du curseur (⏳ — d'ici là, rien) ;
    - « cloud autorisé » → les deux.
    """
    if user is None or not getattr(user, 'is_authenticated', False):
        return set()
    policy = getattr(getattr(user, 'profile', None), 'cloud_policy', 'local_only')
    if policy == 'local_only' or (automatic and policy != 'cloud_allowed'):
        return set()
    from wama.accounts.models import UserApiKey
    keys = set()
    # `values_list` : les modèles seuls, sans déchiffrer la clé.
    for opened in (UserApiKey.objects.filter(user=user).exclude(api_key='')
                   .values_list('open_models', flat=True)):
        keys.update(opened or [])
    return keys
