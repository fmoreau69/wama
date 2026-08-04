"""
Propose les librairies tierces candidates au corpus `library` — NE SÈME RIEN.

Le semis reste un geste EXPLICITE (SPEC §7.4-3) : cette commande informe la décision, elle ne la
prend pas. Une fois un candidat retenu :

    python manage.py manifest_export --kind library <clé>

Usage :
    python manage.py library_candidates                 # candidats non encore semés
    python manage.py library_candidates --tous          # + ceux déjà semés
    python manage.py library_candidates --min-apps 3    # seulement les libs transverses
    python manage.py library_candidates --format json
"""
import json

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = ("Liste les librairies tierces importées par le code WAMA, avec leur provenance, "
            "pour décider lesquelles semer au corpus `library`. N'écrit rien.")

    def add_arguments(self, parser):
        parser.add_argument('--tous', action='store_true',
                            help="Inclure les librairies déjà semées au corpus.")
        parser.add_argument('--min-apps', type=int, default=0,
                            help="Ne garder que les libs importées par au moins N apps.")
        parser.add_argument('--format', default='table', choices=('table', 'json'))
        parser.add_argument('--limit', type=int, default=0, help="0 = pas de limite.")

    def handle(self, *args, **o):
        from wama.common.services.library_index import candidats, non_resolus, semees

        lignes = [c for c in candidats() if c['nb_apps'] >= o['min_apps']]
        if not o['tous']:
            lignes = [c for c in lignes if not c['semee']]
        if o['limit']:
            lignes = lignes[:o['limit']]

        if o['format'] == 'json':
            self.stdout.write(json.dumps(
                {'candidats': lignes, 'non_resolus': non_resolus(),
                 'semees': sorted(semees())}, ensure_ascii=False, indent=2))
            return

        if not lignes:
            self.stdout.write(self.style.SUCCESS("Aucun candidat (tout est déjà semé ?)."))
        else:
            self.stdout.write(f"{'DISTRIBUTION':<32} {'VERSION':<12} {'REQ':<4} {'SEM':<4} APPS")
            self.stdout.write('-' * 96)
            for c in lignes:
                apps = ', '.join(c['apps'][:6]) or '—'
                if len(c['apps']) > 6:
                    apps += f" (+{len(c['apps']) - 6})"
                self.stdout.write(
                    f"{c['dist'][:31]:<32} {c['version'][:11]:<12} "
                    f"{'oui' if c['declaree'] else '—':<4} {'oui' if c['semee'] else '—':<4} {apps}")

        nr = non_resolus()
        self.stdout.write('')
        self.stdout.write(f"{len(lignes)} candidat(s) affiché(s) · {len(semees())} déjà semée(s).")
        if nr:
            # Ni devinés, ni masqués : ce sont typiquement du code vendoré, un submodule, ou une
            # dépendance optionnelle absente du venv courant. À qualifier à la main.
            self.stdout.write(self.style.WARNING(
                f"{len(nr)} module(s) tiers sans distribution connue : {', '.join(nr[:15])}"
                + (' …' if len(nr) > 15 else '')))
        self.stdout.write(self.style.NOTICE(
            "Semis EXPLICITE : python manage.py manifest_export --kind library <clé>"))
