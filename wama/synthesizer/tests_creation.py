"""UNE façon de créer une synthèse — card, outil (Studio, assistant), lot, import (2026-09-30).

Ce que ces tests gardent : les surfaces aboutissent au MÊME objet par le même service
(`synthesizer.services.create_synthesis`) ; l'outil du Studio lit les PORTS (fichier de travail,
voix de référence) au lieu de ne connaître que le texte ; un fichier d'autrui est refusé partout.
"""
import os
from pathlib import Path

from django.conf import settings
from django.contrib.auth.models import Group, User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from wama.synthesizer.models import BatchSynthesisItem, VoiceSynthesis


def _grant(user):
    """Le rôle qui ouvre le synthesizer : un test de vue FRANCHIT le portier, il ne le contourne pas."""
    from wama.accounts.permissions import GROUP_PREFIX
    group, _ = Group.objects.get_or_create(name=f'{GROUP_PREFIX}communication')
    user.groups.add(group)


def _file_in_home(user, rel, data):
    path = Path(settings.MEDIA_ROOT) / 'users' / str(user.id) / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return os.path.relpath(path, settings.MEDIA_ROOT).replace('\\', '/')


class OneCreationPathTest(TestCase):

    def setUp(self):
        self.user = User.objects.create_user('synth_creator', password='x')
        _grant(self.user)
        self.client.force_login(self.user)

    def _check_ready(self, synthesis, text):
        self.assertIn(text, synthesis.text_content, 'le texte extrait est ENREGISTRÉ')
        self.assertGreater(synthesis.word_count, 0)
        self.assertTrue(BatchSynthesisItem.objects.filter(synthesis=synthesis).exists(),
                        'un lot d’un élément, pour apparaître dans la file')

    def test_the_card_with_a_work_file(self):
        response = self.client.post(reverse('synthesizer:upload'), {
            'file': SimpleUploadedFile('notes.txt', 'Bonjour la card'.encode()),
            'tts_model': 'synthesizer:kokoro', 'speed': '1.2'})
        self.assertEqual(200, response.status_code, response.content[:200])
        synthesis = VoiceSynthesis.objects.get(pk=response.json()['id'])
        self._check_ready(VoiceSynthesis.objects.get(pk=synthesis.pk), 'Bonjour la card')
        self.assertEqual((synthesis.tts_model, synthesis.speed), ('synthesizer:kokoro', 1.2))

    def test_the_card_with_typed_text(self):
        response = self.client.post(reverse('synthesizer:upload_text'),
                                    {'text_content': 'Bonjour le texte saisi'})
        self.assertEqual(200, response.status_code, response.content[:200])
        synthesis = VoiceSynthesis.objects.get(pk=response.json()['id'])
        self._check_ready(synthesis, 'Bonjour le texte saisi')
        self.assertTrue(synthesis.text_file.name.endswith('.txt'))

    def test_the_tool_reads_the_work_file_and_the_reference_voice_ports(self):
        from wama.tool_api import execute_tool
        doc = _file_in_home(self.user, 'synthesizer/input/brief.txt', 'Consigne du Studio'.encode())
        voice = _file_in_home(self.user, 'media_library/assets/me.wav', b'RIFF0000WAVE')
        result = execute_tool('add_to_synthesizer',
                              {'work_file': doc, 'reference_voice': voice}, self.user)
        self.assertNotIn('error', result, result)
        synthesis = VoiceSynthesis.objects.get(pk=result['item_id'])
        self._check_ready(synthesis, 'Consigne du Studio')
        self.assertTrue(synthesis.voice_reference, 'la voix de référence branchée est reçue')

    def test_the_tool_without_any_input_is_refused(self):
        from wama.tool_api import synthesize_text
        self.assertIn('error', synthesize_text(self.user, text='  '))

    def test_an_other_users_file_is_refused_by_the_tool_and_the_import(self):
        other = User.objects.create_user('synth_other', password='x')
        foreign = _file_in_home(other, 'synthesizer/input/private.txt', b'secret')
        from wama.tool_api import synthesize_text
        self.assertIn('error', synthesize_text(self.user, work_file=foreign))
        response = self.client.post(reverse('synthesizer:import_individual_from_path'),
                                    {'server_path': foreign})
        self.assertEqual(403, response.status_code)
        self.assertFalse(VoiceSynthesis.objects.filter(user=self.user).exists())


