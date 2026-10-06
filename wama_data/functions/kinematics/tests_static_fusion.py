"""« Pose longue » des immobiles (`static_fusion`, 2026-10-06) : réunir les fragments d'un même garé."""
import pandas as pd
from django.test import SimpleTestCase

from wama.common.catalog.data_types import DataType, TypedFrame
from wama_data.functions.kinematics.static_fusion import long_exposure_groups


class LongExposureGroupsTest(SimpleTestCase):

    def test_fragments_of_one_parked_car_are_joined_under_the_most_observed(self):
        frags = [('a', 10.0, 5.0, 40, 'four_wheel'), ('b', 10.6, 5.3, 8, 'four_wheel'),
                 ('c', 9.5, 4.8, 3, 'four_wheel')]
        self.assertEqual(long_exposure_groups(frags), {'b': 'a', 'c': 'a'})

    def test_two_cars_side_by_side_stay_two(self):
        """Contre-épreuve : deux garés voisins (2,3 m centre à centre) ne se réunissent pas."""
        frags = [('a', 0.0, 0.0, 30, 'four_wheel'), ('b', 2.3, 0.0, 30, 'four_wheel')]
        self.assertEqual(long_exposure_groups(frags), {})

    def test_a_row_of_cars_does_not_chain(self):
        """Une file de fragments à 1,2 m de proche en proche : chacun est jugé contre le GROUPE, pas contre son
        seul voisin — sinon toute la file deviendrait un seul garé."""
        frags = [(f'f{i}', 1.2 * i, 0.0, 10, 'four_wheel') for i in range(6)]
        roots = long_exposure_groups(frags)
        self.assertGreaterEqual(len(set(f[0] for f in frags) - set(roots)), 3)   # au moins 3 objets distincts

    def test_fragments_seen_together_as_two_boxes_are_two_objects(self):
        frags = [('a', 0.0, 0.0, 30, 'four_wheel'), ('b', 0.8, 0.0, 10, 'four_wheel')]
        self.assertEqual(long_exposure_groups(frags, [{'a', 'b'}]), {})
        self.assertEqual(long_exposure_groups(frags), {'b': 'a'})

    def test_a_car_and_a_bike_are_not_joined(self):
        frags = [('a', 0.0, 0.0, 30, 'four_wheel'), ('b', 0.5, 0.0, 10, 'two_wheel')]
        self.assertEqual(long_exposure_groups(frags), {})

    def test_declared_in_the_catalogue(self):
        from wama.common.catalog import function_catalog as fc
        fc.load_all()
        spec = fc.get('long_exposure_groups')
        self.assertIsNotNone(spec)
        df = pd.DataFrame([{'id': 'a', 'e': 0.0, 'n': 0.0, 'n_obs': 30, 'family': 'four_wheel'},
                           {'id': 'b', 'e': 0.5, 'n': 0.2, 'n_obs': 5, 'family': 'four_wheel'}])
        out = spec.fn(TypedFrame(df, DataType.TABLE))
        self.assertEqual(out.df.to_dict('records'), [{'id': 'b', 'root': 'a'}])
