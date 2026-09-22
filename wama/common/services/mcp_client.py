"""
Client MCP du moteur de l'assistant — la surface « wama-dev » vue DEPUIS l'assistant
(ROADMAP §8d Phase 3, étape 5, moitié « outils de dev » ; demande de Fabien du 2026-09-22 :
« améliorer WAMA depuis l'assistant, sans forcément passer par Claude, uniquement pour les
rôles admin et dev »).

POURQUOI UN CLIENT, ET PAS UN IMPORT. Les outils de développement (rôles wama-dev-ai, bac à
sable d'apps) vivent dans un process SÉPARÉ — `dev_tools.py`, servi par
`run_mcp_server --surface dev` — et la règle §16 les tient HORS du process de prod. L'assistant,
lui, tourne dans le process de prod. Pour qu'un développeur puisse lui demander « propose la glu
du reader dans une jumelle » avec un modèle LOCAL, l'assistant devient CLIENT MCP de cette
surface : il RELAIE, il ne charge rien. La porte reste celle du serveur dev — droits vérifiés à
chaque appel (`is_developer`), arguments admis déclarés par rôle, sandbox sur jumelles seulement,
propositions écrites dans `wama-dev-ai/outputs/` et JAMAIS appliquées.

CE QUE CE MODULE NE FAIT PAS : décider qui est développeur (le prédicat `is_developer` n'est
appelé ici que pour ne pas ouvrir une connexion inutile — le serveur REVÉRIFIE) ; exécuter quoi
que ce soit en local ; importer `dev_tools` (§16, gardé par `tests_mcp_client`).

FAIL-SAFE : serveur absent ou injoignable → aucun outil de dev annoncé, l'assistant répond quand
même (un assistant muet parce qu'un service optionnel dort serait le pire défaut). Une session
par opération : le moteur est sans état et un tour dure des secondes ; la LISTE est gardée
quelques instants par process pour ne pas payer une connexion à chaque tour.

Identité : le jeton d'API DRF du compte — le même que `/api/v1/` et que tout client MCP
(`mcp_server.user_for_token`). Créé à la demande s'il n'existe pas encore, comme le fait la page
de profil.
"""
from __future__ import annotations

import json
import logging
import time

logger = logging.getLogger(__name__)

#: Préfixe des outils de la surface dev (`dev_tools.DEV_TOOLS`) — c'est à lui que la boucle de
#: l'assistant reconnaît un appel à relayer plutôt qu'à passer à `execute_tool`.
DEV_TOOL_PREFIX = 'dev_'
#: Délai de connexion : un serveur dev absent doit coûter au plus ce temps-là, une fois par cache.
CONNECT_TIMEOUT_S = 5
#: Durée de garde de la liste d'outils par compte (secondes) — elle ne change qu'au déploiement.
LIST_CACHE_S = 60

_list_cache: dict = {}   # user.pk → (expiration monotonic, liste)


def is_dev_tool(name: str) -> bool:
    return bool(name) and str(name).startswith(DEV_TOOL_PREFIX)


def dev_surface_url() -> str:
    """Adresse de l'endpoint MCP de la surface dev — le registre des sources externes fait foi."""
    from wama.common.external_sources import base_url
    from wama.common.services.mcp_server import MCP_PATH
    return base_url('wama_mcp_dev').rstrip('/') + MCP_PATH


def _api_key(user) -> str:
    from rest_framework.authtoken.models import Token
    return Token.objects.get_or_create(user=user)[0].key


