"""
Gardes des outils de LANCEMENT du pivot assistant (`start_*`) — le côté ÉCRITURE.

LE DÉFAUT MESURÉ (2026-09-23, depuis Discord). `start_anonymizer` rendait
`property 'processed' of 'Media' object has no setter` : il écrivait encore
`media.processed = False` et filtrait `Media.objects.filter(processed=False)`, alors que
l'audit du 2026-07-11 a remplacé ce booléen par `status` et n'a laissé `processed` qu'en
PROPERTY dérivée, pour les lecteurs. **Les deux branches de l'outil étaient donc mortes** —
l'assistant n'a jamais pu lancer une anonymisation, ni à l'unité (AttributeError) ni en lot
(FieldError sur un filtre SQL portant sur une property). Deux mois sans que rien ne le dise :
le scénario nocturne appelle les lectures, pas les lancements.

CE QUE CES GARDES TIENNENT :
  1. l'anonymizer se lance VRAIMENT depuis l'assistant, et par la MÊME brique anti-race que
     le bouton ▶ de sa card (`begin_processing`) — même verrou, mêmes resets, même refus du
     double lancement ;
  2. générique, pour les dix apps : un `start_*` appelé sans élément RÉPOND (dict d'erreur),
     il ne lève pas. C'est ce contrôle-là qui aurait attrapé la branche de lot, et il vaut
     pour toute app portée ensuite.

⚠ Aucune tâche Celery n'est réellement envoyée : `.delay` est remplacé par un double.
"""
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

from wama import tool_api as T


class _FakeTask:
    id = 'fake-task-id'


class StartAnonymizerTest(TestCase):

    def setUp(self):
        self.user = get_user_model().objects.create_user('starter', password='x')

    def _media(self, status='PENDING'):
        from wama.anonymizer.models import Media
        return Media.objects.create(
            user=self.user, status=status, file_ext='.jpg', media_type='image',
            file=SimpleUploadedFile('photo.jpg', b'x'))

    def test_starting_one_item_really_launches_it(self):
        media = self._media()
        with mock.patch('wama.anonymizer.tasks.process_single_media.delay',
                        return_value=_FakeTask()) as delay:
            result = T.start_anonymizer(self.user, media_id=media.pk)

        self.assertNotIn('error', result)
        self.assertEqual('started', result['status'])
        media.refresh_from_db()
        self.assertEqual('RUNNING', media.status)
        self.assertEqual('fake-task-id', media.task_id)
        # La tâche de la card, sur l'élément seul (`force_individual` n'a plus d'effet,
        # `anonymizer/tasks.py:137` — la triade déclarée ne le passe pas).
        delay.assert_called_once_with(media.pk)

    def test_an_item_already_running_is_refused_not_relaunched(self):
        media = self._media(status='RUNNING')
        with mock.patch('wama.anonymizer.tasks.process_single_media.delay',
                        return_value=_FakeTask()) as delay:
            result = T.start_anonymizer(self.user, media_id=media.pk)
        self.assertIn('error', result)
        delay.assert_not_called()

    def test_someone_elses_item_is_not_found(self):
        media = self._media()
        other = get_user_model().objects.create_user('intruder', password='x')
        with mock.patch('wama.anonymizer.tasks.process_single_media.delay',
                        return_value=_FakeTask()) as delay:
            result = T.start_anonymizer(other, media_id=media.pk)
        self.assertIn('introuvable', result.get('error', ''))
        delay.assert_not_called()

    def test_the_batch_branch_answers_on_an_empty_queue(self):
        """La branche qui levait `FieldError` (filtre SQL sur une property)."""
        result = T.start_anonymizer(self.user)
        self.assertIn('error', result)

    def test_the_batch_branch_launches_what_has_not_succeeded(self):
        waiting, failed = self._media(), self._media(status='FAILURE')
        done = self._media(status='SUCCESS')          # abouti : hors lot
        with mock.patch('wama.anonymizer.tasks.process_single_media.delay',
                        return_value=_FakeTask()):
            result = T.start_anonymizer(self.user)
        self.assertEqual(2, result['count'])
        self.assertEqual({waiting.pk, failed.pk}, set(result['ids']))
        # Chacun par le lanceur du ▶ (« en cours » posé sous verrou), l'abouti intact.
        statuses = {m.pk: m.status for m in type(done).objects.filter(user=self.user)}
        self.assertEqual({waiting.pk: 'RUNNING', failed.pk: 'RUNNING', done.pk: 'SUCCESS'}, statuses)


