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

def abilities_for(task: str, remote_type: str = '') -> dict:
    """Drapeaux `ModelAbility` qu'une TÂCHE distante garantit — ceux que `select_model(requires=…)`
    exige (`completion` pour un chat, `embedding` pour un vecteur).

    Lus dans la colonne Ollama de `TASK_TO_PLATFORM_TAGS` — le seul référentiel qui parle en
    capacités, et la table que la découverte Ollama utilise déjà. Jusqu'au 2026-09-18 une table
    locale (`_TASK_ABILITIES`) redisait deux lignes de cette colonne et oubliait la troisième :
    les embeddings d'Albert n'avaient pas `embedding=True`, donc un `requires=['embedding']` ne
    les voyait jamais, alors que `ollama:bge-m3` le portait.
    """
    from wama.model_manager.models import platform_tag
    flags = {}
    ability = platform_tag(task, 'ollama')
    if ability:
        flags[ability] = True
    if remote_type in _CHAT_MULTIMODAL:
        flags['vision'] = True
    return flags

#: Types distants qui désignent un modèle de CHAT acceptant des images (Claude, gemma-4 et
#: mistral-small chez Albert). MESURÉ le 2026-09-16 : les ranger en `captioning`/`vlm` les sortait
#: du domaine de l'assistant, alors qu'Ollama range exactement les mêmes modèles en `llm` avec
#: `vision=True` (`ollama:gemma4:12b`). On suit la convention LOCALE : une seule façon de dire
#: « modèle de conversation qui voit », sinon le même modèle se lit différemment selon d'où il vient.
_CHAT_MULTIMODAL = ('image-text-to-text',)

#: Familles DISTANTES dont le type annoncé par le FOURNISSEUR est imprécis — même nature que
#: `model_registry.FAMILLES_OLLAMA`, et même règle : déclaration HUMAINE, jamais devinée d'un nom.
#: Mesuré le 2026-09-16 : Albert sert `lightonocr-2-1b` en `image-text-to-text`, c'est-à-dire
#: « modèle de chat qui voit » — or c'est un OCR, et il entrait donc au menu de l'assistant.
#: Clé = `<source>:<préfixe de FAMILLE>` (pas un identifiant complet : épingler `lightonocr-2-1b`
#: raterait `lightonocr-3` en silence, et un fournisseur renomme ses versions plus souvent qu'il ne
#: change de famille — même règle de préfixe que `FAMILLES_OLLAMA`).
#: Valeur = tâche de NOTRE vocabulaire (`ModelTask`).
FAMILLES_DISTANTES = {
    'albert:lightonocr': 'ocr',
}


def _tache_declaree(model_key: str):
    """Tâche DÉCLARÉE pour la famille de `model_key`, ou None."""
    for prefixe, tache in FAMILLES_DISTANTES.items():
        if model_key.startswith(prefixe):
            return tache
    return None


#: Version d'API qu'Anthropic exige sur chaque requête.
ANTHROPIC_VERSION = '2023-06-01'
#: Protocoles SANS liste de modèles. ⚠ MESURÉ le 2026-09-15 : le jeton `claude setup-token` est
#: REFUSÉ (HTTP 401) par `GET /v1/models`, alors qu'il fait tourner le CLI (appel réel OK). Le
#: CLI choisit lui-même son modèle : il n'y a donc rien à découvrir, et un « refus » affiché au
#: profil aurait laissé croire que le jeton ne marche pas.
UNLISTABLE_PROTOCOLS = ('claude_cli',)


def _auth_headers(src, api_key: str) -> dict:
    """En-têtes d'authentification de la liste de modèles, selon le protocole DÉCLARÉ."""
    if src.protocol == 'anthropic':
        return {'x-api-key': api_key, 'anthropic-version': ANTHROPIC_VERSION}
    return {'Authorization': f'Bearer {api_key}'}


class CloudDiscoveryError(RuntimeError):
    """Découverte impossible — message lisible par l'utilisateur, jamais la clé."""


