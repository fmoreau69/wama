"""PISTES AUTOMATIQUES d'un média — un producteur analyse un fichier, le commun range et rend
(2026-11-25, `common/utils/media_marks.py`, `ROUTE §10.7.14 ⑲`).

Held here, on the STATEMENTS — no producer is named :
  * a derived file with a key lives in the user's hidden folder and maps back to its original, so
    the sweep and the integrity audit count it as derived whatever its producer ;
  * every registered producer states a function of the catalogue whose output and settings are
    its own, and an analysis that resolves ;
  * the cycle is the one of every derived fact (`derived_json`) : one task per version of the
    file, « pending », « failed », « ready » read — never stored on a card ;
  * the marks are read by the COMMON reader, under its names, from tracks stated on the spot ;
  * other settings replace the stored track ; what was drawn from a file goes with it ;
  * the assistant reads them through `get_file_marks`, on its own files only ;
  * a producer with a MODEL (`ROUTE §10.7.14 ㉑`) : one analysis fills several tracks with one
    queued task, a track it leaves empty is ready and empty, it is only analysed when its track
    is asked by name, and what a card's process already computed is deposited, not recomputed.
"""
import inspect
import os
import shutil
import tempfile
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase, override_settings

from wama import tool_api as T
from wama.common.catalog import function_catalog as fc
from wama.common.catalog import marks
from wama.common.catalog.data_types import DataType
from wama.common.catalog.marks import DERIVED, InvalidTracks, Track
from wama.common.utils import media_marks as mm
from wama.common.utils import video_compat as vc

LOCMEM = {'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
                      'LOCATION': 'media-marks-tests'}}
TASK = 'wama.common.tasks.make_media_marks_task.delay'
KEY = 'witness_parts'


def witness_rows(path, gap=0.0):
    """The analysis of the witness producer : two parts, apart by its one setting."""
    if os.path.getsize(path) == 0:
        raise RuntimeError('unreadable')
    return [{'start': 0.0, 'end': 2.0, 'name': 'intro'},
            {'start': 2.0 + gap, 'end': 5.0, 'name': 'verse'}]


def _witness():
    return mm.Producer(
        track=Track(KEY, 'Parts', kind=DataType.SEGMENTS, origin=KEY, attributes=('name',),
                    gestures=('label', 'mask'), edits=DERIVED),
        natures=('audio',), detect=f'{__name__}:witness_rows')


#: A witness ANALYSIS : one pass of a « model » fills two tracks, on demand, by its own task.
PASS, BARS, TONES = 'witness_pass', 'witness_bars', 'witness_tones'


def witness_pass(path):
    """One pass, two tracks — the second one left empty by a file that says so."""
    with open(path, 'rb') as source:
        content = source.read()
    if not content:
        raise RuntimeError('unreadable')
    return {BARS: [{'start': 0.0, 'end': 2.0, 'number': 1}, {'start': 2.0, 'end': 4.0, 'number': 2}],
            TONES: [] if content.startswith(b'ATONAL') else [{'start': 0.0, 'end': 4.0, 'tone': 'C'}]}


class _WitnessTask:
    """Stand-in of the Celery task of an app (`Producer.task`)."""
    sent = []

    @classmethod
    def delay(cls, *arguments):
        cls.sent.append(arguments)


witness_task = _WitnessTask


def _witness_pass(**changed):
    stated = dict(natures=('audio',), detect=f'{__name__}:witness_pass', analysis=PASS,
                  task=f'{__name__}:witness_task', on_demand=True)
    stated.update(changed)
    return [mm.Producer(track=Track(key, label, kind=DataType.SEGMENTS, origin=key,
                                    attributes=(attribute,)), **stated)
            for key, label, attribute in ((BARS, 'Bars', 'number'), (TONES, 'Tones', 'tone'))]


def _only(test, *witnesses):
    """The registry holds the witnesses ALONE for the time of a test, whatever the apps register
    for the same nature (the structure of a song, for every audio) — and gets them back after."""
    mm.producers()                      # the apps have registered : the patch restores them all
    patch = mock.patch.dict(mm._PRODUCERS, clear=True)
    patch.start()
    test.addCleanup(patch.stop)
    for producer in witnesses:
        mm.register_producer(producer)


