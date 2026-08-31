"""
Moteur de l'assistant IA — boucle agentique multi-surface (chantier « passerelle de canaux », étape 0).

POURQUOI CE MODULE. Jusqu'au 2026-08-20 la boucle agentique vivait dans `wama/views.py`
(`_chat_with_ollama`), enfermée dans une vue session+CSRF : seule la page web pouvait
converser avec l'assistant. Les canaux tiers (bot Matrix/Tchap, Discord — cible de la
passerelle) exigent le même cerveau derrière une surface token (`/api/v1/assistant/chat/`).
L'extraction suit la règle de centralisation : UN moteur, N surfaces clientes (vue web,
API v1, adaptateurs de canaux à venir).

CE QUE L'EXTRACTION REMPLACE :
  • `views._chat_with_ollama` — déplacée ici À COMPORTEMENT CONSTANT (mêmes prompts, même
    résolution rôle→tier par le catalogue, même bascule de contexte, mêmes options Ollama).
  • `views._chat_with_claude` — SUPPRIMÉE : elle appelait le SDK `anthropic` en direct avec
    un modèle FIGÉ (`claude-sonnet-4-20250514`, périmé) et SANS outils. Les fournisseurs
    cloud passent désormais par `llm_chat()` (LiteLLM, brique commune) et profitent de la
    MÊME boucle à outils que le chemin local. Un nom de modèle en dur dans un chemin
    d'appel est le piège déjà documenté sur `_route_model_by_context`.

CE QUI EST VOLONTAIREMENT DIFFÉRÉ (décision Fabien 2026-08-20) : la persistance de
conversation. L'historique est fourni PAR LE CLIENT à chaque tour (localStorage côté web,
store du bot côté canal) — la jonction avec la brique mémoire/RAG (`common/memory/`,
chantier en cours dans une autre instance) se fera quand elle aura livré, sans changer
la signature : `history` deviendra simplement résoluble côté serveur.

Sécurité : `history` est ASSAINI (rôles user/assistant seulement) — un client token ne
peut pas injecter de tour `system`.
"""
from __future__ import annotations

import json
import logging
import os
import re

from django.conf import settings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Prompts système
# ---------------------------------------------------------------------------

#: `{LANGUE}` est résolu par `_language_instruction()` depuis le profil de l'utilisateur.
#: Avant le 2026-08-20 la langue était ÉCRITE EN DUR (« in French ») : un utilisateur dont le
#: profil dit `en` recevait quand même du français, et `preferred_language` — pourtant respecté
#: par le synthesizer et la pipeline de prompts — n'avait aucun effet ici. Le durcissement
#: devenait structurant depuis l'extraction « UN cerveau, N surfaces » : la consigne vaut pour
#: TOUTES les surfaces (web, API, futurs bots), pas seulement la page d'accueil.
WAMA_SYSTEM_PROMPT = """You are a helpful assistant for WAMA (Web App for Multimodal Automation), a Django-based web application for media processing including video anonymization, audio transcription, voice synthesis, image generation, and image/video enhancement. Answer questions concisely and helpfully in {LANGUE}."""


def _language_instruction(user) -> str:
    """Nom ANGLAIS de la langue de réponse (le prompt système est rédigé en anglais).

    Source = `UserProfile.preferred_language`, comme `prompt_pipeline` et `app_metadata` —
    surtout PAS une nouvelle préférence. Utilisateur inconnu ou langue non répertoriée →
    français, qui était le comportement en dur jusqu'ici : on ne change rien pour les
    utilisateurs dont le profil dit déjà `fr` (c'est le défaut du modèle).
    """
    from wama.common.tts.constants import LANGUAGE_NAMES_EN
    langue = getattr(getattr(user, 'profile', None), 'preferred_language', None) or 'fr'
    return LANGUAGE_NAMES_EN.get(langue, 'French')