class StartTranscriberTest(TestCase):
    """The assistant starts a transcript through the SAME launcher as the ▶ of its card.

    Since 2026-10-03 the card carries a PIPELINE : a launch replays only what is stale, and the
    result of a process is cleared by ITS glue when it is replayed — never on the click. The tool
    kept its own reset, which emptied the text and the segments : a launch replaying the summary
    alone summarised an empty text and ended « done » without text."""

    def setUp(self):
        from wama.transcriber.models import Transcript, TranscriptSegment
        self.user = get_user_model().objects.create_user('transcript-starter', password='x')
        self.t = Transcript.objects.create(user=self.user, status='SUCCESS', text='bonjour à tous',
                                           language='fr', audio=SimpleUploadedFile('a.wav', b'x'))
        TranscriptSegment.objects.create(transcript=self.t, start_time=0, end_time=1,
                                         text='bonjour à tous')

    def test_a_relaunch_keeps_the_text_and_the_segments_for_the_pipeline_to_decide(self):
        from wama.transcriber import views
        task = mock.Mock(**{'delay.return_value': _FakeTask()})
        with mock.patch.object(views, '_task_for', return_value=task):
            result = T.start_transcriber(self.user, transcript_id=self.t.pk)
        self.assertEqual('started', result['status'])
        task.delay.assert_called_once_with(self.t.pk)
        self.t.refresh_from_db()
        self.assertEqual(('RUNNING', 'fake-task-id'), (self.t.status, self.t.task_id))
        self.assertEqual(('bonjour à tous', 'fr'), (self.t.text, self.t.language))
        self.assertEqual(1, self.t.segments.count())

    def test_a_running_transcript_is_refused(self):
        from wama.transcriber import views
        type(self.t).objects.filter(pk=self.t.pk).update(status='RUNNING')
        task = mock.Mock()
        with mock.patch.object(views, '_task_for', return_value=task):
            result = T.start_transcriber(self.user, transcript_id=self.t.pk)
        self.assertIn('déjà en cours', result['error'])
        task.delay.assert_not_called()


