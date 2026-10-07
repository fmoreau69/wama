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
from django.test import SimpleTestCase, TestCase

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
        # Its catalogue KEY (what the select posts since route F4b ⑤), and the bare id of before.
        for named in (MUSETALK, 'musetalk-v1.5'):
            with self.subTest(named=named):
                job, keys = self._run('face.png', named)
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
        from wama.avatarizer.utils.model_config import ANIMATION_SPEC
        field = next(p for p in PARAMS_JSON if p['name'] == 'animation_model')
        self.assertEqual('catalog', field['options_source'])
        # Route F4b ⑤ (2026-10-07): ONE declaration, by TASK — the worker's draw reads it too.
        self.assertEqual(ANIMATION_SPEC, field['options_query'])
        self.assertNotIn('source', field['options_query'], 'a domain by source hides installed models')
        self.assertFalse(field.get('choices'), 'a static list would bring the bare-id key space back')
        self.assertEqual('silent', field['options_auto'])
        self.assertEqual({'panel', 'item', 'batch'}, set(field['contexts']))

    def test_the_worker_draws_in_the_declared_domain(self):
        """The select and the draw read ONE declaration — a second, written in the worker, would
        drift (it said `source='avatarizer'` until 2026-10-07)."""
        import inspect
        src = inspect.getsource(workers)
        self.assertIn('spec=ANIMATION_SPEC', src)
        self.assertNotIn("'source': 'avatarizer', 'task': 'lip-sync'", src)

    def test_every_writer_stores_a_catalogue_key(self):
        for given, stored in (('musetalk-v1.5', MUSETALK), (MUSETALK, MUSETALK),
                              ('auto', 'auto'), ('', '')):
            with self.subTest(given=given):
                job = AvatarJob.objects.create(user=self.user, mode='standalone',
                                               avatar_source='upload', avatar_upload='x/face.png',
                                               animation_model=given)
                self.assertEqual(stored, AvatarJob.objects.get(pk=job.pk).animation_model)

    def test_the_tts_select_stays_the_first_catalog_field(self):
        """Le tirage du moteur TTS lit le domaine du PREMIER select `catalog` (`catalog_field`)."""
        from wama.common.utils.auto_model import catalog_domain
        self.assertEqual({'task': 'text-to-speech'}, catalog_domain('avatarizer'))

    def test_creation_keeps_a_catalog_model_and_turns_anything_else_into_auto(self):
        from wama.avatarizer.views import _animation_model_or_auto
        # The key the select posts, and the bare id an older surface (assistant, batch) still sends.
        self.assertEqual(workers.TALKINGHEAD_KEY, _animation_model_or_auto(workers.TALKINGHEAD_KEY))
        self.assertEqual(workers.TALKINGHEAD_KEY, _animation_model_or_auto('talkinghead'))
        self.assertEqual(MUSETALK, _animation_model_or_auto(' musetalk-v1.5 '))
        for value in ('', None, 'auto', 'ghost-model', 'codeformer', 'synthesizer:kokoro'):
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
        for posted in (workers.TALKINGHEAD_KEY, 'talkinghead'):
            with self.subTest(posted=posted):
                r = self.client.post(reverse('avatarizer:update_settings', args=[job.id]),
                                     {'animation_model': posted})
                self.assertEqual(200, r.status_code, r.content)
                job.refresh_from_db()
                self.assertEqual(workers.TALKINGHEAD_KEY, job.animation_model)

    def test_the_item_modal_finds_the_stored_model_among_its_options(self):
        """The ⚙ modal fetches the options endpoint with the DECLARED domain, then re-selects the
        stored value only if it is an option — otherwise it falls back to « auto » and a save
        overwrites the choice. Stored value and options share ONE key space, measured as the
        modal builds its request (`_optionQuery`)."""
        from urllib.parse import urlencode
        from django.contrib.auth.models import Group
        from django.urls import reverse
        from wama.accounts.permissions import DEFAULT_APP_ACCESS, GROUP_PREFIX
        from wama.avatarizer.params import PARAMS_JSON
        for role in (DEFAULT_APP_ACCESS.get('model_manager') or {}).get('roles', []):
            self.user.groups.add(Group.objects.get_or_create(name=f'{GROUP_PREFIX}{role}')[0])
        self.client.force_login(self.user)
        field = next(p for p in PARAMS_JSON if p['name'] == 'animation_model')
        query = urlencode(sorted(field['options_query'].items())) + '&auto=silent'
        response = self.client.get(reverse('model_manager:api_model_options') + '?' + query)
        self.assertEqual(200, response.status_code, response.content[:200])
        offered = {o[0] if isinstance(o, list) else o['value']
                   for g in response.json()['groups'] for o in g['options']}
        for stored in ('musetalk-v1.5', MUSETALK, 'auto'):
            with self.subTest(stored=stored):
                job = AvatarJob.objects.create(user=self.user, mode='standalone',
                                               avatar_source='upload', avatar_upload='x/face.png',
                                               animation_model=stored)
                self.assertIn(job.gear_data['animation-model'], offered)


