"""⚑ sam3_label_arbitration (2026-09-29) — un marquage revendiqué par deux prompts garde UN label.

Mesuré frames 7164/7170 : la rangée de triangles d'un ralentisseur sortait sous `crossing`. Avec
un 3ᵉ prompt `shark_teeth`, SAM3 la rendrait sous les DEUX labels, les prompts étant interrogés
séparément ; l'arbitrage garde le plus confiant."""
import unittest

import numpy as np

from wama_lab.cam_analyzer.utils.marking_world import _LABEL_KIND
from wama_lab.cam_analyzer.utils.sam3_road_analyzer import DEFAULT_MARKING_PROMPTS, arbitrate_labels


def _mask(x0, y0, x1, y1, shape=(100, 200)):
    m = np.zeros(shape, dtype=bool)
    m[y0:y1, x0:x1] = True
    return m


class ArbitrateLabelsTest(unittest.TestCase):

    def test_the_same_pixels_under_two_labels_keep_the_most_confident(self):
        entries = [{'label': 'crossing', 'confidence': 0.82}, {'label': 'shark_teeth', 'confidence': 0.91}]
        kept, dropped = arbitrate_labels(entries, [_mask(10, 40, 150, 52), _mask(12, 40, 150, 53)])
        self.assertEqual([e['label'] for e in kept], ['shark_teeth'])
        self.assertEqual(dropped, {('shark_teeth', 'crossing'): 1})

    def test_distinct_markings_are_both_kept(self):
        entries = [{'label': 'crossing', 'confidence': 0.9}, {'label': 'shark_teeth', 'confidence': 0.8}]
        kept, dropped = arbitrate_labels(entries, [_mask(10, 60, 150, 95), _mask(10, 20, 150, 30)])
        self.assertEqual(len(kept), 2)
        self.assertEqual(dropped, {})

    def test_two_masks_of_the_same_label_are_left_alone(self):
        entries = [{'label': 'crossing', 'confidence': 0.9}, {'label': 'crossing', 'confidence': 0.5}]
        kept, _ = arbitrate_labels(entries, [_mask(10, 60, 150, 95), _mask(10, 60, 150, 95)])
        self.assertEqual(len(kept), 2)

    def test_a_small_mask_inside_a_large_one_counts_as_the_same_object(self):
        """Recouvrement rapporté au PLUS PETIT : une bande isolée dans tout le passage piéton."""
        entries = [{'label': 'crossing', 'confidence': 0.9}, {'label': 'stop_line', 'confidence': 0.4}]
        kept, _ = arbitrate_labels(entries, [_mask(0, 50, 200, 100), _mask(20, 60, 60, 70)])
        self.assertEqual([e['label'] for e in kept], ['crossing'])

    def test_kept_entries_keep_their_original_order(self):
        entries = [{'label': 'a', 'confidence': 0.1}, {'label': 'b', 'confidence': 0.9}, {'label': 'c', 'confidence': 0.5}]
        masks = [_mask(0, 0, 10, 10), _mask(50, 0, 60, 10), _mask(100, 0, 110, 10)]
        kept, _ = arbitrate_labels(entries, masks)
        self.assertEqual([e['label'] for e in kept], ['a', 'b', 'c'])


class SharkTeethPromptTest(unittest.TestCase):

    def test_the_third_prompt_is_declared_and_aggregated_as_its_own_kind(self):
        self.assertIn('shark_teeth', [p['label'] for p in DEFAULT_MARKING_PROMPTS])
        self.assertEqual(_LABEL_KIND['shark_teeth'], 'shark_teeth')


if __name__ == '__main__':
    unittest.main(verbosity=2)