WAMA_TOOLS_PROMPT = """
You can interact with WAMA applications by calling tools.
When you need to perform an action, output ONLY the JSON tool call on a single line, with NO surrounding text:
{"tool": "<name>", "args": {<arguments>}}

{TOOLS}

Rules:
- Make ONE tool call per turn. Wait for the result before calling another tool.
- When the user asks you to perform an action (add a file, launch processing, etc.), use the tools.
- When the user asks a question or wants information, answer directly without tools.
- Always confirm what you did after tool calls.
- Respond in {LANGUE}.
- COMPLETION NOTIFICATION: After starting a task (start_anonymizer, start_imager, start_enhancer, start_audio_enhancer, start_synthesizer, start_describer, start_transcriber), automatically call the corresponding get_*_status tool. If the task is already SUCCESS/done, immediately report the result with the file URL/preview link. If still RUNNING/PENDING, tell the user "La tâche a démarré — vous serez notifié dès la fin." and explain they can ask "quel est le statut ?" to check progress.
- OUTPUT LINKS: When a get_*_status result shows status="SUCCESS" or status="done" and contains output_url / audio_url / output_urls / video_url, ALWAYS include these links in your response using Markdown format: [📥 Télécharger](URL) or [🖼️ Voir l'image](URL).

File search strategy:
- When the user asks to anonymize a file: check "anon_input" first, then "temp".
- When the user asks to transcribe a file: check "transcriber_input" first, then "temp".
- When the user asks to describe a file: check "describer_input" first, then "temp".
- For any other request, search "temp" first.
- When the user references an asset from the médiathèque (e.g. "ma voix X", "l'image Y"), use list_media_assets to find it.
- If the file is not found in any folder, tell the user to upload it via the WAMA File Manager at /filemanager/ or the corresponding application page.
"""


# ---------------------------------------------------------------------------
# Résolution du modèle
# ---------------------------------------------------------------------------

# Rôles de la surface chat → TIER de résolution (llm_utils.modele_par_tier — LE point
# unique existant, mécanique du describer depuis le 2026-08-04). Plus de table de tags :
# elle mourait au premier remplacement de modèle (qwen3.5:35b-a3b → qwen3.6:35b, leçon du
# 2026-08-12, cf. check_model_declarations). `priority` exprime une préférence nominale
# (jamais un tag épinglé) ; prefer_loaded=False = intention de GABARIT explicite (le rôle
# 'dev' veut le tier heavy, pas le petit modèle déjà en mémoire).
_ROLE_TIER = {
    'dev':        {'tier': 'heavy', 'prefer_loaded': False},
    'coder':      {'tier': 'heavy', 'prefer_loaded': False},
    'architect':  {'tier': 'heavy', 'prefer_loaded': False},
    'debug':      {'tier': 'heavy', 'priority': ['coder'], 'prefer_loaded': False},
    'fast':       {'tier': 'default'},
    'ultra_fast': {'tier': 'fast'},
}

#: Fournisseurs traités par le chemin LOCAL (Ollama direct, usage tokens compris).
_LOCAL_PROVIDERS = ('wama-dev-ai', 'ollama')

#: Nom de fournisseur côté surface chat → nom attendu par `llm_chat()`/LiteLLM.
_PROVIDER_ALIAS = {'claude': 'anthropic'}

#: Fournisseurs servis par l'ABONNEMENT du titulaire (CLI Claude Code headless), et non
#: par une API facturée. Réservés aux administrateurs/développeurs — la garde est posée
#: dans `run_assistant_turn`, passage obligé des trois surfaces.
#: ⚠ NE PAS confondre avec `claude` (= API Anthropic, FACTURÉE au token). Les deux parlent
#: au même modèle par deux canaux de facturation opposés ; c'est la confusion que la
#: session du 31/08 a dû lever, et le libellé d'UI doit la lever aussi.
_SUBSCRIPTION_PROVIDERS = ('claude-abo',)


def resolve_chat_model(key: str) -> str:
    """Rôle de chat ('dev', 'fast'…) → tag Ollama résolu par le catalogue (source unique) ;
    un tag complet ('gemma4:12b') passe tel quel."""
    regle = _ROLE_TIER.get(key)
    if regle is None:
        return key
    try:
        from wama.common.utils.llm_utils import modele_par_tier
        return modele_par_tier(**regle) or key
    except Exception:
        logger.debug('[ai_chat] résolution du modèle par tier indisponible', exc_info=True)
        return key


