"""
Désinstalle une librairie du registre `common.models.Library` — le pendant d'`install_library`
(2026-10-23) : même contrat, même journal.

    python manage.py uninstall_library airllm            # PLAN (dry-run, défaut)
    python manage.py uninstall_library airllm --apply    # exécution

Refusé tant qu'un paquet installé ou un manifeste du corpus en a besoin. Un seul paquet retiré,
jamais ses dépendances. Le registre garde sa ligne, désinstallée et non autorisée.
"""
import json

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = ("Désinstalle une librairie du registre Library (dry-run par défaut ; --apply exécute "
            "puis rejoue les patches venv).")

    def add_arguments(self, parser):
        parser.add_argument('key', help="Clé du registre (nom de distribution PyPI).")
        parser.add_argument('--apply', action='store_true',
                            help="Exécuter réellement (sinon : plan seul).")

    def handle(self, *args, **o):
        from wama.model_manager.services.model_installer import uninstall_library

        res = uninstall_library(o['key'], apply=o['apply'], via='cli')
        self.stdout.write(json.dumps(res, ensure_ascii=False, indent=2, default=str))
        if not res.get('ok'):
            self.stderr.write(self.style.ERROR(res.get('error', 'échec')))
        elif not o['apply']:
            self.stdout.write(self.style.NOTICE(
                "Plan seul — rien n'a été retiré. Ajouter --apply pour exécuter."))
        else:
            self.stdout.write(self.style.SUCCESS(f"✓ {o['key']} désinstallée — venv_linux (référence)."))
