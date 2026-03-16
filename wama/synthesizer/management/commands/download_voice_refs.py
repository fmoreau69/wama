"""
Management command : télécharge les voix de référence manquantes.

Usage :
    python manage.py download_voice_refs
    python manage.py download_voice_refs --force
"""

from django.core.management.base import BaseCommand

from wama.synthesizer.utils.voice_utils import (
    VOICE_DOWNLOAD_CATALOG,
    _VOICE_DATASETS_CATALOG,
    download_missing_voice_refs,
    get_voice_refs_dir,
)


class Command(BaseCommand):
    help = 'Télécharge les fichiers de voix de référence manquants dans media/synthesizer/voice_references/'

    def add_arguments(self, parser):
        parser.add_argument(
            '--force',
            action='store_true',
            help='Re-télécharge même si les fichiers existent déjà',
        )

    def handle(self, *args, **options):
        refs_dir = get_voice_refs_dir()
        force    = options['force']
        total    = len(set(VOICE_DOWNLOAD_CATALOG) | set(_VOICE_DATASETS_CATALOG))

        self.stdout.write(f"Dossier cible : {refs_dir}")
        self.stdout.write(f"Fichiers dans le catalogue : {total}")
        if force:
            self.stdout.write(self.style.WARNING("Mode --force : re-téléchargement forcé"))
        self.stdout.write("")

        results = download_missing_voice_refs(force=force)

        for rel_path, status in results.items():
            if status == 'downloaded':
                self.stdout.write(self.style.SUCCESS(f"  ✓  {rel_path}"))
            elif status == 'skipped':
                self.stdout.write(f"  –  {rel_path} (déjà présent)")
            else:
                self.stdout.write(self.style.ERROR(f"  ✗  {rel_path} (échec — vérifier les logs)"))

        n_ok    = sum(1 for s in results.values() if s == 'downloaded')
        n_skip  = sum(1 for s in results.values() if s == 'skipped')
        n_fail  = sum(1 for s in results.values() if s == 'failed')

        self.stdout.write("")
        self.stdout.write(
            f"Résultat : {n_ok} téléchargées, {n_skip} déjà présentes, {n_fail} échec(s)"
        )

        if n_fail:
            self.stdout.write(
                self.style.WARNING(
                    "\nPour les voix en échec, téléchargez manuellement un fichier WAV "
                    "(6-10s, voix claire) et placez-le dans le dossier correspondant "
                    "en respectant la convention de nommage : "
                    "{genre}_{age}[_{n}]_{langue}.wav"
                )
            )