# Safe context limits per model (chars, not tokens — ~4 chars/token estimate)
# Below these limits quality stays high; above them we upgrade to a larger model.
#: Repli quand le catalogue ne connaît pas la fenêtre de contexte d'un modèle (~4 caractères
#: par jeton, marge de sécurité prise sur 30K jetons).
_SAFE_CHARS_DEFAUT = 120_000

#: Fraction de la fenêtre annoncée qu'on s'autorise à remplir : l'estimation en caractères est
#: grossière et le prompt système s'ajoute au fil de la conversation.
_MARGE_CONTEXTE = 0.6


def _safe_char_limit(nom_modele: str) -> int:
    """
    Limite de contexte, en caractères, DÉRIVÉE du catalogue.

    Remplace une table codée en dur (2026-08-04) qui listait quatre modèles nommés : elle
    devenait fausse au premier remplacement — `qwen3.5:35b-a3b` y figurait encore alors que la
    prospection venait de le remplacer par `qwen3.6:35b`. La fenêtre réelle est désormais lue
    dans `capabilities['context_length']`, renseignée depuis `/api/show`.
    """
    try:
        from wama.model_manager.models import AIModel
        m = AIModel.objects.filter(model_key=f"ollama:{nom_modele}", is_downloaded=True).first()
        ctx = (m.capabilities or {}).get('context_length') if m else None
        if ctx:
            return int(ctx * 4 * _MARGE_CONTEXTE)
    except Exception:
        logger.debug("[ai_chat] fenêtre de contexte indisponible pour %s", nom_modele, exc_info=True)
    return _SAFE_CHARS_DEFAUT


def _build_wama_context(user) -> str:
    """
    Build a short WAMA status string to inject into the system prompt.
    Tells the assistant about current queue state without revealing sensitive data.
    """
    try:
        from django.apps import apps as django_apps
        lines = []
        checks = [
            ('anonymizer',   'Media',            'status'),
            ('transcriber',  'Transcript',       'status'),
            ('describer',    'Description',      'status'),
            ('enhancer',     'Enhancement',      'status'),
            ('imager',       'Generation',       'status'),
            ('synthesizer',  'VoiceSynthesis',   'status'),
            ('composer',     'ComposerGeneration','status'),
            ('reader',       'ReadingItem',      'status'),
        ]
        for app_label, model_name, _ in checks:
            try:
                model = django_apps.get_model(f'wama.{app_label}', model_name)
                pending = model.objects.filter(user=user, status='PENDING').count()
                running = model.objects.filter(user=user, status__in=['RUNNING', 'processing']).count()
                failed  = model.objects.filter(user=user, status__in=['FAILURE', 'ERROR', 'error']).count()
                if pending or running or failed:
                    parts = []
                    if pending: parts.append(f"{pending} en attente")
                    if running: parts.append(f"{running} en cours")
                    if failed:  parts.append(f"{failed} en erreur")
                    lines.append(f"  - {app_label}: {', '.join(parts)}")
            except Exception:
                pass
        if lines:
            return "\n\nÉtat actuel des files WAMA (utilisateur connecté):\n" + "\n".join(lines)
        return "\n\nToutes les files WAMA sont vides pour cet utilisateur."
    except Exception:
        return ""