def _run(user, action):
    """Exécute `action(session)` dans une session MCP ouverte pour `user` — synchrone pour
    l'appelant (le moteur tourne dans une vue Django). Point d'injection des tests, qui y
    branchent une session en mémoire sur le vrai serveur de la surface dev.

    ⚠ L'ORM (jeton) est lu AVANT la boucle asyncio : Django refuse l'ORM en contexte async."""
    import anyio

    key = _api_key(user)
    url = dev_surface_url()

    async def main():
        import httpx
        from mcp import ClientSession
        from mcp.client.streamable_http import streamablehttp_client

        # ⚠ Client HTTP SANS l'environnement (`trust_env=False`) : la surface dev est une source
        # LOCALE (`external_sources`, scope LOCAL), et le client par défaut du SDK lit les
        # variables de proxy — mesuré le 2026-09-22 : le proxy de l'université répondait 503 à
        # `127.0.0.1:8771` et l'assistant concluait « aucun outil de dev ». Même geste que le
        # `trust_env=False` des appels Ollama (`llm_utils`) — c'est l'équivalent httpx de
        # `proxies_for()` pour un service local.
        def local_client(headers=None, timeout=None, auth=None):
            return httpx.AsyncClient(headers=headers, timeout=timeout, auth=auth,
                                     trust_env=False, follow_redirects=True)

        async with streamablehttp_client(url, headers={'Authorization': f'Bearer {key}'},
                                         timeout=CONNECT_TIMEOUT_S,
                                         httpx_client_factory=local_client) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                return await action(session)

    return anyio.run(main)


def dev_tools_for(user) -> list:
    """Outils de développement que l'assistant peut ANNONCER à `user` :
    `[{'name', 'description', 'args'}]` — vide pour un non-développeur, ou sans serveur dev.

    La description est le docstring complet de l'outil, sur une ligne : c'est elle qui dit au
    modèle les actions et arguments admis (`create app=…`, `role : librarian (dist | repo)…`)."""
    from wama.accounts.permissions import is_developer

    if user is None or not is_developer(user):
        return []
    now = time.monotonic()
    cached = _list_cache.get(user.pk)
    if cached and cached[0] > now:
        return cached[1]

    async def action(session):
        return (await session.list_tools()).tools

    try:
        tools = [{'name': t.name,
                  'description': ' '.join((t.description or '').split()),
                  'args': list(((t.inputSchema or {}).get('properties') or {}).keys())}
                 for t in _run(user, action)]
    except Exception:
        logger.debug("[mcp_client] surface dev injoignable à %s — aucun outil de développement "
                     "annoncé", dev_surface_url(), exc_info=True)
        tools = []
    _list_cache[user.pk] = (now + LIST_CACHE_S, tools)
    return tools


def tools_block(tools: list) -> str:
    """Bloc de prompt des outils de dev — MÊME forme que `tool_api.build_tools_list`
    (`- nom(args): description`), précédé de ce qu'un modèle doit savoir de cette surface."""
    if not tools:
        return ''
    lines = [
        '',
        "Development tools (the user is a WAMA developer; these run in the separate development "
        "surface): a role writes a PROPOSAL awaiting human validation and never applies it; the "
        "sandbox only touches twin apps (<app>_NN), never the original app. Launches are "
        "background jobs — follow them with dev_job_status and read proposals with "
        "dev_read_output. Report the job id and what the developer should check.",
    ]
    for t in tools:
        lines.append(f"- {t['name']}({', '.join(t.get('args') or [])}): {t.get('description', '')}")
    return '\n'.join(lines)


def call_dev_tool(user, name: str, arguments) -> dict:
    """Relaie UN appel d'outil de dev à la surface, et rend son résultat comme `execute_tool`
    (un dict ; une erreur porte `error`). Jamais d'exception : une surface qui tombe en cours
    de tour devient un résultat d'outil lisible par le modèle."""
    async def action(session):
        return await session.call_tool(name, dict(arguments or {}))

    try:
        result = _run(user, action)
    except Exception as e:
        return {'error': f"Surface de développement injoignable ({dev_surface_url()}) : {e}"}
    if getattr(result, 'structuredContent', None) is not None:
        return result.structuredContent
    text = ''.join(getattr(c, 'text', '') or '' for c in (result.content or []))
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else {'result': parsed}
    except ValueError:
        return {'error': text or 'erreur inconnue'} if result.isError else {'result': text}
