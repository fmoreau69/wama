"""Fait d'un modèle installé le SUCCESSEUR d'un autre, partout où l'ancien était choisi
(`services/succession.py`). L'installation d'une proposition de mise à jour le fait seule ; cette
commande sert une succession constatée APRÈS coup (olmOCR v1 → olmOCR-2, installé avant le
mécanisme). Sans `--apply`, elle compte et n'écrit rien.

    python manage.py supersede_model reader:olmocr huggingface:allenai/olmOCR-2-7B-1025
    python manage.py supersede_model reader:olmocr huggingface:allenai/olmOCR-2-7B-1025 --apply
"""
import json

from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Le successeur d'un modèle remplace l'ancien dans les cards, les réglages et les lots."

    def add_arguments(self, parser):
        parser.add_argument('old_key', help="clé de catalogue de l'ancienne version")
        parser.add_argument('new_key', help='clé de catalogue de la nouvelle version (installée)')
        parser.add_argument('--apply', action='store_true', help='écrire (sinon : compter)')

    def handle(self, *args, **opts):
        from wama.model_manager.services.succession import supersede
        result = supersede(opts['old_key'], opts['new_key'], apply=opts['apply'])
        if result.get('error'):
            raise CommandError(result['error'])
        self.stdout.write(json.dumps(result, ensure_ascii=False, indent=2))
        if not opts['apply']:
            self.stdout.write("(à blanc — relancer avec --apply pour écrire)")
