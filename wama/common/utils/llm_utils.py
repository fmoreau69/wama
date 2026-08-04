"""
WAMA Common — LLM utilities
Shared Ollama client for use in Celery workers (transcriber, describer, ...).
"""

import json
import logging
import re
from typing import Optional

logger = logging.getLogger(__name__)


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


def _llm_par_catalogue(tier: str, exige):
    """
    Résout un tier via `select_model()` — brique VRAM-aware du model_manager.

    `prefer_loaded=True` porte la demande centrale : à qualité comparable, privilégier un
    modèle DÉJÀ en mémoire plutôt que d'imposer un déchargement/rechargement. Le signal vient
    de `/api/ps`, remonté dans le catalogue par `model_registry._ollama_charges()`.

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
            prefer_loaded=True,
            vram_budget_gb=_PLAFOND_TIER.get(tier),
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

    options: dict = {"temperature": 0.3, "num_predict": num_predict}
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
) -> tuple[Optional[str], Optional[str]]:
    """
    Unified LLM chat function — provider-agnostic entry point.

    Phase 1 (local only): provider defaults to 'ollama' → delegates to ollama_chat().
    Phase 2 (hybrid): provider can be 'openai', 'anthropic', 'grok', 'mistral', etc.
      Routes via LiteLLM with the user's API key from UserProviderConfig.

    Args:
        messages:   List of {"role": ..., "content": ...} dicts.
        model:      Model name without provider prefix (e.g. 'qwen3.5:9b', 'gpt-4o').
                    If None, falls back to provider-specific default.
        provider:   'ollama' (default) | 'openai' | 'anthropic' | 'grok' | 'mistral'.
                    If None, reads settings.LITELLM_PROVIDER (default: 'ollama').
        num_predict: Max tokens to generate (Ollama) / max_tokens (cloud).
        num_ctx:    KV cache size in tokens (Ollama only, ignored for cloud).
        think:      Qwen3 thinking mode (Ollama only, ignored for cloud).
        keep_alive: Résidence VRAM après réponse (Ollama only, ignoré pour le cloud).
                    '0' = décharger tout de suite (cf. ollama_chat).
        timeout:    HTTP timeout in seconds.
        api_key:    Cloud API key (required for non-Ollama providers).
        api_base:   Override API base URL (e.g. custom Ollama host).

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
        )

    # ── Phase 2: cloud provider via LiteLLM ───────────────────────────────────
    try:
        import litellm
    except ImportError:
        logger.error("[llm_utils] litellm not installed — pip install litellm")
        return None, "litellm not installed (pip install litellm)"

    # Build the LiteLLM model string: "provider/model_name"
    if model is None:
        # Provider-specific defaults
        _defaults = {
            'openai':    'gpt-4o',
            'anthropic': 'claude-sonnet-4-6',
            'grok':      'grok-3',
            'xai':       'grok-3',
            'gemini':    'gemini-2.0-flash',
            'mistral':   'mistral-large-latest',
            'groq':      'llama-3.3-70b-versatile',
            'deepseek':  'deepseek-chat',
        }
        model = _defaults.get(provider, 'gpt-4o')

    # Map du nom de fournisseur WAMA → préfixe attendu par LiteLLM (ex. grok → xai/).
    _LITELLM_PREFIX = {'grok': 'xai', 'google': 'gemini'}
    prefix = _LITELLM_PREFIX.get(provider, provider)
    litellm_model = model if '/' in model else f"{prefix}/{model}"

    # Ollama routé via LiteLLM (cas rare : provider='ollama' explicite) → api_base local par défaut.
    if prefix == 'ollama' and not api_base:
        api_base = getattr(settings, 'OLLAMA_HOST', 'http://127.0.0.1:11434')

    kwargs: dict = {
        'model':      litellm_model,
        'messages':   messages,
        'timeout':    timeout,
        'max_tokens': num_predict,
    }
    if api_key:
        kwargs['api_key'] = api_key
    if api_base:
        kwargs['api_base'] = api_base

    try:
        response = litellm.completion(**kwargs)
        text = response.choices[0].message.content or ''
        if not text.strip():
            return None, "LLM returned empty response"
        return text.strip(), None
    except Exception as e:
        logger.error(f"[llm_utils] LiteLLM error ({provider}/{model}): {e}")
        return None, str(e)


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


def generate_meeting_summary(
    text: str,
    language: str = 'fr',
    speakers: Optional[list] = None,
    model: str = '',
) -> str:
    """
    Generate a structured meeting summary (compte-rendu de réunion) using Ollama.

    Args:
        text:     Transcript or meeting text (truncated to ~8000 chars).
        language: 'fr' | 'en'
        speakers: Optional list of speaker IDs from diarization.
        model:    Ollama model to use.

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
    result_text, error = ollama_chat(messages, model=model, think=False, num_predict=4096)
    if not result_text:
        result_text, error = ollama_chat(messages, model=model, think=False, num_predict=4096)

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
) -> dict:
    """
    Verify text coherence and suggest corrections using Ollama.

    Args:
        text:         Source text to verify (truncated to ~6000 chars).
        content_hint: 'transcription' | 'description' | 'audio' | 'video' | 'image' | 'text'
        language:     'fr' | 'en'
        model:        Ollama model to use.

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
    result_text, error = ollama_chat(messages, model=model, think=False, num_predict=4096)
    if not result_text:
        result_text, error = ollama_chat(messages, model=model, think=False, num_predict=4096)

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


def analyze_segments_coherence(
    segments: list,
    language: str = 'fr',
    model: str = '',
) -> dict:
    """Analyse la cohérence PAR SEGMENT (1 seul appel LLM).

    Args:
        segments: liste de dicts {'index': int, 'text': str}.
        language: 'fr' | 'en'.

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
        result_text, error = ollama_chat(messages, model=model, think=False)
        if not result_text:
            result_text, error = ollama_chat(messages, model=model, think=False)
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
) -> dict:
    """Propose des noms d'intervenants à partir des présentations dans la transcription.

    Cherche les indices d'identité (« je suis X », « bonjour, ici Y », « je passe la
    parole à Z ») pour associer un nom à chaque libellé de locuteur (SPEAKER_NN).

    Args:
        segments: liste de dicts {'speaker_id': str, 'text': str} (libellés canoniques).
        language: 'fr' | 'en'.

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
        result_text, error = ollama_chat(messages, model=model, think=False, num_predict=1024)
        if not result_text:
            result_text, error = ollama_chat(messages, model=model, think=False, num_predict=1024)
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
) -> dict:
    """
    Generate a structured summary (summary, key_points, action_items) using Ollama.

    Args:
        text:         Source text to summarize (will be truncated to ~8000 chars).
        content_hint: 'transcription' | 'description' | 'audio' | 'video'
        language:     'fr' | 'en'
        model:        Ollama model to use.

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
    result_text, error = ollama_chat(messages, model=model, think=False, num_predict=4096)
    if not result_text:
        result_text, error = ollama_chat(messages, model=model, think=False, num_predict=4096)

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