def _route_model_by_context(ollama_model: str, messages: list) -> str:
    """
    Upgrade the Ollama model if the conversation context is too long for it.
    Uses a conservative char-based estimate (~4 chars per token).
    """
    total_chars = sum(len(m.get('content', '')) for m in messages)
    if total_chars <= _safe_char_limit(ollama_model):
        return ollama_model

    # Bascule vers le modèle le plus CAPABLE du catalogue — plus vers un nom figé.
    # L'ancienne cible codée en dur était `qwen3.5:35b-a3b` : la prospection l'ayant remplacé
    # par `qwen3.6:35b` le 2026-08-04, l'assistant basculait vers un modèle ABSENT dès que la
    # conversation s'allongeait. Un nom en dur dans un chemin de repli est un piège : il ne
    # casse que le jour où le repli sert.
    try:
        from wama.model_manager.services.model_selector import select_model
        meilleur = select_model('ollama', model_type='llm', requires=['completion'],
                                prefer_loaded=False)
        cible = meilleur.model_key.split(':', 1)[1] if meilleur else ollama_model
    except Exception:
        logger.debug("[ai_chat] sélection du modèle de repli indisponible", exc_info=True)
        cible = ollama_model

    if cible != ollama_model:
        logger.info("[ai_chat] contexte trop long (%d caractères) pour %s — bascule vers %s",
                    total_chars, ollama_model, cible)
    return cible


# ---------------------------------------------------------------------------
# Appels LLM
# ---------------------------------------------------------------------------

def _ollama_call(messages: list, ollama_model: str) -> tuple:
    """
    Low-level Ollama POST.

    Returns:
        (text: str, usage: dict) on success
        (None, error_dict) on failure
    """
    import httpx

    # Résolution par la BRIQUE COMMUNE, comme les 8 autres consommateurs d'Ollama
    # (`llm_utils`, `memory/embed`, `model_registry`, `vision_probe`…). Elle détecte WSL2 et
    # calcule la passerelle de l'hôte Windows toute seule.
    #
    # ⚠ Le repli codé en dur sur `127.0.0.1` était juste en apparence : sous WSL2 cette adresse
    # désigne la VM, pas l'hôte où tourne Ollama. L'assistant ne fonctionnait donc que parce que
    # `start_wama_prod.sh:44` exporte `OLLAMA_HOST` — n'importe quel autre contexte (commande de
    # gestion, cron, test, shell) tombait sur un 503, alors que tous les autres appelants
    # marchaient partout. Constaté le 2026-08-21 en testant l'assistant hors du script.
    # ⚠ On lit l'ENV, pas `settings.OLLAMA_HOST` : ce réglage vaut
    # `os.environ.get('OLLAMA_HOST', 'http://127.0.0.1:11434')` (settings.py:661), donc il n'est
    # JAMAIS vide — un `or` dessus retomberait toujours sur le mauvais défaut au lieu de laisser
    # la brique répondre. Une valeur explicitement exportée continue de gagner.
    from wama.common.utils.ollama_host import ollama_base

    ollama_host = (os.environ.get('OLLAMA_HOST') or ollama_base()).rstrip('/')
    ollama_url = f"{ollama_host}/api/chat"

    try:
        with httpx.Client(timeout=180.0, trust_env=False) as client:
            resp = client.post(
                ollama_url,
                json={
                    "model": ollama_model,
                    "messages": messages,
                    "options": {"temperature": 0.7, "num_predict": 4096},
                    "stream": False,
                },
            )
        if resp.status_code != 200:
            return None, {'error': f'Ollama error: {resp.text}', 'status': resp.status_code}

        data = resp.json()
        text = data.get("message", {}).get("content", "")
        usage = {
            'input_tokens': data.get("prompt_eval_count", 0),
            'output_tokens': data.get("eval_count", 0),
        }
        return text, usage

    except httpx.ConnectError:
        host_cfg = getattr(settings, 'OLLAMA_HOST', 'http://127.0.0.1:11434')
        return None, {
            'error': (
                f'Ollama inaccessible à {ollama_url}. '
                f'Vérifiez que Ollama est démarré (ollama serve) et que OLLAMA_HOST '
                f'pointe sur la bonne adresse (actuel : {host_cfg}).'
            ),
            'status': 503,
        }
    except httpx.TimeoutException:
        return None, {'error': 'Ollama : délai dépassé. Le modèle est peut-être en cours de chargement.', 'status': 504}
    except Exception as e:
        logger.error(f"Ollama error: {e}")
        return None, {'error': f'Ollama error: {e}', 'status': 500}


