"""Le format de sortie AUTOMATIQUE du converter — une règle, lue par toutes les voies (2026-10-18).

Décision de Fabien : « ça doit être automatique, ça dépend simplement de l'entrée ». Le converter
le faisait de quatre façons selon la voie — premier format de la liste (JS du dépôt), dernier
format employé (repli du serveur), dernier ou RIEN (« Envoyer vers »), refus d'un format absent
(outil de l'assistant, donc le Studio) — et l'import par lot créait des jobs sans format. La règle
unique : `format_router.output_format_for` — choix explicite ← dernier format employé pour la
nature ← défaut de la nature. Seul un format CHOISI se retient.
"""
import json
from unittest import mock

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase

from wama.converter.utils.format_router import (default_output_format, get_output_formats,
                                                last_output_format, output_format_for,
                                                remember_output_format)

PNG = bytes.fromhex(
    '89504e470d0a1a0a0000000d4948445200000001000000010802000000907753de'
    '0000000c49444154789c63f8cfc00000000300015f0f18e20000000049454e44ae426082')


def _chosen(nature='image'):
    """Un format offert qui n'est PAS le défaut de la nature (sinon « choisi » et « automatique »
    ne se distinguent pas)."""
    return next(f for f in get_output_formats(nature) if f != default_output_format(nature))


class TheRuleTest(TestCase):

    def setUp(self):
        self.user = User.objects.create_user('fmt_rule', password='x')

    def test_the_default_of_a_nature_is_the_first_format_of_its_list(self):
        for nature in ('image', 'video', 'audio', 'document', 'archive'):
            with self.subTest(nature=nature):
                self.assertEqual(get_output_formats(nature)[0], default_output_format(nature))
        self.assertEqual('', default_output_format('nope'))

    def test_without_anything_chosen_the_default_of_the_nature_applies(self):
        self.assertEqual(default_output_format('video'), output_format_for(self.user, 'video'))

    def test_the_last_format_chosen_for_the_nature_wins_over_its_default(self):
        remember_output_format(self.user, 'image', _chosen())
        self.assertEqual(_chosen(), output_format_for(self.user, 'image'))
        # Contre-épreuve : la mémoire est PAR nature.
        self.assertEqual(default_output_format('video'), output_format_for(self.user, 'video'))

    def test_an_explicit_choice_wins_and_a_choice_not_offered_is_refused(self):
        remember_output_format(self.user, 'image', _chosen())
        self.assertEqual('png', output_format_for(self.user, 'image', 'PNG'))
        with self.assertRaises(ValueError):
            output_format_for(self.user, 'image', 'mp4')

    def test_a_remembered_format_no_longer_offered_falls_back_to_the_default(self):
        remember_output_format(self.user, 'image', 'mp4')
        self.assertEqual('', last_output_format(self.user, 'image'))
        self.assertEqual(default_output_format('image'), output_format_for(self.user, 'image'))


class EveryRouteReadsTheRuleTest(TestCase):

    def setUp(self):
        self.user = User.objects.create_user('fmt_routes', password='x')
        self.client = Client()
        self.client.force_login(self.user)

    def _upload(self, **post):
        r = self.client.post('/converter/upload/',
                             {'file': SimpleUploadedFile('n.png', PNG, 'image/png'), **post})
        self.assertEqual(200, r.status_code, r.content)
        from wama.converter.models import ConversionJob
        return ConversionJob.objects.get(pk=r.json()['id'])

    def test_a_drop_without_format_gets_the_automatic_format_and_is_not_refused(self):
        self.assertEqual(default_output_format('image'), self._upload().output_format)

    def test_a_format_chosen_at_the_drop_becomes_the_next_automatic_one(self):
        self._upload(output_format=_chosen())
        self.assertEqual(_chosen(), self._upload().output_format)

    def test_an_automatic_format_is_not_remembered(self):
        self._upload()
        self.assertEqual('', last_output_format(self.user, 'image'))

    def test_a_drop_with_a_format_not_offered_is_refused(self):
        r = self.client.post('/converter/upload/',
                             {'file': SimpleUploadedFile('n.png', PNG, 'image/png'),
                              'output_format': 'mp4'})
        self.assertEqual(400, r.status_code)

    def test_the_assistant_tool_and_so_the_studio_no_longer_require_a_format(self):
        from django.conf import settings
        from pathlib import Path
        from wama.tool_api import convert_file
        rel = f'users/{self.user.id}/temp/studio.png'
        path = Path(settings.MEDIA_ROOT) / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(PNG)
        with mock.patch('wama.converter.tasks.convert_media_task.delay') as delay:
            delay.return_value.id = 'no-task'
            auto = convert_file(self.user, rel)
            self.assertNotIn('error', auto, auto)
            self.assertEqual(default_output_format('image'), auto['output_format'])
            self.assertEqual('', last_output_format(self.user, 'image'), 'automatique : non retenu')
            chosen = convert_file(self.user, rel, output_format=_chosen())
        self.assertEqual(_chosen(), chosen['output_format'])
        self.assertEqual(_chosen(), last_output_format(self.user, 'image'),
                         'un format CHOISI sur un nœud devient le dernier employé')
        self.assertIn('error', convert_file(self.user, rel, output_format='mp4'))

    def test_a_file_arriving_by_url_gets_its_format_with_its_nature(self):
        from wama.converter.models import ConversionJob
        from wama.converter.tasks import _derive_media_type
        job = ConversionJob.objects.create(user=self.user, input_filename='', media_type='',
                                           output_format='', status='PENDING')
        touched = _derive_media_type(job, '/tmp/x.mp4', 'x.mp4')
        self.assertEqual({'media_type', 'output_format'}, set(touched))
        self.assertEqual(('video', default_output_format('video')),
                         (job.media_type, job.output_format))

    def test_automatic_in_the_item_modal_resolves_the_format_again(self):
        from wama.converter.models import ConversionJob
        remember_output_format(self.user, 'image', _chosen())
        job = ConversionJob.objects.create(user=self.user, input_filename='a.png', media_type='image',
                                           output_format='png', status='PENDING')
        r = self.client.post(f'/converter/settings/{job.id}/', {'output_format': ''})
        self.assertEqual(200, r.status_code, r.content)
        job.refresh_from_db()
        self.assertEqual(_chosen(), job.output_format)
        # Contre-épreuve : un réglage posté SANS le format ne le touche pas.
        r = self.client.post(f'/converter/settings/{job.id}/',
                             {'options_json': json.dumps({'quality': 70})})
        job.refresh_from_db()
        self.assertEqual(_chosen(), job.output_format)
