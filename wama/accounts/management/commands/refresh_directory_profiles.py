"""
Met à jour, depuis l'annuaire, le profil de chaque compte d'annuaire DÉJÀ en base
(`accounts/directory_consent.py`, `PROFILES_PERMISSIONS.md §1.12`) : ce que chaque personne garde
sur son profil, le minimum compris, et rien qu'elle n'ait pas choisi. Les comptes que l'annuaire
ne connaît plus sont nommés, pas touchés.

  manage.py refresh_directory_profiles            lecture seule : ce qui changerait
  manage.py refresh_directory_profiles --apply    écrit les mises à jour
"""
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Met à jour les profils des comptes d'annuaire déjà en base. Lecture seule sans --apply."

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true',
                            help="Écrit les mises à jour. Sans elle : rien ne s'écrit.")

    def handle(self, *args, **options):
        from wama.accounts import directory, directory_consent

        try:
            report = directory_consent.refresh_all(apply=options['apply'])
        except directory.DirectoryUnavailable as e:
            self.stderr.write(self.style.ERROR(f'Annuaire indisponible : {e}'))
            return
        verb = 'mis à jour' if options['apply'] else 'à mettre à jour'
        self.stdout.write(f"{report['accounts']} compte(s) d'annuaire : {len(report['updated'])} "
                          f"{verb}, {len(report['unknown'])} inconnu(s) de l'annuaire.")
        for username in report['unknown']:
            self.stdout.write(f'  inconnu de l\'annuaire : {username}')
        if not options['apply']:
            self.stdout.write(self.style.WARNING("Rien n'est écrit : relancer avec --apply."))