def _claude_code_call(messages: list) -> tuple:
    """
    Un tour SUR L'ABONNEMENT, via le CLI Claude Code headless.

    ⚠⚠ CE QU'IL FAUT SAVOIR AVANT DE S'EN SERVIR — deux propriétés qui ne se voient pas :

    1. **`claude -p` est SANS ÉTAT.** Chaque appel est un process NEUF, sans mémoire du
       précédent : `demander()` fait un `subprocess.run`, jamais un `--resume`. L'historique
       est donc replié dans le prompt ici — sinon l'assistant serait amnésique d'un message
       à l'autre alors que la surface affiche un fil continu.
    2. **Le coût dépend du CACHE, pas du nombre d'appels** (mesuré le 31/08, cf.
       `claude_code.py`) : le cache de prompt (TTL 1 h) traverse les invocations, donc un
       appel à cache chaud coûte ~0,03 $ contre ~0,54 $ à froid. Ce qui coûte est le premier
       appel après une heure de silence — pas le fait d'enchaîner. ⚠ `--resume` a été testé
       pour amortir ce coût et **réfuté** : la session reprise construit un préfixe différent
       et rate le cache partagé (0,39 $, soit douze fois un appel frais à cache chaud).

    ⚠ Les outils WAMA ne sont PAS disponibles par ce chemin : Claude Code répond avec SES
    outils à lui (lecture du dépôt), et rend un texte final. Un « ajoute ce fichier à
    l'imager » n'aboutira donc pas ici — c'est le fournisseur local ou `claude` qu'il faut.
    """
    from wama.common.services.claude_code import ClaudeCodeIndisponible, demander

    morceaux = []
    for tour in messages or []:
        contenu = (tour.get('content') or '').strip()
        if not contenu:
            continue
        role = tour.get('role')
        if role == 'system':
            morceaux.append(contenu)
        elif role == 'assistant':
            morceaux.append(f"[Assistant] {contenu}")
        else:
            morceaux.append(f"[Utilisateur] {contenu}")

    try:
        resultat = demander('\n\n'.join(morceaux))
    except ClaudeCodeIndisponible as e:
        return None, {'error': str(e), 'status': 503}

    if not resultat.get('success'):
        return None, {'error': resultat.get('error', 'échec inconnu'), 'status': 502}

    # `cost_usd` est un ÉQUIVALENT-API rapporté par le CLI, PAS un débit : sur abonnement la
    # dépense s'impute au crédit inclus. Remonté quand même — c'est le bon indicateur
    # RELATIF pour comparer deux tâches, et le seul signal que ce chemin n'est pas gratuit.
    return resultat.get('texte', ''), {'input_tokens': 0, 'output_tokens': 0,
                                       'cost_usd': resultat.get('cout_usd')}


def _llm_call(messages: list, llm_model: str | None, provider: str) -> tuple:
    """
    Un tour de LLM, quel que soit le fournisseur.

    Chemin local (`wama-dev-ai`/`ollama`) : `_ollama_call` INCHANGÉ — usage tokens compris.
    Chemin cloud : `llm_chat()` (LiteLLM, brique commune) — les clés API viennent de
    l'environnement, le modèle par défaut du fournisseur vient de `llm_chat` (jamais figé
    ici). L'usage n'est pas remonté par `llm_chat` (contrat (text, err)) → compté à 0,
    assumé tant que le besoin ne l'exige pas.

    Returns:
        (text, usage_dict) on success · (None, error_dict) on failure
    """
    if provider in _LOCAL_PROVIDERS:
        return _ollama_call(messages, llm_model)

    if provider in _SUBSCRIPTION_PROVIDERS:
        return _claude_code_call(messages)

    from wama.common.utils.llm_utils import llm_chat
    text, err = llm_chat(
        messages,
        model=llm_model,
        provider=_PROVIDER_ALIAS.get(provider, provider),
        num_predict=4096,
        timeout=180.0,
    )
    if text is None:
        return None, {'error': err or 'LLM error', 'status': 502}
    return text, {'input_tokens': 0, 'output_tokens': 0}


# ---------------------------------------------------------------------------
# Boucle agentique
# ---------------------------------------------------------------------------

