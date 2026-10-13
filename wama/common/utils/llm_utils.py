"""
WAMA Common — LLM utilities
Shared Ollama client for use in Celery workers (transcriber, describer, ...).
"""

import json
import logging
import re
from typing import Optional

logger = logging.getLogger(__name__)

#: Le fournisseur a répondu, mais sans texte. Un motif NOMMÉ, parce qu'un appelant le distingue
#: d'une panne : l'assistant le traite comme une réponse vide (un nouvel essai), pas comme une
#: erreur — gpt-oss sur Albert range parfois son appel d'outil NATIF dans le raisonnement et
#: rend un `content` vide (mesuré le 2026-10-10).
EMPTY_RESPONSE_ERROR = "LLM returned empty response"


def get_describer_model(content_type: str, output_style: str) -> str:
    """
    Return the Ollama model name to use for a given (content_type, output_style) pair.

    Le TIER exprime une INTENTION ; le modèle est résolu par le catalogue, jamais nommé ici :
      image   → exige `completion` + `vision`      (aucun plafond VRAM)
      heavy   → meeting, scientific, coherence     (aucun plafond)
      default → detailed, audio, video             (≤ 16 Go)
      fast    → summary, bullet_points             (≤ 8 Go)

    Ordre de résolution : réglage explicite (`settings.DESCRIBER_LLM_MODELS`, qui ÉPINGLE et
    court-circuite) → `select_model()` sur le catalogue (VRAM libre, préférence aux modèles
    déjà chargés) → repli Ollama direct. Aucun nom de modèle n'est codé en dur : les tables
    figées d'avant le 2026-08-04 auraient toutes désigné un modèle absent après le passage de
    qwen3.5 à qwen3.6.
    """
    from django.conf import settings
    models: dict = getattr(settings, 'DESCRIBER_LLM_MODELS', {})
    # `or`, PAS le défaut de `.get()` : depuis que les clés existent avec une valeur VIDE,
    # `models.get('default', '<nom>')` renvoie '' et le repli ne s'applique jamais — un nom de
    # modèle vide partirait jusqu'à l'appel Ollama.
    default = models.get('default') or ''

    # Le TIER reste déclaratif — classer la tâche est une décision métier légitime.
    # Ce qui change : le tier ne désigne plus un NOM figé, il exprime une INTENTION que le
    # catalogue résout selon les ressources réellement disponibles.
    # `completion` est exigé PARTOUT : sans lui, la sélection retenait bge-m3 — un modèle
    # d'EMBEDDING, incapable de générer du texte — parce que la découverte Ollama étiquette
    # embeddings et modèles de chat sous le même `ModelType.LLM`. Le drapeau vient désormais
    # des capacités déclarées par Ollama.
    if content_type == 'image':
        tier, exige = 'image', ['completion', 'vision']
    elif output_style in ('meeting', 'scientific'):
        tier, exige = 'heavy', ['completion']
    elif output_style in ('summary', 'bullet_points'):
        tier, exige = 'fast', ['completion']
    else:
        tier, exige = 'default', ['completion']

    # Un réglage explicite (env/settings) reste PRIORITAIRE : une spécificité se déclare,
    # elle ne se devine pas. On ne consulte le catalogue que si l'exploitant n'a rien imposé.
    impose = models.get(tier)
    if impose:
        return str(impose)

    choisi = _llm_par_catalogue(tier, exige)
    if choisi is None and exige:
        # Dégradation HONNÊTE : aucun modèle du catalogue ne déclare la capacité demandée.
        # C'est le cas de `vision` — la découverte Ollama refuse volontairement de l'affirmer
        # (`/api/tags` ne dit pas si un modèle est multimodal). Plutôt que de rendre une chaîne
        # vide, on retombe sur une sélection sans exigence, en le TRAÇANT.
        # Correctif de fond : peupler la capacité `vision` via `model_manager/services/
        # vision_probe.py`, qui sait tester un modèle — non fait ici, hors périmètre.
        logger.info("[llm_utils] aucun modèle ne déclare %s ; repli sans exigence (tier %s)",
                    exige, tier)
        choisi = _llm_par_catalogue(tier, None)
    return str(choisi or default or _dernier_recours())


# ── Le modèle de langage qu'un select de CARD désigne (2026-10-13) ─────────────────────────────
# Le select `llm_model` d'une app (describer, reader) porte une clé de catalogue ou « auto ». Une
# clé désigne un modèle LOCAL (Ollama) : ces aides ne portent pas la clé d'un utilisateur, un
# distant posé par un autre chemin est donc REFUSÉ en le disant plutôt que parti avec la clé de
# l'instance ; et un modèle désigné qui ne répond pas est une erreur dite, jamais un repli muet
# (règle du transcriber). Sortie du describer (`backends/model_choice.py`) quand le reader en a eu
# besoin : une seule lecture pour toutes les apps.

def designated_local_model(key: str, role: str = 'langage', owner: str = 'Cette application') -> str:
    """Le nom Ollama d'une clé `ollama:<nom>` ; `ValueError` pour toute autre source."""
    from wama.common.utils.model_keys import split_key
    source, model_id = split_key(key)
    if source != 'ollama' or not model_id:
        raise ValueError(f"Modèle de {role} « {key} » : {owner} n'appelle que des modèles "
                         "locaux (Ollama) pour ce rôle.")
    return model_id


def card_llm(key: str, auto=None, owner: str = 'Cette application'):
    """`(nom, fournisseur)` du modèle de langage qu'une card demande : sous « auto », `auto()`
    (le comportement propre à l'app — un tier, le défaut du funnel…) et le fournisseur du réglage
    global ; sinon le modèle désigné, chez Ollama."""
    from wama.common.utils.auto_model import is_auto
    if is_auto(key):
        return (auto() if auto else ''), None
    return designated_local_model(key, 'langage', owner), 'ollama'


def ollama_catalog_key(name: str) -> str:
    """La clé de catalogue d'un modèle Ollama nommé — ce qu'une ligne d'exécution retient."""
    return f'ollama:{name}' if name else ''


def modele_par_defaut() -> str:
    """
    Modèle LLM à utiliser quand l'appelant n'en impose aucun — résolu, jamais figé.

    C'est LE point unique de résolution : les fonctions de ce module prennent `model=''` par
    défaut et passent ici. Avant, chacune portait `model: str = 'qwen3.5:9b'` — six noms en dur
    qui auraient tous désigné un modèle absent dès l'installation de qwen3.6.
    """
    return _llm_par_catalogue('default', ['completion']) or _dernier_recours()


