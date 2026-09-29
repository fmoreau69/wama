"""
Le moteur TTS d'un travail se stocke en CLÉ DE CATALOGUE (2026-09-29, demande de Fabien).

Le défaut vivait en littéral dans ~12 sites, la plupart au nom court `coqui-xtts` : toléré par la
résolution du moteur, mais la clé stockée n'était plus celle du catalogue. Une constante
(`DEFAULT_TTS_MODEL`) et une normalisation à l'ENTRÉE (`tts_catalog_key`) la tiennent.
"""
from django.contrib.auth.models import User
from django.test import SimpleTestCase, TestCase

from wama.common.tts.constants import DEFAULT_TTS_MODEL, tts_catalog_key


class TtsCatalogKeyTest(SimpleTestCase):

    def test_a_short_engine_name_becomes_its_catalog_key(self):
        self.assertEqual(tts_catalog_key('coqui-xtts'), 'synthesizer:coqui-xtts')
        self.assertEqual(tts_catalog_key(' kokoro '), 'synthesizer:kokoro')

    def test_counter_proof_a_catalog_key_and_auto_are_kept(self):
        self.assertEqual(tts_catalog_key('synthesizer:bark'), 'synthesizer:bark')
        self.assertEqual(tts_catalog_key('auto'), 'auto')
        self.assertEqual(tts_catalog_key(''), '')
        self.assertEqual(tts_catalog_key(None), '')

    def test_both_job_models_default_to_the_constant(self):
        from wama.avatarizer.models import AvatarJob
        from wama.synthesizer.models import VoiceSynthesis
        for model in (VoiceSynthesis, AvatarJob):
            self.assertEqual(model._meta.get_field('tts_model').get_default(), DEFAULT_TTS_MODEL)

    def test_the_default_is_an_engine_the_service_runs(self):
        from wama.synthesizer.backends import engine_for_model
        self.assertEqual(engine_for_model(DEFAULT_TTS_MODEL), 'coqui')

    def test_an_avatarizer_batch_line_stores_the_catalog_key(self):
        from wama.avatarizer.views import _unified_item_to_avatar_row as row
        line = {'reference': 'a.png', 'prompt': 'Bonjour'}
        self.assertEqual(row({**line, 'options': {'tts': 'coqui-xtts'}})['tts_model'],
                         'synthesizer:coqui-xtts')
        self.assertEqual(row({**line, 'options': {}})['tts_model'], DEFAULT_TTS_MODEL)


class AssistantToolStoresTheCatalogKeyTest(TestCase):
    """La voie de l'ASSISTANT : un modèle cité par son nom court est stocké en clé de catalogue."""

    def test_synthesize_text_normalises_a_short_name(self):
        from wama.synthesizer.models import VoiceSynthesis
        from wama.tool_api import synthesize_text
        user = User.objects.create_user('tts_key_user', password='x')
        result = synthesize_text(user, 'Bonjour à tous.', tts_model='coqui-xtts')
        synthesis = VoiceSynthesis.objects.get(pk=result['synthesis_id'])
        try:
            self.assertEqual(synthesis.tts_model, 'synthesizer:coqui-xtts')
        finally:
            synthesis.text_file.delete(save=False)


class NoSecondDefaultInTheScriptTest(SimpleTestCase):
    """Le JS du synthesizer ne redéclare plus le défaut : vide → `DEFAULT_TTS_MODEL` côté serveur."""

    def test_the_served_script_parses_and_names_no_engine_by_default(self):
        from pathlib import Path

        from django.conf import settings
        for base in ('wama/synthesizer/static', 'staticfiles'):
            src = (Path(settings.BASE_DIR) / base / 'synthesizer/js/index.js').read_text(encoding='utf-8')
            self.assertNotIn("v('tts_model', 'coqui-xtts')", src, base)
            try:
                from py_mini_racer import MiniRacer
            except ImportError:
                continue
            MiniRacer().eval('(function(){' + src + '\n})')     # parse sans exécuter



class EmptyPostedModelTest(TestCase):
    """Le JS poste `tts_model=''` quand le select manque : la vue doit prendre le défaut, jamais
    stocker une chaîne vide (sans `or DEFAULT_TTS_MODEL`, `tts_catalog_key('')` rendrait '')."""

    def test_upload_text_with_an_empty_model_stores_the_default(self):
        from django.contrib.auth.models import Group
        from django.urls import reverse

        from wama.accounts.permissions import DEFAULT_APP_ACCESS, GROUP_PREFIX
        from wama.synthesizer.models import VoiceSynthesis
        user = User.objects.create_user('tts_empty_model', password='x')
        for role in (DEFAULT_APP_ACCESS.get('synthesizer') or {}).get('roles', []):
            user.groups.add(Group.objects.get_or_create(name=f'{GROUP_PREFIX}{role}')[0])
        self.client.force_login(user)
        res = self.client.post(reverse('synthesizer:upload_text'),
                               {'text_content': 'Bonjour à tous.', 'tts_model': ''})
        self.assertEqual(res.status_code, 200, res.content[:300])
        synthesis = VoiceSynthesis.objects.filter(user=user).latest('pk')
        try:
            self.assertEqual(synthesis.tts_model, DEFAULT_TTS_MODEL)
        finally:
            synthesis.text_file.delete(save=False)
