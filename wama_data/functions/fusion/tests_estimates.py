"""Tests de la fusion d'estimations — vérités SYNTHÉTIQUES, chaque règle de l'en-tête a son test.

Le test qui compte est `LaFusionRefuseLesSourcesCorreleesTest` : sans lui, le module rendrait
un chiffre faux avec l'apparence d'une confirmation (§INVENTAIRE E, risque « corrélation »).

    python3 -m unittest wama_data.functions.fusion.tests_estimates
"""
import math
import unittest

from wama.common.catalog.data_types import DataType, TypedFrame

from .estimates import fuse_series, fuse_estimates, sigma_of, shared_native_source


def _rows(values, field='value', **extra):
    return [{'time': float(i), field: v, **extra} for i, v in enumerate(values)]


class SigmaOfTest(unittest.TestCase):
    def test_constante_colonne_relative_tenue_et_declaree(self):
        row = {'value': 20.0, 's': 1.5, 'held': True}
        self.assertEqual(sigma_of(row, 3.0, 20.0), 3.0)
        self.assertEqual(sigma_of(row, {'field': 's'}, 20.0), 1.5)
        self.assertAlmostEqual(sigma_of(row, {'model': 'relative', 'ratio': 0.2}, 20.0), 4.0)
        self.assertIsNone(sigma_of(row, {'model': 'held', 'field': 'held', 'sigma': 3.0}, 20.0),
                          "un cap TENU n'est pas une mesure")
        self.assertEqual(sigma_of({'held': False}, {'model': 'held', 'field': 'held', 'sigma': 3.0}, 1.0), 3.0)
        self.assertIsNone(sigma_of(row, {'model': 'declared', 'note': '?'}, 20.0),
                          "non chiffrée : ne pèse pas")
        self.assertIsNone(sigma_of(row, None, 20.0))
        self.assertIsNone(sigma_of(row, 0.0, 20.0))
        self.assertIsNone(sigma_of(row, True, 20.0), "un booléen n'est pas une σ")


class LaFusionPondereParLInverseDeLaVarianceTest(unittest.TestCase):
    def test_deux_sources_independantes_la_plus_sure_pese_le_plus(self):
        gps = {'name': 'gps', 'rows': _rows([100.0] * 5), 'field': 'value',
               'uncertainty': 10.0, 'derived_from': ['gps']}
        img = {'name': 'image', 'rows': _rows([109.0] * 5), 'field': 'value',
               'uncertainty': 3.0, 'derived_from': ['image']}
        rows, report = fuse_series([gps, img])
        self.assertEqual(len(rows), 5)
        # 1/σ² : gps 0,01, image 0,111 → fusion ≈ 100 + 9·0,917 = 108,26
        self.assertAlmostEqual(rows[0]['value'], 108.26, places=1)
        self.assertAlmostEqual(rows[0]['sigma'], 1 / math.sqrt(0.01 + 1 / 9), places=4)
        self.assertLess(rows[0]['sigma'], 3.0, "fusionner deux sources réduit σ")
        self.assertEqual(report['rows_multi_source'], 5)
        self.assertEqual([s['valid'] for s in report['sources']], [5, 5])

    def test_une_grandeur_circulaire_se_moyenne_en_vecteur(self):
        a = {'name': 'a', 'rows': _rows([350.0]), 'field': 'value', 'uncertainty': 5.0,
             'derived_from': ['gps']}
        b = {'name': 'b', 'rows': _rows([10.0]), 'field': 'value', 'uncertainty': 5.0,
             'derived_from': ['image']}
        rows, _ = fuse_series([a, b], circular=True)
        self.assertAlmostEqual(rows[0]['value'], 0.0, places=6, msg="350° et 10° font 0°, pas 180°")
        rows_lin, _ = fuse_series([a, b], circular=False)
        self.assertAlmostEqual(rows_lin['value'] if isinstance(rows_lin, dict) else rows_lin[0]['value'], 180.0)

    def test_les_lignes_tenues_sont_ecartees_et_comptees(self):
        rows = _rows([37.0, 37.0, 37.0], held=False)
        rows[1]['held'] = True
        src = {'name': 'cap filtré', 'rows': rows, 'field': 'value',
               'uncertainty': {'model': 'held', 'field': 'held', 'sigma': 3.0},
               'derived_from': ['gps']}
        fused, report = fuse_series([src], circular=True)
        self.assertEqual([r['time'] for r in fused], [0.0, 2.0])
        self.assertEqual(report['sources'][0], {'name': 'cap filtré', 'valid': 2, 'dropped': 1,
                                                'derived_from': ['gps']})

    def test_une_source_seule_rend_la_source_avec_sa_sigma(self):
        src = {'name': 's', 'rows': _rows([1.0, 2.0]), 'field': 'value', 'uncertainty': 0.5,
               'derived_from': ['bbox']}
        fused, _ = fuse_series([src])
        self.assertEqual([(r['value'], r['sigma'], r['n_sources']) for r in fused],
                         [(1.0, 0.5, 1), (2.0, 0.5, 1)])

    def test_l_alignement_temporel_respecte_la_tolerance(self):
        a = {'name': 'a', 'rows': [{'time': 0.00, 'value': 10.0}], 'field': 'value',
             'uncertainty': 1.0, 'derived_from': ['gps']}
        b = {'name': 'b', 'rows': [{'time': 0.02, 'value': 20.0}], 'field': 'value',
             'uncertainty': 1.0, 'derived_from': ['image']}
        fused, _ = fuse_series([a, b], tolerance_s=0.05)
        self.assertEqual(len(fused), 1, "20 ms < 50 ms : même instant")
        self.assertAlmostEqual(fused[0]['value'], 15.0)
        fused, _ = fuse_series([a, b], tolerance_s=0.01)
        self.assertEqual(len(fused), 2, "20 ms > 10 ms : deux instants")