class KeyedDerivedPathTest(SimpleTestCase):

    def test_a_keyed_file_lives_in_the_hidden_folder_and_maps_back_to_its_original(self):
        for original, stored in (
                ('users/7/converter/input/clip.mp4',
                 'users/7/.preview/converter/input/clip.mp4.shots.marks.json'),
                ('system_assets/song.wav', '.preview/system_assets/song.wav.shots.marks.json')):
            self.assertEqual(stored, vc.derived_rel(original, vc.keyed_suffix('shots')))
            self.assertEqual(original, vc.original_of_copy(stored))

    def test_a_key_is_an_identifier_and_anything_else_is_not_derived(self):
        with self.assertRaises(ValueError):
            vc.keyed_suffix('two words')
        self.assertEqual('', vc.original_of_copy('users/7/.preview/a/.marks.json'))
        self.assertEqual('', vc.original_of_copy('users/7/.preview/a/clip.mp4.two words.marks.json'))


class EveryProducerStatesItsFunctionTest(SimpleTestCase):
    """Generic : whatever the apps register."""

    def test_at_least_one_producer_is_registered_by_the_apps(self):
        self.assertTrue(mm.producers(), 'no app registers a producer of automatic tracks')

    def test_each_one_states_a_function_whose_output_and_settings_are_its_own(self):
        for key, producer in mm.producers().items():
            with self.subTest(producer=key):
                spec = fc.get(producer.function)
                self.assertIsNotNone(spec, f'{key} : function « {producer.function} » not in the '
                                           f'catalogue')
                self.assertEqual(producer.track.kind, spec.outputs[0].data_type)
                self.assertIn(spec.inputs[0].data_type, producer.natures)
                detect = fc.resolve_impl(producer.detect)
                taken = set(inspect.signature(detect).parameters)
                self.assertLessEqual({p.key for p in spec.params}, taken,
                                     'a declared setting the analysis does not take')
                # Ce que la piste déclare est ce que la fonction dit produire.
                self.assertLessEqual(set(producer.track.carried()),
                                     set(spec.outputs[0].produced_fields))
                # La fonction lancée (un nœud du Studio) prend son port d'entrée et l'appelant.
                job = set(inspect.signature(fc.resolve_impl(spec.impl)).parameters)
                self.assertLessEqual({spec.inputs[0].key, 'user_id'}, job)
                # Une analyse qui ne tourne pas sur la file commune nomme une tâche qui existe.
                if producer.task:
                    self.assertTrue(callable(getattr(fc.resolve_impl(producer.task), 'delay', None)),
                                    f'{key} : « {producer.task} » is no task')

    def test_the_tracks_of_one_analysis_are_one_pass(self):
        """Whatever the apps register : the producers that name the same analysis share what
        makes it one pass — and a model is never run by merely listing the tracks of a file."""
        shared = {}
        for producer in mm.producers().values():
            if producer.analysis:
                shared.setdefault(producer.analysis, []).append(producer)
        for name, mates in shared.items():
            with self.subTest(analysis=name):
                self.assertEqual(1, len({(p.detect, p.task, p.natures, p.function, p.on_demand)
                                         for p in mates}))
                self.assertEqual(1, len({p.derived.name for p in mates}), 'one queue mark')
                self.assertEqual(len(mates), len({p.derived.suffix for p in mates}),
                                 'one stored file per track')
        for key, producer in mm.producers().items():
            if producer.task:
                with self.subTest(producer=key):
                    self.assertTrue(producer.on_demand,
                                    'an analysis on the queue of an app is asked, never automatic')

    def test_the_registry_of_tracks_lists_what_the_producers_fill(self):
        from wama.common import registries
        entries = registries.get('tracks').entries()
        self.assertEqual(len(mm.producers()),
                         sum(1 for entry in entries.values() if entry['model'] == 'media'))
        for key, producer in mm.producers().items():
            with self.subTest(producer=key):
                app = fc.spec_app(fc.get(producer.function))
                self.assertEqual(
                    {'app': app, 'model': 'media', **marks.describe(producer.track),
                     'natures': list(producer.natures), 'function': producer.function,
                     'analysis': producer.analysis, 'on_demand': producer.on_demand},
                    entries[f'{app}.media.{key}'])

    def test_the_settings_of_an_analysis_go_through_the_declared_function(self):
        """The common door of a function : a number out of its declared bounds is bounded, an
        unreadable one is refused by name — before any analysis (the media need not exist)."""
        samples = {'video': 'clip.mp4', 'audio': 'song.wav', 'image': 'photo.png'}
        for key, producer in mm.producers().items():
            bounded = [p for p in fc.get(producer.function).params if p.max is not None]
            name = samples.get(producer.natures[0])
            if not bounded or not name:
                continue
            setting = bounded[0]
            with self.subTest(producer=key):
                self.assertEqual({setting.key: setting.max},
                                 mm._checked_params(producer, {setting.key: setting.max + 1}))
                with self.assertRaisesRegex(ValueError, setting.key):
                    mm.make_media_marks(f'users/0/nowhere/{name}', key,
                                        {setting.key: 'not a number'})

    def test_an_incoherent_statement_is_refused_when_registered(self):
        good = _witness()
        for name, bad in (
                ('a source', mm.Producer(track=Track(KEY, 'P', source='rows'), natures=('audio',),
                                         detect=good.detect)),
                ('no nature', mm.Producer(track=good.track, natures=(), detect=good.detect)),
                ('unknown nature', mm.Producer(track=good.track, natures=('smell',),
                                               detect=good.detect)),
                ('a key that is no identifier',
                 mm.Producer(track=Track('two words', 'P'), natures=('audio',), detect=good.detect)),
                ('a detect that is no path', mm.Producer(track=good.track, natures=('audio',),
                                                         detect='nowhere'))):
            with self.subTest(case=name), self.assertRaises(InvalidTracks):
                mm.register_producer(bad)
        self.assertNotIn(KEY, mm.producers())