class StartOneProcessFromTheAssistantTest(TestCase):
    """2026-10-14 (Fabien's decision) — the assistant launches ONE step of a card, as the ▶ of
    that step does : the same function (`process_views.start_one_process`), behind the button
    and behind `start_<app>(…, process=…)`. Without it, the assistant could only relaunch the
    whole card."""

    def setUp(self):
        from wama.transcriber.models import Transcript
        self.user = get_user_model().objects.create_user('step-starter', password='x')
        self.t = Transcript.objects.create(user=self.user, status='SUCCESS', text='bonjour',
                                           language='fr', generate_summary=True,
                                           audio=SimpleUploadedFile('a.wav', b'x'))

    def test_one_step_is_launched_as_its_card_button_does(self):
        from wama.transcriber import views
        task = mock.Mock(**{'apply_async.return_value': _FakeTask()})
        with mock.patch.object(views, '_task_for', return_value=task):
            result = T.start_transcriber(self.user, transcript_id=self.t.pk, process='summarize')
        self.assertEqual(('started', 'summarize'), (result.get('status'), result.get('process')),
                         result)
        task.apply_async.assert_called_once_with(args=(self.t.pk,), kwargs={'process': 'summarize'})
        task.delay.assert_not_called()
        self.t.refresh_from_db()
        self.assertEqual(('RUNNING', 'fake-task-id', 'bonjour'),
                         (self.t.status, self.t.task_id, self.t.text))

    def test_an_unknown_step_is_refused_and_the_steps_are_named(self):
        from wama.transcriber import views
        task = mock.Mock()
        with mock.patch.object(views, '_task_for', return_value=task):
            result = T.start_transcriber(self.user, transcript_id=self.t.pk, process='nope')
        self.assertIn('process inconnu', result['error'])
        self.assertIn('summarize', result['error'], 'the assistant learns the steps from here')
        task.apply_async.assert_not_called()
        self.t.refresh_from_db()
        self.assertEqual('SUCCESS', self.t.status)

    def test_a_step_needs_the_element(self):
        self.assertIn('error', T.start_transcriber(self.user, process='summarize'))

    def test_a_step_of_someone_elses_card_is_not_found(self):
        stranger = get_user_model().objects.create_user('step-stranger', password='x')
        result = T.start_transcriber(stranger, transcript_id=self.t.pk, process='summarize')
        self.assertIn('introuvable', result.get('error', ''))
        self.t.refresh_from_db()
        self.assertEqual('SUCCESS', self.t.status)

    def test_the_step_reset_of_the_composer_receives_the_step(self):
        """The composer replaces only the outputs of the step it relaunches : its declared
        `reset_for_process` gets the step, as the card ▶ gives it."""
        from wama.composer import views
        from wama.composer.models import ComposerGeneration
        gen = ComposerGeneration.objects.create(user=self.user, prompt='a calm piano',
                                                status='SUCCESS')
        task = mock.Mock(**{'apply_async.return_value': _FakeTask()})
        with mock.patch.object(views, '_task_for', return_value=task), \
                mock.patch.object(views, '_reset_for_relaunch') as reset:
            result = T.start_composer(self.user, generation_id=gen.pk, process='render')
        self.assertEqual('started', result.get('status'), result)
        self.assertEqual('render', reset.call_args.args[1])


class StartImagerTest(TestCase):
    """The hand-written `start_imager` sent the IMAGE task to every generation, video included —
    its card ▶ picks the task by `_task_for` (2026-10-12). The declared triad names that function."""

    def test_a_video_generation_is_started_with_the_video_task(self):
        from wama.imager.models import ImageGeneration
        user = get_user_model().objects.create_user('video-starter', password='x')
        gen = ImageGeneration.objects.create(user=user, prompt='a cat', generation_mode='txt2vid')
        with mock.patch('wama.imager.tasks.generate_video_task.delay',
                        return_value=_FakeTask()) as video, \
                mock.patch('wama.imager.tasks.generate_image_task.delay') as image:
            result = T.start_imager(user, generation_id=gen.pk)
        self.assertEqual('started', result['status'])
        video.assert_called_once_with(gen.pk)
        image.assert_not_called()


