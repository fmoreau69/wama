"""
Modèles DISTANTS au catalogue — découverte par la clé d'un UTILISATEUR (ROADMAP §8d Phase 3, 4b).

LE VERROU LEVÉ : `AIModel` ne savait décrire que des modèles LOCAUX. Un modèle distant y entre
désormais comme les autres (le modèle porte son moteur, le fournisseur se DÉRIVE) : ligne
`<source>:<id>`, `execution='cloud'`, moteur = la source `external_sources` qui porte adresse et clé.

DÉCOUVERTE PAR LES CLÉS DES UTILISATEURS (Fabien, 15/09) : à l'enregistrement d'une clé, WAMA lit
les modèles ouverts à CE compte (`GET /models`) et les garde avec la clé ; le catalogue porte
l'UNION. Chaque utilisateur ne choisit que ce que SA clé ouvre.
⚠ Une clé qui ne voit plus un modèle ne prouve pas qu'il a disparu (il peut être fermé à ce seul
compte) : une ligne n'est retirée que si AUCUNE clé de la source ne l'ouvre plus — MARQUÉE
indisponible, jamais supprimée (`retire_unlisted`). *Ce paragraphe disait jusqu'au 2026-10-12
« elle ne retire rien du catalogue » : périmé depuis `retire_unlisted` (18/09).*

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


def type_from_modalities(architecture: dict) -> str:
    """Type (tag HuggingFace) d'un modèle décrit par ses MODALITÉS — la forme d'OpenRouter
    (`architecture.input_modalities` / `output_modalities`), qui ne publie pas de `type`.

    Seuls entrent les modèles qui RÉPONDENT EN TEXTE : un modèle qui produit une image ou du son
    par la même interface ne s'appelle pas par `llm_chat`, et le ranger en `text-to-image`
    l'aurait fait proposer par l'imager sans aucun moteur pour l'exécuter. '' = hors catalogue
    (`task_and_type` rend alors None, comme pour tout type inconnu).
    """
    outputs = {str(x) for x in (architecture.get('output_modalities') or [])}
    inputs = {str(x) for x in (architecture.get('input_modalities') or [])}
    if outputs != {'text'}:
        return ''
    return 'image-text-to-text' if 'image' in inputs else 'text-generation'


def _is_free(pricing) -> bool:
    """Prix publié nul en entrée ET en sortie (les modèles `:free` d'OpenRouter)."""
    if not isinstance(pricing, dict):
        return False
    try:
        return float(pricing.get('prompt')) == 0 and float(pricing.get('completion')) == 0
    except (TypeError, ValueError):
        return False


#: Lectures de la liste avant de conclure qu'un fournisseur n'en rend AUCUNE (2026-10-12).
#: MESURÉ ce jour chez ILaaS : `GET /models` répond `{"data": []}` en HTTP 200 à 9 lectures
#: sur 20, avec la même clé et les mêmes en-têtes, quand les autres rendent les 6 modèles — un
#: serveur de leur répartiteur ne connaît pas la clé (le chat, lui, répond 10 fois sur 10).
#: Cinq lectures laissent ~2 % de chances de n'en avoir que des vides, pour une seconde au plus.
LISTING_ATTEMPTS = 5


def list_remote_models(source: str, api_key: str, timeout: float = 20.0) -> list:
    """Modèles ouverts à `api_key` chez `source` : [{id, name, type, aliases[, cost_tier]}].

    Une liste VIDE n'est pas une réponse (2026-10-12) : une clé qu'un fournisseur de modèles
    accepte et à laquelle il n'ouvre rien, c'est une panne de sa liste, pas un fait. La prendre
    pour une liste vidait la clé de ses modèles et retirait leurs lignes du catalogue
    (`retire_unlisted`), au geste « Enregistrer » comme à la sonde nocturne — sans rien
    afficher. Elle est relue (`LISTING_ATTEMPTS`), puis levée en `CloudDiscoveryError` : c'est
    le chemin qui GARDE la liste précédente et dit l'erreur sur la ligne de la clé.
    """
    import requests

    src = external_sources.get(source)
    label = src.label
    params = {'limit': 1000} if src.protocol == 'anthropic' else None
    for _attempt in range(LISTING_ATTEMPTS):
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
        data = r.json().get('data') or []
        if data:
            break
    else:
        raise CloudDiscoveryError(f"{label} n'a rendu aucun modèle ({LISTING_ATTEMPTS} lectures) : "
                                  "liste précédente conservée")
    out = []
    for m in data:
        if not m.get('id'):
            continue
        # Protocole OpenAI (Albert) : `type` est une tâche. Chez Anthropic, `type` vaut « model »
        # (la nature de l'objet), pas une tâche : on prend alors le type DÉCLARÉ par la source.
        # Une liste qui décrit ses MODALITÉS (OpenRouter, 2026-10-10) dit elle-même ce qu'est le
        # modèle : le type par défaut de la source ne la complète pas.
        arch = m.get('architecture')
        if src.protocol == 'openai' and m.get('type'):
            remote_type = m['type']
        elif isinstance(arch, dict):
            remote_type = type_from_modalities(arch)
        else:
            remote_type = src.default_remote_type
        # Le dépôt SERVI, quand le fournisseur le nomme : alias `org/nom` chez Albert,
        # `hugging_face_id` chez OpenRouter — même forme pour la provenance (`cloud_identity`).
        aliases = list(m.get('aliases') or [])
        if m.get('hugging_face_id') and m['hugging_face_id'] not in aliases:
            aliases.append(m['hugging_face_id'])
        item = {'id': m['id'], 'name': m.get('display_name') or m.get('name') or m['id'],
                'type': remote_type or '', 'aliases': aliases}
        if _is_free(m.get('pricing')):
            item['cost_tier'] = 'free'      # un modèle gratuit chez un fournisseur facturé
        out.append(item)
    return out


def declared_listing(source: str) -> list:
    """Liste DÉCLARÉE d'un fournisseur sans liste de modèles (abonnement Claude Code : le CLI
    choisit lui-même) — même forme que ce que `list_remote_models` rend, un seul modèle `default`.

    Sans cette ligne, l'abonnement n'existerait pas pour le sélecteur commun et il faudrait lui
    tailler un chemin à part — exactement ce qu'on cherche à supprimer. `declared` reste lisible
    en base (`extra_info['declared']`) : la ligne est déclarée, jamais découverte chez le fournisseur.
    """
    src = external_sources.get(source)
    remote_type = src.default_remote_type or ''
    # Les modèles que la SOURCE déclare (`ExternalSource.declared_models`, 2026-10-04 : les
    # alias de Claude Code) ; une source qui n'en déclare aucun garde la ligne unique d'origine.
    declared = src.declared_models or (('default', src.label, ''),)
    return [{'id': model_id, 'name': name, 'type': remote_type, 'aliases': [], 'declared': True,
             **({'description': description} if description else {})}
            for model_id, name, description in declared]


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
                                           default_inputs_for, model_type_for_task)
    from .model_registry import ModelInfo

    src = external_sources.get(source)
    remote_type = item.get('type') or ''
    task, model_type = task_and_type(remote_type)
    if not model_type:
        return None
    key = f"{source}:{item['id']}"
    # La tâche DÉCLARÉE prime sur celle qu'annonce le fournisseur, et la CATÉGORIE en dérive.
    declared_task = _tache_declaree(key)
    if declared_task:
        task = declared_task
        model_type = model_type_for_task(task) or model_type
    hf_id = next((a for a in (item.get('aliases') or []) if '/' in str(a)), '')
    declared = bool(item.get('declared'))
    # Modalités et entrées : ce que la tâche IMPLIQUE (table commune), plus l'image quand le
    # modèle VOIT — la même dérivation que la découverte Ollama (`_capacites_canoniques`).
    abilities = abilities_for(task, remote_type)
    caps = {**default_inputs_for(task), 'task': task, **abilities}
    if abilities.get('vision') and 'image' not in caps.get('modalities', []):
        caps['modalities'] = [*caps.get('modalities', []), 'image']
    # La TEMPÉRATURE (2026-10-21) : un modèle de conversation distant la lit — `llm_chat` la
    # transmet au fournisseur. Pas l'abonnement Claude Code : le CLI ne la prend pas. Anthropic
    # la borne à 1 (son API refuse au-delà). La GRAINE et le TOP P (2026-10-22) : un fournisseur
    # compatible OpenAI les reçoit (Albert les propose) ; l'API Anthropic n'a pas de graine et
    # refuse un top_p à côté d'une température — `llm_chat` ne les lui envoie pas.
    from wama.common.utils.llm_utils import openai_compatible_source
    from wama.common.utils.model_capabilities import SEED, TEMPERATURE, TOP_P
    if abilities.get('completion'):
        # Écrit vide pour l'abonnement : « ne la lit pas » est un fait, qui grise le réglage.
        if src.protocol in UNLISTABLE_PROTOCOLS:
            caps['params'] = []
        elif openai_compatible_source(src.key):
            # La règle même de l'appel (`llm_chat` n'envoie graine et top_p qu'à elle).
            caps['params'] = [TEMPERATURE, SEED, TOP_P]
        else:
            caps['params'] = [TEMPERATURE]
            if src.protocol == 'anthropic':
                caps['max_temperature'] = 1.0
    return ModelInfo(
        id=item['id'], name=item.get('name') or item['id'],
        model_type=ModelType(model_type), source=ModelSource(source),
        description=(item.get('description')
                     or (f"{src.label} — le modèle est choisi par le fournisseur" if declared
                         else f"{src.label} — modèle distant ({remote_type})")),
        hf_id=hf_id or None, vram_gb=0, ram_gb=0, is_downloaded=False,
        backend_ref=source, execution=EXECUTION_CLOUD,
        cost_tier=item.get('cost_tier') or src.cost_tier,
        # Le MOTEUR est le fournisseur (inventaire `external_sources.llm_engine_inventory`).
        composition={'runtime': {'engine': source}},
        capabilities=caps,
        extra_info={'remote_type': remote_type, 'aliases': list(item.get('aliases') or []),
                    'hosting': src.hosting, **({'declared': True} if declared else {})},
    )