@override_settings(CACHES=LOCMEM)
class MediaMarksServiceTest(TestCase):

    def setUp(self):
        from django.core.cache import cache
        cache.clear()
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root, True)
        media = override_settings(MEDIA_ROOT=self.root)
        media.enable()
        self.addCleanup(media.disable)
        _only(self, _witness())
        self.rel = 'users/7/composer/input/song.wav'
        self._write(self.rel, b'RIFF-not-really-audio')

    def _abs(self, rel):
        return os.path.join(self.root, rel)

    def _write(self, rel, content):
        os.makedirs(os.path.dirname(self._abs(rel)), exist_ok=True)
        with open(self._abs(rel), 'wb') as out:
            out.write(content)

    def _state(self, **kwargs):
        with mock.patch(TASK) as delay, self.captureOnCommitCallbacks(execute=True):
            state = mm.marks_state(self.rel, **kwargs)
        return state[KEY], delay

    def test_a_media_of_another_nature_has_no_automatic_track(self):
        self._write('users/7/notes.txt', b'x')
        self.assertEqual((), mm.media_tracks('users/7/notes.txt'))
        self.assertEqual({}, mm.marks_state('users/7/notes.txt'))

    def test_the_first_ask_queues_one_task_per_version_and_says_pending(self):
        state, delay = self._state()
        self.assertEqual({'status': 'pending'}, state)
        delay.assert_called_once_with(self.rel, KEY)
        state, again = self._state()
        self.assertEqual({'status': 'pending'}, state)
        again.assert_not_called()
        # La piste est là, vide, tant que l'analyse n'a pas tourné.
        self.assertEqual({KEY: []}, mm.read_media_tracks(self.rel))

    def test_the_marks_are_read_by_the_common_reader_until_the_original_is_replaced(self):
        self.assertTrue(mm.make_media_marks(self.rel, KEY))
        state, _delay = self._state()
        self.assertEqual({'status': 'ready', 'count': 2, 'start': 0.0, 'end': 5.0, 'params': {}},
                         state)
        tracks = mm.media_tracks(self.rel)
        self.assertEqual(
            [{'start': 0.0, 'end': 2.0, 'origin': KEY, 'name': 'intro'},
             {'start': 2.0, 'end': 5.0, 'origin': KEY, 'name': 'verse'}],
            marks.read_track(self.rel, KEY, tracks))
        said = marks.outline(self.rel, tracks)[KEY]
        self.assertEqual((2, DERIVED, ['label', 'mask']),
                         (said['count'], said['edits'], said['gestures']))
        _span, inside = marks.read_span(self.rel, 2.5, 3.0, tracks=tracks)
        self.assertEqual([1], [entry['rank'] for entry in inside[KEY]])
        self.assertEqual('Parts — 2 sur 0:05', mm.summary(self.rel, KEY))
        stored = self._abs(mm.producers()[KEY].derived.rel(self.rel))
        later = os.path.getmtime(stored) + 10
        os.utime(self._abs(self.rel), (later, later))
        state, delay = self._state()
        self.assertEqual('pending', state['status'], 'older than its original : analysed again')
        delay.assert_called_once()
        self.assertEqual([], mm.read_media_tracks(self.rel)[KEY], 'a stale track is not served')

    def test_an_analysis_is_kept_unless_other_settings_are_asked(self):
        with mock.patch(f'{__name__}.witness_rows', side_effect=witness_rows) as analysis:
            self.assertTrue(mm.make_media_marks(self.rel, KEY))
            self.assertTrue(mm.make_media_marks(self.rel, KEY), 'idempotent')
            self.assertEqual(1, analysis.call_count)
            self.assertTrue(mm.make_media_marks(self.rel, KEY, {'gap': 0.5}))
            self.assertEqual(2, analysis.call_count)
            self.assertTrue(mm.make_media_marks(self.rel, KEY, {'gap': 0.5}))
            self.assertTrue(mm.make_media_marks(self.rel, KEY), 'no setting asked : kept')
            self.assertEqual(2, analysis.call_count)
        self.assertEqual(2.5, mm.read_media_tracks(self.rel)[KEY][1]['start'])
        self.assertEqual({'gap': 0.5}, mm.marks_state(self.rel, schedule=False)[KEY]['params'])

    def test_a_failure_is_said_while_polling_and_retried_when_a_page_opens(self):
        self._write(self.rel, b'')
        self._state()
        self.assertFalse(mm.make_media_marks(self.rel, KEY))
        state, delay = self._state()
        self.assertEqual({'status': 'failed'}, state)
        delay.assert_not_called()
        state, delay = self._state(retry_failed=True)
        self.assertEqual({'status': 'pending'}, state)
        delay.assert_called_once_with(self.rel, KEY)

    def test_a_stored_file_of_another_shape_is_not_a_track(self):
        mm.producers()[KEY].derived.store(self.rel, {'v': 0, 'rows': [1]})
        state, delay = self._state()
        self.assertEqual('pending', state['status'])
        delay.assert_called_once()
        mm.producers()[KEY].derived.store(self.rel, {'v': 0, 'marks': [{'start': 9, 'end': 9.5}]})
        self.assertTrue(mm.make_media_marks(self.rel, KEY), 'an older shape is analysed again')
        self.assertEqual(2, len(mm.read_media_tracks(self.rel)[KEY]))

    def test_an_unknown_producer_or_a_media_it_does_not_take_is_refused(self):
        with self.assertRaises(ValueError):
            mm.make_media_marks(self.rel, 'nobody')
        self._write('users/7/notes.txt', b'x')
        with self.assertRaises(ValueError):
            mm.make_media_marks('users/7/notes.txt', KEY)

    def test_nothing_is_analysed_or_stored_outside_the_media(self):
        """Every door that takes a path goes through the common guard of the media
        (`media_paths.resolve_under_media_root`) : absolute or relative, it stays inside."""
        self.assertEqual(self.rel, mm.media_rel(self._abs(self.rel)))
        self.assertEqual(self.rel, mm.media_rel(self.rel.replace('/', '\\')))
        for outside in ('../outside/song.wav', os.path.join(os.path.dirname(self.root), 'song.wav'),
                        'users/7/../../../song.wav', ''):
            with self.subTest(path=outside):
                self.assertEqual('', mm.media_rel(outside))
                with self.assertRaises(ValueError):
                    mm.make_media_marks(outside, KEY)
        self.assertTrue(mm.make_media_marks(self._abs(self.rel), KEY), 'its absolute path is it')
        self.assertEqual(2, len(mm.read_media_tracks(self.rel)[KEY]))

    def test_the_task_makes_what_the_service_makes(self):
        from wama.common.tasks import make_media_marks_task
        self.assertTrue(make_media_marks_task.run(self.rel, KEY))
        self.assertEqual(2, len(mm.read_media_tracks(self.rel)[KEY]))

    def test_the_marks_go_with_their_original_and_the_sweep_knows_them(self):
        mm.make_media_marks(self.rel, KEY)
        stored = self._abs(mm.producers()[KEY].derived.rel(self.rel))
        self.assertTrue(os.path.exists(stored))
        self.assertEqual({'seen': 1, 'removed': 0}, vc.sweep_orphan_playback_copies())
        self.assertTrue(vc.drop_playback_copy(self.rel), 'what was drawn from a file goes with it')
        self.assertFalse(os.path.exists(stored))
        mm.make_media_marks(self.rel, KEY)
        os.remove(self._abs(self.rel))
        self.assertEqual({'seen': 1, 'removed': 1}, vc.sweep_orphan_playback_copies())


