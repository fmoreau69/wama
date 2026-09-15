"""
Lance un serveur MCP de WAMA.

    python manage.py run_mcp_server                        # surface « wama » (outils tool_api)
    python manage.py run_mcp_server --surface dev          # surface « wama-dev » (outils de dev)
    python manage.py run_mcp_server --port 8770
    WAMA_MCP_TOKEN=<jeton> python manage.py run_mcp_server --transport stdio

Deux SURFACES, toujours dans deux process distincts (ROADMAP §16 — les outils de développement ne
sont jamais chargés dans le process de prod), adresses déclarées dans `external_sources`
(`wama_mcp`, `wama_mcp_dev`). Deux transports :
  • `http`  — process à part, un jeton d'API par requête (`Authorization: Bearer …`) ;
  • `stdio` — le CLIENT lance le process (Claude Code, IDE) ; le compte est celui du jeton posé
              dans `WAMA_MCP_TOKEN`. ⚠ stdout est alors le canal du protocole : cette commande
              n'y écrit rien.
"""
import os

from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = ("Serveur MCP de WAMA — surface « wama » (outils tool_api) ou « dev » (outils de "
            "développement) ; HTTP streamable par défaut, ou stdio avec WAMA_MCP_TOKEN.")

    def add_arguments(self, parser):
        parser.add_argument('--surface', choices=('wama', 'dev'), default='wama',
                            help="wama (outils tool_api) ou dev (rôles wama-dev-ai, bac à "
                                 "sable — réservé aux développeurs).")
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

        surface = mcp_server.SURFACE_DEV if options['surface'] == 'dev' else mcp_server.SURFACE_WAMA

        if options['transport'] == 'stdio':
            user = mcp_server.user_for_token(os.environ.get(mcp_server.TOKEN_ENV, ''))
            if user is None:
                raise CommandError(
                    f"{mcp_server.TOKEN_ENV} absent ou invalide : le transport stdio exige le "
                    f"jeton d'API WAMA d'un compte actif (page de profil).")
            anyio.run(mcp_server.serve_stdio, user, surface)
            return

        import uvicorn
        host, port = mcp_server.http_address(options['host'], options['port'], surface)
        self.stderr.write(f"Serveur MCP {surface} → http://{host}:{port}{mcp_server.MCP_PATH}")
        uvicorn.run(mcp_server.build_http_app(host, port, surface), host=host, port=port,
                    log_level='info')
