"""MARKS — the events and segments of a card, read under ONE vocabulary (`catalog/marks.py`).

Step 1 of `WAMA_APP_GENERATION_ROUTE.md §10.7` (Fabien, 2026-11-24 : « aligner tout le
fonctionnement temporel de WAMA »). An app states its tracks ; one reader gives the marks under
the common names, whatever the way they are stored. No app is named in the behaviour tests ; the
last class loops over every registered statement.
"""
import ast
import copy
import json
from pathlib import Path
from types import SimpleNamespace

from django.apps import apps as django_apps
from django.conf import settings
from django.test import SimpleTestCase

from wama.common.catalog import marks
from wama.common.catalog.data_types import CANONICAL_FIELDS, DataType
from wama.common.catalog.marks import INCLUSION, PARTITION, Track


def _card(label, **values):
    return SimpleNamespace(_meta=SimpleNamespace(label_lower=label), **values)


class _Registered:
    """A statement registered for the time of a test, then removed."""

    def __init__(self, label, tracks):
        self.label, self.tracks = label, tracks

    def __enter__(self):
        marks.register_tracks(self.label, self.tracks)
        return self

    def __exit__(self, *exc):
        marks._REGISTRY.pop(self.label, None)


CALLS = []


def rows_by_path(card):
    """Read through its dotted path (`'module:function'`)."""
    CALLS.append(card)
    return card.rows


class OneReaderTest(SimpleTestCase):

    def test_a_track_is_read_under_the_common_names_whatever_the_stored_ones(self):
        tracks = (
            Track('windows', 'Windows', source='windows',
                  fields=(('start', 't_enter'), ('end', 't_exit')), attributes=('name',)),
            Track('beeps', 'Beeps', source='beeps', kind=DataType.EVENTS,
                  fields=(('time', 'ts'),), attributes=(('value', 'level'),), origin='sensor'),
        )
        card = _card('t.card',
                     windows=[{'t_enter': 2, 't_exit': 5.5, 'name': 'A', 'radius': 40},
                              SimpleNamespace(t_enter=7.0, t_exit=None, name=''),
                              {'t_enter': None, 't_exit': 3}, {'name': 'no time at all'}],
                     beeps=SimpleNamespace(all=lambda: [{'ts': 1.5, 'level': 3}, {'ts': 'x'}]))
        with _Registered('t.card', tracks):
            read = marks.read_tracks(card)
        self.assertEqual([{'start': 2.0, 'end': 5.5, 'name': 'A', 'origin': 'windows'},
                          {'start': 7.0, 'end': None, 'origin': 'windows'}], read['windows'],
                         'a row or an object ; an end that is absent is an OPEN segment ; a row '
                         'without a start is no mark ; only the stated attributes are kept')
        self.assertEqual([{'time': 1.5, 'value': 3, 'origin': 'sensor'}], read['beeps'])
        self.assertEqual(['windows', 'beeps'], list(read), 'in the stated order')
        # The names are those of the data types : what the Segmenter already reads.
        self.assertEqual(CANONICAL_FIELDS[DataType.SEGMENTS], [k for k in read['windows'][0]][:2])
        self.assertEqual(CANONICAL_FIELDS[DataType.EVENTS], [k for k in read['beeps'][0]][:1])

    def test_the_marks_of_a_track_say_their_parent_in_three_ways(self):
        tracks = (
            Track('turns', 'Turns', runs_of='lines', by='speaker'),
            Track('lines', 'Lines', source=f'{__name__}:rows_by_path',
                  fields=(('start', 'start_time'), ('end', 'end_time')),
                  attributes=('text', ('speaker', 'speaker_id')), parent='turns'),
            Track('words', 'Words', within='words', parent='lines',
                  attributes=(('text', 'word'),), origin='engine', origin_field='timing'),
            Track('notes', 'Notes', source='notes', parent='lines', parent_ref='line'),
        )
        card = _card('t.talk', rows=[
            {'start_time': 0, 'end_time': 2, 'text': 'a b', 'speaker_id': 'S1',
             'words': [{'word': 'a', 'start': 0, 'end': 1}, {'word': 'b', 'start': 1, 'end': 2,
                                                            'timing': 'estimated'}]},
            {'start_time': None, 'text': 'untimed', 'words': [{'word': 'x', 'start': 9, 'end': 9.5}]},
            {'start_time': 2.5, 'end_time': 4, 'text': 'c', 'speaker_id': 'S1', 'words': None},
            {'start_time': 4, 'end_time': 6, 'text': 'd', 'speaker_id': 'S2',
             'words': [{'word': 'd', 'start': 4.2, 'end': 5}]}],
            notes=[{'start': 0.5, 'end': 0.6, 'line': 2}, {'start': 1, 'end': 1, 'line': -1},
                   {'start': 1, 'end': 1, 'line': 9}])
        del CALLS[:]
        with _Registered('t.talk', tracks):
            read = marks.read_tracks(card)
            self.assertEqual(read['words'], marks.read_track(card, 'words'))
        self.assertEqual([{'start': 0.0, 'end': 4.0, 'origin': 'runs', 'speaker': 'S1'},
                          {'start': 4.0, 'end': 6.0, 'origin': 'runs', 'speaker': 'S2'}],
                         read['turns'], 'DERIVED : the runs of lines of one speaker')
        self.assertEqual([0, 0, 1], [m['parent'] for m in read['lines']],
                         'by CONTAINMENT : the turn whose bounds hold its start')
        self.assertEqual([('a', 0, 'engine'), ('b', 0, 'estimated'), ('x', None, 'engine'),
                          ('d', 2, 'engine')],
                         [(m['text'], m['parent'], m['origin']) for m in read['words']],
                         'by CONSTRUCTION : the rank of its line among the lines READ — the '
                         'words of an untimed line have no parent')
        self.assertEqual([2, None, None], [m['parent'] for m in read['notes']],
                         'by REFERENCE : a rank outside the track is no parent')
        self.assertEqual(2, len(CALLS), 'one reading of the source per reading of the card')

    def test_a_track_that_was_not_stated_is_an_error_and_a_card_without_tracks_reads_empty(self):
        self.assertEqual({}, marks.read_tracks(_card('t.none')))
        self.assertEqual((), marks.tracks_of(_card('t.none')))
        with _Registered('t.one', (Track('a', 'A', source='a'),)):
            with self.assertRaises(KeyError):
                marks.read_track(_card('t.one', a=[]), 'b')


