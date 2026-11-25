"""
Rapproche les comptes de WAMA de l'annuaire, pour les unités suivies (`accounts/directory.py`,
`PROFILES_PERMISSIONS.md §1.12`). LECTURE SEULE : dit les arrivées (personnes sans compte) et les
départs (comptes que l'annuaire ne compte plus dans leur unité) ; ne crée ni ne ferme rien.

  manage.py reconcile_directory_accounts                    les unités du réglage de l'instance
  manage.py reconcile_directory_accounts --code "CODE"      une unité nommée (répétable)
  manage.py reconcile_directory_accounts --notify           prévient aussi les administrateurs
"""
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Arrivées et départs des unités suivies, d'après l'annuaire. Lecture seule."

    def add_arguments(self, parser):
        parser.add_argument('--code', action='append', default=[],
                            help="Code EXACT d'une unité (répétable). Défaut : les unités suivies.")
        parser.add_argument('--notify', action='store_true',
                            help='Prévient les administrateurs dans WAMA si quelque chose a changé.')

    def handle(self, *args, **options):
        from wama.accounts import directory

        try:
            report = directory.reconcile(options['code'] or None)
        except directory.DirectoryUnavailable as e:
            self.stderr.write(self.style.ERROR(f'Annuaire indisponible : {e}'))
            return
        if not report['units']:
            self.stdout.write("Aucune unité suivie : nommer une unité (--code) ou régler "
                              "WAMA_DIRECTORY_FOLLOWED_UNITS dans l'environnement de l'instance.")
            return
        self.stdout.write(f"{len(report['units'])} unité(s) : " + ' · '.join(report['units']))
        for key, label in (('arrivals', 'arrivée(s), sans compte'), ('departures', 'départ(s)')):
            self.stdout.write(f"{len(report[key])} {label}")
            for username in report[key]:
                self.stdout.write(f'  {username}')
        if options['notify']:
            self.stdout.write(f"{directory.report_reconciliation(report)} notification(s) posée(s).")
