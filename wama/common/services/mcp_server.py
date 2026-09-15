"""
Serveur MCP de WAMA — l'adaptateur MINCE au-dessus de `tool_api`.

POURQUOI (2026-09-15, décision de Fabien : « interagir de la même manière, qu'il s'agisse d'un
modèle local Ollama, de Claude Code, d'Albert ou de n'importe quel autre cloud ») : l'assistant
avait UN moteur et UN registre d'outils, mais chaque cerveau y accédait à sa façon — boucle JSON
dans le prompt pour Ollama et LiteLLM, rien pour Claude Code, qui tourne sa propre boucle avec
SES outils (`assistant_engine._claude_code_call`). MCP est la norme officielle d'outils : un
serveur, et tout client — Claude Code, un IDE, le moteur de l'assistant — voit les MÊMES outils
sous le MÊME contrat.

CE QUI ÉTAIT DÉJÀ TRANCHÉ, ET QUE CE MODULE APPLIQUE (ne pas le redécouvrir) :
  • ROADMAP §16 : « MCP = exposer `tool_api` existant, PAS un protocole maison » ; les outils de
    dev/admin vivent dans un serveur SÉPARÉ, jamais chargés dans le process de prod ;
  • ROADMAP §8d Phase 3 : SDK Python officiel `mcp`, installé par la route `library`
    (`manifests/libraries/mcp.json`, avec `constraints.pip` pour garder starlette) ;
  • REPRISE du 2026-08-04 : « adaptateur mince sur TOOL_REGISTRY, dont `tool_descriptions()`
    dérive déjà nom/description/schéma ».

CE QU'IL FAIT, ET RIEN D'AUTRE :
  • `tools/list` → `TOOL_REGISTRY` filtré par `tool_accessible` (le filtre de `/api/v1/tools/`),
    description = `tool_descriptions()`, arguments = `tool_input_schema()` ;
  • `tools/call` → `execute_tool`, LA porte unique (gating F7, coercition, bornes de choix) ;
  • identité → le jeton d'API DRF du compte (le même que `/api/v1/`, affiché sur la page de
    profil). Un client MCP agit pour UN compte, exactement comme un script qui appelle l'API.

⚠ AUCUNE validation ni aucun gating n'est recopié ici. La validation d'entrée du SDK est même
COUPÉE (`validate_input=False`) : elle refuserait `"3"` pour un nombre, que `execute_tool`
coerce en 3. Deux portes qui ne disent pas la même chose finissent par diverger.
"""
from __future__ import annotations

import json
import logging
from contextlib import asynccontextmanager
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

#: Nom du serveur « prod » : les outils de `tool_api`. Les outils de dev/admin sont un AUTRE
#: serveur, dans un autre process (ROADMAP §16) — jamais une option de celui-ci.
SERVER_NAME = 'wama'
#: Portée posée sur un jeton vérifié. Un seul niveau : le compte, avec ses droits d'app.
SCOPE = 'wama'
#: Chemin de l'endpoint HTTP streamable.
MCP_PATH = '/mcp'
#: Variable portant le jeton d'API en transport stdio (le client lance le process lui-même).
TOKEN_ENV = 'WAMA_MCP_TOKEN'

INSTRUCTIONS = (
    "Outils de WAMA, la plateforme média/IA du laboratoire : déposer un fichier dans une app, "
    "lancer un traitement, suivre sa progression, lire un résultat, interroger le catalogue de "
    "modèles et la mémoire. Chaque outil agit pour le compte dont le jeton a ouvert la session, "
    "avec ses droits."
)


# ── Exécution synchrone (ORM Django) hors de la boucle asyncio ──────────────────────────────

async def _run_sync(fn):
    """Exécute `fn` (ORM, bloquant) dans un thread. Point d'injection des tests (exécution en
    ligne, pour rester dans la transaction du test)."""
    import anyio
    return await anyio.to_thread.run_sync(_with_db_hygiene(fn))


def _with_db_hygiene(fn):
    """Connexions fermées avant/après : un thread de travail ne doit pas garder une connexion
    Postgres morte d'une requête à l'autre (même précaution que les workers Django)."""
    def wrapper():
        from django.db import close_old_connections
        close_old_connections()
        try:
            return fn()
        finally:
            close_old_connections()
    return wrapper


# ── Identité : le jeton d'API WAMA, rien d'autre ─────────────────────────────────────────────

def user_for_token(key: str):
    """Compte ACTIF porteur de ce jeton d'API, ou None."""
    if not key:
        return None
    from rest_framework.authtoken.models import Token
    token = Token.objects.select_related('user').filter(key=key).first()
    if token is None or not token.user.is_active:
        return None
    return token.user


def _user_by_pk(pk):
    from django.contrib.auth import get_user_model
    return get_user_model().objects.filter(pk=pk, is_active=True).first()


class WamaTokenVerifier:
    """`TokenVerifier` du SDK adossé au jeton d'API WAMA — aucune seconde gestion de jetons.

    Le compte voyage dans `AccessToken.subject` (sa clé primaire) : le SDK compare aussi cette
    identité pour refuser qu'une session ouverte par un jeton soit reprise par un autre.
    """

    async def verify_token(self, token: str):
        from mcp.server.auth.provider import AccessToken
        user = await _run_sync(lambda: user_for_token(token))
        if user is None:
            return None
        return AccessToken(token=token, client_id=f'wama-user-{user.pk}',
                           scopes=[SCOPE], subject=str(user.pk))


