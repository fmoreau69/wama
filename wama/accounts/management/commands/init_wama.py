from django.core.management.base import BaseCommand
from django.db import transaction

from wama.accounts.views import get_or_create_anonymous_user


class Command(BaseCommand):
    help = "Initialise WAMA : utilisateur anonyme"

    @transaction.atomic
    def handle(self, *args, **options):
        self.stdout.write("🔧 Initialisation de WAMA...")

        # Crée ou récupère l'utilisateur anonyme
        anon_user = get_or_create_anonymous_user()
        self.stdout.write(f"✅ Utilisateur anonyme prêt : {anon_user.username}")

        # (Les « paramètres globaux » de l'anonymizer ne se sèment plus, 2026-09-27 : ses
        # défauts sont ceux de son schéma, lus par la brique `user_settings`.)

        self.stdout.write(self.style.SUCCESS("🎉 WAMA est initialisé !"))
