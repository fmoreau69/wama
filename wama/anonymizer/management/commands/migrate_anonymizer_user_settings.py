"""Transfère les réglages de l'anonymizer de la table legacy `UserSettings` vers la brique commune.

Depuis le 2026-09-27 l'anonymizer garde les réglages de l'utilisateur dans `user_settings`
(défauts = son schéma) et un média NAÎT avec eux ; la tâche ne lit plus que ses colonnes. Deux
choses restent à reprendre de l'ancien monde, et c'est tout ce que fait cette commande :

1. **Les préférences** : pour chaque ligne `UserSettings`, les valeurs qui DIFFÈRENT du défaut
   de la table legacy deviennent des préférences. Une valeur égale au défaut n'est pas recopiée :
   l'utilisateur garde alors le défaut du schéma — qui a pu changer (flou 25 → 75). Une
   préférence déjà posée dans la brique n'est jamais écrasée.
2. **Les médias en attente** : l'ancienne tâche relisait les réglages de l'utilisateur AU
   LANCEMENT, sauf pour un média « personnalisé ». Les médias non personnalisés qui n'ont pas
   encore tourné (ni en cours, ni réussis) reçoivent donc dans leurs colonnes ce que l'ancienne
   tâche aurait lu — ils seront traités comme ils l'auraient été.

Usage :
    python manage.py migrate_anonymizer_user_settings           # simulation
    python manage.py migrate_anonymizer_user_settings --apply
"""
from django.core.management.base import BaseCommand
from django.db import transaction

#: Ce que l'ancienne tâche lisait dans `UserSettings` pour un média non personnalisé.
TASK_READ_FIELDS = ('precision_level', 'use_segmentation', 'use_sam3', 'sam3_prompt',
                    'interpolate_detections', 'classes2blur', 'blur_ratio', 'roi_enlargement',
                    'progressive_blur', 'detection_threshold', 'max_interpolation_frames',
                    'show_preview', 'show_boxes', 'show_labels', 'show_conf', 'model_to_use')


def _legacy_default(field):
    default = field.get_default()
    return default() if callable(default) else default


class Command(BaseCommand):
    help = "Transfère les réglages legacy de l'anonymizer vers la brique user_settings"

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true', help='écrire (sinon : simulation)')

    def handle(self, *args, **options):
        from wama.anonymizer.models import Media, UserSettings
        from wama.anonymizer.params import CLASSES_SETTING, USER_SETTINGS_DEFAULTS
        from wama.common.models import UserAppSetting
        from wama.common.utils.user_settings import save_user_app_settings

        apply = options['apply']
        names = [n for n in (*USER_SETTINGS_DEFAULTS, CLASSES_SETTING)
                 if any(f.name == n for f in UserSettings._meta.concrete_fields)]
        fields = {n: UserSettings._meta.get_field(n) for n in names}

        prefs_total = medias_total = 0
        with transaction.atomic():
            for legacy in UserSettings.objects.select_related('user'):
                user = legacy.user
                already = set(UserAppSetting.objects.filter(user=user, app='anonymizer')
                              .values_list('name', flat=True))
                prefs = {}
                for name, field in fields.items():
                    value = getattr(legacy, name)
                    if name in already or value is None or value == _legacy_default(field):
                        continue
                    prefs[name] = value
                if prefs:
                    self.stdout.write(f"  {user.username}: {sorted(prefs)}")
                    prefs_total += len(prefs)
                    if apply:
                        save_user_app_settings(user, 'anonymizer', prefs)

                values = {n: getattr(legacy, n) for n in TASK_READ_FIELDS if hasattr(legacy, n)}
                pending = (Media.objects.filter(user=user, MSValues_customised=False)
                           .exclude(status__in=('RUNNING', 'SUCCESS')))
                count = pending.count()
                if count:
                    self.stdout.write(f"  {user.username}: {count} média(s) en attente "
                                      f"reçoivent les réglages lus au lancement")
                    medias_total += count
                    if apply:
                        pending.update(**values)

            if not apply:
                transaction.set_rollback(True)

        verb = 'transférées' if apply else 'à transférer (simulation, --apply pour écrire)'
        self.stdout.write(self.style.SUCCESS(
            f"{prefs_total} préférence(s) {verb} ; {medias_total} média(s) en attente complétés"))