def _dernier_recours() -> str:
    """
    Repli quand le catalogue ne rend rien — **sans nom de modèle en dur**.

    Un nom figé ici pourrit : il désigne un modèle que la prospection remplacera (qwen3.5 →
    qwen3.6) et l'appel partira vers un modèle absent. On interroge donc Ollama directement,
    qui sait ce qui est réellement installé, et on prend le premier modèle capable de
    complétion.

    Si Ollama ne répond pas non plus, on retourne '' : l'appel échouera avec un message clair
    (« modèle vide ») au lieu de réclamer un modèle fantôme et de faire croire à une panne
    Ollama. Échouer lisiblement vaut mieux qu'échouer ailleurs.
    """
    try:
        import requests
        from .ollama_host import ollama_base, ollama_kwargs
        r = requests.get(f"{ollama_base()}/api/tags", **ollama_kwargs(timeout=5))
        r.raise_for_status()
        modeles = r.json().get('models', [])
        for m in modeles:
            if 'embedding' not in (m.get('capabilities') or []):
                return m.get('name', '')
        return modeles[0].get('name', '') if modeles else ''
    except Exception:
        logger.warning("[llm_utils] ni catalogue ni Ollama : aucun modèle résoluble")
        return ''


#: Plafond VRAM indicatif par tier, en Go. `fast` doit rester petit pour la latence ;
#: `heavy` a droit à tout ce qui tient. Ce sont des bornes, pas des noms de modèles —
#: elles survivent au remplacement de qwen3.5 par qwen3.6 sans être modifiées.
_PLAFOND_TIER = {'fast': 8.0, 'default': 16.0, 'heavy': None, 'image': None}


def modele_par_tier(tier: str = 'default', exige=None, priority=None,
                    prefer_loaded: bool = True) -> str:
    """
    Résolution PUBLIQUE d'un tier (`heavy`/`default`/`fast`) — même mécanique que
    `modele_par_defaut`, avec exigences et préférences en plus. Adoptée par la surface
    CHAT de l'assistant (2026-08-12, rôles → tiers) en remplacement de sa table de tags
    `_OLLAMA_MODEL_MAP`, morte au remplacement qwen3.5→qwen3.6 :
      - `priority=['coder']` exprime « un modèle code de préférence » (rôle debug) sans
        épingler un tag ;
      - `prefer_loaded=False` exprime une intention de GABARIT explicite (le rôle 'dev'
        du chat veut le tier heavy, pas le petit modèle déjà chargé).
    """
    return (_llm_par_catalogue(tier, list(exige or ['completion']), priority=priority,
                               prefer_loaded=prefer_loaded)
            or _dernier_recours())


def _llm_par_catalogue(tier: str, exige, priority=None, prefer_loaded: bool = True):
    """
    Résout un tier via `select_model()` — brique VRAM-aware du model_manager.

    `prefer_loaded=True` porte la demande centrale : à qualité comparable, privilégier un
    modèle DÉJÀ en mémoire plutôt que d'imposer un déchargement/rechargement. Le signal vient
    de `/api/ps`, remonté dans le catalogue par `model_registry._ollama_charges()`.
    `priority`/`prefer_loaded` : passe-plats déclaratifs de `modele_par_tier` (chat).

    Best-effort : toute panne (catalogue vide, model_manager indisponible) retourne None et
    l'appelant retombe sur le réglage déclaré. Un describer ne doit jamais échouer parce que
    la sélection intelligente est indisponible.
    """
    try:
        from wama.model_manager.services.model_selector import select_model
        m = select_model(
            'ollama',
            model_type='llm',
            requires=exige,
            prefer_loaded=prefer_loaded,
            vram_budget_gb=_PLAFOND_TIER.get(tier),
            priority=priority,
        )
        if m is None:
            return None
        # `model_key` = 'ollama:<nom:tag>' ; les appelants attendent le nom nu.
        return m.model_key.split(':', 1)[1] if ':' in m.model_key else m.name
    except Exception:
        logger.debug("[llm_utils] sélection catalogue indisponible pour le tier %s",
                     tier, exc_info=True)
        return None


def ollama_chat(
    messages: list,
    model: str = '',
    num_predict: int = 2048,
    num_ctx: Optional[int] = None,
    think: bool = True,
    timeout: float = 180.0,
    keep_alive: Optional[str] = None,
    temperature: Optional[float] = None,
) -> tuple[Optional[str], Optional[str]]:
    """
    Send a chat request to the local Ollama server.

    Args:
        messages:    List of {"role": ..., "content": ...} dicts.
        model:       Ollama model name.
        num_predict: Max tokens to generate (default 2048).
        num_ctx:     KV cache context window (tokens). If None, Ollama uses the
                     model's default (often 32K–128K), which can require 10–15 GB
                     of VRAM even for small models. Pass an explicit value (e.g.
                     8192) for formatting/short tasks to cap memory usage.
        think:       Enable Qwen3 thinking mode (default True). Set False for
                     deterministic formatting tasks to avoid consuming the
                     token budget on reasoning before the actual answer.
        timeout:     HTTP timeout in seconds (default 180). Use a shorter value
                     (e.g. 30) for non-critical tasks where fast-fail is preferred.
        keep_alive:  Résidence VRAM du modèle APRÈS la réponse (défaut Ollama : 5m).
                     Passer '0' pour décharger immédiatement — impératif pour les
                     passes courtes qui PRÉCÈDENT un gros chargement GPU (ex.
                     enrichissement de prompt avant une diffusion), sinon les
                     poids du LLM squattent la VRAM pendant toute la génération.

    Returns:
        (text, None)  on success
        (None, error) on failure
    """
    import httpx

    from .ollama_host import ollama_base

    # Résolution via la brique : sous WSL2, `127.0.0.1` désigne la VM et non l'hôte Windows où
    # tourne Ollama. Le contournement du proxy, lui, est déjà assuré plus bas par le
    # `trust_env=False` du client httpx (équivalent httpx de `ollama_proxies()`).
    url = f"{ollama_base()}/api/chat"

    # Funnel de résolution — `ollama_chat` est le point de passage de toutes les fonctions de ce
    # module (résumé, cohérence, noms de locuteurs…). Depuis que leurs défauts sont vides plutôt
    # que figés sur un nom, c'est ICI que le catalogue tranche ; sans cette ligne, un appelant
    # qui n'impose rien enverrait `"model": ""` à Ollama.
    model = model or modele_par_defaut()

    # `temperature` : 0.3 par défaut, comme avant pour tous les appelants ; un appel qui veut une
    # sortie DÉTERMINISTE la pose (l'OCR à 0.0 — `glm_ocr_backend`, qui gardait son propre client
    # Ollama pour cette seule raison jusqu'au 2026-10-07).
    options: dict = {"temperature": 0.3 if temperature is None else temperature}
    # `None` = pas de plafond (défaut d'Ollama) — même contrat que la branche cloud de
    # `llm_chat`, où `None` n'envoie pas `max_tokens`.
    if num_predict is not None:
        options["num_predict"] = num_predict
    if num_ctx is not None:
        options["num_ctx"] = num_ctx

    payload = {
        "model": model,
        "messages": messages,
        "options": options,
        "stream": False,
    }
    if not think:
        payload["think"] = False
    if keep_alive is not None:
        payload["keep_alive"] = keep_alive

    try:
        with httpx.Client(timeout=timeout, trust_env=False) as client:
            resp = client.post(url, json=payload)
        if resp.status_code != 200:
            return None, f"Ollama HTTP {resp.status_code}: {resp.text[:200]}"
        text = resp.json().get("message", {}).get("content", "") or ""
        if not text.strip():
            logger.warning(f"[llm_utils] Ollama returned empty content for model={model}")
            return None, "Ollama returned empty response"
        return text.strip(), None
    except Exception as e:
        logger.error(f"[llm_utils] Ollama error: {e}")
        return None, str(e)


