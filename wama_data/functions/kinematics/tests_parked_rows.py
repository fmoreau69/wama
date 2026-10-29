"""Cap des garés par leur rangée (`parked_rows`, 2026-10-29) : l'espacement dit bataille ou créneau."""
import math

import pandas as pd
from django.test import SimpleTestCase

from wama.common.catalog.data_types import DataType, TypedFrame
from wama_data.functions.kinematics.parked_rows import row_heading, row_heading_counts, row_headings


def row(count, spacing, compass_deg, jitter=0.0, start=(0.0, 0.0), prefix='g'):
    """`count` garés alignés au cap compas `compass_deg`, tous les `spacing` m ; décalage latéral alterné."""
    ue, un = math.sin(math.radians(compass_deg)), math.cos(math.radians(compass_deg))
    out = []
    for k in range(count):
        side = jitter if k % 2 else -jitter
        out.append((f'{prefix}{k}', start[0] + k * spacing * ue + side * un,
                    start[1] + k * spacing * un - side * ue))
    return out


def axial_gap(a, b):
    return abs(((a - b) + 90.0) % 180.0 - 90.0)


class RowHeadingTest(SimpleTestCase):

    def test_a_tight_row_is_angled_parking_perpendicular_to_the_row(self):
        res = row_headings(row(8, 2.4, 11.0, jitter=0.3))
        kind, heading, spacing = res['g4']
        self.assertEqual(kind, 'angled')
        self.assertLess(axial_gap(heading, 101.0), 5.0)
        self.assertAlmostEqual(spacing, 2.4, delta=0.2)

    def test_a_loose_row_is_parallel_parking_along_the_row(self):
        kind, heading, _spacing = row_headings(row(6, 5.5, 11.0, jitter=0.3))['g2']
        self.assertEqual(kind, 'parallel')
        self.assertLess(axial_gap(heading, 11.0), 5.0)

    def test_an_in_between_spacing_or_a_lone_car_is_unknown(self):
        self.assertEqual(row_headings(row(6, 4.0, 11.0))['g2'][0], 'unknown')
        self.assertEqual(row_heading((0.0, 0.0), [(30.0, 0.0), (0.0, 0.0)])[0], 'unknown')

    def test_twin_anchors_of_one_car_do_not_make_a_parallel_row_angled(self):
        """Deux ancres d'un même garé (deux passages) à 0,8 m : l'écart est écarté, pas compté."""
        cars = row(6, 5.5, 11.0)
        twins = [(f't{k}', e + 0.8 * math.sin(math.radians(11.0)), n + 0.8 * math.cos(math.radians(11.0)))
                 for k, (_g, e, n) in enumerate(cars)]
        self.assertEqual(row_headings(cars + twins)['g2'][0], 'parallel')

    def test_a_car_off_the_row_line_is_left_out_of_the_row(self):
        cars = row(6, 2.4, 11.0) + [('far', 6.0, -4.0)]
        self.assertEqual(row_headings(cars)['g3'][0], 'angled')

    def test_counts_and_the_function_spec_wrapper(self):
        from wama_data.functions.kinematics.parked_rows import parked_row_frame
        cars = row(8, 2.4, 11.0) + row(6, 5.5, 11.0, start=(60.0, 0.0), prefix='p')
        counts = row_heading_counts(row_headings(cars))
        self.assertEqual(sum(counts.values()), 14)
        self.assertGreaterEqual(counts['angled'], 6)
        self.assertGreaterEqual(counts['parallel'], 4)
        frame = parked_row_frame(TypedFrame(pd.DataFrame(cars, columns=['id', 'e', 'n']), DataType.TABLE))
        self.assertEqual(list(frame.df.columns), ['id', 'kind', 'heading', 'spacing'])
        self.assertEqual(frame.meta, counts)
