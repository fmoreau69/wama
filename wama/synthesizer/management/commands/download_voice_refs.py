"""
Management command : télécharge les voix de référence manquantes — dans la MÉDIATHÈQUE.

Usage :
    python manage.py download_voice_refs
    python manage.py download_voice_refs --force

Depuis le 2026-09-13 (MEDIA_STORAGE_TIERING §9.4), une voix téléchargée devient une ligne
`SystemAsset(voice)` avec ses attributs (langue/âge/genre) et sa provenance — plus un fichier
nu dans un dossier.
"""

from django.core.management.base import BaseCommand

from wama.common.tts.voice_refs import (
    VOICE_DOWNLOAD_CATALOG,
    _VOICE_DATASETS_CATALOG,
    download_missing_voice_refs,
)


class Command(BaseCommand):
    help = 'Télécharge les voix de référence manquantes dans la médiathèque (SystemAsset voice)'

    def add_arguments(self, parser):
        parser.add_argument(
            '--force',
            action='store_true',
            help='Re-télécharge même si la voix est déjà en médiathèque (le fichier est remplacé)',
        )

    def handle(self, *args, **options):
        force = options['force']
        total = len(set(VOICE_DOWNLOAD_CATALOG) | set(_VOICE_DATASETS_CATALOG))

        self.stdout.write("Cible : médiathèque — SystemAsset(asset_type='voice')")
        self.stdout.write(f"Voix dans le catalogue : {total}")
        if force:
            self.stdout.write(self.style.WARNING("Mode --force : re-téléchargement forcé"))
        self.stdout.write("")

        results = download_missing_voice_refs(force=force)

        for name, status in results.items():
            if status == 'downloaded':
                self.stdout.write(self.style.SUCCESS(f"  ✓  {name}"))
            elif status == 'skipped':
                self.stdout.write(f"  –  {name} (déjà en médiathèque)")
            else:
                self.stdout.write(self.style.ERROR(f"  ✗  {name} (échec — vérifier les logs)"))

        n_ok = sum(1 for s in results.values() if s == 'downloaded')
        n_skip = sum(1 for s in results.values() if s == 'skipped')
        n_fail = sum(1 for s in results.values() if s == 'failed')

        self.stdout.write("")
        self.stdout.write(f"Résultat : {n_ok} téléchargées, {n_skip} déjà présentes, {n_fail} échec(s)")

        if n_fail:
            self.stdout.write(self.style.WARNING(
                "\nPour les voix en échec, déposez un WAV (6-10 s, voix claire) dans la médiathèque "
                "(type Voix) avec ses attributs langue / âge / genre."))