def declared_llm_source(provider: str):
    """La source `external_sources` d'un fournisseur DISTANT que `llm_chat` sait appeler, ou None.

    UN FOURNISSEUR EXISTE S'IL EST AU REGISTRE, POINT (chantier 5 de `WAMA_HARNESS.md`, soldé le
    2026-10-11). Jusque-là, `llm_chat` acceptait n'importe quel nom que LiteLLM connaît, avec sa
    table de modèles par défaut (`openai`, `mistral`, `groq`, `gemini`, `grok`, `deepseek`) :
    aucune n'avait de source, donc ni garde « 100 % local », ni clé personnelle, ni clé posée
    sur la page « Sources externes » — et aucune clé n'était configurée nulle part. Un fournisseur
    de plus se DÉCLARE (`ExternalSource`, famille `llm`) : il gagne tout cela d'un coup.
    L'abonnement Claude Code (`claude_cli`) est déclaré mais ne passe pas par LiteLLM."""
    from wama.common import external_sources
    source = external_sources.by_key().get(provider)
    if source is None or source.kind != 'llm' or source.protocol == 'claude_cli':
        return None
    return source


def openai_compatible_source(provider: str) -> str:
    """La source `external_sources` d'un fournisseur qui parle le protocole OpenAI depuis une
    AUTRE adresse que celle d'OpenAI (Albert, ILaaS), ou ''. Le nom du fournisseur EST celui
    de la source.

    DÉRIVÉ du registre (2026-10-07) : c'était une table à la main (`{'albert': 'albert'}`), qu'il
    aurait fallu compléter à chaque fournisseur — un fournisseur déclaré `llm` + `openai` mais
    oublié ici partait chez OpenAI avec sa clé."""
    from wama.common import external_sources
    source = external_sources.by_key().get(provider)
    if source is not None and source.kind == 'llm' and source.protocol == 'openai':
        return source.key
    return ''


#: Réglage Django qui surcharge le modèle par défaut d'un fournisseur.
_DEFAULT_MODEL_SETTINGS = {'albert': 'ALBERT_MODEL'}


def default_cloud_model(provider: str) -> str:
    """Modèle par défaut d'un fournisseur cloud : réglage déclaré, sinon celui de sa source
    (`ExternalSource.default_model`) ; '' pour un fournisseur non déclaré."""
    from django.conf import settings
    from wama.common import external_sources
    setting_name = _DEFAULT_MODEL_SETTINGS.get(provider)
    configured = getattr(settings, setting_name, '') if setting_name else ''
    source = external_sources.by_key().get(provider)
    return configured or (source.default_model if source is not None else '')


#: Limite de débit (HTTP 429) d'un fournisseur LLM : attendre et recommencer, plafonné. Albert
#: accorde 10 requêtes par minute et par clé ; un tour d'assistant à huit outils en fait neuf, et
#: le 429 finissait le tour par son message brut (mesuré le 2026-10-10, rejeu du fil web n° 37).
#: L'attente sans `Retry-After` est DÉCLARÉE par la source quand elle est mesurée
#: (`ExternalSource.rate_limit_wait_s`, Albert : une fenêtre entière) ; `RATE_LIMIT_WAIT_S` est
#: celle des autres — une minute, la fenêtre la plus courante d'une limite de débit.
RATE_LIMIT_RETRIES = 1
RATE_LIMIT_WAIT_S = 60.0
RATE_LIMIT_MAX_WAIT_S = 60.0

#: Motifs d'une note de saturation (`cloud_models.note_saturation`) — affichés à l'utilisateur.
RATE_LIMITED = 'limite de débit'
UNAVAILABLE = 'indisponible'
#: Une PANNE du fournisseur, pas une faute de la requête : statut HTTP, ou type d'erreur LiteLLM.
_OUTAGE_STATUSES = (408, 500, 502, 503, 504)
_OUTAGE_TYPES = ('APIConnectionError', 'Timeout', 'ServiceUnavailableError',
                 'InternalServerError', 'BadGatewayError')


def _rate_limited(exc) -> bool:
    return getattr(exc, 'status_code', None) == 429 or type(exc).__name__ == 'RateLimitError'


def _retry_after(exc, wait_s: float) -> float:
    """L'attente que le fournisseur DEMANDE (`Retry-After`), sinon `wait_s`, plafonnée."""
    headers = getattr(getattr(exc, 'response', None), 'headers', None) or {}
    try:
        wait = float(headers.get('retry-after'))
    except (TypeError, ValueError):
        wait = wait_s
    return min(max(wait, 1.0), RATE_LIMIT_MAX_WAIT_S)


def provider_saturation(exc, wait_s: float = RATE_LIMIT_WAIT_S):
    """(portée, durée, motif) quand l'échec dit que le FOURNISSEUR est saturé ou en panne — None
    pour une faute de la requête (clé refusée, modèle inconnu), qu'un autre fournisseur ne règle
    pas. Portée `key` : la limite tient à la clé ; `all` : la panne vaut pour tous.
    Reconnu par le statut ou le type LiteLLM, jamais par le texte du message."""
    if _rate_limited(exc):
        return 'key', _retry_after(exc, wait_s), RATE_LIMITED
    if (getattr(exc, 'status_code', None) in _OUTAGE_STATUSES
            or type(exc).__name__ in _OUTAGE_TYPES):
        from wama.model_manager.services.cloud_models import OUTAGE_NOTE_S
        return 'all', OUTAGE_NOTE_S, UNAVAILABLE
    return None


def _note_provider_failure(provider: str, exc, wait_s: float, scope) -> None:
    """Note le fournisseur saturé quand l'échec le dit (`provider_saturation`) — le tirage
    automatique l'écarte alors le temps de la note (bascule, `ROADMAP §8d` étape 2). `scope` :
    la portée de la clé, ou la fonction qui la calcule (lue seulement ici, en cas d'échec)."""
    found = provider_saturation(exc, wait_s)
    if found is None:
        return
    reach, seconds, reason = found
    try:
        from wama.model_manager.services.cloud_models import ALL_KEYS, note_saturation
        if reach != 'key':
            scope = ALL_KEYS
        elif callable(scope):
            scope = scope()
        note_saturation(provider, scope=scope, seconds=seconds, reason=reason)
    except Exception:
        logger.debug('[llm_utils] note de saturation impossible (%s)', provider, exc_info=True)


