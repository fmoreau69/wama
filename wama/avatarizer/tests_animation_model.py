"""Le MODÈLE D'ANIMATION se choisit (2026-10-03).

Jusque-là le job ne portait aucun choix : le worker tirait toujours d'après la nature de
l'avatar, et la page ne nommait que MuseTalk. Le job porte désormais `animation_model` :
« auto » (défaut, comportement inchangé) ou un modèle `lip-sync` du catalogue. Un modèle NOMMÉ
doit accepter l'avatar fourni — sinon le lancement le REFUSE avec sa raison, jamais un repli
silencieux sur un autre modèle.

Les moteurs sont des doubles (`FakeRender`) : c'est le CHOIX qui est testé, pas le rendu.
"""
from pathlib import Path
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase

from wama.avatarizer import workers
from wama.avatarizer.models import AvatarJob
from wama.avatarizer.tests_talkinghead_engine import FakeRender, _media, _silent_wav
from wama.model_manager.models import AIModel

User = get_user_model()
MUSETALK = 'avatarizer:musetalk-v1.5'


def _register_models():
    AIModel.objects.update_or_create(model_key=MUSETALK, defaults=dict(
        name='MuseTalk v1.5', model_type='lipsync', source='avatarizer',
        is_available=True, is_downloaded=True, vram_gb=4.0,
        composition={'runtime': {'engine': 'musetalk'}},
        capabilities={'task': 'lip-sync', 'inputs_required': ['work_image', 'work_audio']}))
    AIModel.objects.update_or_create(model_key=workers.TALKINGHEAD_KEY, defaults=dict(
        name='TalkingHead', model_type='lipsync', source='avatarizer',
        is_available=True, is_downloaded=True, vram_gb=0.2,
        composition={'runtime': {'engine': 'talkinghead'}},
        capabilities={'task': 'lip-sync', 'inputs_required': ['work_object3d', 'work_audio'],
                      'inputs_optional': ['prompt']}))


class NamedAnimationModelTest(TestCase):

    def setUp(self):
        FakeRender.calls = []
        _register_models()
        self.user = User.objects.create_user('animation_model_user', password='x')
        wav_dir = Path(settings.MEDIA_ROOT) / 'tmp_tests'
        wav_dir.mkdir(parents=True, exist_ok=True)
        for p in (patch.object(workers, '_call_tts_service',
                               side_effect=lambda job: _silent_wav(wav_dir / f'tts{job.id}.wav')),
                  # La connexion de test ne se ferme pas : le squelette commun la recycle en tête.
                  patch('wama.common.utils.task_skeleton.close_old_connections')):
            p.start()
            self.addCleanup(p.stop)

    def _run(self, avatar_name, animation_model):
        job = AvatarJob.objects.create(
            user=self.user, mode='pipeline', text_content='Bonjour.',
            tts_model='synthesizer:kokoro', avatar_source='upload',
            avatar_upload=_media(f'avatarizer/{self.user.id}/input/{avatar_name}'),
            animation_model=animation_model)
        with patch.object(workers, '_backend', return_value=FakeRender()) as by_key, \
                patch('wama.common.utils.input_match.input_attribute_verdict',
                      return_value=(None, '')):
            workers.generate_avatar.apply(args=[job.id])
        job.refresh_from_db()
        return job, [c.args[0] for c in by_key.call_args_list]

    def test_a_new_job_draws_automatically(self):
        self.assertEqual('auto', AvatarJob._meta.get_field('animation_model').get_default())

    def test_auto_still_follows_the_nature_of_the_avatar(self):
        job, keys = self._run('face.png', 'auto')
        self.assertEqual('SUCCESS', job.status, job.error_message)
        self.assertEqual([MUSETALK], keys)
        job, keys = self._run('head.glb', 'auto')
        self.assertEqual('SUCCESS', job.status, job.error_message)
        self.assertEqual([workers.TALKINGHEAD_KEY], keys)

    def test_a_named_model_is_the_one_that_runs(self):
        job, keys = self._run('face.png', 'musetalk-v1.5')
        self.assertEqual('SUCCESS', job.status, job.error_message)
        self.assertEqual([MUSETALK], keys)

    def test_a_named_model_that_cannot_animate_the_avatar_is_refused_before_any_render(self):
        """Pas de repli silencieux : MuseTalk demandé sur un GLB n'est PAS remplacé par TalkingHead."""
        job, keys = self._run('head.glb', 'musetalk-v1.5')
        self.assertEqual('FAILURE', job.status)
        self.assertIn("n'anime pas un avatar 3D", job.error_message)
        self.assertIn('auto', job.error_message)
        self.assertEqual([], keys)
        job, keys = self._run('face.png', 'talkinghead')
        self.assertEqual('FAILURE', job.status)
        self.assertIn("n'anime pas une photo", job.error_message)
        self.assertEqual([], keys)

    def test_a_model_unknown_to_the_catalog_is_refused(self):
        job, keys = self._run('face.png', 'ghost-model')
        self.assertEqual('FAILURE', job.status)
        self.assertIn('inconnu du catalogue', job.error_message)
        self.assertEqual([], keys)