def task_and_type(remote_type: str):
    """(tâche NÔTRE, model_type) d'un type annoncé par le fournisseur, ou (None, None).

    Aucune devinette : un type qu'aucun vocabulaire ne connaît (le reranking d'Albert,
    `text-classification`) n'entre pas au catalogue plutôt que d'y entrer mal rangé.
    """
    from wama.model_manager.models import canonical_task, model_type_for_task
    from .prospector import hf_task_to_wama

    if remote_type in _CHAT_MULTIMODAL:
        return 'text-generation', 'llm'
    tag = _PROVIDER_TYPE_TO_HF_TAG.get(remote_type, remote_type or '')
    task = canonical_task(tag)
    model_type = model_type_for_task(task)
    if model_type:
        return task, model_type
    task, model_type = hf_task_to_wama(tag)
    return (task, model_type) if task else (None, None)


def list_remote_models(source: str, api_key: str, timeout: float = 20.0) -> list:
    """Modèles ouverts à `api_key` chez `source` : [{id, name, type, aliases}]."""
    import requests

    src = external_sources.get(source)
    label = src.label
    params = {'limit': 1000} if src.protocol == 'anthropic' else None
    try:
        r = requests.get(f"{external_sources.base_url(source)}/models",
                         headers=_auth_headers(src, api_key), params=params,
                         proxies=external_sources.proxies_for(source), timeout=timeout)
    except requests.RequestException as exc:
        raise CloudDiscoveryError(f"{label} injoignable ({type(exc).__name__})") from exc
    if r.status_code in (401, 403):
        raise CloudDiscoveryError(f"clé refusée par {label} (HTTP {r.status_code})")
    if not r.ok:
        raise CloudDiscoveryError(f"{label} : HTTP {r.status_code}")
    out = []
    for m in (r.json().get('data') or []):
        if not m.get('id'):
            continue
        # Protocole OpenAI (Albert) : `type` est une tâche. Chez Anthropic, `type` vaut « model »
        # (la nature de l'objet), pas une tâche : on prend alors le type DÉCLARÉ par la source.
        remote_type = (m.get('type') if src.protocol == 'openai' else '') or src.default_remote_type
        out.append({'id': m['id'], 'name': m.get('display_name') or m['id'],
                    'type': remote_type or '', 'aliases': m.get('aliases') or []})
    return out


def declared_listing(source: str) -> list:
    """Liste DÉCLARÉE d'un fournisseur sans liste de modèles (abonnement Claude Code : le CLI
    choisit lui-même) — même forme que ce que `list_remote_models` rend, un seul modèle `default`.

    Sans cette ligne, l'abonnement n'existerait pas pour le sélecteur commun et il faudrait lui
    tailler un chemin à part — exactement ce qu'on cherche à supprimer. `declared` reste lisible
    en base (`extra_info['declared']`) : la ligne est déclarée, jamais découverte chez le fournisseur.
    """
    src = external_sources.get(source)
    return [{'id': 'default', 'name': src.label, 'type': src.default_remote_type or '',
             'aliases': [], 'declared': True}]


def model_info_for(source: str, item: dict):
    """`ModelInfo` d'un modèle distant rangeable, ou None si aucun vocabulaire ne sait le ranger.

    La ligne de catalogue n'est plus écrite ici (2026-09-18) : elle passe par la synchronisation
    commune (`ModelSyncService._sync_model`), avec les mêmes règles de fusion que tout modèle
    découvert. Ce qui se déclare ici est ce que la découverte SAIT d'un modèle distant : sa tâche
    (traduite du type annoncé), ses drapeaux, son moteur (le fournisseur), son coût, et qu'il ne
    s'exécute pas ici. `platform_ref` n'est PAS posé par la découverte — comme pour tout modèle,
    c'est la provenance (`set_identity`) qui le porte, par le manifeste (cf. `refresh_key`).
    """
    from wama.model_manager.models import (EXECUTION_CLOUD, ModelSource, ModelType,
                                           model_type_for_task)
    from .model_registry import ModelInfo

    src = external_sources.get(source)
    remote_type = item.get('type') or ''
    task, model_type = task_and_type(remote_type)
    if not model_type:
        return None
    key = f"{source}:{item['id']}"
    # La tâche DÉCLARÉE prime sur celle qu'annonce le fournisseur, et la CATÉGORIE en dérive.
    declaree = _tache_declaree(key)
    if declaree:
        task = declaree
        model_type = model_type_for_task(task) or model_type
    hf_id = next((a for a in (item.get('aliases') or []) if '/' in str(a)), '')
    declared = bool(item.get('declared'))
    return ModelInfo(
        id=item['id'], name=item.get('name') or item['id'],
        model_type=ModelType(model_type), source=ModelSource(source),
        description=(f"{src.label} — le modèle est choisi par le fournisseur" if declared
                     else f"{src.label} — modèle distant ({remote_type})"),
        hf_id=hf_id or None, vram_gb=0, ram_gb=0, is_downloaded=False,
        backend_ref=source, execution=EXECUTION_CLOUD, cost_tier=src.cost_tier,
        # Le MOTEUR est le fournisseur (inventaire `external_sources.llm_engine_inventory`).
        composition={'runtime': {'engine': source}},
        capabilities={'task': task, **abilities_for(task, remote_type)},
        extra_info={'remote_type': remote_type, 'aliases': list(item.get('aliases') or []),
                    'hosting': src.hosting, **({'declared': True} if declared else {})},
    )


