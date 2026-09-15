"""
Lance le serveur MCP de WAMA — les outils de `tool_api` pour tout client MCP.

    python manage.py run_mcp_server                      # HTTP streamable (adresse : `wama_mcp`)
    python manage.py run_mcp_server --port 8770
    WAMA_MCP_TOKEN=<jeton> python manage.py run_mcp_server --transport stdio

Deux transports, un même serveur (`common/services/mcp_server.py`) :
  • `http`  — process à part, un jeton d'API par requête (`Authorization: Bearer …`). C'est le
              mode d'un service supervisé, joignable par plusieurs clients.
  • `stdio` — le CLIENT lance le process (Claude Code, IDE) ; le compte est celui du jeton posé
              dans `WAMA_MCP_TOKEN`. ⚠ stdout est alors le canal du protocole : cette commande
              n'y écrit rien.
"""
import os

from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = ("Serveur MCP de WAMA (outils tool_api) — HTTP streamable par défaut, ou stdio "
            "avec WAMA_MCP_TOKEN.")

    def add_arguments(self, parser):
        parser.add_argument('--transport', choices=('http', 'stdio'), default='http',
                            help="http (process supervisé, jeton par requête) ou stdio "
                                 "(lancé par le client, jeton dans WAMA_MCP_TOKEN).")
        parser.add_argument('--host', default='',
                            help="Hôte d'écoute (défaut : registre des sources externes).")
        parser.add_argument('--port', type=int, default=0,
                            help="Port d'écoute (défaut : registre des sources externes).")

    def handle(self, *args, **options):
        import anyio

        from wama.common.services import mcp_server

        if options['transport'] == 'stdio':
            user = mcp_server.user_for_token(os.environ.get(mcp_server.TOKEN_ENV, ''))
            if user is None:
                raise CommandError(
                    f"{mcp_server.TOKEN_ENV} absent ou invalide : le transport stdio exige le "
                    f"jeton d'API WAMA d'un compte actif (page de profil).")
            anyio.run(mcp_server.serve_stdio, user)
            return

        import uvicorn
        host, port = mcp_server.http_address(options['host'], options['port'])
        self.stderr.write(f"Serveur MCP WAMA → http://{host}:{port}{mcp_server.MCP_PATH}")
        uvicorn.run(mcp_server.build_http_app(host, port), host=host, port=port,
                    log_level='info')