def _completion(litellm, wait_s: float = RATE_LIMIT_WAIT_S, retries: Optional[int] = None,
                **kwargs):
    """`litellm.completion`, avec l'attente sur 429 (`Retry-After` s'il est donné, sinon `wait_s`,
    plafonné). Reconnu par le statut ou le type LiteLLM, jamais par le texte du message.
    `retries=0` : aucune attente — l'appelant a un autre fournisseur sous la main."""
    import time
    retries = RATE_LIMIT_RETRIES if retries is None else retries
    for attempt in range(retries + 1):
        try:
            return litellm.completion(**kwargs)
        except Exception as e:
            if not _rate_limited(e) or attempt >= retries:
                raise
            wait = _retry_after(e, wait_s)
            logger.warning(f"[llm_utils] limite de débit ({kwargs.get('model')}) — "
                           f"nouvel essai dans {wait:.0f} s")
            time.sleep(wait)


def llm_chat(
    messages: list,
    model: str = None,
    provider: str = None,
    num_predict: int = 2048,
    num_ctx: Optional[int] = None,
    think: bool = True,
    timeout: float = 180.0,
    api_key: Optional[str] = None,
    api_base: Optional[str] = None,
    keep_alive: Optional[str] = None,
    temperature: Optional[float] = None,
    on_delta=None,
    tools: Optional[list] = None,
    data_reuse_ok: bool = False,
    rate_limit_wait: bool = True,
    saturation_scope='instance',
) -> tuple[Optional[str], Optional[str]]:
    """
    Unified LLM chat function — provider-agnostic entry point.

    Phase 1 (local only): provider defaults to 'ollama' → delegates to ollama_chat().
    Phase 2 (hybrid): provider is a source DECLARED in `external_sources` (kind `llm`: albert,
      ilaas, openrouter, anthropic) — any other name is refused (`declared_llm_source`).
      Routes via LiteLLM; the caller passes the key (per-user keys: `accounts.api_keys.key_for`),
      otherwise the instance key of the source is used.

    Args:
        messages:   List of {"role": ..., "content": ...} dicts.
        model:      Model name without provider prefix (e.g. 'qwen3.5:9b', 'gpt-oss-120b').
                    If None, falls back to the default declared by the source.
        provider:   'ollama' (default) | a declared `llm` source.
                    If None, reads settings.LITELLM_PROVIDER (default: 'ollama').
                    A source of protocol `openai` is routed as `openai/<model>` with the address
                    and key of `external_sources`.
        num_predict: Max tokens to generate (Ollama) / max_tokens (cloud). None = no cap.
        temperature: Sampling temperature (None = provider default; Ollama: 0.3).
        num_ctx:    KV cache size in tokens (Ollama only, ignored for cloud).
        think:      Qwen3 thinking mode (Ollama only, ignored for cloud).
        keep_alive: Résidence VRAM après réponse (Ollama only, ignoré pour le cloud).
                    '0' = décharger tout de suite (cf. ollama_chat).
        timeout:    HTTP timeout in seconds.
        api_key:    Cloud API key (required for non-Ollama providers).
        api_base:   Override API base URL (e.g. custom Ollama host).
        on_delta:   Cloud only. Si fourni, la réponse est demandée EN FLUX et chaque fragment
                    de TEXTE part à `on_delta(fragment)` au fil de l'eau ; le retour reste le
                    texte entier. La réflexion d'un modèle de raisonnement arrive par un
                    autre champ et n'est jamais transmise. Ignoré sur le chemin Ollama, qui
                    a son propre flux côté assistant (`assistant_engine._ollama_stream`).
        tools:      Cloud only. Outils DÉCLARÉS au format standard OpenAI (`[{type: function,
                    function: {name, description, parameters}}]`). Un appel rendu par le
                    fournisseur revient comme TEXTE `{"tool": nom, "args": {…}}` — la forme que la
                    boucle de l'assistant lit déjà (`_parse_tool_call`) ; le premier seul s'il y en
                    a plusieurs, la boucle en exécute un par tour (2026-10-11, gpt-oss d'Albert).
        data_reuse_ok: Cloud only. L'utilisateur accepte qu'un hébergeur garde ou réutilise ses
                    requêtes (dernier cran de son plafond, `chat_with_source`) : la règle
                    `no_reuse_request_body` de la source n'est alors PAS envoyée. Faux par
                    défaut — un appel sans utilisateur reste strict (2026-10-12).
        rate_limit_wait: Cloud only. Faux : un 429 échoue TOUT DE SUITE, sans l'attente ni le
                    nouvel essai — l'appelant a un autre fournisseur (tirage rejoué, 2026-10-13).
        saturation_scope: Cloud only. Portée de la CLÉ employée (`cloud_models.saturation_scope`),
                    ou la fonction sans argument qui la calcule — lue seulement en cas d'échec.
                    Un échec qui dit le fournisseur saturé le NOTE pour elle, et le tirage
                    automatique l'écarte le temps de la note (`ROADMAP §8d` étape 2).

    Returns:
        (text, None) on success · (None, error_string) on failure
    """
    from django.conf import settings

    if provider is None:
        provider = getattr(settings, 'LITELLM_PROVIDER', 'ollama')

    # ── Phase 1: local Ollama (transparent, no change in behavior) ────────────
    if provider == 'ollama':
        return ollama_chat(
            messages=messages,
            # Funnel de résolution : un appelant qui n'impose rien obtient le modèle choisi par
            # le catalogue (VRAM libre + préférence aux modèles déjà chargés), jamais un nom figé.
            model=model or modele_par_defaut(),
            num_predict=num_predict,
            num_ctx=num_ctx,
            think=think,
            timeout=timeout,
            keep_alive=keep_alive,
            temperature=temperature,
        )

    # ── Phase 2: cloud provider via LiteLLM ───────────────────────────────────
    try:
        import litellm
    except ImportError:
        logger.error("[llm_utils] litellm not installed — pip install litellm")
        return None, "litellm not installed (pip install litellm)"

    from wama.common import external_sources
    declared = declared_llm_source(provider)
    if declared is None:
        return None, (f"fournisseur « {provider} » non déclaré dans WAMA : un fournisseur distant "
                      "se déclare au registre des sources externes (famille llm)")
    model = model or default_cloud_model(provider)
    if not model:
        # Sans ce refus, LiteLLM recevrait `openai/` seul : une erreur DISTANTE qui accuse le
        # fournisseur au lieu du code.
        return None, f"aucun modèle demandé, et « {provider} » n'en déclare pas par défaut"
    # Sans clé de l'appelant (usage SANS utilisateur), celle de l'INSTANCE — posée sur la page
    # « Sources externes », sinon le `.env`. Pour TOUTE source déclarée : jusqu'au 2026-10-11 la
    # seule branche OpenAI-compatible la lisait, et l'API Anthropic ignorait la clé de la page.
    api_key = api_key or external_sources.api_key(provider)

    if openai_compatible_source(provider):
        # Fournisseur compatible OpenAI hébergé AILLEURS qu'OpenAI (Albert) : préfixe `openai/`
        # TOUJOURS posé — ses identifiants portent eux-mêmes un « / » (`mistralai/Mistral-…`),
        # que la règle `'/' in model` ci-dessous prendrait pour un préfixe de fournisseur.
        # Adresse et clé viennent du registre, jamais de `OPENAI_API_BASE` : global au
        # processus, il détournerait aussi les appels destinés à OpenAI.
        litellm_model = f"openai/{model}"
        api_base = api_base or external_sources.base_url(provider)
        if not api_key:
            return None, (f"clé absente pour « {provider} » : la poser sur la page « Sources "
                          f"externes » ou définir {declared.api_key_env} dans .env")
        # Règle DÉCLARÉE par la source (2026-10-10 — OpenRouter : aucun hébergeur qui garde ou
        # entraîne sur les données), sauf si l'utilisateur a accepté cette réutilisation au
        # plafond de son profil (2026-10-12).
        extra_body = (json.loads(declared.no_reuse_request_body)
                      if declared.no_reuse_request_body and not data_reuse_ok else None)
    else:
        # Source au protocole natif de LiteLLM (API Anthropic) : son nom EST le préfixe.
        extra_body = None
        litellm_model = model if '/' in model else f"{provider}/{model}"

    kwargs: dict = {
        'model':      litellm_model,
        'messages':   messages,
        'timeout':    timeout,
    }
    # `None` = pas de plafond : un manifeste ou une glu de code dépassent vite 2 048 jetons, et
    # un modèle de raisonnement (gpt-oss) prend sa réflexion sur le même budget.
    if num_predict is not None:
        kwargs['max_tokens'] = num_predict
    if temperature is not None:
        kwargs['temperature'] = temperature
    if api_key:
        kwargs['api_key'] = api_key
    if api_base:
        kwargs['api_base'] = api_base
    if extra_body:
        kwargs['extra_body'] = extra_body
    if tools:
        kwargs['tools'] = tools
    # Attente sur 429 sans `Retry-After` : celle que la source a MESURÉE, sinon la commune.
    wait_s = declared.rate_limit_wait_s or RATE_LIMIT_WAIT_S
    retries = None if rate_limit_wait else 0

    try:
        if on_delta is not None:
            # FLUX (2026-10-04) : le fournisseur rend son premier texte en ~0,5 s et sa fin en
            # 1 à 2 s (mesuré sur Albert) — sans flux, l'écran et la voix attendaient la fin.
            pieces = []
            calls: dict = {}                 # appel d'outil reçu par morceaux, par `index`
            for chunk in _completion(litellm, wait_s, retries, stream=True, **kwargs):
                choices = getattr(chunk, 'choices', None) or []
                delta = getattr(choices[0], 'delta', None) if choices else None
                fragment = getattr(delta, 'content', None)
                if fragment:
                    pieces.append(fragment)
                    on_delta(fragment)
                for part in _listed(getattr(delta, 'tool_calls', None)):
                    slot = calls.setdefault(getattr(part, 'index', 0) or 0, ['', ''])
                    fn = getattr(part, 'function', None)
                    slot[0] += getattr(fn, 'name', None) or ''
                    slot[1] += getattr(fn, 'arguments', None) or ''
            if calls:
                return tool_call_text(*calls[min(calls)]), None
            text = ''.join(pieces)
            if not text.strip():
                return None, EMPTY_RESPONSE_ERROR
            return text.strip(), None
        response = _completion(litellm, wait_s, retries, **kwargs)
        message = response.choices[0].message
        for call in _listed(getattr(message, 'tool_calls', None))[:1]:
            return tool_call_text(call.function.name, call.function.arguments), None
        text = message.content or ''
        if not text.strip():
            return None, EMPTY_RESPONSE_ERROR
        return text.strip(), None
    except Exception as e:
        logger.error(f"[llm_utils] LiteLLM error ({provider}/{model}): {e}")
        _note_provider_failure(provider, e, wait_s, saturation_scope)
        return None, str(e)


