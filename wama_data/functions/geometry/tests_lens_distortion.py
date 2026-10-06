"""Distorsion par les lignes droites (`lens_distortion`, 2026-10-06) — sans mire, par une seule caméra.

Rig simulé : image 384 × 248, focale 256 px (≈ 74° de champ, la caméra avant d'ENA_CASA). Des droites du
monde, vues à travers un objectif de distorsion connue (modèle radial inverse du placement), puis bruitées
d'un tiers de pixel : la mesure doit retrouver la distorsion — et rien d'autre qu'elle.
"""
import numpy as np
import pandas as pd
from django.test import SimpleTestCase

from wama.common.catalog.data_types import DataType, TypedFrame
from wama_data.functions.geometry.lens_distortion import (plumb_line_distortion, redistort,
                                                          straightness_residual_px, undistort_points)

W, H, F = 384, 248, 256.0
CX, CY = W / 2.0, H / 2.0


def _seen_line(p0, p1, k, rng, n=60, noise_px=0.33):
    """Une droite du monde (extrémités en coordonnées normalisées REDRESSÉES) telle que l'image la montre."""
    t = np.linspace(0.0, 1.0, n)
    xu = p0[0] + t * (p1[0] - p0[0])
    yu = p0[1] + t * (p1[1] - p0[1])
    xd, yd = redistort(xu, yu, k)
    pts = np.stack([xd * F + CX, yd * F + CY], 1)
    return pts + rng.normal(0.0, noise_px, pts.shape)


def _scene(k, n_lines=80, seed=3):
    """Droites excentrées (bordures, façades) d'orientations variées, plus des contours COURBES du monde
    (roues, ronds-points) qu'aucune distorsion ne redresse."""
    rng = np.random.default_rng(seed)
    chains = []
    for _ in range(n_lines):
        c = rng.uniform(0.5, 0.75) * np.array([np.cos(a := rng.uniform(0, 2 * np.pi)), 0.75 * np.sin(a)])
        d = np.array([np.cos(b := rng.uniform(0, np.pi)), np.sin(b)]) * rng.uniform(0.12, 0.2)
        chains.append(_seen_line(c - d, c + d, k, rng))
    for _ in range(20):
        th = np.linspace(0, np.pi, 50)
        r = rng.uniform(15, 30)
        # loin du centre, là où ils seraient JUGÉS : au centre, ils seraient écartés d'emblée et le filtre
        # des contours courbes ne serait jamais mis à l'épreuve (garde aveugle à la mutation, 2026-10-06)
        ox, oy = rng.choice([rng.uniform(20, 70), rng.uniform(314, 364)]), rng.uniform(30, 218)
        chains.append(np.stack([ox + r * np.cos(th), oy + r * np.sin(th)], 1))
    return chains


class PlumbLineDistortionTest(SimpleTestCase):

    def test_it_finds_the_distortion_of_the_lens(self):
        res = plumb_line_distortion(_scene(0.4), F, F, CX, CY)
        self.assertTrue(res['clear'], res)
        self.assertAlmostEqual(res['k'], 0.4, delta=0.1)
        self.assertLessEqual(res['flat_range'][0], 0.4)
        self.assertGreaterEqual(res['flat_range'][1], 0.4)

    def test_a_strong_distortion_is_not_underestimated(self):
        """Le défaut des deux premières versions (pied re-déformé, puis médiane des écarts relatifs) : une
        distorsion forte rendue trop faible."""
        for seed in (3, 11):
            res = plumb_line_distortion(_scene(0.7, seed=seed), F, F, CX, CY)
            self.assertTrue(res['clear'], res)
            self.assertAlmostEqual(res['k'], 0.7, delta=0.12)

    def test_a_lens_without_distortion_measures_zero(self):
        """Contre-épreuve : aucune distorsion, aucune n'est inventée."""
        res = plumb_line_distortion(_scene(0.0), F, F, CX, CY)
        self.assertTrue(res['clear'], res)
        self.assertAlmostEqual(res['k'], 0.0, delta=0.1)

    def test_curved_contours_of_the_world_are_left_out(self):
        res = plumb_line_distortion(_scene(0.4), F, F, CX, CY)
        self.assertLessEqual(res['n_far'], 80)             # les 20 arcs ne passent pas pour des droites
        self.assertEqual(res['n_chains'], 100)

    def test_a_minimum_at_the_edge_of_the_grid_is_no_verdict(self):
        """Une distorsion hors de la grille explorée : le minimum tombe au BORD, la valeur n'est qu'une borne."""
        res = plumb_line_distortion(_scene(0.6), F, F, CX, CY, ks=(0.0, 0.1, 0.2))
        self.assertEqual(res['k'], 0.2)
        self.assertFalse(res['clear'])

    def test_the_gap_is_measured_in_the_observed_image(self):
        """Le biais qui a coûté deux essais : un écart pris dans l'image REDRESSÉE croît avec k, rapporté à
        la longueur il décroît. Dans l'image observée, une droite sans bruit vue à travers k a un écart nul
        à SON k, et non nul ailleurs."""
        rng = np.random.default_rng(0)
        line = _seen_line((0.2, -0.35), (0.55, -0.1), 0.6, rng, noise_px=0.0)
        self.assertLess(straightness_residual_px(line, 0.6, F, F, CX, CY), 1e-3)
        self.assertGreater(straightness_residual_px(line, 0.0, F, F, CX, CY), 0.2)
        self.assertGreater(straightness_residual_px(line, 1.2, F, F, CX, CY), 0.2)

    def test_redistort_inverts_the_lens_model(self):
        pts = np.array([[300.0, 40.0], [20.0, 230.0], [192.0, 124.0]])
        xu, yu = undistort_points(pts, 0.5, F, F, CX, CY)
        xd, yd = redistort(xu, yu, 0.5)
        np.testing.assert_allclose(np.stack([xd * F + CX, yd * F + CY], 1), pts, atol=1e-3)

    def test_too_few_straight_contours_give_no_verdict(self):
        res = plumb_line_distortion(_scene(0.4, n_lines=10), F, F, CX, CY)
        self.assertFalse(res['clear'])
        self.assertIsNone(plumb_line_distortion([], F, F, CX, CY))

    def test_declared_in_the_catalogue(self):
        from wama.common.catalog import function_catalog as fc
        fc.load_all()
        spec = fc.get('plumb_line_distortion')
        self.assertIsNotNone(spec)
        rows = [{'chain': i, 'u': u, 'v': v} for i, c in enumerate(_scene(0.4)) for u, v in c]
        out = spec.fn(TypedFrame(pd.DataFrame(rows), DataType.TABLE), fx_px=F, fy_px=F, width=W, height=H)
        self.assertAlmostEqual(float(out.df['k'][0]), 0.4, delta=0.1)