class ReplacedReferenceVoiceIsReleasedTest(TestCase):
    """La modale d'une synthèse EXISTANTE remplace sa voix de référence : l'ancienne est LIBÉRÉE
    (`release_card_file`), comme dans « Démarrer tout » — elle restait orpheline sans un mot
    (2026-10-20)."""

    def setUp(self):
        self.user = User.objects.create_user('synth_voice_swap', password='x')
        _grant(self.user)
        self.client.force_login(self.user)
        response = self.client.post(reverse('synthesizer:upload_text'),
                                    {'text_content': 'Bonjour la voix'})
        self.synthesis = VoiceSynthesis.objects.get(pk=response.json()['id'])

    def _post_voice(self, name):
        return self.client.post(reverse('synthesizer:update_settings', args=[self.synthesis.pk]),
                                {'voice_reference': SimpleUploadedFile(name, b'RIFF0000WAVE')})

    def test_replacing_the_reference_voice_releases_the_old_one(self):
        from wama.common.models import ReleasedFile
        self.assertEqual(200, self._post_voice('first.wav').status_code)
        first = VoiceSynthesis.objects.get(pk=self.synthesis.pk).voice_reference.name
        self.assertTrue(first)
        self.assertEqual(200, self._post_voice('second.wav').status_code)
        second = VoiceSynthesis.objects.get(pk=self.synthesis.pk).voice_reference.name
        self.assertNotEqual(first, second)
        self.assertTrue(ReleasedFile.objects.filter(user=self.user, path=first).exists(),
                        "l'ancienne voix est notée libérée, l'utilisateur en sera prévenu")
        self.assertFalse(ReleasedFile.objects.filter(path=second).exists())


class PanelSettingsFollowTheSchemaTest(TestCase):
    """Les réglages du VOLET circulent par le SCHÉMA, plus par des listes de clés (2026-10-18).

    Relevé par la session assistant en ajoutant deux réglages au schéma : ils s'affichaient sans
    être postés à la création, enregistrés sur une card inspectée, ni appliqués par « Démarrer
    tout ». Ce qui est tenu ici, côté serveur : « Démarrer tout » passe par LA fonction de réglage
    d'une synthèse (`_apply_synthesis_settings`), et la création mémorise le volet par l'écrivain
    commun (`save_panel_settings`). Côté front : `tests.FrontReadsThePanelBySchemaTest`."""

    def setUp(self):
        self.user = User.objects.create_user('synth_panel_schema', password='x')
        _grant(self.user)
        self.client.force_login(self.user)

    def _typed(self, **settings):
        response = self.client.post(reverse('synthesizer:upload_text'),
                                    {'text_content': 'Bonjour le volet', **settings})
        self.assertEqual(200, response.status_code, response.content[:200])
        return VoiceSynthesis.objects.get(pk=response.json()['id'])

    def test_start_all_applies_every_posted_schema_setting(self):
        """`start_all` relisait cinq champs à la main : le format de sortie et le curseur
        rapide/qualité, que le volet poste pourtant, n'atteignaient pas les synthèses relancées."""
        from unittest import mock
        first, second = self._typed(), self._typed()
        task = mock.MagicMock()
        task.delay.return_value.id = 'task-x'
        with mock.patch('wama.synthesizer.views._ensure_workers_imported'),                 mock.patch('wama.synthesizer.views.synthesize_voice', task, create=True):
            response = self.client.post(reverse('synthesizer:start_all'),
                                        {'output_format': 'mp3', 'quality_intent': '80', 'speed': '1.3'})
        self.assertEqual(200, response.status_code, response.content[:200])
        for synthesis in (first, second):
            synthesis.refresh_from_db()
            self.assertEqual(('mp3', 80, 1.3),
                             (synthesis.output_format, int(synthesis.quality_intent), synthesis.speed))
        self.assertEqual(2, task.delay.call_count)

    def test_the_panel_choices_are_remembered_by_the_common_writer(self):
        from wama.common.models import UserAppSetting
        from wama.synthesizer.views import synthesis_panel_values
        self._typed(language='en', tts_model='synthesizer:kokoro')
        values = synthesis_panel_values(self.user)
        self.assertEqual(('en', 'synthesizer:kokoro'), (values['language'], values['tts_model']))
        # Une valeur ÉGALE au défaut n'est pas figée : la préférence est retirée (règle commune).
        self._typed(language='fr', tts_model='synthesizer:kokoro')
        self.assertFalse(UserAppSetting.objects.filter(
            user=self.user, app='synthesizer', name='preferred_language').exists())
        self.assertEqual('fr', synthesis_panel_values(self.user)['language'])