def _key_models() -> tuple:
    """Les deux domiciles d'une clé posée : celle d'un utilisateur (profil) et celle de l'instance
    (page Sources externes, 2026-10-07). Même forme (`accounts.ProviderKey`) : la découverte,
    l'union des modèles ouverts et la sonde nocturne les lisent sans les distinguer."""
    from wama.accounts.models import InstanceApiKey, UserApiKey
    return UserApiKey, InstanceApiKey


def cloud_model_infos() -> dict:
    """`{model_key: ModelInfo}` de TOUS les modèles distants qu'une clé posée ouvre — la
    découverte CLOUD du registre (`ModelRegistry._discover_cloud_models`).

    Lecture de la base seule (`remote_listing` des clés), jamais du réseau : la liste est relue
    chez le fournisseur par `refresh_key`, au geste d'enregistrement. L'union se fait sur toutes
    les clés d'une source — une clé qui n'ouvre pas un modèle ne prouve pas que le fournisseur
    l'a retiré.
    """
    rows = [row for model in _key_models()
            for row in (model.objects.exclude(api_key='').exclude(remote_listing=[])
                        .values_list('source', 'remote_listing'))]
    infos = {}
    for source, listing in rows:
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
    from wama.model_manager.models import AIModel, EXECUTION_CLOUD

    opened = set()
    for model in _key_models():
        for keys in model.objects.filter(source=source).values_list('open_models', flat=True):
            opened.update(keys or [])
    rows = AIModel.objects.filter(source=source, execution=EXECUTION_CLOUD, is_proposed=False)
    retired = rows.exclude(model_key__in=opened).filter(is_available=True).update(is_available=False)
    rows.filter(model_key__in=opened, is_available=False).update(is_available=True)
    drop_renamed(source)
    return retired


