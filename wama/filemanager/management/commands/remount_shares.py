"""`manage.py remount_shares` — remonter les dossiers connectés au démarrage (2026-11-06).

Lancé par `start_wama_prod.sh` après gunicorn. Il remplace un `curl` sans session vers
`/filemanager/api/mounts/remount/`, que la route acceptait par l'adresse `127.0.0.1` et que la
garde du gestionnaire de fichiers refusait au visiteur depuis le 2026-10-12 (mesuré : 403 — le
remontage au démarrage ne se faisait plus). Une commande n'a pas d'adresse à croire.
"""
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Remonte les partages réseau invités et les dossiers distants connectés."

    def handle(self, *args, **options):
        from wama.filemanager.views import remount_shares
        result = remount_shares()
        self.stdout.write(f"Remounted: {result['remounted']}, Skipped: {result['skipped']}")
        for error in result['errors']:
            self.stdout.write(f"  - {error.get('mount')}: {error.get('error') or error.get('info')}")
