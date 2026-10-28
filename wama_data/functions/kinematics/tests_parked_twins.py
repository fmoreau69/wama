"""Garés en double (`parked_twins`, 2026-10-28) : classer les paires proches, réunir les seuls suspects."""
import pandas as pd
from django.test import SimpleTestCase

from wama.common.catalog.data_types import DataType, TypedFrame
from wama_data.functions.kinematics.parked_twins import (parked_twin_groups, parked_twin_pairs,
                                                         twin_pair_counts, twin_pair_kind)


def span(t0, t1, step=0.5):
    """Instants d'observation réguliers de t0 à t1 (s)."""
    return [t0 + k * step for k in range(int((t1 - t0) / step) + 1)]


class TwinPairKindTest(SimpleTestCase):

    def test_two_boxes_of_one_image_are_two_cars_whatever_their_times(self):
        self.assertEqual(twin_pair_kind(span(0, 10), span(0, 10), seen_as_two=True), 'same_image')

    def test_seen_at_the_same_instant_without_two_boxes(self):
        """Deux caméras au même instant, jamais deux boîtes d'une même image : un objet non recollé."""
        self.assertEqual(twin_pair_kind(span(0, 10), [5.1]), 'same_instant')

    def test_overlapping_periods_never_at_the_same_instant_are_nested(self):
        self.assertEqual(twin_pair_kind([0.0, 4.0, 8.0], [2.0, 6.0, 10.0]), 'nested')

    def test_one_after_the_other_within_a_minute_is_consecutive(self):
        self.assertEqual(twin_pair_kind(span(0, 10), span(40, 50)), 'consecutive')

    def test_more_than_a_minute_apart_are_distinct_passes(self):
        self.assertEqual(twin_pair_kind(span(0, 10), span(200, 210)), 'distinct_passes')
        self.assertEqual(twin_pair_kind(span(200, 210), span(0, 10)), 'distinct_passes')   # symétrique

    def test_long_exposure_objects_seen_at_different_passes_are_distinct_passes(self):
        """Deux garés de pose longue (plusieurs passages chacun) dont les PÉRIODES se chevauchent, mais jamais
        vus au même passage : deux passages distincts, pas des imbriqués (rejeu du 2026-10-28)."""
        a = span(0, 10) + span(1000, 1010)
        b = span(500, 510) + span(2000, 2010)
        self.assertEqual(twin_pair_kind(a, b), 'distinct_passes')


class ParkedTwinPairsTest(SimpleTestCase):

    def test_only_pairs_under_two_metres_are_judged_and_counted_by_kind(self):
        objs = [('a', 0.0, 0.0, span(0, 10)), ('b', 1.5, 0.0, span(0, 10)),          # deux voitures
                ('c', 0.0, 1.6, [1.25, 5.25]),                                        # suspect de a
                ('d', 30.0, 0.0, span(0, 10))]                                      # loin
        pairs = parked_twin_pairs(objs, [{'a', 'b'}])
        kinds = {frozenset(p[:2]): p[3] for p in pairs}
        self.assertEqual(kinds[frozenset('ab')], 'same_image')
        self.assertEqual(kinds[frozenset('ac')], 'nested')
        self.assertNotIn(frozenset('ad'), kinds)
        counts = twin_pair_counts(pairs)
        self.assertEqual(counts['pairs'], len(pairs))
        self.assertEqual(counts['same_image'], 1)
        self.assertEqual(counts['suspects'], len(pairs) - 1)


class ParkedTwinGroupsTest(SimpleTestCase):

    def test_suspects_are_joined_under_the_most_observed(self):
        objs = [('a', 0.0, 0.0, span(0, 20), 'four_wheel'),
                ('b', 1.6, 0.0, [3.25, 7.25, 11.25], 'four_wheel'),           # imbriqué
                ('c', 0.5, 1.0, span(40, 45), 'four_wheel')]               # à la suite
        self.assertEqual(parked_twin_groups(objs), {'b': 'a', 'c': 'a'})

    def test_two_cars_seen_together_stay_two(self):
        """Contre-épreuve : la paire la plus nombreuse de la mesure (165 sur 333) n'est jamais réunie."""
        objs = [('a', 0.0, 0.0, span(0, 10), 'four_wheel'), ('b', 1.5, 0.0, span(0, 10), 'four_wheel')]
        self.assertEqual(parked_twin_groups(objs, [{'a', 'b'}]), {})

    def test_distinct_passes_stay_two(self):
        objs = [('a', 0.0, 0.0, span(0, 10), 'four_wheel'), ('b', 1.0, 0.0, span(300, 310), 'four_wheel')]
        self.assertEqual(parked_twin_groups(objs), {})

    def test_a_car_and_a_bike_are_not_joined(self):
        objs = [('a', 0.0, 0.0, span(0, 10), 'four_wheel'), ('b', 0.5, 0.0, [3.3], 'two_wheel')]
        self.assertEqual(parked_twin_groups(objs), {})

    def test_a_row_of_parked_cars_does_not_chain(self):
        """Une file à 1,5 m de proche en proche, sans jamais deux boîtes d'une image : chaque membre doit être
        suspect de TOUS les autres, donc à moins de 2 m de chacun — jamais toute la file en un garé."""
        objs = [(f'f{i}', 1.5 * i, 0.0, [i + 0.3 * k for k in range(20 - i)], 'four_wheel') for i in range(6)]
        roots = parked_twin_groups(objs)
        self.assertGreaterEqual(len({o[0] for o in objs} - set(roots)), 3)
        for absorbed, root in roots.items():
            ia, ir = int(absorbed[1:]), int(root[1:])
            self.assertLess(abs(ia - ir) * 1.5, 2.0)

    def test_declared_in_the_catalogue(self):
        from wama.common.catalog import function_catalog as fc
        fc.load_all()
        spec = fc.get('parked_twin_groups')
        self.assertIsNotNone(spec)
        rows = ([{'id': 'a', 't': t, 'e': 0.0, 'n': 0.0, 'family': 'four_wheel'} for t in span(0, 10)]
                + [{'id': 'b', 't': t, 'e': 1.2, 'n': 0.0, 'family': 'four_wheel'} for t in (2.25, 6.25)])
        out = spec.fn(TypedFrame(pd.DataFrame(rows), DataType.TABLE))
        self.assertEqual(out.df.to_dict('records'), [{'id': 'b', 'root': 'a'}])
        self.assertEqual(out.meta['suspects'], 1)
