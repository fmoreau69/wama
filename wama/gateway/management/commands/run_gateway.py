"""
`manage.py run_gateway <canal>` — fait tourner un adaptateur de canal.

POURQUOI UNE COMMANDE DE GESTION, et pas autre chose (arbitrage Fabien du 2026-08-21) :
  • un bot est un CLIENT À SOCKET PERSISTANT — il se connecte et reste connecté. Ce n'est
    ni une requête (gunicorn), ni une tâche qui commence et finit (Celery). Le loger dans
    un worker Celery immobiliserait ce worker pour toujours ;
  • une commande de gestion a l'ORM, les settings et les logs de WAMA sans rien recâbler,
    et se supervise exactement comme les autres process du démarrage.

Exploitation :
    python manage.py run_gateway discord
À superviser comme les autres process WAMA (redémarrage automatique) : une passerelle qui
meurt ne se voit pas — personne ne reçoit d'erreur, les messages restent simplement sans
réponse.
"""
import logging

from django.core.management.base import BaseCommand, CommandError

logger = logging.getLogger(__name__)

#: Adaptateurs disponibles. Ajouter un canal = ajouter une entrée ici et un module dans
#: `gateway/adapters/` — le cœur (`gateway/core.py`) n'a pas à changer.
ADAPTATEURS = ('discord',)


class Command(BaseCommand):
    help = "Fait tourner un adaptateur de canal (Discord, puis Tchap/Matrix)."

    def add_arguments(self, parser):
        parser.add_argument('canal', choices=ADAPTATEURS,
                            help="Canal à servir (%s)" % ', '.join(ADAPTATEURS))
        parser.add_argument('--check', action='store_true',
                            help="Vérifie la configuration et quitte SANS se connecter.")

    def handle(self, *args, **options):
        canal = options['canal']
        if canal == 'discord':
            self._discord(verification_seule=options['check'])

    def _discord(self, verification_seule: bool):
        from wama.gateway.adapters import discord_bot

        try:
            bot_token = discord_bot.bot_token()
        except RuntimeError as e:
            raise CommandError(str(e))

        salons = discord_bot._allowed_channels()
        self.stdout.write(f"Canal        : discord")
        self.stdout.write(f"Jeton        : présent ({len(bot_token)} caractères)")

        # ⚠ Un identifiant Discord (snowflake) est un ENTIER de 17 à 20 chiffres. Une valeur
        # comme « #wama » ne correspondra JAMAIS à `message.channel.id` : le salon ne serait
        # pas reconnu comme dédié, et comme la liste blanche PRIME sur la mention, le bot
        # resterait MUET dans ce salon — y compris mentionné. Panne silencieuse et
        # déroutante (vécue le 2026-08-22) : mieux vaut refuser de démarrer.
        invalides = sorted(s for s in salons if not (s.isdigit() and 17 <= len(s) <= 20))
        if invalides:
            raise CommandError(
                "WAMA_DISCORD_ALLOWED_CHANNELS attend des IDENTIFIANTS numériques, pas des "
                "noms de salon.\n  Valeur(s) invalide(s) : " + ', '.join(invalides) +
                "\n  Pour obtenir un identifiant : Discord → Paramètres → Avancés → activer "
                "le « Mode développeur », puis clic droit sur le salon → « Copier "
                "l'identifiant » (18-19 chiffres)."
            )

        if salons:
            self.stdout.write("Canal dédié   : " + ', '.join(sorted(salons))
                              + "  (répond SANS mention ; muet ailleurs)")
        else:
            # Sans liste blanche, le bot répond partout où on le mentionne. Ce n'est PAS le
            # modèle retenu (WAMA a son canal, il n'entre pas dans ceux du labo) : on le dit.
            self.stdout.write(self.style.WARNING(
                "Canal dédié   : AUCUN — le bot répondra sur MENTION dans tout salon où il "
                "est présent.\n                Déclarez WAMA_DISCORD_ALLOWED_CHANNELS avec "
                "l'id du canal WAMA."))

        try:
            client = discord_bot.build_client()
        except RuntimeError as e:
            raise CommandError(str(e))

        if verification_seule:
            self.stdout.write(self.style.SUCCESS(
                "Configuration valide — client construit, AUCUNE connexion établie."))
            return

        self.stdout.write(self.style.SUCCESS("Connexion à Discord…  (Ctrl+C pour arrêter)"))
        try:
            client.run(bot_token, log_handler=None)   # log_handler=None : garder les logs WAMA
        except KeyboardInterrupt:                 # pragma: no cover
            self.stdout.write("Arrêt demandé.")
