"""Copies de LECTURE des vidéos que le navigateur ne lit pas (`video_compat`, 2026-10-06).

    python manage.py playback_copies              # met en file les copies manquantes
    python manage.py playback_copies --dry-run    # dit seulement combien de vidéos sont portées
    python manage.py playback_copies --sweep      # retire les copies dont l'original est parti

Le récepteur générique crée une copie À L'IMPORT ; cette commande rattrape les vidéos importées
AVANT lui. Elle ne touche jamais un original : une copie s'écrit dans le dossier caché de
l'utilisateur (`users/<id>/.preview/`), jamais à côté du fichier ni dans un dossier connecté.
"""
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Met en file les copies de lecture manquantes, ou balaie les copies orphelines."

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true',
                            help="Compter, sans rien mettre en file ni retirer.")
        parser.add_argument('--sweep', action='store_true',
                            help="Retirer les copies dont l'original n'existe plus.")

    def handle(self, *args, **options):
        from wama.common.utils import video_compat
        if options['sweep']:
            result = video_compat.sweep_orphan_playback_copies(dry_run=options['dry_run'])
            self.stdout.write(f"copies vues : {result['seen']} · retirées : {result['removed']}")
            return
        result = video_compat.backfill_playback_copies(dry_run=options['dry_run'])
        self.stdout.write(f"vidéos portées par des cards : {result['videos']} · "
                          f"mises en file : {result['queued']}")