def _listed(value) -> list:
    """`tool_calls` d'une réponse LiteLLM : une liste, ou rien (None, ou tout autre objet)."""
    return list(value) if isinstance(value, (list, tuple)) else []


def tool_call_text(name: str, arguments) -> str:
    """Un appel d'outil NATIF (nom + arguments JSON du fournisseur) rendu dans la forme texte de
    l'assistant, `{"tool": nom, "args": {…}}`. Des arguments illisibles restent visibles dans
    `args` sous `_raw` : l'outil les refusera avec son message, plutôt qu'un appel muet."""
    try:
        args = json.loads(arguments) if isinstance(arguments, str) else dict(arguments or {})
    except (TypeError, ValueError):
        args = {'_raw': arguments}
    return json.dumps({'tool': name or '', 'args': args if isinstance(args, dict) else {}},
                      ensure_ascii=False)


def chat_with_catalog_model(catalog_key: str, messages: list, *, user=None,
                            num_predict: Optional[int] = None, think: bool = False,
                            timeout: Optional[float] = None,
                            temperature: Optional[float] = None,
                            ) -> tuple[Optional[str], Optional[str]]:
    """
    Un appel LLM désigné par une CLÉ DE CATALOGUE (`ollama:qwen3.8:latest`,
    `albert:gpt-oss-120b`, `anthropic:claude-opus-5`, ou `auto`) — `(texte, None)` ou
    `(None, erreur)`, le contrat de `llm_chat`.

    POURQUOI (2026-09-30, route « app de zéro ») : une app dont le réglage « Modèle » tire ses
    options du catalogue (route F4b, `options_source: catalog`) stocke une CLÉ, et `llm_chat`
    attend un fournisseur + un nom. Le geste qui passe de l'un à l'autre n'existait qu'en privé,
    dans l'assistant (`assistant_engine._llm_call`) : la 1ʳᵉ app à en avoir besoin (l'Editor)
    l'aurait recopié.

    Règles :
      - `auto` (ou vide) → REFUSÉ, avec le geste à faire : « auto » n'est pas une clé, il se
        TIRE avant l'appel — par `auto_model.resolve_model_choice(item.model, app_id=…,
        item=item)` dans une app (domaine, curseur et distants de SON schéma : le chemin de la
        prévision « Prévu : … »), par `modele_par_defaut()` hors app. ⚠ Jusqu'au 2026-10-01 cette
        branche partait d'elle-même au funnel `modele_par_defaut` : une app qui oubliait de tirer
        passait par un AUTRE chemin que sa prévision — l'écran annonçait un modèle, le lancement en
        prenait un autre (relevé par Fabien sur le Writer). Refuser rend l'oubli visible ;
      - `ollama:<nom>` → Ollama, en local ;
      - `<source>:<modèle>` d'une source déclarée de type `llm` (`external_sources`) → le nom du
        fournisseur EST le nom de la source (albert, anthropic) ; la clé est celle de
        l'UTILISATEUR, par la garde commune `cloud_access` (profil « 100 % local », modèle ouvert
        par sa clé, clé posée) — jamais la clé d'instance pour un utilisateur connecté ;
      - l'abonnement Claude Code (`claude_code:*`) n'est pas un appel LiteLLM : refusé ici.
    `num_predict` (jetons max) : `None` par défaut = sans plafond — même raison que `timeout`
    ci-dessous : un document entier (le HTML d'une dizaine de diapositives) dépasse vite un plafond
    écrit d'avance, et la glu RECOPIE le défaut qu'elle lit ici. `think`, `temperature` : ceux de
    `llm_chat`.
    `timeout` : `None` par défaut, et c'est voulu — dans une tâche, la borne est la DURÉE MAX du
    squelette (`task_skeleton._time_guard`, réglable au profil et par modèle). Un délai plus court
    posé ici ajoute un échec arbitraire : mesuré le 2026-10-01, la 1ʳᵉ génération réelle de
    l'Editor (HTML d'une dizaine de diapositives, qwen3.8 local) est tombée sur un `300` que la glu
    avait RECOPIÉ du défaut de cette signature. Ne le fixer que pour un appel interactif.
    ⚠ Signature EXPLICITE, pas de `**kwargs` qui relaie (2026-10-01) : un relais cache la vraie
    signature au modèle QUI ÉCRIT l'appel et au contrôle qui le juge — le rôle `codegen` avait
    passé `max_tokens` et `max_new_tokens`, `TypeError` assuré au premier lancement.
    """
    from wama.common.utils.model_keys import split_key
    llm_kwargs = {'num_predict': num_predict, 'think': think, 'timeout': timeout,
                  'temperature': temperature}
    key = (catalog_key or '').strip()
    from wama.common.utils.auto_model import is_auto
    if is_auto(key):
        return None, ("« auto » n'est pas une clé de catalogue : le tirer avant l'appel — "
                      "`resolve_model_choice` dans une app (le chemin de la prévision), "
                      "`modele_par_defaut()` hors app")
    # La lecture UNIQUE de `<source>:<identifiant>` (brique `model_keys`, ralliée le 2026-10-01 :
    # un `partition(':')` maison en était la 13ᵉ copie). Une valeur sans source connue n'est pas
    # une clé de catalogue.
    source, model_id = split_key(key)
    if not source or not model_id:
        return None, f"clé de catalogue invalide : {catalog_key!r} (attendu <source>:<modèle>)"
    if source == 'ollama':
        return llm_chat(messages, model=model_id, provider='ollama', **llm_kwargs)
    if source == 'claude_code':
        return None, ("l'abonnement Claude Code n'est pas un fournisseur d'app : il est réservé "
                      "à l'assistant")
    from wama.common import external_sources
    declared = external_sources.by_key().get(source)
    if declared is None or declared.kind != 'llm':
        return None, f"« {source} » n'est pas un fournisseur LLM déclaré dans WAMA"
    from wama.model_manager.services.cloud_models import CloudAccessRefused
    try:
        return chat_with_source(source, model_id, messages, user=user, **llm_kwargs)
    except CloudAccessRefused as refused:
        return None, str(refused)