# ── Les deux opérations, en synchrone : ce que le protocole appelle ─────────────────────────

def tools_for(user) -> list:
    """Outils MCP visibles par `user` — le registre filtré par ses droits, comme `/api/v1/tools/`.
    Un outil non exécutable par ce compte n'est pas ANNONCÉ : sinon le client le propose puis se
    prend un refus."""
    import mcp.types as types
    from wama.accounts.permissions import tool_accessible
    from wama.tool_api import TOOL_REGISTRY, tool_descriptions, tool_input_schema

    descriptions = tool_descriptions()
    return [types.Tool(name=name,
                       description=(descriptions.get(name) or {}).get('description') or '',
                       inputSchema=tool_input_schema(name))
            for name in sorted(TOOL_REGISTRY) if tool_accessible(user, name)]


def call(user, name: str, arguments) -> dict:
    """Un appel d'outil = `execute_tool`. Rien de plus."""
    from wama.tool_api import execute_tool
    return execute_tool(name, dict(arguments or {}), user)


def _as_call_result(result):
    """Résultat d'outil → `CallToolResult`. Le dict voyage deux fois : en texte JSON (tout client
    sait le lire) et en contenu structuré ; `isError` suit la convention de `tool_api`, où une
    erreur est un dict portant `error`."""
    import mcp.types as types
    payload = result if isinstance(result, dict) else {'result': result}
    text = json.dumps(payload, ensure_ascii=False, default=str)
    return types.CallToolResult(content=[types.TextContent(type='text', text=text)],
                                structuredContent=json.loads(text),
                                isError='error' in payload)


# ── Le serveur ───────────────────────────────────────────────────────────────────────────────

def build_server(fixed_user=None):
    """Serveur MCP « wama ».

    `fixed_user` : compte de la session en stdio (le client lance le process avec son jeton).
    Sans lui, le compte est lu PAR REQUÊTE depuis l'authentification HTTP.
    """
    from mcp.server.lowlevel import Server

    server = Server(SERVER_NAME, instructions=INSTRUCTIONS)

    async def current_user():
        if fixed_user is not None:
            return fixed_user
        try:
            request = server.request_context.request
        except LookupError:
            return None
        principal = request.scope.get('user') if request is not None else None
        subject = getattr(getattr(principal, 'access_token', None), 'subject', None)
        if not subject:
            return None
        return await _run_sync(lambda: _user_by_pk(subject))

    @server.list_tools()
    async def list_tools():
        user = await current_user()
        if user is None:
            return []
        return await _run_sync(lambda: tools_for(user))

    # `validate_input=False` : la validation qui fait foi est `execute_tool` (cf. en-tête).
    @server.call_tool(validate_input=False)
    async def call_tool(name, arguments):
        user = await current_user()
        if user is None:
            return _as_call_result({'error': 'unauthenticated',
                                    'detail': "Jeton d'API WAMA requis."})
        return _as_call_result(await _run_sync(lambda: call(user, name, arguments)))

    return server


async def serve_stdio(user) -> None:
    """Transport stdio : un process par client, compte fixé au lancement.

    ⚠ stdout EST le canal du protocole : rien d'autre ne doit y écrire (journaux sur stderr).
    """
    from mcp.server.stdio import stdio_server
    server = build_server(fixed_user=user)
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


def http_address(host: str = '', port: int = 0) -> tuple:
    """(hôte, port) d'écoute — le registre des sources externes par défaut (`wama_mcp`)."""
    from wama.common.external_sources import base_url
    declared = urlparse(base_url('wama_mcp'))
    return host or declared.hostname or '127.0.0.1', port or declared.port or 8770


def build_http_app(host: str, port: int):
    """Application ASGI : HTTP streamable, authentifiée par jeton, protégée du DNS rebinding.

    ⚠ La protection DNS rebinding est DÉSACTIVÉE par défaut dans le SDK (compatibilité) : un site
    web ouvert dans le navigateur pourrait sinon joindre ce serveur local. Elle est activée ici,
    bornée aux adresses d'écoute.
    """
    from mcp.server.auth.middleware.bearer_auth import BearerAuthBackend, RequireAuthMiddleware
    from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
    from mcp.server.transport_security import TransportSecuritySettings
    from starlette.applications import Starlette
    from starlette.middleware import Middleware
    from starlette.middleware.authentication import AuthenticationMiddleware
    from starlette.routing import Route

    hosts = sorted({host, '127.0.0.1', 'localhost'})
    manager = StreamableHTTPSessionManager(
        app=build_server(),
        security_settings=TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=[f'{h}:{port}' for h in hosts],
            allowed_origins=[f'http://{h}:{port}' for h in hosts]))

    @asynccontextmanager
    async def lifespan(app):
        async with manager.run():
            yield

    endpoint = RequireAuthMiddleware(manager.handle_request, required_scopes=[SCOPE])
    return Starlette(
        routes=[Route(MCP_PATH, endpoint=endpoint, methods=['GET', 'POST', 'DELETE'])],
        middleware=[Middleware(AuthenticationMiddleware,
                               backend=BearerAuthBackend(WamaTokenVerifier()))],
        lifespan=lifespan)