def drop_renamed(source: str) -> list:
    """SUPPRIME les lignes retirées de `source` qui ne sont qu'un ANCIEN NOM d'une ligne vivante —
    même identifiant à la casse près, ou identifiant que le fournisseur déclare parmi les ALIAS du
    vivant (`extra_info['aliases']`). Rend les clés supprimées.

    Un renommage ne fait pas un modèle de plus (2026-10-22, Fabien : « si le modèle n'existe pas on
    supprime la ligne fantôme par la route, mais on vérifie d'abord ») : vérifié en direct chez
    Albert, `qwen3-coder-30b-A3b-instruct` est servi `…-a3b-…`, et `openai/gpt-oss-120b` est un
    alias déclaré de `gpt-oss-120b`. Garder ces lignes MARQUÉES ne gardait aucun historique
    (aucune exécution, aucune carte) mais gardait un piège : sous un système de fichiers insensible
    à la casse, le manifeste de `…-A3b-…` EST celui de `…-a3b-…` — son export l'a écrasé deux fois
    (2026-09-18, 2026-10-22). Même geste que les alias internes d'Ollama (`model_sync`), qui ne
    sont pas des modèles non plus.

    ⚠ La doctrine de `retire_unlisted` tient pour tout le reste : un modèle que le fournisseur a
    RETIRÉ (aucun nom vivant ne le reprend) reste marqué, et une ligne qui porte un historique
    d'exécution (`ModelRuntimeStat`) n'est jamais supprimée. Le corpus n'est pas touché : la ligne
    retirée n'y entre pas (`manifest_export._model_keys`), et son nom de fichier peut être celui
    de la ligne vivante.
    """
    from wama.model_manager.models import AIModel, EXECUTION_CLOUD, ModelRuntimeStat

    rows = AIModel.objects.filter(source=source, execution=EXECUTION_CLOUD, is_proposed=False)
    live = list(rows.filter(is_available=True))
    names = {m.model_key.partition(':')[2].lower() for m in live}
    aliases = {str(a) for m in live for a in ((m.extra_info or {}).get('aliases') or [])}
    doomed = [g.model_key for g in rows.filter(is_available=False)
              if (g.model_key.partition(':')[2].lower() in names
                  or g.model_key.partition(':')[2] in aliases)
              and not ModelRuntimeStat.objects.filter(model_key=g.model_key).exists()]
    if doomed:
        logger.info("[cloud_models] %s : anciens noms d'un modèle renommé, supprimés : %s",
                    source, doomed)
        AIModel.objects.filter(model_key__in=doomed).delete()
    return doomed


