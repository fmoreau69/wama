"""Copies de LECTURE des médias que le navigateur ne lit pas — ou, pour un audio, ne positionne pas
juste (`video_compat`, 2026-10-06 ; audio le 2026-11-18).

    python manage.py playback_copies                         # met en file les copies manquantes
    python manage.py playback_copies --dry-run               # compte seulement, rien ne part
    python manage.py playback_copies --audio-only --dry-run  # les audios seuls
    python manage.py playback_copies --sweep                 # retire les copies dont l'original est parti

Le récepteur générique crée une copie À L'IMPORT ; cette commande rattrape les médias importés
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
        parser.add_argument('--audio-only', action='store_true',
                            help="Les audios seuls (positionnement inexact : MP3, AAC brut, Vorbis).")

    def handle(self, *args, **options):
        from wama.common.utils import video_compat
        if options['sweep']:
            result = video_compat.sweep_orphan_playback_copies(dry_run=options['dry_run'])
            self.stdout.write(f"copies vues : {result['seen']} · retirées : {result['removed']}")
            return
        result = video_compat.backfill_playback_copies(dry_run=options['dry_run'],
                                                       audio_only=options['audio_only'])
        line = (f"vidéos portées par des cards : {result['videos']} · audios : {result['audios']} · "
                f"mises en file : {result['queued']}")
        if options['dry_run']:
            line += (f"\naudios présents sur le disque : {result['audio_on_disk']} · non positionnables "
                     f"(copie à faire) : {result['audio_to_copy']} · dont copie déjà à jour : "
                     f"{result['audio_copied']}")
        self.stdout.write(line)