class TracksStatedOnTheSpotTest(SimpleTestCase):
    """A holder no app states tracks for — the streams of a data file — is read by the SAME reader,
    with the tracks its source states on the spot."""

    TRACKS = (Track('blocks', 'Blocks', source=lambda holder: holder['blocks']),
              Track('steps', 'Steps', source=lambda holder: holder['steps'], parent='blocks',
                    constraint=INCLUSION, attributes=('name',)))
    HOLDER = {'blocks': [{'start': 0, 'end': 10}, {'start': 10, 'end': None}],
              'steps': [{'start': 1, 'end': 2, 'name': 'a'}, {'start': 12, 'end': 30, 'name': 'b'}]}

    def test_they_are_read_and_checked_like_registered_ones(self):
        read = marks.read_tracks(self.HOLDER, self.TRACKS)
        self.assertEqual(['blocks', 'steps'], list(read))
        self.assertEqual([('a', 0), ('b', 1)], [(m['name'], m['parent']) for m in read['steps']])
        self.assertEqual(read['steps'], marks.read_track(self.HOLDER, 'steps', self.TRACKS))
        self.assertEqual([], marks.violations(self.HOLDER, 'steps', tracks=self.TRACKS))
        late = dict(self.HOLDER, steps=[{'start': 8, 'end': 11, 'name': 'c'}])
        self.assertEqual(1, len(marks.violations(late, 'steps', tracks=self.TRACKS)))
        self.assertNotIn('', marks.registered(), 'nothing was registered for it')

    def test_what_is_stated_on_the_spot_replaces_what_an_app_registered(self):
        card = _card('t.spot', rows=[{'start': 1, 'end': 2}])
        with _Registered('t.spot', (Track('rows', 'Rows', source='rows'),)):
            self.assertEqual(['rows'], list(marks.read_tracks(card)))
            self.assertEqual(['one'], list(marks.read_tracks(
                card, (Track('one', 'One', source='rows'),))))

    def test_an_incoherent_statement_is_turned_down_before_anything_is_read(self):
        read = []
        orphan = (Track('steps', 'Steps', source=lambda holder: read.append(1) or [],
                        parent='nowhere'),)
        for reading in (lambda: marks.read_tracks(self.HOLDER, orphan),
                        lambda: marks.read_track(self.HOLDER, 'steps', orphan),
                        lambda: marks.violations(self.HOLDER, 'steps', tracks=orphan)):
            with self.assertRaises(marks.InvalidTracks):
                reading()
        self.assertEqual([], read)
        with self.assertRaises(KeyError):
            marks.read_track(self.HOLDER, 'absent', self.TRACKS)


