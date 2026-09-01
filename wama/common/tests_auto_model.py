"""Tests de la brique COMMUNE d'auto-sélection de modèle (`common/utils/auto_model.py`).

Trois surfaces : la résolution (« auto » → tirage par le domaine du schéma, valeur
explicite respectée, repli sans jamais lever), la prévision (le modèle qui serait retenu
maintenant), et l'endpoint d'options (« auto » servi en 1ʳᵉ position, opt-in `auto=1`).
"""

from django.contrib.auth import get_user_model
from django.test import Client, TestCase

from wama.common.utils.auto_model import (
    AUTO_LABEL, catalog_domain, is_auto, predict_model_choice, resolve_model_choice,
)
from wama.model_manager.models import AIModel


def _tts(model_key, name, vram_gb):
    return AIModel.objects.create(
        model_key=model_key, name=name, model_type='speech', source='synthesizer',
        vram_gb=vram_gb, is_available=True, is_downloaded=True,
        capabilities={'task': 'text-to-speech', 'modalities': ['audio']},
    )


class ResolutionAutoTest(TestCase):

    def setUp(self):
        self.leger = _tts('synthesizer:tts-leger', 'TTS léger', 0.5)
        self.lourd = _tts('synthesizer:tts-lourd', 'TTS lourd', 4.0)

    def test_une_valeur_explicite_revient_telle_quelle(self):
        self.assertEqual(
            resolve_model_choice('synthesizer:tts-lourd', app_id='synthesizer'),
            'synthesizer:tts-lourd')

    def test_auto_tire_dans_le_domaine_declare_au_schema_et_rend_la_cle_entiere(self):
        """Le domaine du tirage EST celui des options (`options_query` du schéma) ; sans
        `source`, l'espace de clés du retour est la clé catalogue ENTIÈRE (règle
        `select_model_id`, mesurée le 2026-09-01)."""
        choix = resolve_model_choice('auto', app_id='synthesizer', fallback='repli')
        self.assertIn(choix, {'synthesizer:tts-leger', 'synthesizer:tts-lourd'})

    def test_une_valeur_vide_vaut_auto(self):
        self.assertTrue(is_auto(''))
        self.assertTrue(is_auto(None))
        choix = resolve_model_choice('', app_id='synthesizer', fallback='repli')
        self.assertIn(choix, {'synthesizer:tts-leger', 'synthesizer:tts-lourd'})

    def test_catalogue_vide_rend_le_repli_sans_lever(self):
        AIModel.objects.all().delete()
        self.assertEqual(
            resolve_model_choice('auto', app_id='synthesizer', fallback='le-repli'),
            'le-repli')

    def test_un_domaine_introuvable_rend_le_repli_sans_lever(self):
        """Une app sans select `catalog` au schéma (ou un spec vide) ne doit pas faire
        échouer un lancement : la brique encaisse et rend le repli."""
        self.assertEqual(
            resolve_model_choice('auto', spec={}, fallback='le-repli'), 'le-repli')

    def test_le_domaine_des_deux_adopteurs_est_lisible_au_schema(self):
        self.assertEqual(catalog_domain('synthesizer'), {'task': 'text-to-speech'})
        self.assertEqual(catalog_domain('avatarizer'), {'task': 'text-to-speech'})


class PrevisionTest(TestCase):

    def setUp(self):
        self.seul = _tts('synthesizer:tts-seul', 'TTS seul', 0.5)

    def test_la_prevision_nomme_le_modele_et_sa_vram(self):
        p = predict_model_choice({'task': 'text-to-speech'})
        self.assertIsNotNone(p)
        self.assertEqual(p['id'], 'synthesizer:tts-seul')
        self.assertEqual(p['name'], 'TTS seul')
        self.assertEqual(p['vram_gb'], 0.5)

    def test_sans_candidat_la_prevision_rend_None(self):
        AIModel.objects.all().delete()
        self.assertIsNone(predict_model_choice({'task': 'text-to-speech'}))


class EndpointOptionsAutoTest(TestCase):

    URL = '/model-manager/api/models/options/'

    def setUp(self):
        _tts('synthesizer:tts-seul', 'TTS seul', 0.5)
        user = get_user_model().objects.create_user(
            username='auto_model_test', password='x')
        self.client = Client()
        self.client.force_login(user)

    def test_auto_est_servi_en_premiere_option_avec_la_prevision(self):
        r = self.client.get(self.URL, {'task': 'text-to-speech', 'auto': '1'})
        self.assertEqual(r.status_code, 200)
        d = r.json()
        premiere = d['groups'][0]['options'][0]
        self.assertEqual(premiere, ['auto', AUTO_LABEL])
        self.assertEqual(d.get('auto_preview', {}).get('name'), 'TTS seul')

    def test_sans_le_drapeau_la_reponse_est_inchangee(self):
        r = self.client.get(self.URL, {'task': 'text-to-speech'})
        d = r.json()
        valeurs = [o[0] for g in d['groups'] for o in g['options']]
        self.assertNotIn('auto', valeurs)
        self.assertNotIn('auto_preview', d)
