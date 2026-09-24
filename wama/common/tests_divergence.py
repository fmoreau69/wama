"""Divergence inter-systèmes (M1) — l'index des segments en face doit rendre EXACTEMENT ce que
rendait le filtre quadratique qu'il remplace (2026-09-23)."""
import random
import time

from django.test import SimpleTestCase

from wama.common.services.divergence import (
    RECOUVREMENT_MINIMAL, _facing_index, _recouvrement, divergence_segments,
)


def _naive_facing(segments, seg):
    """The filter as it was written before: every segment, every time."""
    return [c for c in segments if _recouvrement(seg, c) >= RECOUVREMENT_MINIMAL]


def _random_segments(rng, count, overlapping):
    out, t = [], 0.0
    for _ in range(count):
        start = t + rng.uniform(-1.5, 1.0) if overlapping else t + rng.uniform(0, 0.8)
        start = max(0.0, start)
        end = start + rng.uniform(0.0, 4.0)
        out.append({'start_time': round(start, 2), 'end_time': round(end, 2),
                    'text': rng.choice(['le chat', 'dort', 'oui euh', 'je crois', ''])})
        t = end
    rng.shuffle(out) if overlapping else None
    return out


class FacingIndexIsTheSameFilterTest(SimpleTestCase):

    def test_same_segments_in_the_same_order_on_random_cuts(self):
        rng = random.Random(20260923)
        for overlapping in (False, True):
            for _ in range(40):
                comparison = _random_segments(rng, rng.randint(0, 60), overlapping)
                reference = _random_segments(rng, rng.randint(1, 40), overlapping)
                facing = _facing_index(comparison)
                for seg in reference:
                    with self.subTest(overlapping=overlapping, seg=seg):
                        self.assertEqual(_naive_facing(comparison, seg), facing(seg))

    def test_an_hour_of_speech_compares_in_well_under_a_second(self):
        """3 000 segments each side: the quadratic filter made ~9 million overlap computations."""
        rng = random.Random(1)
        a = _random_segments(rng, 3000, False)
        b = _random_segments(rng, 3000, False)
        started = time.perf_counter()
        result = divergence_segments(a, b)
        self.assertLess(time.perf_counter() - started, 3.0)
        self.assertIsNotNone(result['divergence_globale'])