def _strip_think_tags(text: str) -> str:
    """Remove <think>...</think> reasoning blocks emitted by thinking models."""
    return re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL).strip()


def _parse_tool_call(text: str) -> dict | None:
    """
    Detect a JSON tool call in the LLM response.

    Expected format (on any line):
        {"tool": "tool_name", "args": {...}}

    Returns parsed dict or None.
    """
    # Strip reasoning tags first
    clean = _strip_think_tags(text)
    # Look for {"tool": ..., "args": ...} anywhere in the text
    match = re.search(r'\{[^{}]*"tool"\s*:\s*"[^"]+"\s*,\s*"args"\s*:\s*\{[^{}]*\}\s*\}', clean)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass
    return None


def _sanitize_history(history) -> list:
    """
    Assainit l'historique fourni par le client : seuls les tours `user`/`assistant` à
    contenu textuel passent. Indispensable depuis que la boucle est exposée à une surface
    token (un client ne doit pas pouvoir injecter un tour `system`).
    """
    clean = []
    for turn in (history or []):
        if (isinstance(turn, dict)
                and turn.get('role') in ('user', 'assistant')
                and isinstance(turn.get('content'), str)):
            clean.append({'role': turn['role'], 'content': turn['content']})
    return clean


def conversation_turn(user, message: str, *, surface: str = 'web', thread_key: str = '',
                         provider: str = 'wama-dev-ai', model: str = 'fast',
                         domain: str = None) -> dict:
    """
    UN tour, avec historique PERSISTÉ côté serveur — la voie normale pour une surface.

    Enveloppe `run_assistant_turn` : résout le fil `(user, surface, thread_key)`, fournit
    son historique au moteur, puis enregistre l'échange. Le moteur, lui, reste SANS ÉTAT —
    c'est ce qui permet de le tester sans base de données et de laisser intacts les clients
    qui gèrent leur propre trace (`run_assistant_turn(history=…)`).

    ⚠ BEST-EFFORT SUR LE STOCKAGE, JAMAIS SUR LA RÉPONSE : si le store est indisponible, on
    répond quand même, sans historique. Un assistant muet parce que sa trace est cassée
    serait un défaut bien pire que la perte de la trace.

    Rend le dict du moteur, augmenté de `conversation_id`.
    """
    from wama.common.services import conversation_store

    fil = None
    historique = []
    try:
        fil = conversation_store.thread(user, surface=surface, thread_key=thread_key)
        historique = conversation_store.history(fil)
    except Exception:
        logger.exception("[ai_chat] store de conversation indisponible — tour sans historique")

    resultat = run_assistant_turn(user, message, provider=provider, model=model,
                                  history=historique, domain=domain)

    if fil is not None and 'error' not in resultat:
        try:
            conversation_store.record_exchange(fil, message, resultat)
            resultat['conversation_id'] = fil.pk
        except Exception:
            logger.exception("[ai_chat] échange non enregistré (fil %s)", fil.pk)

    return resultat


