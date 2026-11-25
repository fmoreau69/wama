"""
Pré-inscrit les comptes d'une unité de l'annuaire (`accounts/directory.py`,
`PROFILES_PERMISSIONS.md §1.12`).

Sans `--apply` : LECTURE SEULE — les unités désignées, leurs personnes, l'état de chacune dans
WAMA, et ce qui serait créé. Avec `--apply` : les personnes sans compte en reçoivent un, INACTIF,
sans mot de passe local, sans rôle ; personne n'est prévenu. Rejouable.

  manage.py preregister_accounts --unit LABO             texte contenu dans le code ou le libellé
  manage.py preregister_accounts --code "CODE EXACT"     répétable
  manage.py preregister_accounts --unit LABO --apply
"""
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = ("Pré-inscrit (comptes INACTIFS) les personnes d'une unité de l'annuaire. "
            "Lecture seule sans --apply.")

    def add_arguments(self, parser):
        from wama.accounts.directory import PREREGISTER_LIMIT
        parser.add_argument('--unit', default='',
                            help="Texte contenu dans le code ou le libellé de l'unité.")
        parser.add_argument('--code', action='append', default=[],
                            help="Code EXACT d'une unité (répétable).")
        parser.add_argument('--apply', action='store_true',
                            help='Crée les comptes absents (inactifs). Sans elle : rien ne s\'écrit.')
        parser.add_argument('--limit', type=int, default=PREREGISTER_LIMIT,
                            help="Refuse de créer plus de comptes que cette borne en un passage "
                                 "(un texte trop court désigne vite toute une université).")

    def handle(self, *args, **options):
        from wama.accounts import directory

        if not options['unit'].strip() and not options['code']:
            self.stderr.write(self.style.ERROR('Désigner une unité : --unit <texte> ou --code <code>.'))
            return
        try:
            found = directory.lookup(options['unit'], options['code'])
        except directory.DirectoryUnavailable as e:
            self.stderr.write(self.style.ERROR(f'Annuaire indisponible : {e}'))
            return
        units, people = found['units'], found['people']
        if not units:
            self.stdout.write("Aucune unité de l'annuaire ne correspond.")
            return

        labels = directory.state_labels()
        self.stdout.write(f'{len(units)} unité(s) :')
        for unit in units:
            self.stdout.write(f"  {unit['code']} — {unit['name']}")
        counts = ', '.join(f"{sum(1 for p in people if p['state'] == state)} {label.lower()}"
                           for state, label in labels.items())
        self.stdout.write(f"{len(people)} personne(s) : {counts}.")
        for person in people:
            self.stdout.write(f"  {person['username']:32s} {labels[person['state']]}")

        absent = [p['username'] for p in people if p['state'] == directory.STATE_ABSENT]
        if not options['apply']:
            self.stdout.write(self.style.WARNING(
                f'{len(absent)} compte(s) seraient pré-inscrits (inactifs). Rien n\'est écrit : '
                f'relancer avec --apply.'))
            return
        try:
            report = directory.preregister(absent, limit=options['limit'])
        except ValueError as e:
            self.stderr.write(self.style.ERROR(f'{e}, ou relever --limit en connaissance de cause.'))
            return
        self.stdout.write(self.style.SUCCESS(
            f"{len(report['created'])} compte(s) pré-inscrit(s), inactifs ; "
            f"{len(report['existing'])} déjà là ; {len(report['missing'])} inconnu(s) de l'annuaire."))
        if report['missing']:
            self.stdout.write(self.style.WARNING('Inconnus : ' + ', '.join(report['missing'])))
