from django.core.management.base import BaseCommand
from django.db import transaction

from wama.accounts.views import get_or_create_anonymous_user
from wama.anonymizer.views import ensure_global_settings


class Command(BaseCommand):
    help = "Initialise WAMA : utilisateur anonyme + paramètres globaux"

    @transaction.atomic
    def handle(self, *args, **options):
        self.stdout.write("🔧 Initialisation de WAMA...")

        # Crée ou récupère l'utilisateur anonyme
        anon_user = get_or_create_anonymous_user()
        self.stdout.write(f"✅ Utilisateur anonyme prêt : {anon_user.username}")

        # Initialise les paramètres globaux
        ensure_global_settings()
        self.stdout.write("✅ Paramètres globaux initialisés")

        self.stdout.write(self.style.SUCCESS("🎉 WAMA est initialisé !"))