def cloud_model_infos() -> dict:
    """`{model_key: ModelInfo}` de TOUS les modèles distants qu'une clé d'utilisateur ouvre —
    la découverte CLOUD du registre (`ModelRegistry._discover_cloud_models`).

    Lecture de la base seule (`UserApiKey.remote_listing`), jamais du réseau : la liste est relue
    chez le fournisseur par `refresh_key`, sur le geste du profil. L'union se fait sur toutes les
    clés d'une source — une clé qui n'ouvre pas un modèle ne prouve pas que le fournisseur l'a
    retiré.
    """
    from wama.accounts.models import UserApiKey

    infos = {}
    for source, listing in (UserApiKey.objects.exclude(api_key='').exclude(remote_listing=[])
                            .values_list('source', 'remote_listing')):
        try:
            external_sources.get(source)
        except KeyError:
            continue                                  # source retirée du registre : ligne muette
        for item in listing or []:
            if not isinstance(item, dict) or not item.get('id'):
                continue
            key = f"{source}:{item['id']}"
            if key in infos:
                continue
            info = model_info_for(source, item)
            if info is not None:
                infos[key] = info
    return infos


def keys_for(source: str, listing: list) -> list:
    """Clés de catalogue des modèles rangeables d'une liste — ce que `UserApiKey.open_models` garde."""
    return [f"{source}:{item['id']}" for item in listing
            if item.get('id') and model_info_for(source, item) is not None]


def retire_unlisted(source: str) -> int:
    """Marque indisponibles les lignes distantes de `source` qu'AUCUNE clé n'ouvre plus, et remet
    disponibles celles qu'une clé ouvre à nouveau. Rend le nombre de lignes retirées.

    Un fournisseur renomme ses identifiants (mesuré le 2026-09-18 chez Albert :
    `openai/gpt-oss-120b` devenu `gpt-oss-120b`, `…-A3b-…` devenu `…-a3b-…`) : la découverte
    AJOUTAIT la nouvelle ligne sans jamais retirer l'ancienne, et le sélecteur proposait deux fois
    le même modèle, dont une version que personne ne pouvait plus appeler.

    Même idiome que le remplacement d'un modèle Ollama (`install_candidate`) : la synchronisation
    commune n'enlève rien (`full_sync()` sans `remove_missing`, et le beat tourne `clean=False`),
    c'est l'ACTEUR qui sait qu'un retrait a eu lieu qui marque les lignes. MARQUÉES, jamais
    supprimées — doctrine de `uninstall_model` : la ligne porte l'historique, et `select_model`
    l'ignore tant qu'elle est indisponible. Re-listée par le fournisseur, elle redevient disponible.
    """
    from wama.accounts.models import UserApiKey
    from wama.model_manager.models import AIModel, EXECUTION_CLOUD

    ouvertes = set()
    for liste in UserApiKey.objects.filter(source=source).values_list('open_models', flat=True):
        ouvertes.update(liste or [])
    lignes = AIModel.objects.filter(source=source, execution=EXECUTION_CLOUD, is_proposed=False)
    retirees = lignes.exclude(model_key__in=ouvertes).filter(is_available=True).update(is_available=False)
    lignes.filter(model_key__in=ouvertes, is_available=False).update(is_available=True)
    return retirees