def refresh_key(row, background: bool = False) -> tuple:
    """Relit chez le fournisseur les modèles ouverts à la clé `row` (`accounts.UserApiKey`), puis
    passe par la MÊME chaîne qu'une installation : synchronisation du catalogue (la découverte
    cloud lit la liste gardée sur la clé), provenance par le manifeste, corpus.

    Rend (nombre de modèles, message d'erreur ou ''). Une erreur est GARDÉE sur la ligne et la
    liste précédente conservée : un fournisseur injoignable ne ferme rien à l'utilisateur.

    `background` (2026-10-02) : la lecture chez le fournisseur reste immédiate — elle dit combien
    de modèles la clé ouvre —, la mise à jour du CATALOGUE (`register_open_models`, réduite aux
    modèles distants le même jour) part en tâche de fond. Faite dans la requête du profil, elle a pris plus de deux
    minutes : bouton « Enregistrer » sans effet visible, serveur web bloqué, double envoi.
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
            logger.warning("[cloud_models] découverte %s pour %s : %s", row.source,
                           getattr(row, 'user_id', 'instance'), exc)
            return 0, row.discovery_error
    row.remote_listing = listing
    row.open_models = keys_for(row.source, listing)
    row.discovered_at, row.discovery_error = timezone.now(), ''
    row.save(update_fields=['remote_listing', 'open_models', 'discovered_at', 'discovery_error'])
    if background:
        # Après la validation de la transaction : la tâche relit la ligne ENREGISTRÉE — et un
        # test (TestCase, jamais validé) n'envoie rien au broker.
        from django.db import transaction
        from wama.accounts.models import InstanceApiKey
        from wama.model_manager.tasks import register_cloud_key_task
        pk, instance = row.pk, isinstance(row, InstanceApiKey)
        transaction.on_commit(lambda: register_cloud_key_task.delay(pk, instance))
    else:
        register_open_models(row)
    return len(row.open_models), ''


def refresh_all_keys() -> dict:
    """Relit chez CHAQUE fournisseur les modèles ouverts à CHAQUE clé posée — la sonde nocturne.

    POURQUOI (constat de Fabien, 2026-10-04) : la liste d'un fournisseur n'était relue qu'au
    geste « Enregistrer » du profil. Mesuré ce jour : toutes les clés du parc dataient leur
    découverte du 18/09 — un modèle publié depuis (Claude Opus 5.5) n'existait pas pour WAMA, et
    un modèle retiré y restait proposé. L'intention « à l'enregistrement, puis PÉRIODIQUEMENT »
    était écrite (`ROADMAP §8d`) ; seule la première moitié était câblée.

    Chaque clé passe par `refresh_key` (même chaîne que le profil : liste, catalogue, retraits,
    provenance). Une erreur de fournisseur est gardée sur la ligne et la liste précédente
    conservée : une panne d'une nuit ne ferme rien. Un fournisseur sans liste (`claude_cli`) n'est
    PAS appelé : sa liste est DÉCLARÉE (`ExternalSource.declared_models`), et sa clé n'est
    rafraîchie que si cette déclaration a changé depuis — c'est ce qui fait entrer un modèle
    déclaré de plus chez les utilisateurs qui ont déjà posé leur jeton.

    Rend {'keys', 'added': {source: [...]}, 'removed': {source: [...]}, 'errors': {source: msg}}.
    """
    sources = {s.key: s for s in external_sources.SOURCES if s.kind == 'llm'}
    summary = {'keys': 0, 'added': {}, 'removed': {}, 'errors': {}}
    rows = [row for model in _key_models()
            for row in model.objects.filter(source__in=list(sources)).exclude(api_key='')
            .order_by('source', 'pk')]
    for row in rows:
        if (sources[row.source].protocol in UNLISTABLE_PROTOCOLS
                and (row.remote_listing or []) == declared_listing(row.source)):
            continue                      # déclaration inchangée : rien à relire, aucun appel
        before = set(row.open_models or [])
        _count, error = refresh_key(row)
        summary['keys'] += 1
        if error:
            summary['errors'][row.source] = error
            continue
        after = set(row.open_models or [])
        if after - before:
            summary['added'].setdefault(row.source, set()).update(after - before)
        if before - after:
            summary['removed'].setdefault(row.source, set()).update(before - after)
    for field in ('added', 'removed'):
        summary[field] = {source: sorted(keys) for source, keys in summary[field].items()}
    return summary


def register_open_models(row) -> None:
    """Le CATALOGUE suit la liste gardée sur la clé `row` : la partie LONGUE de `refresh_key`
    (synchronisation complète, retraits, provenance), lancée en tâche de fond depuis le profil."""
    listing = row.remote_listing or []
    # Synchronisation des seuls modèles DISTANTS (même écriture que la synchronisation commune,
    # sans les disques ni les apps : ~5 min de découverte complète pour une clé, 2026-10-02),
    # puis retrait de ce que plus aucune clé n'ouvre, puis provenance : l'identité d'éditeur
    # (dépôt HuggingFace servi) entre par le manifeste et le corpus reçoit la ligne.
    from .model_sync import ModelSyncService
    from .provenance import cloud_identity, set_identity
    try:
        ModelSyncService().sync_cloud_models()
    except Exception:
        logger.warning("synchronisation cloud échouée après la découverte %s (le sync "
                       "périodique rattrapera)", row.source, exc_info=True)
    retire_unlisted(row.source)
    for item in listing:
        identity = cloud_identity(item)
        key = f"{row.source}:{item['id']}"
        if identity and key in row.open_models:
            try:
                set_identity(key, identity)
            except Exception:
                logger.warning("provenance non enregistrée pour %s", key, exc_info=True)


def hosting_ceiling(user) -> str:
    """PLAFOND d'hébergement du profil (`UserProfile.cloud_hosting_max`), sur l'échelle
    `external_sources.HOSTING_SCALE` — le défaut de l'échelle si le profil ne dit rien."""
    value = getattr(getattr(user, 'profile', None), 'cloud_hosting_max', '')
    return value if value in external_sources.HOSTING_SCALE else external_sources.HOSTING_CEILING_DEFAULT


