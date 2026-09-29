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
- AN add_* TOOL QUEUES, IT DOES NOT RUN. Its result carries `status: queued` and `next_step`: you MUST then call that start_* tool in the same turn. Until you do, nothing is processing — never say « la tâche a été lancée », and never report a result you have not read in a get_*_status result.
- COMPLETION NOTIFICATION: After starting a task (start_anonymizer, start_imager, start_enhancer, start_audio_enhancer, start_synthesizer, start_describer, start_transcriber), automatically call the corresponding get_*_status tool. If the task is already SUCCESS/done, immediately report the result with the file URL/preview link. If still RUNNING/PENDING, tell the user "La tâche a démarré — vous serez notifié dès la fin." and explain they can ask "quel est le statut ?" to check progress.
- OUTPUT LINKS: When a get_*_status result shows status="SUCCESS" or status="done" and contains output_url / audio_url / output_urls / video_url, ALWAYS include these links in your response using Markdown format: [📥 Télécharger](URL) or [🖼️ Voir l'image](URL).
- QUALITY LEVEL: when an add_* result carries `quality_level`, tell the user the task was queued at that level, e.g. « niveau Équilibré (55) — réglable par le curseur Rapide ↔ Qualité de l'assistant ». It is the user's own slider setting, applied to the task for them.
- NEVER INVENT A LINK. A URL may appear in your answer ONLY if it is copied character for character from a tool result you received in THIS conversation. If you do not have such a result, call the matching get_*_status tool and wait for it — never write a plausible-looking address (example.com, a path you guessed, a filename you rebuilt).
- NEVER CLAIM YOU CANNOT DO SOMETHING THAT A TOOL IN THE LIST ABOVE DOES. Check the list first. If a tool exists and fails, report WHAT FAILED, quoting the error message returned by the tool — do not turn a failure into « je ne peux pas » or « cela dépasse mes capacités ». A wrong refusal costs the user more than an error message.

File search strategy:
- When the user asks to anonymize a file: check "anon_input" first, then "temp".
- When the user asks to transcribe a file: check "transcriber_input" first, then "temp".
- When the user asks to describe a file: check "describer_input" first, then "temp".
- For any other request, search "temp" first.
- When the user references an asset from the médiathèque (e.g. "ma voix X", "l'image Y"), use list_media_assets to find it.
- If the file is not found in any folder, tell the user to upload it via the WAMA File Manager at /filemanager/ or the corresponding application page.
"""

#: Consigne ajoutée SUR LES SURFACES DE CANAL seulement (Discord, Matrix…). Sans elle, le
#: modèle répondait « je ne peux pas envoyer de fichiers par Discord » — faux : la passerelle
#: JOINT au message les sorties trouvées dans les résultats d'outils du tour
#: (`gateway/core.py::_produced_files` → `Reply.files` → `discord.File`). Mesuré le 2026-09-23
#: sur un échange réel : l'utilisateur a demandé trois fois son fichier, a reçu trois refus et
#: un lien INVENTÉ (`https://example.com/…`), alors que le canal savait le lui envoyer.
#: ⚠ Un lien `/media/…` est protégé par session : hors WAMA il ne s'ouvre pas — la pièce
#: jointe n'est donc pas un confort, c'est le SEUL chemin de récupération dans un canal.
CHANNEL_FILES_PROMPT = """
Channel surface ({SURFACE}):
- Files are ATTACHED to your reply automatically. Every /media/… output URL found in the tool results of THIS turn is uploaded to the conversation by the gateway — you have nothing to call for that.
- So NEVER answer that you cannot send a file here. To send the result of a task, call the matching get_*_status tool in this turn: its output_url makes the file travel with your answer. Then simply say the file is attached.
- DO NOT paste the /media/… path in your answer: it needs a browser session, so it is dead text here. The gateway adds the real download link itself, next to the file it uploads. Just say the file is attached.
"""

def surface_attaches_files(surface: str) -> bool:
    """La réponse de cette surface est-elle publiée par un ADAPTATEUR qui joint les fichiers ?

    LA LISTE N'EST PAS ICI : elle est déclarée par la passerelle (`gateway.core.CHANNELS`),
    qui est ce qui joint. Le moteur la LIT — il ne la redéclare pas, sinon le jour où un
    adaptateur Matrix arrive, l'assistant continuerait d'affirmer à ses utilisateurs qu'il ne
    peut pas leur envoyer de fichier. (`Conversation.SURFACES` répond à une autre question :
    quelles surfaces existent — web et api comprises, qui ne joignent rien.)

    Passerelle absente ou non installée : `False`, donc aucune promesse faite à l'utilisateur.
    """
    try:
        from wama.gateway.core import CHANNELS
    except Exception:          # pragma: no cover — WAMA tourne sans la passerelle
        return False
    return surface in CHANNELS


# ---------------------------------------------------------------------------
# Résolution du modèle
# ---------------------------------------------------------------------------

# Rôles de la surface chat → TIER de résolution (llm_utils.modele_par_tier — LE point
# unique existant, mécanique du describer depuis le 2026-08-04). Plus de table de tags :
# elle mourait au premier remplacement de modèle (qwen3.5:35b-a3b → qwen3.6:35b, leçon du
# 2026-08-12, cf. check_model_declarations). `priority` exprime une préférence nominale
# (jamais un tag épinglé) ; prefer_loaded=False = intention de GABARIT explicite (le rôle
# 'dev' veut le tier heavy, pas le petit modèle déjà en mémoire).
#: Anciens RÔLES de chat. Ils désignaient un GABARIT de modèle (`_ROLE_TIER`) — ce que le curseur
#: commun Rapide ↔ Qualité exprime désormais, sur une échelle continue au lieu de six paliers
#: nommés. Un client qui en envoie encore un est traité comme « auto » : le prendre pour un nom de
#: modèle enverrait « fast » à Ollama, qui n'a pas ce modèle.
_LEGACY_ROLES = ('fast', 'ultra_fast', 'dev', 'coder', 'architect', 'debug')

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

#: Fournisseur DISTANT de la surface chat → source `external_sources` qui porte sa clé
#: (2026-09-15). C'est la seule table à la main qui reste : elle traduit les noms historiques
#: de la surface ; tout le reste (libellé, hébergement, coût, modèles) se lit de la source et
#: du catalogue.
PROVIDER_SOURCES = {'albert': 'albert', 'claude': 'anthropic', 'claude-abo': 'claude_code'}

#: Source du CATALOGUE → fournisseur du moteur. Inverse de la table ci-dessus, plus Ollama : c'est
#: ce qui permet de ne choisir qu'un MODÈLE et d'en dériver le fournisseur.
SOURCE_PROVIDERS = {'ollama': 'ollama',
                    **{source: provider for provider, source in PROVIDER_SOURCES.items()}}




def assistant_settings(user) -> dict:
    """Réglages DURABLES de l'assistant pour `user` (brique commune `user_settings`, app
    `assistant`), complétés par les défauts DÉRIVÉS de son schéma."""
    from wama.assistant.params import USER_SETTINGS_DEFAULTS
    from wama.common.utils.user_settings import get_user_app_settings
    if user is None or not getattr(user, 'is_authenticated', False):
        return dict(USER_SETTINGS_DEFAULTS)
    return get_user_app_settings(user, 'assistant', USER_SETTINGS_DEFAULTS)


def resolve_turn_model(user, provider=None, model=None, domain=None) -> tuple:
    """(fournisseur, modèle) d'un tour — le fournisseur SE DÉRIVE du modèle, comme partout
    ailleurs dans WAMA (« le MODÈLE porte son moteur »).

    Ordre : ce que la SURFACE impose (API, test) > le RÉGLAGE durable de l'utilisateur > le
    TIRAGE « auto » commun (`auto_model.resolve_model_choice` : domaine déclaré par le schéma de
    l'assistant, curseur de qualité, VRAM libre, modèles distants que SES clés ouvrent).

    Catalogue muet (première installation, model_manager indisponible) : repli sur le chemin
    local historique, jamais une erreur — un assistant qui ne répond plus vaut moins qu'un
    assistant qui répond avec le modèle par défaut d'Ollama.
    """
    from wama.common.utils.auto_model import AUTO, is_auto, resolve_model_choice

    if model in _LEGACY_ROLES:
        model = None
    if provider:
        return provider, model
    reglages = assistant_settings(user)
    cle = model or reglages.get('model') or AUTO
    # Domaine de DÉVELOPPEMENT : BRIDÉ aux modèles de niveau dev (Fabien, 22/09) — le choix
    # manuel est respecté s'il a le niveau, remplacé sinon ; rien de disponible → (None, None),
    # que `run_assistant_turn` transforme en refus lisible, jamais en petit modèle.
    from wama.common.utils.assistant_skills import resolve_domain
    if resolve_domain(domain).development and user is not None:
        from wama.common.services.development_models import development_model
        key = development_model(user, requested=None if is_auto(cle) else cle)
        if not key:
            return None, None
        source, _, model_id = str(key).partition(':')
        return SOURCE_PROVIDERS.get(source, 'wama-dev-ai'), (model_id or None)
    if is_auto(cle):
        try:
            from wama.common.utils.assistant_skills import resolve_domain
            from wama.model_manager.services.cloud_models import allowed_cloud_keys
            # Le DOMAINE d'intervention déclare la compétence à privilégier (dev → 'coding') :
            # le tirage classe alors sur CE sous-indice de banc quand tout le lot le porte.
            family = resolve_domain(domain).benchmark_family or None
            cloud = allowed_cloud_keys(user)
            # Tour CONNECTÉ = tour OUTILLÉ : le tirage est borné au plancher de l'assistant
            # outillé (`development_models.AGENT_CODING_FLOOR`, 29/09) — sous lui, le modèle
            # annonce des tâches qu'il n'a pas lancées (mesuré sur Discord, 22, 23 et 27/09).
            floor = {}
            if user is not None:
                from wama.common.services.development_models import agent_candidates
                lot = agent_candidates(user, cloud_keys=cloud)
                if lot:
                    floor['candidates'] = lot
                else:
                    logger.warning("[ai_chat] aucun modèle au plancher de l'assistant outillé — "
                                   "tirage non borné, le contrôle de sortie reste seul garde")
            cle = resolve_model_choice(AUTO, app_id='assistant', requires=['completion'],
                                       quality_intent=reglages.get('quality_intent'),
                                       benchmark_family=family,
                                       cloud_keys=cloud, **floor) or ''
        except Exception:
            logger.debug('[ai_chat] tirage automatique indisponible', exc_info=True)
            cle = ''
    if not cle:
        return 'wama-dev-ai', None
    source, _, model_id = str(cle).partition(':')
    return SOURCE_PROVIDERS.get(source, 'wama-dev-ai'), (model_id or None)


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
                # `ERROR`/`error` retirés le 2026-09-18 : mesuré à zéro ligne sur les 18 modèles
                # portant un `status`. `failed` reste — c'est le vocabulaire vivant du Lab.
                failed  = model.objects.filter(user=user, status__in=['FAILURE', 'failed']).count()
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

#: Position NOMMÉE du curseur Rapide ↔ Qualité à partir de laquelle la RÉFLEXION du modèle
#: (`think`, Ollama) est demandée — la déclinaison à paliers commune (`preset_key_for_intent` :
#: fast 15 / balanced 50 / quality 85), pas un seuil de plus. MESURÉ le 2026-09-22 sur
#: `qwen3.5:4b` chaud, même message : 12,7 s avec réflexion (1 908 jetons dont 7 354 caractères
#: de « pensée » pour 244 de réponse) contre 2,4 s sans — ×5. Le défaut du curseur (50,
#: « balanced ») reste donc SANS réflexion ; qui pousse vers « Qualité » la retrouve. Vérifié le
#: même jour : un modèle SANS la capacité `thinking` (glm-ocr) accepte `think:false` sans erreur.
THINKING_PRESET = 'quality'


def thinking_wanted(quality_intent) -> bool:
    """La réflexion du modèle est-elle demandée pour ce réglage de curseur ?"""
    from wama.common.utils.auto_model import preset_key_for_intent
    try:
        return preset_key_for_intent(quality_intent) == THINKING_PRESET
    except Exception:
        return False


def _ollama_call(messages: list, ollama_model: str, think: bool = None, on_delta=None) -> tuple:
    """
    Low-level Ollama POST.

    `think` : None = défaut du modèle (réflexion ON pour les modèles qui la portent) ; False la
    coupe ; True la demande. Dérivé du curseur par `thinking_wanted`, jamais figé ici.

    `on_delta(fragment)` : si fourni, la réponse est demandée EN FLUX (`stream: True`) et chaque
    fragment est remis à l'appelant au fil de l'eau — levier 5 de `WAMA_LLM §1bis`. Sans lui,
    le corps est IDENTIQUE à ce qu'il était : un seul POST, une seule réponse. Ce défaut compte,
    car l'API v1 et la passerelle n'ont aucune raison de payer un flux qu'elles n'affichent pas.

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

    payload = {
        "model": ollama_model,
        "messages": messages,
        "options": {"temperature": 0.7, "num_predict": 4096},
        "stream": bool(on_delta),
    }
    if think is not None:
        payload["think"] = bool(think)
    try:
        if on_delta:
            return _ollama_stream(ollama_url, payload, on_delta)
        with httpx.Client(timeout=180.0, trust_env=False) as client:
            resp = client.post(ollama_url, json=payload)
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
        # Le RÉGLAGE (sans la réécriture WSL2) — c'est lui que l'utilisateur peut corriger.
        from wama.common.external_sources import base_url
        host_cfg = base_url('ollama')
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


def _ollama_stream(ollama_url: str, payload: dict, on_delta) -> tuple:
    """Un tour Ollama EN FLUX : les fragments partent à `on_delta` au fil de l'eau, et la
    fonction rend le même couple `(texte complet, usage)` que la voie synchrone — l'appelant
    n'a donc rien d'autre à changer, et la boucle à outils continue de raisonner sur un texte
    entier.

    ⚠ Le texte accumulé ici est le texte BRUT : c'est l'appelant qui décide ce qui s'AFFICHE
    (un appel d'outil et un bloc de réflexion n'ont rien à faire à l'écran) — cf. `_TokenGate`.
    """
    import httpx

    chunks, usage = [], {'input_tokens': 0, 'output_tokens': 0}
    with httpx.Client(timeout=180.0, trust_env=False) as client:
        with client.stream('POST', ollama_url, json=payload) as resp:
            if resp.status_code != 200:
                resp.read()
                return None, {'error': f'Ollama error: {resp.text}', 'status': resp.status_code}
            for line in resp.iter_lines():
                if not line:
                    continue
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:      # ligne partielle : Ollama émet un JSON par ligne
                    continue
                fragment = (data.get('message') or {}).get('content') or ''
                if fragment:
                    chunks.append(fragment)
                    on_delta(fragment)
                if data.get('done'):
                    usage = {'input_tokens': data.get('prompt_eval_count', 0),
                             'output_tokens': data.get('eval_count', 0)}
    return ''.join(chunks), usage


class _TokenGate:
    """Décide, AU FIL DE L'EAU, ce qu'un fragment a le droit de montrer à l'écran.

    Trois choses arrivent par le même canal et une seule doit s'afficher :
      • la RÉFLEXION du modèle (`<think>…</think>`) — elle vaut 7 354 caractères pour 244 de
        réponse sur un tour mesuré : l'afficher noierait la réponse ;
      • un APPEL D'OUTIL (`{"tool": …}`) — c'est un ordre, pas une phrase ; l'afficher ferait
        lire du JSON à l'utilisateur, puis disparaître ;
      • la RÉPONSE, la seule attendue.

    ⚠ La décision doit se prendre SANS attendre la fin, sinon il n'y a plus de flux. D'où
    l'attente prudente au DÉBUT de chaque itération : tant que le premier caractère utile n'est
    pas connu, on retient. Un `{` ouvre un appel d'outil et ferme le robinet pour cette
    itération entière ; tout autre caractère l'ouvre définitivement. C'est décidable sur UN
    caractère, et c'est ce qui rend le filtre possible en flux.
    """

    def __init__(self, emit):
        self._emit = emit
        self._buffer = ''
        self._decided = False
        self._muted = False
        self._in_think = False

    def feed(self, fragment: str) -> None:
        self._buffer += fragment
        if self._in_think:
            fin = self._buffer.find('</think>')
            if fin < 0:
                return
            self._buffer = self._buffer[fin + len('</think>'):]
            self._in_think = False
        if not self._decided:
            rest = self._buffer.lstrip()
            if rest.startswith('<think>'):
                self._in_think = True
                self._buffer = rest[len('<think>'):]
                return self.feed('')
            # `<` seul peut être le début de `<think>` : on attend d'en savoir plus.
            if not rest or (rest[0] == '<' and not rest.startswith('<think>')
                            and len(rest) < len('<think>')):
                return
            self._decided = True
            self._muted = rest[0] == '{'
            self._buffer = rest
        if self._muted or not self._buffer:
            return
        self._emit(self._buffer)
        self._buffer = ''

    def close(self) -> None:
        """Fin d'itération : ce qui restait en attente part, sauf si l'itération était muette."""
        if self._decided and not self._muted and self._buffer:
            self._emit(self._buffer)
        self._buffer = ''


def _claude_code_call(messages: list, user=None) -> tuple:
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

    ⚠ DEUX jeux d'outils se superposent sur ce chemin, et c'est à connaître. La boucle
    agentique de `run_assistant_turn` reste CÂBLÉE pour tous les fournisseurs — le prompt
    d'outils est injecté et un appel émis serait exécuté. Mais Claude Code a DÉJÀ tourné sa
    propre boucle (avec SES outils : lecture du dépôt) et rend un texte final ; rien ne
    garantit qu'il émette en plus le format d'appel attendu par WAMA. Un « ajoute ce fichier
    à l'imager » est donc à adresser au fournisseur local ou `claude`, non parce que les
    outils manquent, mais parce que ce chemin-ci n'est pas fait pour eux.
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
        resultat = demander('\n\n'.join(morceaux), user=user)
    except ClaudeCodeIndisponible as e:
        return None, {'error': str(e), 'status': 503}

    if not resultat.get('success'):
        return None, {'error': resultat.get('error', 'échec inconnu'), 'status': 502}

    # `cost_usd` est un ÉQUIVALENT-API rapporté par le CLI, PAS un débit : sur abonnement la
    # dépense s'impute au crédit inclus. Remonté quand même — c'est le bon indicateur
    # RELATIF pour comparer deux tâches, et le seul signal que ce chemin n'est pas gratuit.
    return resultat.get('texte', ''), {'input_tokens': 0, 'output_tokens': 0,
                                       'cost_usd': resultat.get('cout_usd')}


def _llm_call(messages: list, llm_model: str | None, provider: str, user=None,
              think: bool = None, on_delta=None) -> tuple:
    """
    Un tour de LLM, quel que soit le fournisseur.

    Chemin local (`wama-dev-ai`/`ollama`) : `_ollama_call` — usage tokens compris ; `think`
    (réflexion du modèle) n'a de sens que là et vient du curseur de l'utilisateur.
    Chemin cloud : `llm_chat()` (LiteLLM, brique commune) — le modèle par défaut du fournisseur
    vient de `llm_chat` (jamais figé ici). L'usage n'est pas remonté par `llm_chat` (contrat
    (text, err)) → compté à 0, assumé tant que le besoin ne l'exige pas.

    Clé d'un fournisseur déclaré dans `external_sources` (Albert, API Anthropic) : celle de
    l'UTILISATEUR, jamais la clé d'instance du `.env` (décision de Fabien du 15/09 — quotas
    répartis) ; l'abonnement suit la même règle (jeton personnel, `claude_code.demander`). Sans
    utilisateur (`user=None`), la clé d'instance sert. Les fournisseurs sans source déclarée
    (OpenAI…) lisent encore l'environnement.

    Returns:
        (text, usage_dict) on success · (None, error_dict) on failure
    """
    if provider in _LOCAL_PROVIDERS:
        # ⚠ Le FLUX n'existe que sur le chemin LOCAL : `llm_chat` (LiteLLM) rend un texte
        # entier, et l'abonnement Claude Code lance un process qui finit avant de parler. Un
        # tour cloud reste donc synchrone, et la surface le sait (elle affiche son attente).
        return _ollama_call(messages, llm_model, think=think, on_delta=on_delta)

    if provider in _SUBSCRIPTION_PROVIDERS:
        return _claude_code_call(messages, user=user)

    from wama.common import external_sources
    from wama.common.utils.llm_utils import llm_chat
    llm_provider = _PROVIDER_ALIAS.get(provider, provider)
    api_key = None
    # Fournisseur DÉCLARÉ (source `llm` : Albert, API Anthropic…) → clé personnelle exigée.
    source = external_sources.by_key().get(llm_provider)
    # ⚠ Un fournisseur NON déclaré (`openai`, `mistral`…) n'a ni clé personnelle ni garde « 100 %
    # local » : pour un utilisateur, LiteLLM se serait replié sur la clé d'instance de
    # l'environnement (trou mesuré par la cartographie du 15/09, atteignable par l'API v1). Il est
    # refusé ; sans utilisateur (rôles en ligne de commande), le chemin d'instance reste ouvert.
    if (user is not None and getattr(user, 'is_authenticated', False)
            and (source is None or source.kind != 'llm')):
        return None, {'error': f"Fournisseur « {provider} » non déclaré dans WAMA : choisissez un "
                               "fournisseur proposé par le sélecteur.", 'status': 400}
    if (source and source.kind == 'llm' and user is not None
            and getattr(user, 'is_authenticated', False)):
        from wama.accounts.api_keys import key_for
        from wama.model_manager.services.cloud_models import allowed_cloud_keys, cloud_refusal
        refus = cloud_refusal(user)
        if refus:
            return None, {'error': refus, 'status': 403}
        # Un modèle NOMMÉ doit être ouvert par la clé de CET utilisateur (découverte).
        if llm_model and f"{source.key}:{llm_model}" not in allowed_cloud_keys(user, automatic=False):
            return None, {'error': f"Le modèle « {llm_model} » n'est pas ouvert par votre clé "
                                   f"{source.label}.", 'status': 403}
        api_key = key_for(user, source.key)
        if not api_key:
            return None, {'error': f"Aucune clé d'API {source.label} dans votre profil : "
                                   "ajoutez-la dans le volet « Clés d'API » de la page Profil.",
                          'status': 400}
    text, err = llm_chat(
        messages,
        model=llm_model,
        provider=llm_provider,
        num_predict=4096,
        timeout=180.0,
        api_key=api_key,
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


#: URL ou chemin média dans une réponse. S'arrête aux délimiteurs Markdown pour ne pas
#: avaler la parenthèse fermante d'un `[libellé](url)`.
_URL_IN_TEXT = re.compile(r'(?:https?://|/media/)[^\s)\]>"\'`]+')
#: Ce qui remplace un lien dont aucun outil n'a parlé. DIT, jamais effacé en silence.
_UNSOURCED_MARK = '(lien non vérifié — retiré)'


def _strip_unsourced_urls(text: str, tool_steps: list, message: str = '',
                          removed: list = None) -> str:
    """Retire d'une réponse les URL dont AUCUN résultat d'outil de ce tour n'a parlé.

    ⚠⚠ POURQUOI UN CONTRÔLE, ET PAS UNE RÈGLE DE PROMPT (mesuré le 2026-09-23, DEUX FOIS).
    Le modèle local a annoncé une anonymisation « terminée avec succès » avec un lien
    `https://example.com/output/…` inventé — puis a RECOMMENCÉ après l'ajout de la règle
    « NEVER INVENT A LINK », dans un tour SANS AUCUN appel d'outil. La cause est mécanique :
    ses propres fabrications sont dans l'historique du fil, qui lui est resservi à chaque
    tour, et un modèle de 4 milliards de paramètres imite ce qu'il lit. *Une règle de prompt
    ne défait pas un exemple que l'on remet sous les yeux du modèle.*

    LES SOURCES ADMISES sont donc les résultats d'outils DE CE TOUR et le message de
    l'utilisateur — **jamais l'historique**, qui est précisément ce qui recycle le mensonge.
    Un lien légitime d'un tour précédent est retiré aussi : le remède est à portée du modèle
    (rappeler l'outil de statut), et dans un canal c'est la PIÈCE JOINTE qui compte.

    ⚠ Ne touche pas au reste du texte : le libellé d'un lien Markdown est conservé.

    `removed` : liste que l'appelant fournit pour RECEVOIR les URL retirées — c'est le signal
    du contrôle de tour inventé (`_invented_turn`), qui ne se lit pas dans le texte rendu.
    """
    if not text:
        return text
    sources = json.dumps(tool_steps or [], ensure_ascii=False) + '\n' + (message or '')

    if removed is None:
        removed = []

    def _known(url):
        return url.rstrip('.,;:!?') in sources or url in sources

    def _in_markdown(match):
        label, url = match.group(1), match.group(2)
        if _known(url):
            return match.group(0)
        removed.append(url)
        return f'{label} {_UNSOURCED_MARK}'.strip()

    def _bare(match):
        url = match.group(0)
        if _known(url):
            return url
        removed.append(url)
        return _UNSOURCED_MARK

    text = re.sub(r'\[([^\]]*)\]\((' + _URL_IN_TEXT.pattern + r')\)', _in_markdown, text)
    text = _URL_IN_TEXT.sub(_bare, text)
    if removed:
        logger.warning("[ai_chat] %d lien(s) sans source retiré(s) de la réponse : %s",
                       len(removed), ', '.join(removed[:5]))
    return text


#: Ce que dit un tour inventé qu'aucun modèle plus fort ne peut reprendre. Remplace TOUTE la
#: réponse : un « c'est terminé » sans outil est faux en entier, pas seulement son lien.
_INVENTED_TURN_NOTICE = (
    "⚠ Je n'ai exécuté aucune action pendant ce tour : ma réponse citait un résultat qu'aucun "
    "outil n'a produit, elle a donc été retirée. Reformulez la demande (par exemple « lance "
    "l'anonymisation de ce fichier » ou « donne-moi le statut »), ou choisissez un modèle plus "
    "capable dans les réglages de l'assistant.")


def _invented_turn(user, message, *, provider, llm_model, local, etiquette, total_usage,
                   history, domain, surface, on_event, escalated_from):
    """Un tour SANS AUCUN appel d'outil dont la réponse citait un résultat (lien retiré par
    `_strip_unsourced_urls`) : le modèle a INVENTÉ une action. Contrôle, pas consigne (29/09).

    ⚠⚠ LE DÉFAUT MESURÉ (Discord, 27/09, fil 11). `qwen3.5:4b`, trois tours, zéro outil :
    « je lance », « la tâche 648 est terminée », un lien. Le filtre retirait bien le lien, mais
    le RESTE de la réponse partait — un faux « terminé » suivi d'un libellé mort, que
    l'utilisateur a pris pour un lien de téléchargement cassé. Retirer l'adresse ne suffit pas
    quand c'est la phrase entière qui est fausse.

    Le signal est MESURÉ, pas deviné dans la langue : aucun `tool_step` ET un lien sans source.
    Un tour sans outil qui ne cite aucun résultat (« bonjour », une explication) n'est pas visé.

    Remède, dans cet ordre : reprendre UNE fois le tour avec un modèle plus fort
    (`development_models.escalation_model`) ; sans lui, ou si la reprise invente aussi,
    dire qu'aucune action n'a été exécutée — jamais relayer la fabrication.
    """
    from wama.common.services.development_models import escalation_model

    source = 'ollama' if local else PROVIDER_SOURCES.get(provider, provider)
    current_key = f'{source}:{llm_model}' if llm_model else None
    logger.warning("[ai_chat] tour inventé (aucun outil, résultat cité) par %s%s",
                   etiquette, f" — reprise de {escalated_from}" if escalated_from else '')

    key = escalation_model(user, current_key) if escalated_from is None else None
    if key:
        src, _, model_id = str(key).partition(':')
        if on_event is not None:
            # Le web a déjà affiché la fabrication en flux : on DIT la reprise ; l'événement
            # `done` remplace ensuite la bulle par la réponse reprise.
            on_event({'type': 'delta',
                      'text': f"\n\n_⟳ Réponse sans source — reprise avec {model_id}…_\n\n"})
        retry = run_assistant_turn(user, message, provider=SOURCE_PROVIDERS.get(src, 'wama-dev-ai'),
                                   model=model_id or None, history=history, domain=domain,
                                   surface=surface, on_event=on_event, escalated_from=etiquette)
        if 'error' not in retry:
            usage = retry.setdefault('usage', {})
            for k, v in total_usage.items():
                usage[k] = (usage.get(k) or 0) + (v or 0)
            retry['model'] = f"{retry.get('model', '')} · repris"
            retry.setdefault('invented_by', etiquette)
            return retry
        logger.warning("[ai_chat] reprise impossible (%s) — aveu", retry.get('error'))

    return {
        'success': True,
        'response': _INVENTED_TURN_NOTICE,
        'model': etiquette,
        'usage': total_usage,
        'tool_steps': [],
        'invented_by': etiquette,
    }


def _parse_tool_call(text: str) -> dict | None:
    """
    Detect a JSON tool call in the LLM response.

    Expected format (on any line):
        {"tool": "tool_name", "args": {...}}

    Returns parsed dict or None.
    """
    # Strip reasoning tags first
    clean = _strip_think_tags(text)
    # Un DÉCODEUR JSON à partir de chaque `{"tool"` — pas un motif. Jusqu'au 2026-09-30 le motif
    # interdisait les accolades IMBRIQUÉES dans `args` (`\{[^{}]*\}`) : un outil dont un argument
    # est un objet — `dev_run_role(args={"catalog": …})`, la chaîne d'intégration de modèles — n'était
    # JAMAIS reconnu, et l'appel revenait à l'utilisateur comme du texte (vécu sur Albert).
    decoder = json.JSONDecoder()
    for start in re.finditer(r'\{\s*"tool"\s*:', clean):
        try:
            call, _ = decoder.raw_decode(clean, start.start())
        except json.JSONDecodeError:
            continue
        if isinstance(call, dict) and isinstance(call.get('tool'), str) \
                and isinstance(call.get('args'), dict):
            return call
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
                         provider: str = None, model: str = None,
                         domain: str = None, on_event=None) -> dict:
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
        # Le fil SE SOUVIENT d'un domaine de DÉVELOPPEMENT chargé (bridage, 22/09) : la surface
        # n'a rien à redire, et le tour suivant reste au niveau dev. Les autres domaines ne
        # collent pas — leur contexte (RAG) se paie à chaque tour, le modèle le recharge s'il
        # en a besoin.
        if domain is None:
            from wama.common.utils.assistant_skills import resolve_domain
            remembered = conversation_store.last_loaded_domain(fil)
            if remembered and resolve_domain(remembered).development:
                domain = remembered
    except Exception:
        logger.exception("[ai_chat] store de conversation indisponible — tour sans historique")

    resultat = run_assistant_turn(user, message, provider=provider, model=model,
                                  history=historique, domain=domain, surface=surface,
                                  on_event=on_event)

    if fil is not None and 'error' not in resultat:
        try:
            conversation_store.record_exchange(fil, message, resultat)
            resultat['conversation_id'] = fil.pk
        except Exception:
            logger.exception("[ai_chat] échange non enregistré (fil %s)", fil.pk)

    return resultat


def run_assistant_turn(user, message: str, provider: str = None,
                       model: str = None, history: list = None,
                       domain: str = None, surface: str = 'web', on_event=None,
                       escalated_from: str = None) -> dict:
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
        provider: imposé par la surface ('albert', 'claude', 'claude-abo'…) ou None — dans ce cas
                  il se DÉRIVE du modèle choisi (réglage de l'utilisateur, sinon tirage « auto »).
        model:    modèle du fournisseur, ou None. Un ancien rôle de chat ('fast', 'dev'…) vaut
                  « auto » (`_LEGACY_ROLES`).
        history:  Tours précédents [{role, content}] — fournis par le client ; assainis ici.
        domain:   Domaine d'intervention (`assistant_skills.DOMAINES` : 'general', 'science',
                  'design', 'dev'). Détermine le skill de RÔLE injecté au prompt système et,
                  pour les domaines qui le déclarent, le rappel du contexte de laboratoire.
        surface:  D'où vient le tour ('web', 'api', 'discord'…). Le moteur reste le même ;
                  seule change la consigne sur CE QUE LA SURFACE SAIT FAIRE de la réponse —
                  un canal joint les fichiers produits, un client web suit des liens.
        escalated_from: INTERNE — étiquette du tour inventé que celui-ci reprend
                  (`_invented_turn`) ; interdit une seconde reprise.

    Returns:
        dict succès : {success, response, model, usage, tool_steps}
        dict erreur : {error, status}
    """
    from wama.tool_api import execute_tool, build_tools_list

    # Le fournisseur se DÉRIVE du modèle (réglage durable de l'utilisateur, sinon tirage « auto »)
    # quand la surface n'impose rien : c'est ce qui donne le MÊME choix au web, à l'API et aux
    # canaux, sans qu'aucune surface ne porte de réglage propre.
    provider, llm_model = resolve_turn_model(user, provider, model, domain=domain)
    from wama.common.utils.assistant_skills import resolve_domain
    development = resolve_domain(domain).development
    if provider is None:
        # Seul cas : domaine de développement sans modèle de niveau dev — on le DIT.
        from wama.common.services.development_models import development_refusal
        return {'error': development_refusal(user), 'status': 503}

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

    # Inject current WAMA queue state into system prompt (when user is known)
    wama_context = _build_wama_context(user) if user else ""
    # Liste des outils GÉNÉRÉE depuis le registre tool_api (source unique → exhaustive,
    # avatarizer/composer/converter inclus). Le préambule + règles restent rédigés à la main.
    # Outils de DÉVELOPPEMENT (2026-09-22) : annoncés en plus à un développeur, RELAYÉS à la
    # surface MCP « wama-dev » (process séparé, §16) par `mcp_client` — vide pour tout autre
    # compte ou sans serveur dev. Le nom est le seul lien : `dev_*` part au relais, le reste à
    # la porte `execute_tool`. Un nom `dev_*` que personne n'a annoncé arrive à la porte, qui le
    # refuse comme inconnu : un non-développeur ne peut pas y appeler quoi que ce soit.
    dev_tools = []
    if user:
        from wama.common.services import mcp_client
        dev_tools = mcp_client.dev_tools_for(user)
    dev_names = {t['name'] for t in dev_tools}
    tools_prompt = (WAMA_TOOLS_PROMPT.replace('{TOOLS}', build_tools_list()
                                              + mcp_client.tools_block(dev_tools))
                    if user else "")
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

    # ORDRE : le FIXE d'abord (base, rôle, annonce, outils — ~12 000 caractères identiques d'un
    # tour à l'autre), le DYNAMIQUE en queue (contexte labo, état des files). Ollama réutilise
    # le cache KV sur le PRÉFIXE commun des jetons : jusqu'au 2026-09-22 l'état des files
    # (56 caractères, changeant) précédait le bloc d'outils, et un seul item en plus dans une
    # file forçait la ré-évaluation de ~3 000 jetons de prompt (mesuré, WAMA_LLM §1bis).
    # La consigne de SURFACE est FIXE pour un fil donné (un canal ne devient pas le web en
    # cours de conversation) : elle se place donc avec le bloc fixe, avant le dynamique.
    surface_prompt = (CHANNEL_FILES_PROMPT.replace('{SURFACE}', surface)
                      if user and surface_attaches_files(surface) else '')

    system_prompt = (WAMA_SYSTEM_PROMPT.replace('{LANGUE}', langue)
                     + (f"\n\n{role}" if role else '')
                     + annonce + tools_prompt.replace('{LANGUE}', langue)
                     + surface_prompt
                     + contexte_labo + wama_context)

    # Réflexion du modèle (chemin local) DÉRIVÉE du curseur Rapide ↔ Qualité de l'utilisateur —
    # le même réglage que le tirage automatique lit (`resolve_turn_model`). En domaine de
    # développement le curseur vaut 100 (bridage) : réflexion demandée.
    from wama.common.services.development_models import DEV_QUALITY_INTENT
    quality = DEV_QUALITY_INTENT if development else assistant_settings(user).get('quality_intent')
    think = thinking_wanted(quality) if local else None

    def _label(provider, llm_model, local):
        base_label = f"wama-dev-ai ({llm_model})" if local else f"{provider} ({llm_model or 'défaut'})"
        # « · dev » : le bridage est VISIBLE — l'utilisateur voit que le tour est passé au
        # modèle de niveau développement (demande de Fabien : le rendre explicite).
        return f"{base_label} · dev" if development else base_label

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

    etiquette = _label(provider, llm_model, local)
    tool_steps = []
    # `cost_usd` accumulé aussi : sans lui, l'équivalent-API rendu par le chemin abonnement
    # était calculé puis JETÉ (mesuré le 31/08 en revérification) — la docstring de
    # `_claude_code_call` promettait de le remonter, aucune surface ne pouvait l'afficher.
    # Reste à 0 pour les autres fournisseurs, qui ne rapportent pas de coût.
    total_usage = {'input_tokens': 0, 'output_tokens': 0, 'cost_usd': 0.0}
    MAX_TOOL_ITERATIONS = 5

    for _ in range(MAX_TOOL_ITERATIONS):
        # FLUX (levier 5) : un portier par itération — il ne laisse passer ni la réflexion du
        # modèle ni un appel d'outil, qui arrivent par le même canal que la réponse.
        gate = None
        if on_event is not None and local:
            gate = _TokenGate(lambda fragment: on_event({'type': 'delta', 'text': fragment}))
        text, result = _llm_call(messages, llm_model, provider, user=user, think=think,
                                 on_delta=(gate.feed if gate else None))
        if gate is not None:
            gate.close()
        if text is None:
            return result  # error dict

        # Accumulate token usage
        total_usage['input_tokens']  += result.get('input_tokens', 0)
        total_usage['output_tokens'] += result.get('output_tokens', 0)
        total_usage['cost_usd']      += result.get('cost_usd') or 0.0

        # Detect tool call in response
        tool_call = _parse_tool_call(text) if user else None

        if not tool_call:
            # No tool call → this is the final answer
            # Strip any remaining reasoning tags from the displayed response
            # Contrôle de SOURCE des liens : ce que le prompt demande, la sortie le VÉRIFIE
            # (les fabrications du fil sont resservies au modèle à chaque tour).
            removed = []
            clean_text = _strip_unsourced_urls(_strip_think_tags(text), tool_steps, message,
                                               removed=removed)
            if removed and not tool_steps and user is not None:
                return _invented_turn(user, message, provider=provider, llm_model=llm_model,
                                      local=local, etiquette=etiquette, total_usage=total_usage,
                                      history=history, domain=domain, surface=surface,
                                      on_event=on_event, escalated_from=escalated_from)
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

        if tool_name in dev_names:
            tool_result = mcp_client.call_dev_tool(user, tool_name, tool_args)
        else:
            tool_result = execute_tool(tool_name, tool_args, user)
            # Le curseur de l'assistant vaut pour les tâches qu'il lance (Fabien, 22/09) — et
            # le résultat le DIT (`quality_level`), pour que le modèle le dise à l'utilisateur.
            try:
                from wama.tool_api import relay_quality_intent
                tool_result = relay_quality_intent(user, tool_name, tool_result)
            except Exception:
                logger.debug("[ai_chat] relais du curseur impossible", exc_info=True)
            # Un AJOUT ne lance rien : le résultat le DIT (23/09). Sans ce rappel, le modèle
            # lit `status: queued` comme « c'est parti » et annonce une tâche qui dort.
            try:
                from wama.tool_api import relay_next_step
                tool_result = relay_next_step(tool_name, tool_result)
            except Exception:
                logger.debug("[ai_chat] relais de l'étape suivante impossible", exc_info=True)

        # BASCULE EN COURS DE TOUR (22/09) : le tour a commencé sur le modèle du curseur, et le
        # modèle vient de charger la compétence dev ou d'appeler un outil de dev — la SUITE du
        # tour (et le fil, cf. `conversation_store.last_loaded_domain`) passe au niveau
        # développement. Sans modèle de ce niveau, l'outil le dit au modèle, qui le dit à
        # l'utilisateur ; on ne continue jamais « comme si ».
        from wama.common.services.development_models import (
            development_model, development_refusal, is_development_step)
        if (not development and user is not None
                and is_development_step({'tool': tool_name, 'args': tool_args})):
            key = development_model(user)
            if key:
                source, _, model_id = str(key).partition(':')
                provider, llm_model = SOURCE_PROVIDERS.get(source, 'wama-dev-ai'), (model_id or None)
                local = provider in _LOCAL_PROVIDERS
                development = True
                think = thinking_wanted(DEV_QUALITY_INTENT) if local else None
                etiquette = _label(provider, llm_model, local)
                logger.info("[ai_chat] passage au niveau développement : %s", etiquette)
            elif isinstance(tool_result, dict):
                tool_result = dict(tool_result, warning=development_refusal(user))
        tool_steps.append({'tool': tool_name, 'args': tool_args, 'result': tool_result})
        if on_event is not None:
            # L'étape part DÈS qu'elle est jouée : « ce qui est pénible n'est pas d'attendre,
            # c'est d'attendre sans savoir » (`WAMA_HARNESS §9 chantier 4`).
            on_event({'type': 'step', 'step': tool_steps[-1]})

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
        'response': _strip_unsourced_urls(_strip_think_tags(last_text), tool_steps, message),
        'model': etiquette,
        'usage': total_usage,
        'tool_steps': tool_steps,
    }