def chat_with_source(source: str, model_id: Optional[str], messages: list, *, user=None,
                     num_predict: Optional[int] = None, think: bool = False,
                     timeout: Optional[float] = None, temperature: Optional[float] = None,
                     on_delta=None, tools: Optional[list] = None,
                     rate_limit_wait: bool = True,
                     ) -> tuple[Optional[str], Optional[str]]:
    """Un appel à un fournisseur LLM DÉCLARÉ (`external_sources`, type `llm` : Albert, API
    Anthropic…), avec la clé de l'UTILISATEUR quand il est connecté — `(texte, None)` ou
    `(None, erreur)` de `llm_chat`. Le nom du fournisseur EST le nom de la source.
    Un échec qui dit le fournisseur saturé le NOTE pour la clé employée (`rate_limit_wait` : celui
    de `llm_chat`).

    ⚠ LÈVE `CloudAccessRefused` (motif + statut HTTP) quand la garde commune refuse (profil
    « 100 % local », modèle non ouvert par la clé, clé absente) : l'appelant choisit sa forme de
    refus — `chat_with_catalog_model` la rend en message, l'assistant en statut.

    POURQUOI une brique (2026-10-01) : ces lignes vivaient EN PRIVÉ dans l'assistant
    (`assistant_engine._llm_call`) ; la 1ʳᵉ app à appeler un LLM par une clé de catalogue (le
    Writer) les aurait recopiées. Sans utilisateur (rôles en ligne de commande), aucune clé n'est
    passée : `llm_chat` prend celle de l'instance, comme avant.
    """
    api_key = None
    data_reuse_ok = False
    scope = 'instance'
    if user is not None and getattr(user, 'is_authenticated', False):
        from wama.model_manager.services.cloud_models import (
            cloud_access, data_reuse_accepted, saturation_scope)
        api_key = cloud_access(user, source, model_id or '')
        # La règle de collecte suit le PLAFOND du profil (Fabien, 2026-10-12).
        data_reuse_ok = data_reuse_accepted(user)
        # La portée de la clé ne se lit qu'en cas d'échec : une requête de moins par appel.
        scope = lambda: saturation_scope(user, source)  # noqa: E731
    return llm_chat(messages, model=model_id or None, provider=source, api_key=api_key,
                    num_predict=num_predict, think=think, timeout=timeout,
                    temperature=temperature, on_delta=on_delta, tools=tools,
                    data_reuse_ok=data_reuse_ok, rate_limit_wait=rate_limit_wait,
                    saturation_scope=scope)


def extract_json_from_llm(text: str) -> Optional[dict]:
    """
    Extract the first valid JSON object from an LLM response.
    Handles reasoning tags (<think>...</think>), markdown code blocks, and
    surrounding prose. Uses raw_decode to find the first parseable object.
    """
    # Strip thinking blocks
    clean = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL).strip()

    # Strip markdown code fences: ```json { ... } ```
    clean = re.sub(r'```(?:json)?\s*', '', clean)
    clean = re.sub(r'```', '', clean).strip()

    # Walk the string looking for a valid JSON object starting at each '{'
    decoder = json.JSONDecoder()
    idx = 0
    while idx < len(clean):
        start = clean.find('{', idx)
        if start == -1:
            break
        try:
            obj, _ = decoder.raw_decode(clean, start)
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            pass
        idx = start + 1

    logger.debug(f"[llm_utils] extract_json_from_llm: no valid JSON found in: {text[:300]!r}")
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Les 5 aides de haut niveau ci-dessous (transcriber + describer + reader).
#
# `_APPEL_LLM` — LE CONTRAT, écrit une fois ici plutôt que redécouvert 10 fois.
#
# Elles appelaient `ollama_chat()` EN DIRECT jusqu'au 2026-09-09 : elles étaient donc
# LOCAL-ONLY par construction — ni routage cloud, ni clé API d'utilisateur, alors que
# `llm_chat()` (LiteLLM, ROADMAP §8d) était déjà adopté par 5 autres consommateurs
# (assistant_engine, prompt_enrichment, qc, translator, prospect_agents).
#
# Deux règles, et elles ne sont pas cosmétiques :
#
# 1. **`model or None`, jamais `model`.** Le défaut de ces signatures est `''`, et la
#    branche cloud de `llm_chat` teste `if model is None` pour appliquer le défaut du
#    fournisseur. Une chaîne VIDE passe ce test, et produit le modèle `"openai/"` —
#    une erreur distante, pas une exception locale.
# 2. **`provider` remonte à l'appelant.** Aucun des 5 consommateurs déjà adoptés ne se
#    repose sur `settings.LITELLM_PROVIDER` : tous passent un `provider` explicite,
#    résolu AVEC leur modèle. Le laisser implicite ici marierait un modèle résolu
#    localement (`gemma4:e4b`) à un fournisseur global cloud — le seul appariement que
#    `llm_chat` ne peut pas rattraper. `None` = « le réglage global décide », ce qui
#    reproduit à l'octet le comportement d'avant tant que `LITELLM_PROVIDER='ollama'`
#    (sa valeur par défaut, `settings.py:845`).
# ─────────────────────────────────────────────────────────────────────────────