class StatedConstraintsTest(SimpleTestCase):

    def _problems(self, constraint, parents, children):
        tracks = (Track('up', 'Up', source='up'),
                  Track('down', 'Down', source='down', parent='up', constraint=constraint))
        with _Registered('t.c', tracks):
            return marks.violations(_card('t.c', up=parents, down=children), 'down')

    def test_inclusion_holds_each_mark_inside_its_parent_and_allows_gaps(self):
        up = [{'start': 0, 'end': 10}, {'start': 10, 'end': None}]
        self.assertEqual([], self._problems(INCLUSION, up, [
            {'start': 1, 'end': 3}, {'start': 6, 'end': 10.04}, {'start': 12, 'end': None}]))
        problems = self._problems(INCLUSION, up[:1], [{'start': 8, 'end': 11}, {'start': 20, 'end': 21}])
        self.assertEqual(2, len(problems), problems)
        self.assertIn('down[0]', problems[0])
        self.assertIn('aucune marque parente', problems[1])
        self.assertEqual([], self._problems('', up[:1], [{'start': 8, 'end': 11}]),
                         'no constraint stated, nothing owed')

    def test_partition_also_covers_the_parent_without_gap_nor_overlap(self):
        up = [{'start': 0, 'end': 9}]
        self.assertEqual([], self._problems(PARTITION, up, [
            {'start': 0, 'end': 4}, {'start': 4, 'end': 9}]))
        for children in ([{'start': 0, 'end': 4}, {'start': 5, 'end': 9}],        # a gap
                         [{'start': 0, 'end': 5}, {'start': 4, 'end': 9}],        # an overlap
                         [{'start': 0, 'end': 4}, {'start': 4, 'end': 8}],        # not to the end
                         [{'start': 1, 'end': 9}]):                               # not from the start
            with self.subTest(children=children):
                self.assertTrue(self._problems(PARTITION, up, children))