class LaFusionRefuseLesSourcesCorreleesTest(unittest.TestCase):
    def test_deux_sources_derivees_de_la_meme_donnee_native_sont_refusees(self):
        trace = {'name': 'cap trace', 'rows': _rows([0.0]), 'field': 'value',
                 'uncertainty': 5.0, 'derived_from': ['bbox', 'gps']}
        ratio = {'name': 'cap ratio', 'rows': _rows([0.0]), 'field': 'value',
                 'uncertainty': 5.0, 'derived_from': ['bbox']}
        self.assertEqual(shared_native_source([trace, ratio]), ('cap trace', 'cap ratio', ['bbox']))
        with self.assertRaises(ValueError) as cm:
            fuse_series([trace, ratio])
        self.assertIn('bbox', str(cm.exception))
        self.assertIn('confrontent', str(cm.exception))

    def test_une_source_non_chiffree_ne_pese_pas_mais_ne_bloque_pas(self):
        sure = {'name': 'a', 'rows': _rows([10.0]), 'field': 'value', 'uncertainty': 1.0,
                'derived_from': ['gps']}
        vague = {'name': 'b', 'rows': _rows([99.0]), 'field': 'value',
                 'uncertainty': {'model': 'declared', 'note': 'σ non étalonnée'},
                 'derived_from': ['image']}
        fused, report = fuse_series([sure, vague])
        self.assertEqual(fused[0]['value'], 10.0)
        self.assertEqual(report['sources'][1]['dropped'], 1)


class LeWrapperTypedFrameTest(unittest.TestCase):
    def _frame(self, values, *, field, derived, unc, name, dt=DataType.TIMESERIES, time='time'):
        import pandas as pd
        df = pd.DataFrame([{time: float(i), field: v} for i, v in enumerate(values)])
        return TypedFrame(df, dt, meta={'estimate': {
            'quantity': 'heading', 'field': field, 'uncertainty': unc,
            'derived_from': derived, 'circular': True, 'name': name}})

    def test_le_wrapper_rend_une_timeseries_typee_et_sa_propre_facette(self):
        gps = self._frame([350.0, 350.0], field='heading_f', derived=['gps'], unc=10.0, name='gps')
        img = self._frame([10.0, 10.0], field='yaw', derived=['image'], unc=10.0, name='vision', time='ts')
        out = fuse_estimates([gps, img])
        self.assertEqual(out.data_type, DataType.TIMESERIES)
        self.assertEqual(list(out.df.columns), ['time', 'heading', 'heading_sigma', 'n_sources'])
        self.assertAlmostEqual(float(out.df['heading'][0]), 0.0, places=6)
        self.assertEqual(int(out.df['n_sources'][0]), 2)
        facet = out.meta['estimate']
        self.assertEqual(facet['derived_from'], ['gps', 'image'], "la fusion hérite des deux provenances")
        self.assertEqual(facet['uncertainty'], {'field': 'heading_sigma'})
        self.assertEqual(out.meta['fusion']['n'], 2)

    def test_sans_facette_ou_avec_des_grandeurs_differentes_le_wrapper_refuse(self):
        import pandas as pd
        nu = TypedFrame(pd.DataFrame({'time': [0.0], 'value': [1.0]}), DataType.TABLE)
        with self.assertRaises(ValueError):
            fuse_estimates([nu])
        a = self._frame([1.0], field='v', derived=['gps'], unc=1.0, name='a')
        b = self._frame([1.0], field='v', derived=['image'], unc=1.0, name='b')
        b.meta['estimate']['quantity'] = 'distance'
        with self.assertRaises(ValueError):
            fuse_estimates([a, b])

    def test_un_seul_frame_hors_liste_est_accepte(self):
        a = self._frame([90.0], field='v', derived=['gps'], unc=2.0, name='a')
        out = fuse_estimates(a)
        self.assertEqual(len(out.df), 1)
        self.assertAlmostEqual(float(out.df['heading_sigma'][0]), 2.0)


if __name__ == '__main__':
    unittest.main()