def refresh_key(row) -> tuple:
    """Relit chez le fournisseur les modèles ouverts à la clé `row` (`accounts.UserApiKey`), puis
    passe par la MÊME chaîne qu'une installation : synchronisation du catalogue (la découverte
    cloud lit la liste gardée sur la clé), provenance par le manifeste, corpus.

    Rend (nombre de modèles, message d'erreur ou ''). Une erreur est GARDÉE sur la ligne et la
    liste précédente conservée : un fournisseur injoignable ne ferme rien à l'utilisateur.
    """
    from django.utils import timezone

    if external_sources.get(row.source).protocol in UNLISTABLE_PROTOCOLS:
        listing = declared_listing(row.source)
    else:
        try:
            listing = list_remote_models(row.source, row.api_key)
        except CloudDiscoveryError as exc:
            row.discovery_error = str(exc)[:255]
            row.save(update_fields=['discovery_error'])
            logger.warning("[cloud_models] découverte %s pour %s : %s", row.source, row.user_id, exc)
            return 0, row.discovery_error
    row.remote_listing = listing
    row.open_models = keys_for(row.source, listing)
    row.discovered_at, row.discovery_error = timezone.now(), ''
    row.save(update_fields=['remote_listing', 'open_models', 'discovered_at', 'discovery_error'])

    # Synchronisation COMMUNE (celle d'une installation), puis retrait de ce que plus aucune clé
    # n'ouvre, puis provenance : l'identité d'éditeur (dépôt HuggingFace servi) entre par le
    # manifeste et le corpus reçoit la ligne — exactement `record_after_install`, sans spec.
    from .model_installer import register_after_install
    from .provenance import cloud_identity, set_identity
    try:
        register_after_install()
    except Exception:
        logger.warning("register_after_install a échoué après la découverte %s (le sync "
                       "périodique rattrapera)", row.source, exc_info=True)
    retire_unlisted(row.source)
    for item in listing:
        identite = cloud_identity(item)
        key = f"{row.source}:{item['id']}"
        if identite and key in row.open_models:
            try:
                set_identity(key, identite)
            except Exception:
                logger.warning("provenance non enregistrée pour %s", key, exc_info=True)
    return len(row.open_models), ''


def cloud_refusal(user) -> str:
    """Motif de refus si `user` est en « 100 % local », sinon ''. Sans utilisateur : ''.

    Domicile UNIQUE de la garde : l'appel LLM de l'assistant et `claude_code.demander` (outil
    `ask_claude_code`, fournisseur abonnement, geste `!code`) la lisent tous deux.
    """
    if user is None or not getattr(user, 'is_authenticated', False):
        return ''
    if getattr(getattr(user, 'profile', None), 'cloud_policy', 'local_only') == 'local_only':
        return ("Votre profil est en « 100 % local » : pour utiliser un fournisseur distant, "
                "choisissez un autre niveau dans la carte « Modèles cloud » de la page Profil.")
    return ''


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
    from wama.accounts.api_keys import llm_sources
    from wama.accounts.models import UserApiKey
    # ⚠ Les SOURCES que CET utilisateur a le droit d'utiliser, pas seulement celles dont une ligne
    # de clé existe : l'abonnement Claude Code est `developer_only`. Mesuré le 2026-09-16 — sans ce
    # filtre, un compte ordinaire portant une ligne `claude_code` voyait le modèle d'abonnement
    # dans le sélecteur commun, alors que la garde du moteur le lui refuse.
    ouvertes = {s.key for s in llm_sources(user)}
    keys = set()
    # `values_list` : les modèles seuls, sans déchiffrer la clé.
    for opened in (UserApiKey.objects.filter(user=user, source__in=ouvertes).exclude(api_key='')
                   .values_list('open_models', flat=True)):
        keys.update(opened or [])
    return keys