def run_assistant_turn(user, message: str, provider: str = 'wama-dev-ai',
                       model: str = 'fast', history: list = None,
                       domain: str = None) -> dict:
    """
    UN tour de conversation avec l'assistant WAMA — cœur SANS ÉTAT, commun à toutes les
    surfaces (vue web `ai_chat`, API v1 `assistant/chat/`, adaptateurs de canaux).

    Pour un historique persisté côté serveur, préférer `conversation_turn()` ci-dessus ;
    cette fonction-ci reste le point d'entrée quand l'appelant apporte son propre `history`
    (harnais de test, client qui gère sa propre trace).

    Boucle agentique : si la réponse du LLM contient un appel d'outil JSON, l'outil est
    exécuté (porte unique `execute_tool`, gating F7 compris) et le résultat réinjecté dans
    la conversation, jusqu'à MAX_TOOL_ITERATIONS fois. Vaut pour le chemin local (Ollama)
    COMME pour les fournisseurs cloud (LiteLLM) — l'ancien chemin Claude sans outils est
    remplacé.

    Args:
        user:     Django User (requis pour l'exécution d'outils ; None = chat sans outils)
        message:  Message utilisateur
        provider: 'wama-dev-ai' (défaut, local) | 'claude'/'anthropic' | 'openai' | …
        model:    Rôle de chat (`_ROLE_TIER` : 'fast', 'dev'…) ou nom de modèle complet.
                  Pour un fournisseur cloud, un rôle de chat est ignoré (défaut fournisseur).
        history:  Tours précédents [{role, content}] — fournis par le client ; assainis ici.
        domain:   Domaine d'intervention (`assistant_skills.DOMAINES` : 'general', 'science',
                  'design', 'dev'). Détermine le skill de RÔLE injecté au prompt système et,
                  pour les domaines qui le déclarent, le rappel du contexte de laboratoire.

    Returns:
        dict succès : {success, response, model, usage, tool_steps}
        dict erreur : {error, status}
    """
    from wama.tool_api import execute_tool, build_tools_list

    provider = provider or 'wama-dev-ai'

    # ⚠ GARDE DE L'ABONNEMENT — posée ICI, et pas dans la vue de chat. `run_assistant_turn`
    # est le passage OBLIGÉ des TROIS surfaces (web `views.ai_chat`, `/api/v1/assistant/`,
    # passerelle Discord) : dans une vue, elle aurait laissé les deux autres ouvertes. Et la
    # surface la plus exposée est justement celle qui n'a pas de menu — un client peut poster
    # `provider` librement, l'UI ne garde rien.
    if provider in _SUBSCRIPTION_PROVIDERS:
        from wama.common.services.claude_code import subscription_allowed
        if not subscription_allowed(user):
            return {'error': "Le fournisseur « abonnement » est réservé aux administrateurs "
                             "et développeurs.", 'status': 403}

    local = provider in _LOCAL_PROVIDERS

    # Résolution du modèle : rôle→tag par le catalogue en local ; en cloud, un rôle de chat
    # n'a pas de sens → None (le défaut du fournisseur est résolu par llm_chat, jamais ici).
    if local:
        llm_model = resolve_chat_model(model)
    else:
        llm_model = None if (not model or model in _ROLE_TIER) else model

    # Inject current WAMA queue state into system prompt (when user is known)
    wama_context = _build_wama_context(user) if user else ""
    # Liste des outils GÉNÉRÉE depuis le registre tool_api (source unique → exhaustive,
    # avatarizer/composer/converter inclus). Le préambule + règles restent rédigés à la main.
    tools_prompt = WAMA_TOOLS_PROMPT.replace('{TOOLS}', build_tools_list()) if user else ""
    # Langue de réponse = profil utilisateur (plus de « in French » en dur).
    # ⚠ La consigne est posée sur les DEUX prompts : ils sont concaténés, et le prompt d'outils
    # portait lui aussi un « Respond in French » en dur — un profil `en` recevait donc deux
    # consignes CONTRADICTOIRES (corrigé 2026-08-21). Toujours `.replace`, jamais `.format` :
    # le prompt d'outils contient des accolades littérales (`{"tool": …}`) que `format` casserait.
    langue = _language_instruction(user)

    # Skill de RÔLE + contexte du laboratoire (`ROADMAP.md` §19.7). Le prompt système était
    # jusqu'ici générique en trois lignes : l'assistant ne savait ni dans quel domaine il
    # intervenait, ni ce que fait ce laboratoire. Le rôle est DÉCLARÉ par domaine, et le
    # contexte n'est cherché que pour les domaines qui le déclarent — pas de recherche
    # vectorielle pour « où en est ma transcription ? ».
    # ⚠ Ce n'est PAS l'enrichissement de prompt : celui-là est fait dans l'app au lancement
    # de la tâche (`process_prompt_for`). Deux natures distinctes, cf. `assistant_skills`.
    role, contexte_labo, annonce = '', '', ''
    try:
        from wama.common.utils.assistant_skills import (
            competences_announcement, role_instructions, laboratory_context,
        )
        role = role_instructions(domain)
        contexte_labo = laboratory_context(user, message, domain)
        # ⚠ On ANNONCE les autres compétences au lieu de toutes les charger : quatre skills
        # concaténés à chaque tour coûteraient des milliers de jetons sur un modèle local à
        # fenêtre étroite, et noieraient la question. L'assistant charge celle dont il a
        # besoin via l'outil `charger_competence` — c'est LUI qui décide, pas la surface qui
        # l'appelle (un adaptateur de canal ne connaît que son protocole).
        annonce = competences_announcement(sauf=domain) if user else ''
    except Exception:
        logger.debug("[ai_chat] skill de rôle indisponible", exc_info=True)

    system_prompt = (WAMA_SYSTEM_PROMPT.replace('{LANGUE}', langue)
                     + (f"\n\n{role}" if role else '')
                     + contexte_labo + annonce
                     + wama_context + tools_prompt.replace('{LANGUE}', langue))

    # Build messages: system + prior history (capped) + current user message
    prior = _sanitize_history(history)[-20:]  # keep last 10 exchanges max
    messages = [
        {"role": "system", "content": system_prompt},
        *prior,
        {"role": "user",   "content": message},
    ]

    if local:
        # Auto-upgrade model if context is too long for the selected model
        llm_model = _route_model_by_context(llm_model, messages)

        # Intention (KIND 'intent', §2bis.4 / §16.6) : si le LLM résolu ne gère pas la langue de
        # l'utilisateur, traduire le message vers une langue qu'il gère. Modèles assistant
        # multilingues (qwen…) → routing direct → AUCUN appel/chargement traducteur (résource-safe :
        # pas de cascade). Ne fait quelque chose que si le modèle déclare explicitement ses langues.
        # (Cloud : sans objet — les modèles frontière sont multilingues, et le routing est
        # indexé sur le catalogue Ollama.)
        try:
            from wama.common.utils.app_metadata import process_prompt_for
            routed = process_prompt_for('assistant', 'message', message, user=user,
                                        model_id=llm_model)
            if routed and routed != message:
                messages[-1]['content'] = routed
        except Exception:
            pass

    etiquette = f"wama-dev-ai ({llm_model})" if local else f"{provider} ({llm_model or 'défaut'})"
    tool_steps = []
    total_usage = {'input_tokens': 0, 'output_tokens': 0}
    MAX_TOOL_ITERATIONS = 5

    for _ in range(MAX_TOOL_ITERATIONS):
        text, result = _llm_call(messages, llm_model, provider)
        if text is None:
            return result  # error dict

        # Accumulate token usage
        total_usage['input_tokens']  += result.get('input_tokens', 0)
        total_usage['output_tokens'] += result.get('output_tokens', 0)

        # Detect tool call in response
        tool_call = _parse_tool_call(text) if user else None

        if not tool_call:
            # No tool call → this is the final answer
            # Strip any remaining reasoning tags from the displayed response
            clean_text = _strip_think_tags(text)
            return {
                'success': True,
                'response': clean_text,
                'model': etiquette,
                'usage': total_usage,
                'tool_steps': tool_steps,
            }

        # Execute the tool
        tool_name = tool_call.get('tool', '')
        tool_args  = tool_call.get('args', {})
        logger.info(f"[ai_chat] tool_call: {tool_name}({tool_args})")

        tool_result = execute_tool(tool_name, tool_args, user)
        tool_steps.append({'tool': tool_name, 'args': tool_args, 'result': tool_result})

        # Add assistant tool-call turn + tool result to conversation
        messages.append({"role": "assistant", "content": text})
        messages.append({
            "role": "user",
            "content": f"Résultat du tool {tool_name} : {json.dumps(tool_result, ensure_ascii=False)}",
        })

    # Reached iteration limit — return last LLM text as-is
    logger.warning("[ai_chat] tool-calling iteration limit reached")
    last_text = messages[-2].get("content", "") if len(messages) >= 2 else ""
    return {
        'success': True,
        'response': _strip_think_tags(last_text),
        'model': etiquette,
        'usage': total_usage,
        'tool_steps': tool_steps,
    }
