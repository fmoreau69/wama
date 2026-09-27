"""Convertit les valeurs stockées de l'anonymizer vers le MODE et les identifiants du catalogue.

2026-09-27 : un média désigne ce qu'il faut flouter par son MODE (`target_mode` : `classes` /
`description`, `app_modes.mode_param`) au lieu du booléen `use_sam3`, et son modèle par
l'identifiant du CATALOGUE (`yolo:<fichier>`, `sam3`, ou `auto`) au lieu d'un chemin
(`detect/faces/x.pt`). Le code nouveau lit les deux formes ; cette commande range les données
une fois pour toutes :

  • médias       — `target_mode` ← `use_sam3` ; `model_to_use` ← son identifiant (`catalogue_id_for`),
                   `auto` s'il était vide ;
  • préférences  — `use_sam3` devient `target_mode` (et disparaît) ; `model_to_use` converti.

Une valeur que le catalogue ne connaît pas est LAISSÉE telle quelle et signalée : elle reste
lisible par la recherche historique (`model_path_for`), rien n'est perdu.

⚠ À lancer APRÈS le rechargement de gunicorn : le code d'avant ne lit ni `target_mode` ni les
identifiants du catalogue.

Usage :
    python manage.py convert_anonymizer_modes_and_models           # simulation
    python manage.py convert_anonymizer_modes_and_models --apply
"""
from collections import Counter

from django.core.management.base import BaseCommand
from django.db import transaction


class Command(BaseCommand):
    help = "Convertit use_sam3 → target_mode et les chemins de modèle → identifiants du catalogue"

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true', help='écrire (sinon : simulation)')

    def handle(self, *args, **options):
        from wama.anonymizer.models import Media
        from wama.anonymizer.utils.yolo_utils import catalogue_id_for
        from wama.common.models import UserAppSetting
        from wama.common.utils.auto_model import AUTO, is_auto
        from wama.common.utils.user_settings import clear_user_app_settings, save_user_app_settings

        apply = options['apply']
        unknown = Counter()

        def converted(value):
            if is_auto(value):
                return AUTO
            key = catalogue_id_for(value)
            if not key:
                unknown[value] += 1
                return value
            return key

        medias = modes = 0
        prefs = 0
        with transaction.atomic():
            for media in Media.objects.only('pk', 'use_sam3', 'target_mode', 'model_to_use'):
                fields = {}
                mode = 'description' if media.use_sam3 else 'classes'
                if media.target_mode != mode:
                    fields['target_mode'] = mode
                    modes += 1
                model = converted(media.model_to_use)
                if model != media.model_to_use:
                    fields['model_to_use'] = model
                if fields:
                    medias += 1
                    if apply:
                        Media.objects.filter(pk=media.pk).update(**fields)

            by_user = {}
            for row in UserAppSetting.objects.filter(app='anonymizer',
                                                     name__in=('use_sam3', 'model_to_use')):
                by_user.setdefault(row.user, {})[row.name] = row.value
            for user, stored in by_user.items():
                values, removed = {}, []
                if 'use_sam3' in stored:
                    values['target_mode'] = 'description' if stored['use_sam3'] else 'classes'
                    removed.append('use_sam3')
                if 'model_to_use' in stored and converted(stored['model_to_use']) != stored['model_to_use']:
                    values['model_to_use'] = converted(stored['model_to_use'])
                if values or removed:
                    prefs += 1
                    self.stdout.write(f"  {user.username}: {values} (retiré : {removed})")
                    if apply:
                        save_user_app_settings(user, 'anonymizer', values)
                        clear_user_app_settings(user, 'anonymizer', removed)

            if not apply:
                transaction.set_rollback(True)

        for value, count in unknown.items():
            self.stdout.write(self.style.WARNING(
                f"  valeur inconnue du catalogue, laissée telle quelle : {value!r} ×{count}"))
        verb = 'converti(s)' if apply else 'à convertir (simulation, --apply pour écrire)'
        self.stdout.write(self.style.SUCCESS(
            f"{medias} média(s) {verb} (dont {modes} changement(s) de mode) ; "
            f"{prefs} utilisateur(s) aux préférences {verb}"))