def data_reuse_accepted(user) -> bool:
    """`user` accepte-t-il qu'un hébergeur garde ou réutilise ses requêtes ? Le dernier cran de
    son plafond le dit (2026-10-12) ; sans utilisateur, non."""
    if user is None or not getattr(user, 'is_authenticated', False):
        return False
    return external_sources.data_reuse_accepted(hosting_ceiling(user))


def cloud_refusal(user, source: str = '') -> str:
    """Motif de refus d'un appel distant pour `user`, sinon ''. Sans utilisateur : ''.

    Deux refus, dans cet ordre : le profil « 100 % local », puis — quand la `source` est nommée —
    un fournisseur hébergé AU-DELÀ du plafond du profil (second axe, 2026-10-03).

    Domicile UNIQUE de la garde : l'appel LLM de l'assistant et `claude_code.demander` (outil
    `ask_claude_code`, fournisseur abonnement, geste `!code`) la lisent tous deux.
    """
    if user is None or not getattr(user, 'is_authenticated', False):
        return ''
    if getattr(getattr(user, 'profile', None), 'cloud_policy', 'local_only') == 'local_only':
        return ("Votre profil est en « 100 % local » : pour utiliser un fournisseur distant, "
                "choisissez un autre niveau dans la carte « Modèles cloud » de la page Profil.")
    if source:
        try:
            src = external_sources.get(source)
        except Exception:
            return ''                       # source inconnue : ce n'est pas à cette garde de le dire
        ceiling = hosting_ceiling(user)
        if not external_sources.hosting_within(src.hosting, ceiling):
            return (f"{src.label} est hébergé par un « {external_sources.HOSTING.get(src.hosting, src.hosting)} » "
                    f"et votre profil s'arrête à « {external_sources.HOSTING_CEILING_LABELS[ceiling]} » : "
                    "relevez ce plafond dans la carte « Modèles cloud » de la page Profil.")
    return ''