@override_settings(CACHES=LOCMEM)
class SharedAnalysisTest(TestCase):
    """A producer with a MODEL : one pass for several tracks, asked — or deposited by the process
    of a card that already ran it."""

    def setUp(self):
        from django.core.cache import cache
        cache.clear()
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root, True)
        media = override_settings(MEDIA_ROOT=self.root)
        media.enable()
        self.addCleanup(media.disable)
        _only(self, *_witness_pass())
        _WitnessTask.sent = []
        self.user = get_user_model().objects.create_user('pass_owner', password='x')
        self.rel = f'users/{self.user.pk}/composer/input/song.wav'
        self._write(b'RIFF-not-really-audio')

    def _write(self, content):
        path = os.path.join(self.root, self.rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'wb') as out:
            out.write(content)

    def _state(self, **kwargs):
        with self.captureOnCommitCallbacks(execute=True):
            return mm.marks_state(self.rel, **kwargs)

    def test_listing_the_tracks_never_runs_the_model_and_asking_one_queues_one_pass(self):
        self.assertEqual({BARS: {'status': 'none', 'on_demand': True},
                          TONES: {'status': 'none', 'on_demand': True}},
                         self._state(retry_failed=True))
        self.assertEqual([], _WitnessTask.sent, 'a listing occupies no graphics card')
        state = self._state(asked=(TONES,))
        self.assertEqual({'status': 'pending'}, state[TONES])
        self.assertEqual([(self.rel, TONES)], _WitnessTask.sent, 'on the queue of its app')
        # La passe est UNE : l'autre piste la sait en file, et la demander n'en lance pas une autre.
        self.assertEqual('pending', self._state(asked=(BARS,))[BARS]['status'])
        self.assertEqual(1, len(_WitnessTask.sent))

    def test_one_pass_fills_every_track_of_the_analysis(self):
        with mock.patch(f'{__name__}.witness_pass', side_effect=witness_pass) as analysis:
            self.assertTrue(mm.make_media_marks(self.rel, TONES))
            self.assertTrue(mm.make_media_marks(self.rel, BARS), 'already there')
            self.assertEqual(1, analysis.call_count)
        read = mm.read_media_tracks(self.rel)
        self.assertEqual(([1, 2], ['C']), ([m['number'] for m in read[BARS]],
                                          [m['tone'] for m in read[TONES]]))
        state = self._state()
        self.assertEqual(('ready', 2, 'ready', 1), (state[BARS]['status'], state[BARS]['count'],
                                                    state[TONES]['status'], state[TONES]['count']))
        self.assertEqual([], _WitnessTask.sent)

    def test_a_track_the_pass_leaves_empty_is_ready_and_empty(self):
        self._write(b'ATONAL')
        self.assertTrue(mm.make_media_marks(self.rel, TONES), 'analysed : nothing to find')
        state = self._state(asked=(TONES, BARS))
        self.assertEqual(('ready', 0, 2), (state[TONES]['status'], state[TONES]['count'],
                                           state[BARS]['count']))
        self.assertEqual([], _WitnessTask.sent, 'an empty track is not analysed again')

    def test_a_pass_that_finds_nothing_at_all_is_a_failure_of_every_track(self):
        self._write(b'')
        self.assertFalse(mm.make_media_marks(self.rel, BARS))
        state = self._state(asked=(BARS, TONES))
        self.assertEqual({'failed'}, {state[BARS]['status'], state[TONES]['status']})
        self.assertEqual([], _WitnessTask.sent)
        self.assertEqual('pending', self._state(asked=(TONES,), retry_failed=True)[TONES]['status'])
        self.assertEqual([(self.rel, TONES)], _WitnessTask.sent)

    def test_what_a_process_already_computed_is_deposited_not_computed_again(self):
        found = {BARS: [{'start': 0.0, 'end': 3.0, 'number': 1}], TONES: []}
        with mock.patch(f'{__name__}.witness_pass') as analysis:
            self.assertTrue(mm.deposit(self.rel, PASS, found))
            self.assertTrue(mm.make_media_marks(self.rel, TONES), 'deposited : kept')
            analysis.assert_not_called()
        read = mm.read_media_tracks(self.rel)
        self.assertEqual(([1], []), ([m['number'] for m in read[BARS]], read[TONES]))
        self.assertEqual('ready', self._state()[TONES]['status'])
        # Rien à ranger, une analyse que personne ne déclare, un média absent : rien, sans lever.
        self.assertFalse(mm.deposit(self.rel, PASS, {BARS: [], TONES: []}))
        self.assertFalse(mm.deposit(self.rel, PASS, None))
        self.assertFalse(mm.deposit(self.rel, 'nobody', found))
        self.assertFalse(mm.deposit(f'users/{self.user.pk}/nowhere.wav', PASS, found))
        self.assertFalse(mm.deposit(f'users/{self.user.pk}/notes.txt', PASS, found))

    def test_a_pass_that_could_not_start_is_said_failed(self):
        self._state(asked=(BARS,))
        mm.mark_failed(self.rel, BARS)
        self.assertEqual('failed', self._state(asked=(BARS,))[BARS]['status'])
        mm.mark_failed(self.rel, 'nobody')      # ne lève jamais

    def test_the_tracks_of_one_analysis_must_state_the_same_pass(self):
        other = _witness_pass(detect=f'{__name__}:witness_rows')[0]
        with self.assertRaisesRegex(InvalidTracks, PASS):
            mm.register_producer(other)
        for bad in (_witness_pass(task='nowhere')[0], _witness_pass(analysis='two words')[0]):
            with self.assertRaises(InvalidTracks):
                mm.register_producer(bad)
        self.assertEqual(f'{__name__}:witness_pass', mm.producers()[BARS].detect)

    def test_the_assistant_lists_them_as_on_demand_and_runs_the_one_it_names(self):
        with self.captureOnCommitCallbacks(execute=True):
            answer = T.execute_tool('get_file_marks', {'file_path': self.rel}, self.user)
        self.assertEqual([(BARS, 'none', True), (TONES, 'none', True)],
                         [(t['key'], t['status'], t.get('on_demand')) for t in answer['tracks']])
        self.assertEqual([], _WitnessTask.sent)
        with self.captureOnCommitCallbacks(execute=True):
            answer = T.execute_tool('get_file_marks', {'file_path': self.rel, 'track': BARS},
                                    self.user)
        self.assertEqual(('pending', BARS), (answer['status'], answer['track']))
        self.assertEqual([(self.rel, BARS)], _WitnessTask.sent)
        mm.make_media_marks(self.rel, BARS)
        answer = T.execute_tool('get_file_marks', {'file_path': self.rel}, self.user)
        self.assertEqual([('ready', None), ('ready', None)],
                         [(t['status'], t.get('on_demand')) for t in answer['tracks']])


