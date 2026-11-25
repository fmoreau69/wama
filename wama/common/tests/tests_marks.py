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
                         read['turns'], 'COMPUTED : the runs of lines of one speaker')
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
            'an attribute under a name the reader writes': (Track('a', 'A', source='a',
                                                                  attributes=('masked',)),),
            'an instant that would be split': (Track('a', 'A', source='a', kind=DataType.EVENTS,
                                                     gestures=('mask', 'split'),
                                                     edits=marks.DERIVED),),
        }
        for case, tracks in bad.items():
            with self.subTest(case=case):
                self.assertTrue(marks.validate(tracks))
                with self.assertRaises(marks.InvalidTracks):
                    marks.register_tracks('t.bad', tracks)
        self.assertNotIn('t.bad', marks.registered(), 'nothing of it is kept')
        # A computed track may stand ABOVE the track it groups : turns over the lines they are
        # the runs of — two chains, no loop.
        self.assertEqual([], marks.validate((
            Track('turns', 'T', runs_of='lines', by='speaker'),
            Track('lines', 'L', source='rows', parent='turns', constraint=INCLUSION))))
        # Read under another common name, a stored `masked` is an attribute like any other ; and
        # `source` is no name of the reader — a segment of the Data world keeps there the origin
        # it had before its margins (`segmentation.margins`).
        self.assertEqual([], marks.validate((Track('a', 'A', source='a',
                                                   attributes=(('hidden', 'masked'), 'source')),)))
        self.assertNotIn('source', marks.RESERVED)
        # A track that is only looked at, one that only gives cards, a computed one coloured by
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
                self.assertEqual('computed' if track.runs_of else 'nested' if track.within
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


class DerivedTrackTest(SimpleTestCase):
    """A DERIVED track (`ROUTE §10.7.14 ⑰`, step 1ter) : a source track and the ordered list of
    the gestures made on it. The list is what is kept ; the reader replays it, the source is
    never changed, and a gesture that no longer finds its mark is skipped and SAID."""

    CHANGING = tuple(sorted(marks.EDIT_DETAILS))

    @staticmethod
    def _track(gestures, kind=DataType.SEGMENTS, **more):
        return Track('parts', 'Parts', source=lambda holder: holder['parts'], kind=kind,
                     attributes=('name',), gestures=gestures, edits=marks.DERIVED, **more)

    PARTS = [{'start': 0, 'end': 10, 'name': 'a'}, {'start': 10, 'end': 20, 'name': 'b'},
             {'start': 20, 'end': 30, 'name': 'c'}]

    def _made(self, track, rows, *gestures):
        """The list of gestures, each one made on the track as it stands after the others."""
        source = marks.read_track({'parts': rows}, 'parts', (track,))
        edits = []
        for gesture, mark, details in gestures:
            edits = marks.extend_edits(track, source, edits, gesture, mark, **details)
        return edits

    def test_the_gestures_are_replayed_and_the_source_is_left_as_it_was(self):
        track = self._track(('split', 'merge', 'mask', 'label'))
        holder = {'parts': copy.deepcopy(self.PARTS)}
        source = marks.read_track(holder, 'parts', (track,))
        untouched = copy.deepcopy(source)
        edits = self._made(track, self.PARTS,
                           ('split', 0, {'at': 4, 'by': 'ada', 'on': '2026-11-25'}),
                           ('merge', 1, {}),
                           ('mask', 1, {}),
                           ('label', 2, {'set': {'name': 'end', 'label': 'kept'}}))
        self.assertEqual({'gesture': 'split', 'mark': 0, 'at': 4, 'by': 'ada', 'on': '2026-11-25',
                          'was': {'start': 0.0, 'end': 10.0}}, edits[0],
                         'a gesture is DATA : what it does, to which mark, what that mark was')
        self.assertEqual({'start': 4.0, 'end': 10.0}, edits[1]['was'],
                         'a merge names its first segment ; the next ones follow it')
        derived, problems = marks.read_derived(holder, 'parts', edits, (track,))
        self.assertEqual([], problems)
        self.assertEqual([
            {'start': 0.0, 'end': 4.0, 'name': 'a', 'origin': 'parts', 'source_ranks': [0],
             'touched': [0]},
            {'start': 4.0, 'end': 20.0, 'name': 'a', 'origin': 'parts', 'source_ranks': [0, 1],
             'touched': [0, 1, 2], 'masked': True},
            {'start': 20.0, 'end': 30.0, 'name': 'end', 'label': 'kept', 'origin': 'parts',
             'source_ranks': [2], 'touched': [3]}], derived)
        self.assertEqual(untouched, source, 'the marks given are not changed')
        self.assertEqual(untouched, marks.read_track(holder, 'parts', (track,)),
                         'the source track still reads as before')
        self.assertEqual(self.PARTS, holder['parts'])
        self.assertEqual((derived, []), marks.apply_edits(track, source, json.loads(json.dumps(edits))),
                         'the list goes to JSON and back, and replays the same')
        self.assertEqual(([dict(m, source_ranks=[i]) for i, m in enumerate(source)], []),
                         marks.read_derived(holder, 'parts', [], (track,)),
                         'no gesture : the marks of the source, each one saying where it comes from')

    def test_a_gesture_finds_its_mark_by_its_place_and_says_when_it_moved_or_is_gone(self):
        """The rule of the human corrections of WAMA (`utils/detections.apply_corrections`) on an
        axis : a gesture names its mark by its PLACE, to outlive a track that is measured again."""
        from wama.common.utils import detections
        track = self._track(('split', 'merge', 'mask', 'label'))
        edits = self._made(track, self.PARTS, ('split', 0, {'at': 4}), ('merge', 1, {}),
                           ('mask', 1, {}), ('label', 2, {'set': {'name': 'end'}}))

        def replayed(rows, kept=edits):
            derived, reports = marks.read_derived({'parts': rows}, 'parts', kept, (track,))
            return ([(m['start'], m['end'], m['name'], bool(m.get('masked'))) for m in derived],
                    [(r['edit'], r['gesture'], r['applied']) for r in reports])

        done = [(0.0, 4.0, 'a', False), (4.0, 20.0, 'a', True), (20.0, 30.0, 'end', False)]
        self.assertEqual((done, []), replayed(self.PARTS))
        # Measured again, the first boundary went from 10 to 9 : every gesture still finds its
        # mark, and the two whose mark moved say so.
        again = [dict(self.PARTS[0], end=9), dict(self.PARTS[1], start=9), self.PARTS[2]]
        self.assertEqual((done, [(0, 'split', True), (1, 'merge', True)]), replayed(again))
        report = marks.read_derived({'parts': again}, 'parts', edits, (track,))[1][0]
        self.assertEqual(({'start': 0.0, 'end': 10.0}, {'start': 0.0, 'end': 9.0}),
                         (report['was'], report['now']), 'what the mark was, what it is')
        # Within the tolerance two bounds are the same : nothing to say.
        close = [dict(self.PARTS[0], end=10.03), dict(self.PARTS[1], start=10.03), self.PARTS[2]]
        self.assertEqual((done, []), replayed(close))
        # Its mark is GONE (the first segment now ends at 3) : the gesture is skipped and said,
        # never made on the neighbour ; the ones that still find their place are made.
        gone = [dict(self.PARTS[0], end=3), dict(self.PARTS[1], start=3), self.PARTS[2]]
        self.assertEqual(([(0.0, 3.0, 'a', False), (3.0, 20.0, 'b', True), (20.0, 30.0, 'end', False)],
                          [(0, 'split', False), (1, 'merge', False), (2, 'mask', True)]),
                         replayed(gone))
        # The threshold is the one of the corrections of detections, read there.
        self.assertIs(detections.CORRECTION_MIN_IOU, marks.CORRECTION_MIN_IOU)
        mask = [marks.new_edit('mask', [{'start': 0.0, 'end': 10.0}], 0)]
        for end, applied in ((5.2, [True]), (4.8, [False])):
            reports = marks.apply_edits(track, [{'start': 0.0, 'end': end}], mask)[1]
            self.assertEqual(applied, [r['applied'] for r in reports], end)
        # A gesture taken out of the middle of the list : those after it are made where their
        # marks now are, and say that these are not what they were.
        self.assertEqual(([(0.0, 20.0, 'a', True), (20.0, 30.0, 'end', False)],
                          [(0, 'merge', True), (1, 'mask', True)]), replayed(self.PARTS, edits[1:]))
        # Lifting a mask is taking it out : nothing else moves, nothing to say.
        self.assertEqual(([(0.0, 4.0, 'a', False), (4.0, 20.0, 'a', False), (20.0, 30.0, 'end', False)],
                          []), replayed(self.PARTS, edits[:2] + edits[3:]))
        # Two marks at the same place : the rank the gesture kept tells them apart.
        twins = [{'start': 0, 'end': 5, 'name': 'x'}, {'start': 0, 'end': 5, 'name': 'y'}]
        second = self._made(track, twins, ('mask', 1, {}))
        self.assertEqual([('x', False), ('y', True)],
                         [(name, masked) for _s, _e, name, masked in replayed(twins, second)[0]])
        # A gesture that names no place names no mark.
        self.assertEqual([(0, 'mask', False)],
                         replayed(self.PARTS, [{'gesture': 'mask', 'mark': 0}])[1])

    def test_only_what_the_track_states_is_done_and_a_gesture_that_cannot_be_never_enters(self):
        rows = [self.PARTS[0], self.PARTS[1], {'start': 20, 'end': None, 'name': 'c'}]
        every = self._track(self.CHANGING)
        source = marks.read_track({'parts': rows}, 'parts', (every,))
        cannot = [
            ('split', 0, {'at': 10}), ('split', 0, {'at': 0.01}), ('split', 0, {}),
            ('split', 7, {'at': 1}), ('split', True, {'at': 5}),
            ('merge', 0, {'count': 1}), ('merge', 2, {}), ('merge', 0, {'count': True}),
            ('label', 0, {'set': {'colour': 'red'}}), ('label', 0, {'set': {'start': 3}}),
            ('label', 0, {}), ('retime', 0, {'start': 5, 'end': 4}), ('retime', 0, {}),
            ('move', 0, {'to': 'x'}), ('reorder', 0, {'to': 0}), ('reorder', 0, {'to': 3}),
            ('add', None, {'end': 4}), ('add', None, {'start': 1, 'end': 2, 'time': 1}),
            ('add', 9, {'start': 1, 'end': 2}), ('add', None, {'start': 1, 'set': {'masked': 1}}),
            ('mask', 0, {'at': 3}), ('extract', 0, {}), ('paint', 0, {}),
        ]
        for gesture, mark, details in cannot:
            with self.subTest(gesture=gesture, mark=mark, details=details):
                with self.assertRaises(marks.InvalidEdit):
                    marks.extend_edits(every, source, [], gesture, mark, **details)
                # Written by hand into a list, it is skipped, said, and changes nothing.
                edit = marks.new_edit(gesture, source, mark, **details)
                derived, reports = marks.apply_edits(every, source, [edit])
                self.assertEqual([(0, gesture, False)],
                                 [(r['edit'], r['gesture'], r['applied']) for r in reports])
                self.assertEqual([dict(m, source_ranks=[i]) for i, m in enumerate(source)], derived)
        # A merge takes segments that follow one another and are all kept, or all masked.
        for first, wrong in ((('mask', 0, {}), 'masqué'), (('reorder', 2, {'to': 0}), 'suivent')):
            with self.subTest(merge_after=first[0]):
                edits = marks.extend_edits(every, source, [], first[0], first[1], **first[2])
                with self.assertRaisesRegex(marks.InvalidEdit, wrong):
                    marks.extend_edits(every, source, edits, 'merge', 0)
        # A track states what may be done to it : nothing else is, whoever wrote the list.
        looked_at = self._track(('mask',))
        for gesture, details in (('split', {'at': 5}), ('delete', {}), ('move', {'to': 3})):
            with self.subTest(not_stated=gesture):
                with self.assertRaises(marks.InvalidEdit):
                    marks.extend_edits(looked_at, source, [], gesture, 0, **details)
                derived, problems = marks.apply_edits(
                    looked_at, source, [marks.new_edit(gesture, source, 0, **details)])
                self.assertIn('ne le permet pas', problems[0]['reason'])
                self.assertEqual([m['start'] for m in source], [m['start'] for m in derived])
        self.assertEqual(set(marks.GESTURES) - {marks.EXTRACT}, set(marks.EDIT_DETAILS),
                         'every gesture that changes a track can be replayed, and only those')
        # An instant has no length (a statement saying otherwise is turned down when registered).
        beeps = Track('parts', 'Parts', source='x', kind=DataType.EVENTS,
                      gestures=marks.SEGMENT_GESTURES, edits=marks.DERIVED)
        self.assertTrue(marks.validate((beeps,)))
        for gesture, details in (('split', {'at': 1}), ('merge', {}), ('retime', {'start': 0})):
            with self.subTest(instant=gesture):
                self.assertIn(gesture, marks.SEGMENT_GESTURES)
                with self.assertRaisesRegex(marks.InvalidEdit, 'segment'):
                    marks.extend_edits(beeps, [{'time': 1.0, 'origin': 'x'}], [], gesture, 0,
                                       **details)

    def test_every_gesture_does_what_it_says(self):
        rows = [self.PARTS[0], self.PARTS[1], {'start': 20, 'end': None, 'name': 'c'}]
        track = self._track(self.CHANGING)

        def after(*gestures):
            derived, problems = marks.read_derived({'parts': rows}, 'parts',
                                                   self._made(track, rows, *gestures), (track,))
            self.assertEqual([], problems)
            return [(m['start'], m['end'], m.get('name'), m['source_ranks']) for m in derived]

        a, b, c = (0.0, 10.0, 'a', [0]), (10.0, 20.0, 'b', [1]), (20.0, None, 'c', [2])
        self.assertEqual([(0.0, 8.0, 'a', [0]), b, (22.0, None, 'c', [2])],
                         after(('retime', 0, {'end': 8}), ('retime', 2, {'start': 22})))
        self.assertEqual([(0.0, None, 'a', [0]), b, c], after(('retime', 0, {'end': None})),
                         'an end that is given as absent opens the segment')
        self.assertEqual([a, (12.0, 22.0, 'b', [1]), (25.0, None, 'c', [2])],
                         after(('move', 1, {'to': 12}), ('move', 2, {'to': 25})),
                         'a move keeps the length ; an open segment stays open')
        self.assertEqual([c, a, b], after(('reorder', 2, {'to': 0})), 'the rank is a datum')
        self.assertEqual([a, c], after(('delete', 1, {})))
        self.assertEqual([a, (3.0, 5.0, 'new', []), b, c],
                         after(('add', None, {'start': 3, 'end': 5, 'set': {'name': 'new'}})),
                         'added at its place on the axis')
        self.assertEqual([(40.0, None, None, []), a, b, c], after(('add', 0, {'start': 40})),
                         'or at the rank that is asked')
        self.assertEqual([(0.0, 10.0, None, [0]), b, c], after(('label', 0, {'set': {'name': ''}})),
                         'an empty value takes the attribute away')
        self.assertEqual([(0.0, 5.0, 'a', [0]), (5.0, 20.0, 'a', [0, 1]), c],
                         after(('split', 0, {'at': 5}), ('merge', 1, {})))
        self.assertEqual([(0.0, None, 'a', [0, 1, 2])], after(('merge', 0, {'count': 3})),
                         'merged with an open segment, the result is open')
        added = marks.read_derived({'parts': rows}, 'parts', self._made(
            track, rows, ('add', None, {'start': 3, 'end': 5})), (track,))[0][1]
        self.assertEqual((marks.ADDED, [0]), (added['origin'], added['touched']))
        self.assertEqual('add', marks.ADDED, 'named after its gesture, as the Segmenter names '
                                             'a production after its mode')
        # Instants : moved, added, masked, labelled — the same list, the same reader.
        beeps = self._track(('move', 'add', 'mask', 'label', 'delete', 'reorder'),
                            kind=DataType.EVENTS)
        ticks = [{'time': 1, 'name': 'go'}, {'time': 5, 'name': 'stop'}]
        derived, problems = marks.read_derived({'parts': ticks}, 'parts', self._made(
            beeps, ticks, ('move', 1, {'to': 6}), ('add', None, {'time': 3}), ('mask', 0, {})),
            (beeps,))
        self.assertEqual([], problems)
        self.assertEqual([(1.0, True), (3.0, None), (6.0, None)],
                         [(m['time'], m.get('masked')) for m in derived])

    def test_the_effective_line_is_what_the_masks_leave_each_segment_at_its_place(self):
        rows = [{'start': 0, 'end': 4}, {'start': 4, 'end': 20}, {'start': 20, 'end': 30},
                {'start': 30, 'end': None}, {'start': 50, 'end': 60}]
        track = self._track(('mask', 'reorder'))
        edits = self._made(track, rows, ('mask', 1, {}))
        derived = marks.read_derived({'parts': rows}, 'parts', edits, (track,))[0]
        before = copy.deepcopy(derived)
        line = marks.effective_line(derived)
        self.assertEqual([(0, 0.0, 0.0), (2, 20.0, 4.0), (3, 30.0, 14.0), (4, 50.0, None)],
                         [(kept['rank'], kept['mark']['start'], kept['at']) for kept in line],
                         'the masked segment is jumped over ; after an open segment whose end '
                         'nobody gave, nothing has a place')
        self.assertEqual([0.0, 4.0, 14.0, 24.0],
                         [kept['at'] for kept in marks.effective_line(derived, end=40)],
                         'closed at the end of its holder, the open segment counts for its length')
        self.assertEqual(5, len(derived), 'a masked mark stays in the track')
        self.assertEqual(before, derived, 'the line is a reading, the marks are not changed')
        self.assertIs(derived[2], line[1]['mark'], 'each kept mark as it is, nothing written in it')
        # The order of the track is the order of the line : a reordered cut is a new sequence.
        moved = marks.read_derived({'parts': rows[:3]}, 'parts', self._made(
            track, rows[:3], ('reorder', 2, {'to': 0})), (track,))[0]
        self.assertEqual([(20.0, 0.0), (0.0, 10.0), (4.0, 14.0)],
                         [(kept['mark']['start'], kept['at']) for kept in marks.effective_line(moved)])
        # Instants : the ones that are kept, with their rank and no place to compute.
        self.assertEqual([{'rank': 1, 'mark': {'time': 2.0}}],
                         marks.effective_line([{'time': 1.0, 'masked': True}, {'time': 2.0}]))

    def test_a_mark_added_finds_its_parent_and_the_constraint_is_checked_on_the_derived_track(self):
        tracks = (Track('up', 'Up', source=lambda holder: holder['up']),
                  Track('down', 'Down', source=lambda holder: holder['down'], parent='up',
                        constraint=INCLUSION, gestures=('add', 'retime', 'split', 'merge'),
                        edits=marks.DERIVED))
        holder = {'up': [{'start': 0, 'end': 10}, {'start': 10, 'end': 20}],
                  'down': [{'start': 1, 'end': 3}, {'start': 12, 'end': 15}]}
        source = marks.read_track(holder, 'down', tracks)
        edits = marks.extend_edits(tracks[1], source, [], 'add', start=16, end=18)
        edits = marks.extend_edits(tracks[1], source, edits, 'split', 0, at=2)
        derived, problems = marks.read_derived(holder, 'down', edits, tracks)
        self.assertEqual(([], [0, 0, 1, 1]), (problems, [m['parent'] for m in derived]),
                         'the two halves keep their parent ; the added one is found by containment')
        self.assertEqual([], marks.violations(holder, 'down', tracks=tracks, edits=edits))
        out = marks.extend_edits(tracks[1], source, edits, 'retime', 1, end=11)
        self.assertEqual(1, len(marks.violations(holder, 'down', tracks=tracks, edits=out)),
                         'a segment resized out of its parent is seen on the derived track')
        self.assertEqual([], marks.violations(holder, 'down', tracks=tracks),
                         'the source track still holds its constraint')
        with self.assertRaisesRegex(marks.InvalidEdit, 'parente'):
            marks.extend_edits(tracks[1], source, [], 'merge', 0)


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