class AnimationModelDeclarationTest(TestCase):

    def setUp(self):
        _register_models()
        self.user = User.objects.create_user('animation_schema_user', password='x')

    def test_the_schema_states_the_select_from_the_catalog(self):
        from wama.avatarizer.params import PARAMS_JSON
        field = next(p for p in PARAMS_JSON if p['name'] == 'animation_model')
        self.assertEqual('catalog', field['options_source'])
        self.assertEqual({'source': 'avatarizer', 'task': 'lip-sync'}, field['options_query'])
        self.assertEqual('silent', field['options_auto'])
        self.assertEqual({'panel', 'item', 'batch'}, set(field['contexts']))

    def test_the_tts_select_stays_the_first_catalog_field(self):
        """Le tirage du moteur TTS lit le domaine du PREMIER select `catalog` (`catalog_field`)."""
        from wama.common.utils.auto_model import catalog_domain
        self.assertEqual({'task': 'text-to-speech'}, catalog_domain('avatarizer'))

    def test_creation_keeps_a_catalog_model_and_turns_anything_else_into_auto(self):
        from wama.avatarizer.views import _animation_model_or_auto
        self.assertEqual('talkinghead', _animation_model_or_auto('talkinghead'))
        self.assertEqual('musetalk-v1.5', _animation_model_or_auto(' musetalk-v1.5 '))
        for value in ('', None, 'auto', 'ghost-model', 'codeformer'):
            self.assertEqual('auto', _animation_model_or_auto(value), repr(value))

    def test_the_item_settings_route_saves_the_choice(self):
        from django.contrib.auth.models import Group
        from django.urls import reverse
        from wama.accounts.permissions import DEFAULT_APP_ACCESS, GROUP_PREFIX
        for role in (DEFAULT_APP_ACCESS.get('avatarizer') or {}).get('roles', []):
            self.user.groups.add(Group.objects.get_or_create(name=f'{GROUP_PREFIX}{role}')[0])
        job = AvatarJob.objects.create(user=self.user, mode='standalone', avatar_source='upload',
                                       avatar_upload='x/face.png')
        self.client.force_login(self.user)
        r = self.client.post(reverse('avatarizer:update_settings', args=[job.id]),
                             {'animation_model': 'talkinghead'})
        self.assertEqual(200, r.status_code, r.content)
        job.refresh_from_db()
        self.assertEqual('talkinghead', job.animation_model)


class SilentAutoTest(TestCase):
    """`options_auto="silent"` : « auto » est proposé, la PRÉVISION se tait — elle ne connaît pas
    l'avatar de l'élément et annoncerait le modèle le plus léger à qui a posé une photo."""

    URL = '/model-manager/api/models/options/?source=avatarizer&task=lip-sync'

    def setUp(self):
        _register_models()
        self.client.force_login(User.objects.create_user('silent_auto_user', password='x'))

    def _values(self, data):
        return [(o[0] if isinstance(o, list) else o['value'])
                for g in data['groups'] for o in g['options']]

    def test_silent_auto_lists_auto_without_a_forecast(self):
        data = self.client.get(self.URL + '&auto=silent').json()
        self.assertEqual(['auto', 'musetalk-v1.5', 'talkinghead'], sorted(self._values(data)))
        self.assertNotIn('auto_preview', data)

    def test_plain_auto_would_forecast_a_model_whatever_the_avatar(self):
        """Contre-épreuve : c'est bien le drapeau qui fait taire — et la prévision ordinaire
        annonce UN modèle sans rien savoir de l'avatar, ce qui est le défaut évité."""
        with patch('wama.model_manager.services.model_selector.get_free_vram_gb', return_value=24.0):
            data = self.client.get(self.URL + '&auto=1').json()
        self.assertIn('auto', self._values(data))
        self.assertIn('auto_preview', data)