def allowed_cloud_keys(user, automatic: bool = True) -> set:
    """`model_key` des modèles distants que `user` autorise — à passer à `select_model(cloud_keys=…)`.

    Les 3 niveaux du profil (Fabien, 15/09) :
    - « 100 % local » → rien, ni en automatique ni au choix manuel ;
    - « cloud si WAMA est saturé » → le choix MANUEL s'ouvre ; le tirage AUTOMATIQUE n'ouvre le
      distant que sur saturation, signal que porte le chantier du curseur (⏳ — d'ici là, rien) ;
    - « cloud autorisé » → les deux.

    SECOND AXE (Fabien, 2026-10-03) — le niveau dit QUAND, ces deux réglages disent JUSQU'OÙ :
    - le PLAFOND d'hébergement (`cloud_hosting_max` : privé < souverain < commercial < commercial
      qui garde ou réutilise les données) borne les
      deux chemins — une source au-delà du plafond n'ouvre rien, ni au tirage ni au choix ;
    - un modèle FACTURÉ À L'USAGE (`cost_tier == 'metered'`) n'entre au tirage AUTOMATIQUE que
      si le profil le dit (`cloud_metered_auto`). Mesuré le 03/10 : avec « cloud autorisé » et
      une clé d'API Anthropic, le tirage rendait un modèle facturé au jeton aux curseurs 0, 50
      et 100 (un distant « coûte » 0 sur la carte, cf. `model_selector._best_by_vram`). Le
      choix MANUEL n'est pas concerné : nommer un modèle payant est un consentement.
      ⚠ Le coût se lit PAR MODÈLE (2026-10-12) : un fournisseur facturé à l'usage porte des
      modèles GRATUITS (`AIModel.cost_tier == 'free'`, 19 chez OpenRouter), qui entrent au tirage
      sans ce consentement. Le filtre lisait le tier de la SOURCE : aucun n'entrait jamais.
    - chez une source dont les gratuits exigent d'accepter l'entraînement
      (`free_models_need_data_reuse`), le tirage ne les retient qu'au DERNIER cran du plafond.
    C'est ici, à l'ADMISSION, que le coût s'arbitre — pas dans le score du sélecteur.

    SATURATION (2026-10-13, `ROADMAP §8d` étape 2) : au tirage automatique, une source qui vient
    de refuser (limite de débit de la clé, panne) est écartée le temps de sa note ; depuis le
    14/10 (étape 3), un modèle dont le quota est atteint l'est aussi, AVANT le refus — les deux
    vivent dans `common/services/source_quota.py`. Le choix MANUEL n'est pas concerné : il reste
    un consentement explicite, et c'est l'appelant qui propose alors un relais.
    """
    if user is None or not getattr(user, 'is_authenticated', False):
        return set()
    profile = getattr(user, 'profile', None)
    policy = getattr(profile, 'cloud_policy', 'local_only')
    if policy == 'local_only' or (automatic and policy != 'cloud_allowed'):
        return set()
    from wama.accounts.api_keys import llm_sources
    from wama.accounts.models import UserApiKey
    ceiling = hosting_ceiling(user)
    metered_auto = bool(getattr(profile, 'cloud_metered_auto', False))
    # ⚠ Les SOURCES que CET utilisateur a le droit d'utiliser, pas seulement celles dont une ligne
    # de clé existe : l'abonnement Claude Code est `developer_only`. Mesuré le 2026-09-16 — sans ce
    # filtre, un compte ordinaire portant une ligne `claude_code` voyait le modèle d'abonnement
    # dans le sélecteur commun, alors que la garde du moteur le lui refuse.
    within = [s for s in llm_sources(user) if external_sources.hosting_within(s.hosting, ceiling)]
    ouvertes = {s.key for s in within}
    # Au tirage automatique, ces sources n'ouvrent que leurs modèles GRATUITS (coût par modèle)…
    free_only = {s.key for s in within
                 if automatic and s.cost_tier == 'metered' and not metered_auto}
    # … et celles-ci n'ouvrent PAS leurs gratuits, servis à la seule condition d'entraîner dessus.
    no_free = {s.key for s in within
               if automatic and s.free_models_need_data_reuse
               and not external_sources.data_reuse_accepted(ceiling)}
    keys = set()
    # `values_list` : les modèles seuls, sans déchiffrer la clé.
    personal = dict(UserApiKey.objects.filter(user=user, source__in=ouvertes).exclude(api_key='')
                    .values_list('source', 'open_models'))
    for opened in personal.values():
        keys.update(opened or [])
    # La clé d'instance PARTAGÉE (2026-10-07) ouvre ses modèles à qui n'a pas posé la sienne —
    # même règle que `api_keys.key_for` : la clé personnelle, posée, prime.
    from wama.accounts.api_keys import shared_sources
    from wama.accounts.models import InstanceApiKey
    borrowed = (shared_sources() & ouvertes) - set(personal)
    for opened in (InstanceApiKey.objects.filter(source__in=borrowed)
                   .values_list('open_models', flat=True)):
        keys.update(opened or [])
    filtered = free_only | no_free
    if filtered:
        from wama.model_manager.models import AIModel
        held = {k for k in keys if k.split(':', 1)[0] in filtered}
        free = set(AIModel.objects.filter(model_key__in=held, cost_tier='free')
                   .values_list('model_key', flat=True))
        for key in held:
            source = key.split(':', 1)[0]
            if (source in free_only and key not in free) or (source in no_free and key in free):
                keys.discard(key)
    if automatic and keys:
        keys = drop_unavailable(user, keys, personal_sources=set(personal))
    return keys


