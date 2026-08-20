"""
WAMA REST API v1 — Views

Exposes WAMA tools via DRF.
Adding a tool to tool_api.TOOL_REGISTRY automatically makes it available here.

Endpoints:
  GET  /api/v1/tools/           → list available tools
  POST /api/v1/tools/run/       → execute a tool
  POST /api/v1/assistant/chat/  → one assistant conversation turn (agentic loop)
"""

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.authentication import TokenAuthentication, SessionAuthentication
from rest_framework.permissions import IsAuthenticated

from wama.tool_api import TOOL_REGISTRY, execute_tool, tool_descriptions


class ListToolsView(APIView):
    """
    GET /api/v1/tools/
    Returns the list of available tools with their description and expected args.
    """
    authentication_classes = [TokenAuthentication, SessionAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        # Filtré par le gating d'app (§F7) : un outil non exécutable par ce compte ne doit pas
        # non plus être ANNONCÉ — sinon un client (assistant, agent externe) le propose puis
        # se prend un 403, et `tools/list` ment sur ce que `tools/run/` accepte.
        from wama.accounts.permissions import tool_accessible

        # Descriptions DÉRIVÉES (schéma de l'app + signature réelle) : plus de `.get(name, {})`
        # à vide — tout outil du registre est décrit, avec ses types, choix et défauts.
        described = tool_descriptions()
        tools = [
            {"name": name, **described[name]}
            for name in TOOL_REGISTRY
            if tool_accessible(request.user, name)
        ]
        return Response({"tools": tools})


class RunToolView(APIView):
    """
    POST /api/v1/tools/run/
    Body: {"tool": "<name>", "args": {...}}
    Executes the tool and returns its result.
    """
    authentication_classes = [TokenAuthentication, SessionAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request):
        tool_name = request.data.get("tool", "").strip()
        args = request.data.get("args", {})

        if not tool_name:
            return Response(
                {"error": "Champ 'tool' manquant."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not isinstance(args, dict):
            return Response(
                {"error": "Champ 'args' doit être un objet JSON."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        result = execute_tool(tool_name, args, request.user)

        if result.get("error") == "forbidden":
            return Response(result, status=status.HTTP_403_FORBIDDEN)

        if "error" in result:
            return Response(result, status=status.HTTP_400_BAD_REQUEST)

        return Response(result)


class AssistantChatView(APIView):
    """
    POST /api/v1/assistant/chat/
    Body: {"message": "...", "provider": "wama-dev-ai"?, "model": "fast"?, "history": [...]?}

    UN tour de conversation avec l'assistant WAMA — le MÊME moteur que la surface web
    (`assistant_engine.run_assistant_turn`, boucle agentique + outils tool_api), mais
    derrière l'auth token : c'est la porte des canaux tiers (bot Matrix/Tchap, Discord —
    chantier « passerelle de canaux », étape 0 du 2026-08-20).

    Persistance de conversation DIFFÉRÉE (décision Fabien 2026-08-20, jonction avec la
    brique mémoire/RAG en cours ailleurs) : `history` est fourni par le client à chaque
    tour, comme le fait la page web (localStorage) — et assaini par le moteur (rôles
    user/assistant seulement, pas d'injection de tour system par un client token).
    """
    authentication_classes = [TokenAuthentication, SessionAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request):
        from wama.common.services.assistant_engine import run_assistant_turn

        message = (request.data.get("message") or "").strip()
        if not message:
            return Response(
                {"error": "Champ 'message' manquant."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        history = request.data.get("history") or []
        if not isinstance(history, list):
            return Response(
                {"error": "Champ 'history' doit être une liste de tours {role, content}."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        result = run_assistant_turn(
            request.user,
            message,
            provider=request.data.get("provider", "wama-dev-ai"),
            model=request.data.get("model", "fast"),
            history=history,
        )

        if "error" in result:
            return Response(result, status=result.pop("status", 500))

        return Response(result)
