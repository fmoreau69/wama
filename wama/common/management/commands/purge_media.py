"""
Purge des médias expirés selon la rétention par utilisateur (UserProfile.media_retention_days).
  python manage.py purge_media            # purge réelle
  python manage.py purge_media --dry-run  # simulation (compte sans supprimer)
"""
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Purge les médias dont l'âge dépasse la rétention de l'utilisateur."

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true', help="Simule sans supprimer.")

    def handle(self, *args, **opts):
        from wama.common.services.retention import purge_expired_media
        res = purge_expired_media(dry_run=opts['dry_run'])
        tag = '[dry-run] ' if res['dry_run'] else ''
        self.stdout.write(self.style.SUCCESS(
            f"{tag}{res['deleted']} média(s) purgé(s) pour {res['users']} utilisateur(s)."
        ))
        for model, n in res['by_model'].items():
            self.stdout.write(f"  - {model}: {n}")