class EveryTriadIsDeclaredTest(TestCase):
    """The ten apps (and the audio of the enhancer) start and report through TRIAD_SPECS — the
    launch of their card ▶, named by path (2026-10-12). A path that no longer resolves (a renamed
    `_task_for`) would only break at the first call of the assistant : it breaks here."""

    APPS = ('anonymizer', 'audio_enhancer', 'avatarizer', 'composer', 'converter', 'describer',
            'enhancer', 'imager', 'reader', 'synthesizer', 'transcriber')

    def test_every_app_triad_is_built_from_its_declaration(self):
        for app in self.APPS:
            with self.subTest(app=app):
                self.assertIn(app, T.TRIAD_SPECS)
                self.assertIn(f"TRIAD_SPECS['{app}']", T.TOOL_REGISTRY[f'start_{app}'].__doc__)
                self.assertIn(f"TRIAD_SPECS['{app}']", T.TOOL_REGISTRY[f'get_{app}_status'].__doc__)

    def test_every_declared_path_resolves(self):
        from django.utils.module_loading import import_string
        for app in self.APPS:
            spec = T.TRIAD_SPECS[app]
            for key in ('model', 'task', 'task_for', 'reset', 'reset_for_process'):
                if isinstance(spec.get(key), str):
                    with self.subTest(app=app, key=key):
                        self.assertTrue(callable(import_string(spec[key])))

    def test_every_entry_passes_the_manifest_ingest(self):
        """The `tool_api` facet carries the entry (`triad_spec`) and the ingest validates it :
        an entry the manifest refuses could not be regenerated (`write_back_app`)."""
        from wama.common.manifests.builtin.app import validate_app_body
        for app, spec in T.TRIAD_SPECS.items():
            with self.subTest(app=app):
                self.assertEqual([], validate_app_body({'tool_api': {'triad_spec': spec}}))
        bad = {**T.TRIAD_SPECS['imager'], 'reset': 42}
        self.assertTrue(validate_app_body({'tool_api': {'triad_spec': bad}}))

    def test_every_status_tool_reads_an_empty_queue(self):
        user = get_user_model().objects.create_user('empty-status', password='x')
        for app in self.APPS:
            with self.subTest(app=app):
                self.assertEqual({'jobs': []}, T.TOOL_REGISTRY[f'get_{app}_status'](user))


class TriadStatusFormsTest(TestCase):
    """The status line forms of the declaration, read on a real card (the anonymizer uses four)."""

    def test_the_declared_forms_are_read_on_the_card(self):
        from wama.anonymizer.models import Media
        from django.core.cache import cache
        user = get_user_model().objects.create_user('status-forms', password='x')
        media = Media.objects.create(user=user, status='RUNNING', file_ext='.jpg', media_type='image',
                                     file=SimpleUploadedFile('photo.jpg', b'x'),
                                     target_mode='classes', sam3_prompt='a face')
        cache.set(f'media_progress_{media.pk}', 42)     # the key the task writes
        try:
            row = T.get_anonymizer_status(user)['jobs'][0]
        finally:
            cache.delete(f'media_progress_{media.pk}')
        self.assertEqual(42, row['progress'])
        self.assertEqual('RUNNING', row['status'])
        self.assertTrue(row['name'].startswith('photo') and row['name'].endswith('.jpg'))
        self.assertIsNone(row['sam3_prompt'], 'when : only for a description target')
        self.assertIsNone(row['output_url'], 'when : only once it succeeded')


class EveryStartToolAnswersTest(TestCase):
    """Générique : un `start_*` sans élément à lancer REND une erreur, il ne LÈVE pas.

    Le contrôle qui manquait. Il ne mesure pas que le lancement marche (cela demande un
    élément par app), mais il traverse le code de sélection de CHAQUE outil — c'est
    exactement là que vivait la moitié du défaut du 23/09, et un filtre écrit sur un champ
    qui n'existe plus lève à la première requête."""

    def test_no_start_tool_raises_when_the_queue_is_empty(self):
        import inspect

        user = get_user_model().objects.create_user('empty-queue', password='x')
        checked = []
        for name, fn in sorted(T.TOOL_REGISTRY.items()):
            if T.tool_role(name) != 'start':
                continue
            params = list(inspect.signature(fn).parameters.values())[1:]
            if any(p.default is inspect.Parameter.empty for p in params):
                continue                       # l'outil EXIGE un id (composer) — hors sujet
            try:
                result = fn(user)
            except Exception as e:             # noqa: BLE001 — c'est ce qu'on interdit
                self.fail(f'{name} a levé {type(e).__name__} : {e}')
            self.assertIsInstance(result, dict, name)
            checked.append(name)
        self.assertGreater(len(checked), 5, f'trop peu d\'outils traversés : {checked}')