def generate_meeting_summary(
    text: str,
    language: str = 'fr',
    speakers: Optional[list] = None,
    model: str = '',
    provider: Optional[str] = None,
) -> str:
    """
    Generate a structured meeting summary (compte-rendu de réunion).

    Args:
        text:     Transcript or meeting text (truncated to ~8000 chars).
        language: 'fr' | 'en'
        speakers: Optional list of speaker IDs from diarization.
        model:    Model name. `''` ⇒ résolu par le funnel (cf. `_APPEL_LLM`).
        provider: Fournisseur LiteLLM. `None` ⇒ `settings.LITELLM_PROVIDER`.

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

    # think=False + budget suffisant + retry (cf. generate_structured_summary).
    result_text, error = llm_chat(messages, model=model or None, provider=provider,
                                  think=False, num_predict=4096)
    if not result_text:
        result_text, error = llm_chat(messages, model=model or None, provider=provider,
                                      think=False, num_predict=4096)

    if error or not result_text:
        logger.warning(f"[llm_utils] generate_meeting_summary failed: {error}")
        return truncated

    data = extract_json_from_llm(result_text)
    if not data:
        logger.warning(f"[llm_utils] Could not parse JSON from meeting summary. Raw: {result_text[:400]!r}")
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
    model: str = '',
    provider: Optional[str] = None,
) -> dict:
    """
    Verify text coherence and suggest corrections.

    Args:
        text:         Source text to verify (truncated to ~6000 chars).
        content_hint: 'transcription' | 'description' | 'audio' | 'video' | 'image' | 'text'
        language:     'fr' | 'en'
        model:        Model name. `''` ⇒ résolu par le funnel (cf. `_APPEL_LLM`).
        provider:     Fournisseur LiteLLM. `None` ⇒ `settings.LITELLM_PROVIDER`.

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

    # think=False : tâche de sortie JSON → pas de raisonnement qui consomme le budget
    # de tokens (cause des réponses vides avec les modèles « thinking » type qwen3).
    # + 1 retry sur réponse vide (intermittence Ollama).
    result_text, error = llm_chat(messages, model=model or None, provider=provider,
                                  think=False, num_predict=4096)
    if not result_text:
        result_text, error = llm_chat(messages, model=model or None, provider=provider,
                                      think=False, num_predict=4096)

    if error or not result_text:
        logger.warning(f"[llm_utils] verify_text_coherence failed: {error}")
        raise RuntimeError(error or "No response from Ollama")

    data = extract_json_from_llm(result_text)
    if not data:
        logger.warning(f"[llm_utils] Could not parse JSON from coherence check. Raw: {result_text[:400]!r}")
        raise RuntimeError("Could not parse JSON response from Ollama")

    return {
        "score":      max(0, min(100, int(data.get("score", 0)))),
        "notes":      [str(n) for n in data.get("notes", []) if n],
        "suggestion": str(data.get("suggestion", text)),
    }


#: Lecture d'un score de cohérence : (plancher, niveau) — la couleur que lui donne l'aperçu
#: commun (celle des modales de résultat du describer et du transcriber, 2026-10-13).
COHERENCE_LEVELS = ((80, 'success'), (50, 'warning'), (0, 'danger'))


def build_coherence_report(score, notes, suggestion, original) -> Optional[dict]:
    """Le rapport de `verify_text_coherence` tel qu'un élément l'a GARDÉ, sous la forme que
    l'aperçu commun montre (`ProcessSpec.result_format='coherence'`) : `{score, level, notes,
    suggestion, original}` — `original` est le texte VÉRIFIÉ, que la face met en regard de la
    version proposée. Les notes gardées en un texte (une par ligne) redeviennent une liste.
    None : pas de score, rien n'a été vérifié."""
    if score is None:
        return None
    score = int(score)
    if isinstance(notes, str):
        notes = notes.splitlines()
    return {'score': score,
            'level': next((level for floor, level in COHERENCE_LEVELS if score >= floor),
                          COHERENCE_LEVELS[-1][1]),
            'notes': [str(n).strip() for n in (notes or []) if str(n).strip()],
            'suggestion': (suggestion or '').strip(),
            'original': (original or '').strip()}


def coherence_report_text(report: dict) -> str:
    """Le rapport en TEXTE — ce que Copier emporte et ce qui identifie la face."""
    parts = [f"Score : {report['score']}/100"]
    if report.get('notes'):
        parts += ['', 'Remarques :'] + [f"• {note}" for note in report['notes']]
    if report.get('suggestion'):
        parts += ['', 'Version proposée :', report['suggestion']]
    return '\n'.join(parts)


