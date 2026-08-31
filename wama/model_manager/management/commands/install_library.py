"""
Installe une librairie du registre `common.models.Library` — la jonction manifeste→pip
(2026-08-31). Chaîne : manifeste `library` (librarian ou extraction) → ingest/projection
→ registre → CETTE commande (décision + exécution) → patches rejoués.

    python manage.py install_library kokoro-onnx                  # PLAN (dry-run, défaut)
    python manage.py install_library kokoro-onnx --allow --apply  # décision humaine + exécution

`--allow` EST la décision humaine explicite (pose `is_allowed`, verrou ROADMAP §16.7 que la
projection ne pose jamais). `--apply` exécute ; sans lui, seul le plan s'affiche.
Installe dans le venv de RÉFÉRENCE (`venv_linux` — venv_win est historique/temporaire).
"""
import json

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = ("Installe une librairie du registre Library (dry-run par defaut ; --allow pose "
            "is_allowed, --apply execute puis rejoue les patches venv).")

    def add_arguments(self, parser):
        parser.add_argument('key', help="Clé du registre (nom de distribution PyPI).")
        parser.add_argument('--allow', action='store_true',
                            help="Poser is_allowed=True (décision humaine explicite).")
        parser.add_argument('--apply', action='store_true',
                            help="Exécuter réellement (sinon : plan seul).")

    def handle(self, *args, **o):
        from wama.common.models import Library
        from wama.model_manager.services.model_installer import install_library

        if o['allow']:
            n = Library.objects.filter(key=o['key']).update(is_allowed=True)
            if not n:
                self.stderr.write(self.style.ERROR(
                    f"« {o['key']} » absente du registre — ingérer son manifeste d'abord."))
                return
            self.stdout.write(f"is_allowed=True posé sur « {o['key']} » (décision humaine).")

        res = install_library(o['key'], apply=o['apply'])
        self.stdout.write(json.dumps(res, ensure_ascii=False, indent=2, default=str))
        if not res.get('ok'):
            self.stderr.write(self.style.ERROR(res.get('error', 'échec')))
        elif not o['apply']:
            self.stdout.write(self.style.NOTICE(
                "Plan seul — rien n'a été installé. Ajouter --apply pour exécuter."))
        else:
            patches = res.get('patches')
            if patches and not patches.get('ok'):
                self.stderr.write(self.style.WARNING(
                    f"⚠ patches non rejoués proprement : {patches}"))
            self.stdout.write(self.style.SUCCESS(
                f"✓ {o['key']}=={res.get('version')} — venv_linux (référence)."))
