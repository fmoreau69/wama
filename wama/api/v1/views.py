"""
WAMA REST API v1 — Views

Exposes WAMA tools via DRF.
Adding a tool to tool_api.TOOL_REGISTRY automatically makes it available here.

Endpoints:
  GET  /api/v1/tools/      → list available tools
  POST /api/v1/tools/run/  → execute a tool
"""

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.authentication import TokenAuthentication, SessionAuthentication
from rest_framework.permissions import IsAuthenticated

from wama.tool_api import TOOL_REGISTRY, TOOL_DESCRIPTIONS, execute_tool


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

        tools = [
            {
                "name": name,
                **TOOL_DESCRIPTIONS.get(name, {"description": "", "args": {}}),
            }
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
