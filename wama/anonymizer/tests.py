"""Anonymizer — ce qui lui est PROPRE dans les réglages de l'utilisateur (2026-09-27).

Le commun est tenu ailleurs, pour toutes les apps : lecture, sauvegarde et remise à zéro des
réglages du volet (`common/tests_panel_user_settings`). Reste ici ce que l'anonymizer seul a :
les classes à flouter, réglage du volet HORS schéma, et la naissance d'un média avec les réglages
de son auteur — la tâche ne relisant plus rien au lancement.

(Les tests du `post_save` de `Media`, qui réinitialisait les `UserSettings` de tout le monde,
sont partis avec lui : le signal et la table ne sont plus lus ni écrits.)
"""
import json

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase

User = get_user_model()


class AnonymizerUserSettingsTest(TestCase):

    def setUp(self):
        from wama.accounts.permissions import GROUP_PREFIX
        self.user = User.objects.create_user('anon_settings', password='x')
        self.user.groups.add(Group.objects.get_or_create(name=f'{GROUP_PREFIX}recherche')[0])
        self.client.force_login(self.user)

    def _save(self, payload):
        return self.client.post('/anonymizer/user_settings/save/', json.dumps(payload),
                                content_type='application/json').json()

    def test_the_blur_default_is_the_model_column_default(self):
        from wama.anonymizer.models import Media
        served = self.client.get('/anonymizer/user_settings/').json()
        self.assertEqual(Media._meta.get_field('blur_ratio').default, served['blur_ratio'])

    def test_the_classes_to_blur_are_kept_cleaned_and_reset(self):
        served = self._save({'classes2blur': ['face', 'false', 'plate']})
        self.assertEqual(['face', 'plate'], served['classes2blur'])
        reset = self.client.post('/anonymizer/reset_user_settings/').json()
        self.assertEqual(['face'], reset['settings']['classes2blur'])

    def test_a_new_media_is_born_with_its_author_settings(self):
        from wama.anonymizer.models import Media
        from wama.anonymizer.views import new_media_settings
        self._save({'blur_ratio': 41, 'show_boxes': False, 'classes2blur': ['plate'],
                    'use_sam3': True, 'sam3_prompt': 'blur the plates'})
        media = Media.objects.create(user=self.user, file='anonymizer/x/input/sample.png',
                                     file_ext='.png',
                                     **new_media_settings(self.user, post={'blur_ratio': '9'}))
        self.assertEqual((9, False, ['plate'], True, 'blur the plates'),
                         (media.blur_ratio, media.show_boxes, media.classes2blur,
                          media.use_sam3, media.sam3_prompt),
                         'the deposit POST wins over the author settings, which win over defaults')

    def test_another_user_settings_do_not_leak_into_my_media(self):
        from wama.anonymizer.views import new_media_settings
        other = User.objects.create_user('anon_settings_other', password='x')
        self._save({'blur_ratio': 41})
        self.assertNotEqual(41, new_media_settings(other)['blur_ratio'])