class IncoherentStatementsTest(SimpleTestCase):

    def test_a_statement_that_cannot_be_read_is_turned_down_when_it_is_registered(self):
        bad = {
            'twice': (Track('a', 'A', source='a'), Track('a', 'A', source='a')),
            'unknown parent': (Track('a', 'A', source='a', parent='z'),),
            'unknown axis': (Track('a', 'A', source='a', axis='colour'),),
            'not a mark': (Track('a', 'A', source='a', kind=DataType.TABLE),),
            'unknown constraint': (Track('a', 'A', source='a'),
                                   Track('b', 'B', source='b', parent='a', constraint='tight')),
            'two origins': (Track('a', 'A', source='a'),
                            Track('b', 'B', source='b', within='kids', parent='a')),
            'no origin': (Track('a', 'A'),),
            'within without parent': (Track('a', 'A', within='kids'),),
            'constraint without parent': (Track('a', 'A', source='a', constraint=INCLUSION),),
            'runs without field': (Track('a', 'A', source='a'), Track('b', 'B', runs_of='a')),
            'lineage loop': (Track('a', 'A', source='a', parent='b'),
                             Track('b', 'B', source='b', parent='a')),
            'derivation loop': (Track('a', 'A', runs_of='b', by='x'),
                                Track('b', 'B', runs_of='a', by='x')),
            'another axis than its parent': (Track('a', 'A', source='a'),
                                             Track('b', 'B', source='b', parent='a', axis='page')),
            # What the screen and the gestures have to know (`ROUTE §10.7.14`).
            'two main tracks': (Track('a', 'A', source='a', main=True),
                                Track('b', 'B', source='b', main=True)),
            'a colour without its scale': (Track('a', 'A', source='a', attributes=('kind',),
                                                 color_by='kind'),),
            'a scale without its colour': (Track('a', 'A', source='a', scale=marks.CATEGORY),),
            'an unknown scale': (Track('a', 'A', source='a', attributes=('kind',),
                                       color_by='kind', scale='rainbow'),),
            'coloured by what no mark carries': (Track('a', 'A', source='a', color_by='kind',
                                                       scale=marks.CATEGORY),),
            'a severity without its three steps': (Track('a', 'A', source='a', attributes=('level',),
                                                         color_by='level', scale=marks.SEVERITY,
                                                         steps=('low', 'high')),),
            'a severity with the same step twice': (Track('a', 'A', source='a', attributes=('level',),
                                                          color_by='level', scale=marks.SEVERITY,
                                                          steps=('low', 'low', 'high')),),
            'an intensity whose bounds are not numbers': (Track('a', 'A', source='a',
                                                                attributes=('gap',), color_by='gap',
                                                                scale=marks.INTENSITY,
                                                                steps=('near', 'far')),),
            'an intensity with one bound twice': (Track('a', 'A', source='a', attributes=('gap',),
                                                        color_by='gap', scale=marks.INTENSITY,
                                                        steps=(2, 2)),),
            'a category with steps': (Track('a', 'A', source='a', attributes=('kind',),
                                            color_by='kind', scale=marks.CATEGORY, steps=('x',)),),
            'steps without a scale': (Track('a', 'A', source='a', steps=(1, 2)),),
            'an unknown gesture': (Track('a', 'A', source='a', gestures=('juggle',),
                                         edits=marks.DERIVED),),
            'a changing gesture that says nowhere to go': (Track('a', 'A', source='a',
                                                                 gestures=('split',)),),
            'a place to go and nothing that changes': (Track('a', 'A', source='a',
                                                             gestures=('extract',),
                                                             edits=marks.IN_PLACE),),
            'an unknown place to go': (Track('a', 'A', source='a', gestures=('mask',),
                                             edits='elsewhere'),),
        }
        for case, tracks in bad.items():
            with self.subTest(case=case):
                self.assertTrue(marks.validate(tracks))
                with self.assertRaises(marks.InvalidTracks):
                    marks.register_tracks('t.bad', tracks)
        self.assertNotIn('t.bad', marks.registered(), 'nothing of it is kept')
        # A derived track may stand ABOVE the track it groups : turns over the lines they are
        # the runs of — two chains, no loop.
        self.assertEqual([], marks.validate((
            Track('turns', 'T', runs_of='lines', by='speaker'),
            Track('lines', 'L', source='rows', parent='turns', constraint=INCLUSION))))
        # A track that is only looked at, one that only gives cards, a derived one coloured by
        # the value it groups : all coherent.
        self.assertEqual([], marks.validate((
            Track('turns', 'T', runs_of='lines', by='speaker', color_by='speaker',
                  scale=marks.CATEGORY),
            Track('lines', 'L', source='rows', parent='turns', main=True, gestures=('extract',)))))


