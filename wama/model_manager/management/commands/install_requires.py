"""
Le MARCHEUR d'app : installe/planifie ce que le manifeste d'app `requires` — modèles +
librairies — en dispatchant vers les drivers existants (2026-08-31, reste ③ de la route).

    python manage.py install_requires synthesizer            # PLAN complet (défaut)
    python manage.py install_requires synthesizer --apply    # exécute (libs is_allowed
                                                             # seulement ; modèles → Celery)

Les gardes restent celles des drivers : `is_allowed` par librairie (poser via
`install_library <clé> --allow`), spec dérivable par modèle. Le plan est toujours complet ;
l'exécution n'emporte que ce que les verrous laissent passer.
"""
import json

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = ("Marcheur d'app : dispatch des requires (modeles + librairies) du manifeste "
            "d'app vers les drivers d'installation. Dry-run par defaut.")

    def add_arguments(self, parser):
        parser.add_argument('app', help="Clé d'app du corpus (manifests/apps/<app>.json).")
        parser.add_argument('--apply', action='store_true',
                            help="Exécuter (sinon : plan seul).")

    def handle(self, *args, **o):
        from wama.model_manager.services.model_installer import install_requirements

        res = install_requirements(o['app'], apply=o['apply'])
        self.stdout.write(json.dumps(res, ensure_ascii=False, indent=2, default=str))
        if not res.get('ok'):
            self.stderr.write(self.style.ERROR(res.get('error') or
                                               'au moins une librairie en échec/refus'))
        elif not o['apply']:
            self.stdout.write(self.style.NOTICE("Plan seul — rien n'a été installé."))
