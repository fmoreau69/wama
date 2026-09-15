"""
Réglages utilisateur DURABLES — `common/utils/user_settings.py` (décision de Fabien, 2026-09-15).

⚠ CE QUE CES GARDES PROTÈGENT : un réglage global d'utilisateur survit à la perte du cache (la
base fait foi) ; les signatures des 8 apps appelantes ne changent pas ; `None` reste une valeur
légitime ; une clé de cache historique se relit sans découper au mauvais `_`.
"""
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.core.cache import cache
from django.test import TestCase

from wama.common.management.commands.import_user_settings_cache import parse_key
from wama.common.models import UserAppSetting
from wama.common.utils import user_settings as us


class ReglagesDurablesTest(TestCase):

    def setUp(self):
        self.user = get_user_model().objects.create_user('reglages_durables', password='x')
        self.addCleanup(self._vider_cache)

    def _vider_cache(self):
        cache.delete_many([us._key(self.user, 'transcriber', n)
                           for n in ('backend', 'hotwords', 'vide', 'objet')])

    def test_un_reglage_survit_a_la_perte_du_cache(self):
        us.save_user_app_settings(self.user, 'transcriber', {'backend': 'whisper'})
        self._vider_cache()
        self.assertEqual('whisper', us.get_user_app_setting(self.user, 'transcriber', 'backend'))
        self.assertTrue(UserAppSetting.objects.filter(user=self.user, name='backend').exists())

    def test_les_defauts_completent_ce_qui_n_est_pas_pose(self):
        us.save_user_app_settings(self.user, 'transcriber', {'backend': 'whisper'})
        self.assertEqual({'backend': 'whisper', 'hotwords': ''},
                         us.get_user_app_settings(self.user, 'transcriber',
                                                  {'backend': 'auto', 'hotwords': ''}))

    def test_none_est_une_valeur_legitime_distincte_de_l_absence(self):
        us.save_user_app_settings(self.user, 'transcriber', {'vide': None})
        self.assertIsNone(us.get_user_app_setting(self.user, 'transcriber', 'vide', 'defaut'))
        self._vider_cache()
        self.assertIsNone(us.get_user_app_setting(self.user, 'transcriber', 'vide', 'defaut'))

    def test_reecrire_met_a_jour_sans_doublon(self):
        us.save_user_app_settings(self.user, 'transcriber', {'backend': 'a'})
        us.save_user_app_settings(self.user, 'transcriber', {'backend': 'b'})
        self._vider_cache()
        self.assertEqual('b', us.get_user_app_setting(self.user, 'transcriber', 'backend'))
        self.assertEqual(1, UserAppSetting.objects.filter(user=self.user, name='backend').count())

    def test_une_valeur_non_json_reste_en_cache_sans_faire_echouer(self):
        us.save_user_app_settings(self.user, 'transcriber', {'objet': {1, 2}})
        self.assertFalse(UserAppSetting.objects.filter(user=self.user, name='objet').exists())
        self.assertEqual({1, 2}, us.get_user_app_setting(self.user, 'transcriber', 'objet'))

    def test_un_anonyme_sans_identifiant_garde_le_cache_seul(self):
        anonyme = AnonymousUser()
        us.save_user_app_settings(anonyme, 'transcriber', {'backend': 'x'})
        self.assertEqual('x', us.get_user_app_setting(anonyme, 'transcriber', 'backend'))
        self.assertFalse(UserAppSetting.objects.filter(name='backend', value='x').exists())
        cache.delete(us._key(anonyme, 'transcriber', 'backend'))


class ClesHistoriquesTest(TestCase):
    """La recopie reconnaît l'app parmi les apps CONNUES — jamais en découpant au premier `_`."""

    APPS = {'describer', 'describer_01', 'converter', 'face_analyzer'}

    def test_un_nom_d_app_et_un_nom_de_reglage_avec_des_soulignes(self):
        self.assertEqual((7, 'describer_01', 'max_length'),
                         parse_key('user_7_describer_01_max_length', self.APPS))
        self.assertEqual((3, 'converter', 'last_format_image'),
                         parse_key('user_3_converter_last_format_image', self.APPS))
        self.assertEqual((3, 'describer', 'max_length'),
                         parse_key('user_3_describer_max_length', self.APPS))

    def test_une_cle_sans_app_connue_est_laissee_de_cote(self):
        self.assertIsNone(parse_key('user_3_inconnue_x', self.APPS))
        self.assertIsNone(parse_key('autre_cle', self.APPS))