class AnimationModelKeysMigrationTest(SimpleTestCase):
    """`0022_animation_model_catalog_keys`: PURE prefixing (no catalogue lookup), reversible on
    its own prefix only — the pattern of `enhancer/0018`."""

    def _run(self, name, rows):
        import importlib
        from wama.common.tests.helpers import run_data_migration
        module = importlib.import_module('wama.avatarizer.migrations.0022_animation_model_catalog_keys')
        return run_data_migration(getattr(module, name), 'animation_model', rows)

    def test_forward_prefixes_bare_ids_and_leaves_auto_and_keys(self):
        self.assertEqual({1: MUSETALK, 2: 'auto', 3: 'huggingface:org/lips', 4: ''},
                         self._run('to_catalog_keys',
                                   {1: 'musetalk-v1.5', 2: 'auto', 3: 'huggingface:org/lips', 4: ''}))

    def test_backward_strips_only_its_own_prefix(self):
        self.assertEqual({1: 'musetalk-v1.5', 2: 'huggingface:org/lips', 3: 'auto'},
                         self._run('to_bare_ids',
                                   {1: MUSETALK, 2: 'huggingface:org/lips', 3: 'auto'}))


class SilentAutoTest(TestCase):
    """`options_auto="silent"` : « auto » est proposé, la PRÉVISION se tait — elle ne connaît pas
    l'avatar de l'élément et annoncerait le modèle le plus léger à qui a posé une photo."""

    #: The query the schema declares (by TASK since route F4b ⑤) — options come back as KEYS.
    URL = '/model-manager/api/models/options/?task=lip-sync'

    def setUp(self):
        _register_models()
        self.client.force_login(User.objects.create_user('silent_auto_user', password='x'))

    def _values(self, data):
        return [(o[0] if isinstance(o, list) else o['value'])
                for g in data['groups'] for o in g['options']]

    def test_silent_auto_lists_auto_without_a_forecast(self):
        data = self.client.get(self.URL + '&auto=silent').json()
        self.assertEqual(['auto', MUSETALK, workers.TALKINGHEAD_KEY], sorted(self._values(data)))
        self.assertNotIn('auto_preview', data)

    def test_plain_auto_would_forecast_a_model_whatever_the_avatar(self):
        """Contre-épreuve : c'est bien le drapeau qui fait taire — et la prévision ordinaire
        annonce UN modèle sans rien savoir de l'avatar, ce qui est le défaut évité."""
        with patch('wama.model_manager.services.model_selector.get_free_vram_gb', return_value=24.0):
            data = self.client.get(self.URL + '&auto=1').json()
        self.assertIn('auto', self._values(data))
        self.assertIn('auto_preview', data)
