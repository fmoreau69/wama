"""
WAMA REST API v1 — Views

Exposes WAMA tools via DRF.
Adding a tool to tool_api.TOOL_REGISTRY automatically makes it available here.

Endpoints:
  GET  /api/v1/tools/            → list available tools
  POST /api/v1/tools/run/        → execute a tool
  POST /api/v1/assistant/chat/   → one assistant conversation turn (agentic loop)
  POST /api/v1/files/upload/     → deposit a file into the caller's space
  GET  /api/v1/files/download/   → read back a file the caller may access
"""

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.authentication import TokenAuthentication, SessionAuthentication
from rest_framework.parsers import FormParser, MultiPartParser
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
            # Domaine d'intervention (`assistant_skills.DOMAINES`) : détermine le skill de
            # rôle et, pour les domaines qui le déclarent, le rappel du contexte de labo.
            domain=request.data.get("domain"),
        )

        if "error" in result:
            return Response(result, status=result.pop("status", 500))

        return Response(result)


class FileUploadView(APIView):
    """
    POST /api/v1/files/upload/   (multipart : champ `file`)

    Dépose un fichier dans l'espace de l'APPELANT et rend son `path` relatif à MEDIA_ROOT —
    la clé que les outils de l'assistant (`list_user_files`, `add_to_<app>`) consomment.

    POURQUOI CET ENDPOINT EXISTE (2026-08-21). `/filemanager/api/upload/` est écrit pour un
    NAVIGATEUR : il n'a pas d'authentification par token, et son `get_user()` retombe sur
    l'utilisateur ANONYME PARTAGÉ hors session. Un bot porteur d'un token (Matrix/Tchap,
    Discord — `ROADMAP.md` §19) s'y voyait refusé par CSRF ; et dans tout montage qui
    contournerait le CSRF, il aurait déposé ses fichiers dans l'espace anonyme au lieu de
    celui du membre du labo, SANS ERREUR. Sans cette porte, la passerelle ne peut pas
    recevoir de pièce jointe du tout.

    Le geste d'enregistrement est PARTAGÉ avec la vue web
    (`filemanager.services.enregistrer_fichier_utilisateur`) — jamais recopié.
    """
    authentication_classes = [TokenAuthentication, SessionAuthentication]
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request):
        from wama.filemanager.services import enregistrer_fichier_utilisateur

        fichier = request.FILES.get("file")
        if fichier is None:
            return Response(
                {"error": "Aucun fichier : envoyer un multipart avec le champ 'file'."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            depose = enregistrer_fichier_utilisateur(request.user, fichier)
        except Exception as exc:  # pragma: no cover — dépend du stockage
            return Response({"error": str(exc)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        return Response(depose, status=status.HTTP_201_CREATED)


class FileDownloadView(APIView):
    """
    GET /api/v1/files/download/?path=<chemin relatif à MEDIA_ROOT>

    Rend le fichier si l'appelant y a droit. Pendant token de `/filemanager/api/download/` :
    les `output_url` que les outils `get_*_status` renvoient exigent une SESSION, donc un bot
    ne peut pas récupérer un résultat sans cette porte — il doit re-télécharger ici puis
    re-poster la pièce jointe dans son canal.

    La garde d'accès est celle du filemanager (`is_path_allowed`, dérivée d'APP_CATALOG,
    scopée par `user.id`, refusant le segment `..`) — réutilisée via
    `filemanager.services.resoudre_chemin_lisible`, JAMAIS réimplémentée : dupliquer une
    garde de sécurité, c'est garantir que les deux copies divergent.
    """
    authentication_classes = [TokenAuthentication, SessionAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        from django.http import FileResponse

        from wama.filemanager.services import resoudre_chemin_lisible

        chemin, erreur = resoudre_chemin_lisible(request.user, request.query_params.get("path"))
        if erreur is not None:
            message, code = erreur
            return Response({"error": message}, status=code)

        return FileResponse(open(chemin, "rb"), as_attachment=True, filename=chemin.name)