class EveryStatedTrackTest(SimpleTestCase):
    """Generic : every app that states tracks, no app named. A new app enters by stating its own."""

    def test_two_worlds_state_their_tracks(self):
        worlds = {django_apps.get_model(label).__module__.split('.')[0]
                  for label in marks.registered()}
        self.assertGreaterEqual(len(worlds), 2, 'a brick is common once two worlds use it')

    def test_every_statement_is_coherent_and_names_what_its_model_carries(self):
        for label, tracks in marks.registered().items():
            model = django_apps.get_model(label)
            with self.subTest(model=label):
                self.assertEqual([], marks.validate(tracks))
                self.assertTrue(all(t.label for t in tracks), 'what the screen calls it')
                for track in tracks:
                    source = track.source
                    if not source:
                        continue
                    if callable(source):
                        continue
                    if ':' in source:
                        module, _, name = source.partition(':')
                        found = getattr(__import__(module, fromlist=[name]), name, None)
                        self.assertTrue(callable(found), f'{track.key} : {source}')
                    else:
                        self.assertTrue(hasattr(model, source), f'{track.key} : {label}.{source}')

    def test_every_model_names_the_one_track_of_its_segmented_line(self):
        """The temporal zone of a card shows its whole line and ONE segmented line : the app says
        which track it is, the screen never picks one (`ROUTE §10.7.14`, E1)."""
        from wama.common.sandbox import twin_source
        seen = 0
        for label, tracks in marks.registered().items():
            if twin_source(label.split('.')[0]):
                continue    # a twin replays the statement of its source, once it is regenerated
            seen += 1
            with self.subTest(model=label):
                self.assertEqual(1, sum(track.main for track in tracks))
                for track in tracks:
                    if track.color_by:
                        self.assertIn(track.color_by, track.carried())
        self.assertGreaterEqual(seen, 2, 'the apps that state, not their twins')

    def test_the_registry_of_tracks_names_every_stated_track_and_only_those(self):
        """What a surface asks (« which tracks does this kind of card carry ? ») is answered by the
        common registry, derived from the statements at each reading."""
        from wama.common import registries
        registry = registries.get('tracks')
        entries = registry.entries()
        stated = {f'{label}.{track.key}': track
                  for label, tracks in marks.registered().items() for track in tracks}
        self.assertEqual(sorted(stated), sorted(entries))
        self.assertEqual(len(stated), registry.count())
        for key, track in stated.items():
            entry = entries[key]
            with self.subTest(track=key):
                self.assertEqual((track.kind, track.axis, track.parent, track.constraint, track.label),
                                 (entry['kind'], entry['axis'], entry['parent'],
                                  entry['constraint'], entry['label']))
                self.assertEqual(key, f"{entry['model']}.{track.key}")
                self.assertEqual(entry['app'], django_apps.get_model(entry['model'])._meta.app_label)
                self.assertEqual('derived' if track.runs_of else 'nested' if track.within
                                 else 'stored', entry['rows'])
                self.assertEqual(
                    (track.main, track.color_by, track.scale, list(track.steps),
                     list(track.gestures), track.edits),
                    (entry['main'], entry['color_by'], entry['scale'], entry['steps'],
                     entry['gestures'], entry['edits']), 'what the screen and the gestures need')
                if entry['parent']:
                    self.assertIn(f"{entry['model']}.{entry['parent']}", entries)

    def test_every_statement_gives_marks_under_the_common_names_only(self):
        """Whatever the stored names, a mark read through a real statement carries `start` and
        `end`, or `time` — a stand-in card whose rows answer every stored name with a number."""
        class Row(dict):
            lists, ranks = (), ()

            def get(self, name, default=None):
                if name in self.lists:
                    return [Row()]
                return 0 if name in self.ranks else 1.0

        for label, tracks in marks.registered().items():
            Row.lists = tuple(t.within for t in tracks if t.within)
            Row.ranks = tuple(t.parent_ref for t in tracks if t.parent_ref)
            values = {t.source: [Row()] for t in tracks if isinstance(t.source, str) and ':' not in t.source}
            card = _card(label, **values)
            with self.subTest(model=label):
                stored = {name for t in tracks for _common, name in t.fields}
                for track in tracks:
                    if track.source and (callable(track.source) or ':' in track.source):
                        continue            # read by a function of the app : its own test
                    if track.runs_of or track.within:
                        base = next(t for t in tracks if t.key in (track.runs_of, track.parent))
                        if base.source and (callable(base.source) or ':' in str(base.source)):
                            continue
                    for mark in marks.read_track(card, track.key):
                        self.assertFalse(stored & set(mark) - {'start', 'end', 'time'},
                                         f'{track.key} : a stored name went through')
                        self.assertTrue({'start', 'end'} <= set(mark) or 'time' in mark)
                        self.assertIn('origin', mark)
                        if track.parent_ref:
                            self.assertEqual(0, mark['parent'], 'the rank its row names')