def analyze_segments_coherence(
    segments: list,
    language: str = 'fr',
    model: str = '',
    provider: Optional[str] = None,
) -> dict:
    """Analyse la cohérence PAR SEGMENT (1 seul appel LLM).

    Args:
        segments: liste de dicts {'index': int, 'text': str}.
        language: 'fr' | 'en'.
        model:    Model name. `''` ⇒ résolu par le funnel (cf. `_APPEL_LLM`).
        provider: Fournisseur LiteLLM. `None` ⇒ `settings.LITELLM_PROVIDER`.

    Returns:
        {index: {"severity": "warn"|"error", "note": str}} — uniquement les
        segments problématiques. **Ne lève jamais** : renvoie {} en cas d'échec
        (l'appelant retombe alors sur la confiance ASR pour la heatmap).
    """
    items = [s for s in segments if (s.get('text') or '').strip()]
    if not items:
        return {}
    lang_label = "en français" if language == 'fr' else "in English"
    lines = [f"[{s['index']}] {(s.get('text') or '').strip()[:300]}" for s in items[:200]]
    messages = [
        {"role": "system", "content": (
            "Tu es un expert en contrôle qualité de transcriptions audio. "
            f"Réponds toujours {lang_label} avec un JSON valide et rien d'autre.")},
        {"role": "user", "content": (
            "Voici une transcription découpée en segments numérotés. Repère UNIQUEMENT les "
            "segments problématiques : répétitions, phrases tronquées/incomplètes, "
            "hallucinations, incohérences sémantiques, mots douteux, changement de langue.\n\n"
            'Retourne un JSON : {"issues": [{"i": <numéro de segment>, '
            '"severity": "warn" ou "error", "note": "<problème en quelques mots>"}]}. '
            'Ne liste QUE les segments à problème ("error" = à corriger, "warn" = à vérifier) ; '
            "les autres sont implicitement corrects.\n\n"
            f"Segments :\n{chr(10).join(lines)}\n\nRéponds UNIQUEMENT avec le JSON.")},
    ]
    try:
        # think=False (sortie JSON) + 1 retry sur réponse vide.
        result_text, error = llm_chat(messages, model=model or None, provider=provider,
                                      think=False)
        if not result_text:
            result_text, error = llm_chat(messages, model=model or None, provider=provider,
                                          think=False)
        if error or not result_text:
            logger.warning(f"[llm_utils] analyze_segments_coherence: {error or 'réponse vide'}")
            return {}
        data = extract_json_from_llm(result_text)
        if not data:
            return {}
        out = {}
        for it in (data.get("issues") or []):
            try:
                i = int(it.get("i"))
            except (TypeError, ValueError):
                continue
            sev = it.get("severity", "warn")
            out[i] = {"severity": sev if sev in ("warn", "error") else "warn",
                      "note": str(it.get("note", "")).strip()}
        return out
    except Exception as e:
        logger.warning(f"[llm_utils] analyze_segments_coherence failed: {e}")
        return {}


def suggest_speaker_names(
    segments: list,
    language: str = 'fr',
    model: str = '',
    provider: Optional[str] = None,
) -> dict:
    """Propose des noms d'intervenants à partir des présentations dans la transcription.

    Cherche les indices d'identité (« je suis X », « bonjour, ici Y », « je passe la
    parole à Z ») pour associer un nom à chaque libellé de locuteur (SPEAKER_NN).

    Args:
        segments: liste de dicts {'speaker_id': str, 'text': str} (libellés canoniques).
        language: 'fr' | 'en'.
        model:    Model name. `''` ⇒ résolu par le funnel (cf. `_APPEL_LLM`).
        provider: Fournisseur LiteLLM. `None` ⇒ `settings.LITELLM_PROVIDER`.

    Returns:
        {SPEAKER_NN: "Nom proposé"} — uniquement les locuteurs pour lesquels un nom
        plausible est trouvé. **Ne lève jamais** : renvoie {} en cas d'échec.
    """
    from wama.transcriber.utils.speakers import normalize_speaker_label
    items = []
    for s in segments:
        spk = normalize_speaker_label(s.get('speaker_id'))
        txt = (s.get('text') or '').strip()
        if spk and txt:
            items.append((spk, txt))
    if not items:
        return {}
    speakers = []
    for spk, _ in items:
        if spk not in speakers:
            speakers.append(spk)
    lang_label = "en français" if language == 'fr' else "in English"
    # On limite le contexte : début de réunion = là où on se présente le plus souvent.
    lines = [f"{spk}: {txt[:200]}" for spk, txt in items[:120]]
    messages = [
        {"role": "system", "content": (
            "Tu es un assistant qui identifie le nom des intervenants d'une transcription "
            f"à partir de leurs présentations. Réponds toujours {lang_label} avec un JSON "
            "valide et rien d'autre.")},
        {"role": "user", "content": (
            "Voici une transcription : chaque ligne commence par l'identifiant du locuteur "
            "puis son texte. À partir des présentations (« je suis … », « ici … », « je passe "
            "la parole à … », appels par le prénom, etc.), associe un NOM à chaque identifiant. "
            "N'invente aucun nom : si tu n'as pas d'indice fiable pour un locuteur, ne l'inclus pas.\n\n"
            f"Identifiants présents : {', '.join(speakers)}\n\n"
            f"Transcription :\n{chr(10).join(lines)}\n\n"
            'Retourne UNIQUEMENT un JSON : {"speakers": [{"id": "SPEAKER_00", "name": "Prénom Nom"}, ...]}.')},
    ]
    try:
        result_text, error = llm_chat(messages, model=model or None, provider=provider,
                                      think=False, num_predict=1024)
        if not result_text:
            result_text, error = llm_chat(messages, model=model or None, provider=provider,
                                          think=False, num_predict=1024)
        if error or not result_text:
            logger.warning(f"[llm_utils] suggest_speaker_names: {error or 'réponse vide'}")
            return {}
        data = extract_json_from_llm(result_text)
        if not data:
            return {}
        out = {}
        for it in (data.get("speakers") or []):
            sid = normalize_speaker_label(it.get("id"))
            name = str(it.get("name", "")).strip()
            if sid and name and sid in speakers:
                out[sid] = name[:120]
        return out
    except Exception as e:
        logger.warning(f"[llm_utils] suggest_speaker_names failed: {e}")
        return {}


def generate_structured_summary(
    text: str,
    content_hint: str = 'transcription',
    language: str = 'fr',
    model: str = '',
    provider: Optional[str] = None,
) -> dict:
    """
    Generate a structured summary (summary, key_points, action_items).

    Args:
        text:         Source text to summarize (will be truncated to ~8000 chars).
        content_hint: 'transcription' | 'description' | 'audio' | 'video'
        language:     'fr' | 'en'
        model:        Model name. `''` ⇒ résolu par le funnel (cf. `_APPEL_LLM`).
        provider:     Fournisseur LiteLLM. `None` ⇒ `settings.LITELLM_PROVIDER`.

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

    # think=False (sortie JSON) + num_predict suffisant + 1 retry : sans ça, un texte long
    # fait que le modèle « thinking » épuise son budget en raisonnement → JSON vide.
    result_text, error = llm_chat(messages, model=model or None, provider=provider,
                                  think=False, num_predict=4096)
    if not result_text:
        result_text, error = llm_chat(messages, model=model or None, provider=provider,
                                      think=False, num_predict=4096)

    if error or not result_text:
        logger.warning(f"[llm_utils] generate_structured_summary failed: {error}")
        raise RuntimeError(error or "No response from Ollama")

    data = extract_json_from_llm(result_text)
    if not data:
        logger.warning(f"[llm_utils] Could not parse JSON from structured summary. Raw: {result_text[:400]!r}")
        raise RuntimeError("Could not parse JSON response from Ollama")

    return {
        "summary":      str(data.get("summary", "")),
        "key_points":   [str(p) for p in data.get("key_points", []) if p],
        "action_items": [str(a) for a in data.get("action_items", []) if a],
    }