@override_settings(CACHES=LOCMEM)
class GetFileMarksTest(TestCase):
    """The assistant's door : its own files, the analysis queued by the first ask."""

    def setUp(self):
        from django.core.cache import cache
        cache.clear()
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root, True)
        media = override_settings(MEDIA_ROOT=self.root)
        media.enable()
        self.addCleanup(media.disable)
        _only(self, _witness())
        self.user = get_user_model().objects.create_user('marks_owner', password='x')
        self.rel = f'users/{self.user.pk}/temp/song.wav'
        os.makedirs(os.path.dirname(os.path.join(self.root, self.rel)))
        with open(os.path.join(self.root, self.rel), 'wb') as out:
            out.write(b'RIFF-not-really-audio')

    def _ask(self, **arguments):
        with mock.patch(TASK) as delay, self.captureOnCommitCallbacks(execute=True):
            answer = T.execute_tool('get_file_marks', {'file_path': self.rel, **arguments},
                                    self.user)
        return answer, delay

    def test_the_first_ask_lists_the_tracks_and_queues_the_analysis(self):
        answer, delay = self._ask()
        self.assertEqual(self.rel, answer['file'])
        self.assertEqual([(KEY, 'Parts', 'pending', 0)],
                         [(t['key'], t['label'], t['status'], t['count'])
                          for t in answer['tracks']])
        delay.assert_called_once_with(self.rel, KEY)
        answer, again = self._ask(track=KEY)
        self.assertEqual(('pending', KEY), (answer['status'], answer['track']))
        self.assertNotIn('marks', answer)
        again.assert_not_called()

    def test_a_ready_track_is_read_whole_or_bounded_by_pages(self):
        mm.make_media_marks(self.rel, KEY)
        answer, delay = self._ask()
        delay.assert_not_called()
        self.assertEqual([('ready', 2, 0.0, 5.0)],
                         [(t['status'], t['count'], t['start'], t['end'])
                          for t in answer['tracks']])
        answer, _delay = self._ask(track=KEY, limit=1)
        self.assertEqual(('ready', 2, 1, 1), (answer['status'], answer['total'],
                                              answer['returned'], answer['next_offset']))
        self.assertEqual('intro', answer['marks'][0]['mark']['name'])
        answer, _delay = self._ask(track=KEY, within_track=KEY, within_mark=1)
        self.assertEqual([1], [entry['rank'] for entry in answer['marks']])
        self.assertEqual({'start': 2.0, 'end': 5.0, 'track': KEY, 'rank': 1}, answer['span'])

    def test_a_failed_analysis_is_retried_by_the_next_ask(self):
        with open(os.path.join(self.root, self.rel), 'wb'):
            pass
        self._ask()
        self.assertFalse(mm.make_media_marks(self.rel, KEY))
        answer, delay = self._ask(track=KEY)
        self.assertEqual('pending', answer['status'])
        delay.assert_called_once_with(self.rel, KEY)

    def test_refusals_are_said(self):
        other = get_user_model().objects.create_user('marks_other', password='x')
        self.assertIn('error', T.execute_tool('get_file_marks', {'file_path': self.rel}, other))
        self.assertIn('error', T.get_file_marks(None, self.rel))
        notes = f'users/{self.user.pk}/temp/notes.txt'
        with open(os.path.join(self.root, notes), 'wb') as out:
            out.write(b'x')
        answer = T.execute_tool('get_file_marks', {'file_path': notes}, self.user)
        self.assertIn('audio', answer['error'], 'the natures that are analysed are named')
        answer, _delay = self._ask(track='nothing')
        self.assertIn(KEY, answer['error'])