def drop_unavailable(user, keys, personal_sources=None) -> set:
    """`keys` moins les modèles qu'un TIRAGE ne peut pas retenir maintenant : une source notée
    saturée (refus récent, panne) ou un modèle dont le quota est atteint — comptés par la brique
    commune des services externes (`source_quota`, `ROADMAP §8d` étapes 2-3). La portée d'une limite
    de débit est la CLÉ : celle de `user` s'il l'a posée, sinon l'instance. `personal_sources` :
    les sources où il a posé sa clé (relues en base si l'appelant ne les a pas).

    La règle du tirage automatique (`allowed_cloud_keys`) ; le tirage de DÉVELOPPEMENT l'applique
    aussi aux souverains qu'il ouvre à part (`development_models.dev_cloud_keys`, 2026-10-20 — il
    les reprenait du choix manuel, qui ne l'applique pas : un ILaaS ou un Albert saturé restait
    tirable par un rôle)."""
    keys = set(keys)
    if not keys or user is None:
        return keys
    if personal_sources is None:
        from wama.accounts.models import UserApiKey
        personal_sources = set(UserApiKey.objects.filter(user=user).exclude(api_key='')
                               .values_list('source', flat=True))
    from wama.common.services.source_quota import unavailable_keys
    busy = unavailable_keys(keys, lambda s: f'user:{user.pk}' if s in personal_sources else 'instance')
    if busy:
        keys = {k for k in keys if k not in busy}
        # Dit dans les journaux : « pourquoi le tirage n'a-t-il pas pris ce modèle ? »
        logger.info('[cloud] écartées du tirage de %s : %s', getattr(user, 'pk', None),
                    ', '.join(f'{k} ({r})' for k, r in sorted(busy.items())))
    return keys