DRAFT = Path(settings.BASE_DIR) / 'manifests' / 'app_drafts' / 'writer.json'


class TracksInTheManifestTest(SimpleTestCase):
    """Schema-driven to the end : the statement of an app is a facet of its manifest
    (`inspector.tracks`), which the generator replays in the `ready()` of an app born from it."""

    STATED = (
        Track('turns', "Tours d'un échange", runs_of='lines', by='speaker', origin='runs',
              color_by='speaker', scale=marks.CATEGORY),
        Track('lines', 'Lignes', source='wama.common.utils.durations:format_clock',
              fields=(('start', 'start_time'), ('end', 'end_time')),
              attributes=('text', ('speaker', 'speaker_id')), parent='turns', constraint=INCLUSION,
              main=True, gestures=('split', 'merge', 'mask', 'extract'), edits=marks.DERIVED),
        Track('beeps', 'Bips', source='beeps', kind=DataType.EVENTS, fields=(('time', 'ts'),),
              attributes=('level', 'gap'), parent='lines', parent_ref='line',
              color_by='level', scale=marks.SEVERITY, steps=('low', 'mid', 'high')),
    )

    def _manifest(self, tracks=None, model=None):
        manifest = json.loads(DRAFT.read_text(encoding='utf-8'))
        item = manifest['body']['processing']['item_model']
        stated = [marks.track_to_dict(t) for t in self.STATED] if tracks is None else tracks
        manifest['body'].setdefault('inspector', {})['tracks'] = {model or item: stated}
        return manifest, item

    def test_a_statement_goes_to_data_and_back_unchanged(self):
        for label, tracks in list(marks.registered().items()) + [('t.stated', self.STATED)]:
            with self.subTest(model=label):
                data = [marks.track_to_dict(t) for t in tracks]
                self.assertEqual(data, json.loads(json.dumps(data)), 'plain data')
                self.assertEqual(tuple(tracks), tuple(marks.track_from_dict(d) for d in data))
        self.assertEqual({'key': 'a', 'label': 'A', 'source': 'rows'},
                         marks.track_to_dict(Track('a', 'A', source='rows')), 'no default written')
        # A manifest keeps its keys SORTED : the order of the fields and of the attributes of a
        # track carries no meaning, and a track read back from it is the one that was stated.
        stated = Track('a', 'A', source='rows', fields=(('start', 't0'), ('end', 't1')),
                       attributes=('text', ('speaker', 'speaker_id'), 'level'))
        stored = json.loads(json.dumps(marks.track_to_dict(stated), sort_keys=True))
        self.assertEqual(stated, marks.track_from_dict(stored))
        self.assertEqual(stated, Track('a', 'A', source='rows', fields=(('end', 't1'), ('start', 't0')),
                                       attributes=('level', ('speaker', 'speaker_id'), 'text')))
        with self.assertRaises(marks.InvalidTracks):
            marks.track_to_dict(Track('a', 'A', source=len))
        with self.assertRaises(marks.InvalidTracks):
            marks.track_from_dict({'key': 'a', 'label': 'A', 'source': 'rows', 'colour': 'red'})
        # What the screen and the gestures have to know goes the same way : the two bounds of an
        # intensity keep their ORDER (calm first, even when it is the higher number), the gestures
        # are a set.
        shown = Track('a', 'A', source='rows', attributes=('gap',), main=True, color_by='gap',
                      scale=marks.INTENSITY, steps=(4.0, 2.0), gestures=('split', 'mask', 'split'),
                      edits=marks.DERIVED)
        self.assertEqual([], marks.validate((shown,)))
        data = json.loads(json.dumps(marks.track_to_dict(shown), sort_keys=True))
        self.assertEqual(([4.0, 2.0], ['mask', 'split'], True), (data['steps'], data['gestures'],
                                                                data['main']))
        self.assertEqual(shown, marks.track_from_dict(data))

    def test_the_facet_of_an_app_is_what_it_registered(self):
        from wama.common.manifests.builtin.app import _inspector
        from wama.common.manifests.codegen.source_safety import source_safety_errors
        seen = 0
        for label, tracks in marks.registered().items():
            app, model = label.split('.')[0], django_apps.get_model(label).__name__
            with self.subTest(model=label):
                facet = _inspector(app).get('tracks') or {}
                self.assertEqual([marks.track_to_dict(t) for t in tracks], facet.get(model))
                self.assertEqual([], source_safety_errors({'inspector': {'tracks': facet}}))
                seen += 1
        self.assertTrue(seen)
        self.assertNotIn('tracks', _inspector('no_such_app'), 'absent when nothing is stated')

    def test_the_generator_replays_the_statement_in_the_ready_of_the_app(self):
        from wama.common.manifests.codegen.apps_gen import render_apps
        manifest, item = self._manifest()
        source, reason = render_apps(manifest)
        self.assertIsNotNone(source, reason)
        compile(source, 'apps.py', 'exec')
        calls = [node for node in ast.walk(ast.parse(source)) if isinstance(node, ast.Call)
                 and getattr(node.func, 'id', '') == 'register_tracks']
        self.assertEqual(1, len(calls))
        self.assertEqual(item, calls[0].args[0].id)
        written = eval(compile(ast.Expression(calls[0].args[1]), 'tracks', 'eval'), {'Track': Track})
        self.assertEqual(self.STATED, written, 'the same tracks, from literals only')
        self.assertIn('from wama.common.catalog.marks import Track, register_tracks', source)
        plain, _reason = render_apps(json.loads(DRAFT.read_text(encoding='utf-8')))
        self.assertNotIn('register_tracks', plain, 'nothing for an app that states none')

    def test_a_statement_the_generator_cannot_replay_stops_the_rendering(self):
        from wama.common.manifests.codegen.apps_gen import render_apps
        good = [marks.track_to_dict(t) for t in self.STATED]
        cases = {
            'a model of another app': self._manifest(model='Stranger')[0],
            'an unknown field': self._manifest([{**good[2], 'colour': 'red'}])[0],
            'a parent that is not stated': self._manifest(good[1:2])[0],
        }
        for case, manifest in cases.items():
            with self.subTest(case=case):
                source, reason = render_apps(manifest)
                self.assertIsNone(source)
                self.assertIn('inspector.tracks', reason)

    def test_a_value_that_would_leave_its_place_in_the_code_is_turned_down(self):
        from wama.common.manifests.codegen.source_safety import source_safety_errors
        good = [marks.track_to_dict(t) for t in self.STATED]
        self.assertEqual([], source_safety_errors({'inspector': {'tracks': {'Item': good}}}))
        hostile = "x'); import os  #"
        for field in ('key', 'source', 'parent', 'origin'):
            with self.subTest(field=field):
                bad = copy.deepcopy(good)
                bad[1][field] = hostile
                self.assertTrue(source_safety_errors({'inspector': {'tracks': {'Item': bad}}}))
        for source in ('os:system', 'wama.x:y; z', 'subprocess.run'):
            with self.subTest(source=source):
                bad = copy.deepcopy(good)
                bad[1]['source'] = source
                self.assertTrue(source_safety_errors({'inspector': {'tracks': {'Item': bad}}}))