def is_cloud_key(model_key) -> bool:
    """La clé de catalogue `model_key` désigne-t-elle un modèle servi par un FOURNISSEUR
    (`AIModel.execution`) ? Faux pour une clé inconnue ou « auto » non résolu : dans le doute,
    l'appelant traite le modèle comme local (le squelette lui garde la carte). La forme par
    instance est `model_selector.is_cloud`."""
    if not model_key:
        return False
    try:
        from wama.model_manager.models import AIModel, EXECUTION_CLOUD
        return AIModel.objects.filter(model_key=model_key, execution=EXECUTION_CLOUD).exists()
    except Exception:
        return False


# La NOTE de saturation d'un fournisseur (étape 2, 13/10) a déménagé le 14/10 dans la brique
# commune des services externes, `common/services/source_quota.py` (étape 3) : la même note sert
# désormais à TOUT service qui refuse, LLM ou non, et le compte des quotas vit à côté d'elle.


class CloudAccessRefused(RuntimeError):
    """Appel distant refusé — message lisible par l'utilisateur ; `status` = code HTTP à rendre."""

    def __init__(self, message: str, status: int = 403):
        super().__init__(message)
        self.status = status


def cloud_access(user, source: str, model_id: str = '') -> str:
    """La CLÉ avec laquelle `user` appelle `source` (et le modèle `model_id` s'il est nommé), ou
    `CloudAccessRefused` avec le motif. Sans utilisateur : la clé d'instance (`key_for`).

    Domicile UNIQUE de la garde d'un APPEL distant (2026-09-30) : elle vivait en ligne dans
    l'assistant (`assistant_engine._llm_call`), et le transcriber — premier moteur d'app à
    appeler un fournisseur — l'aurait recopiée. Trois refus, dans cet ordre : profil « 100 %
    local », modèle nommé qu'AUCUNE clé de cet utilisateur n'ouvre, pas de clé posée.
    """
    from wama.accounts.api_keys import key_for
    if user is not None and getattr(user, 'is_authenticated', False):
        refusal = cloud_refusal(user, source)
        if refusal:
            raise CloudAccessRefused(refusal, 403)
        if model_id and f"{source}:{model_id}" not in allowed_cloud_keys(user, automatic=False):
            raise CloudAccessRefused(f"Le modèle « {model_id} » n'est pas ouvert par votre clé "
                                     f"{external_sources.get(source).label}.", 403)
    api_key = key_for(user, source)
    if not api_key:
        raise CloudAccessRefused(f"Aucune clé d'API {external_sources.get(source).label} dans "
                                 "votre profil : ajoutez-la dans le volet « Clés d'API » de la "
                                 "page Profil.", 400)
    return api_key
