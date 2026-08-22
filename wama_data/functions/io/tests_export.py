"""Tests des ADAPTATEURS de l'Exporter — la frontière pandas et la chaîne complète.

Le cœur (`core/tests_export.py`) est pur. Ici on éprouve ce qu'il ne peut pas voir : la conversion
`TypedFrame`, le choix automatique des mesures, et surtout le CHAÎNAGE RÉEL
Segmenter → Calculator → Exporter, qui est la raison d'être du module.
"""
import unittest

from wama.common.catalog.data_types import DataType, TypedFrame
from wama.common.catalog.function_catalog import can_connect, get


def _signal():
    import pandas as pd
    return TypedFrame(pd.DataFrame({'time': [0.0, 1.0, 2.0, 3.0, 4.0],
                                    'value': [10.0, 20.0, 30.0, 40.0, 50.0]}), DataType.SIGNAL)


def _segments():
    import pandas as pd
    return TypedFrame(pd.DataFrame([
        {'trip_id': 'P01', 'name': '0_15', 'start': 0.0, 'end': 1.0},
        {'trip_id': 'P01', 'name': '15_30', 'start': 2.0, 'end': 3.0},
        {'trip_id': 'P02', 'name': '0_15', 'start': 0.0, 'end': 2.0},
    ]), DataType.SEGMENTS)


class ChaineCompleteTest(unittest.TestCase):
    """Segmenter → Calculator → Exporter : ce que le module existe pour produire."""

    def _large(self, **kw):
        from wama_data.functions.temporal.calculation import calcul_par_segment
        from ..io.export import export_pivot
        avec = calcul_par_segment(_segments(), _signal(), statistiques='moyenne,max')
        return export_pivot(avec, **kw)

    def test_une_ligne_par_passation_et_le_type_change(self):
        large = self._large(cle_ligne='trip_id', cle_colonne='name',
                            mesures='value_moyenne,value_max')
        self.assertEqual(len(large.df), 2, "3 segments, 2 passations")
        self.assertEqual(large.data_type, DataType.TABLE,
                         "ce ne sont plus des segments : la ligne n'a ni début ni fin")

    def test_les_colonnes_portent_la_forme_du_livrable(self):
        large = self._large(cle_ligne='trip_id', cle_colonne='name',
                            mesures='value_moyenne,value_max')
        for attendue in ('0_15.value_moyenne', '15_30.value_max'):
            self.assertIn(attendue, large.df.columns)

    def test_les_mesures_se_DEDUISENT_quand_on_n_en_nomme_aucune(self):
        """Défaut utile : après un `calcul_par_segment` ce sont exactement les indicateurs
        produits, et les nommer un par un serait à refaire à chaque statistique ajoutée."""
        large = self._large(cle_ligne='trip_id', cle_colonne='name')
        self.assertIn('0_15.value_moyenne', large.df.columns)
        self.assertIn('0_15.n', large.df.columns, "les champs de service sont des mesures aussi")

    def test_start_et_end_ne_sont_JAMAIS_etales(self):
        # `0_15.start` redirait ce que le nom de la fenêtre porte déjà.
        large = self._large(cle_ligne='trip_id', cle_colonne='name')
        for colonne in large.df.columns:
            self.assertFalse(colonne.endswith('.start'), colonne)
            self.assertFalse(colonne.endswith('.end'), colonne)

    def test_l_ordre_des_colonnes_vient_du_COEUR(self):
        # Un livrable dont les colonnes bougent d'un export à l'autre est incomparable.
        large = self._large(cle_ligne='trip_id', cle_colonne='name',
                            mesures='value_moyenne,value_max')
        self.assertEqual(list(large.df.columns), large.meta['colonnes'])
        self.assertEqual(list(large.df.columns)[0], 'trip_id')

    def test_une_fenetre_non_observee_s_ecrit_VIDE_dans_le_tableau(self):
        """P02 n'a pas de fenêtre `15_30`. Dans le cadre pandas le trou devient `NaN` ; ce qui
        compte est ce qui sort à l'écriture — une cellule vide se lit « pas de donnée », `0` se
        lirait comme une mesure."""
        from ..io.export import export_tableau
        large = self._large(cle_ligne='trip_id', cle_colonne='name', mesures='value_moyenne')
        tableau = export_tableau(large)
        ligne_p02 = [l for l in tableau[1:] if l[0] == 'P02'][0]
        self.assertIn('', ligne_p02)
        self.assertNotIn('0', ligne_p02)
        self.assertNotIn('nan', [c.lower() for c in ligne_p02])

    def test_la_decimation_reduit_les_lignes_lues(self):
        large = self._large(cle_ligne='trip_id', cle_colonne='name', pas_de_decimation=2)
        # Une ligne sur deux du LONG (3 segments → 2 lus : P01/0_15 et P02/0_15).
        self.assertEqual(len(large.df), 2)

    def test_l_identite_peut_porter_plusieurs_colonnes(self):
        from ..io.export import export_pivot
        import pandas as pd
        segs = TypedFrame(pd.DataFrame([
            {'p': 'P01', 's': 'A', 'name': 'x', 'start': 0.0, 'end': 1.0, 'v': 1},
            {'p': 'P01', 's': 'B', 'name': 'x', 'start': 0.0, 'end': 1.0, 'v': 2},
        ]), DataType.SEGMENTS)
        large = export_pivot(segs, cle_ligne='p, s', cle_colonne='name', mesures='v')
        self.assertEqual(len(large.df), 2)
        self.assertEqual(list(large.df.columns)[:2], ['p', 's'])


class CatalogueTest(unittest.TestCase):

    def test_la_fonction_est_au_catalogue_et_decrite(self):
        spec = get('export_pivot_large')
        self.assertIsNotNone(spec, "absente du catalogue — donc invisible du canvas")
        self.assertTrue(spec.description.strip())
        self.assertTrue(callable(spec.fn))

    def test_le_calculator_alimente_l_exporter(self):
        ok, raison = can_connect(get('calcul_par_segment').outputs[0],
                                 get('export_pivot_large').inputs[0],
                                 available_fields=['start', 'end'])
        self.assertTrue(ok, raison)

    def test_un_segmenteur_alimente_aussi_l_exporter(self):
        # L'export ne dépend pas du Calculator : des segments nus s'exportent tout autant.
        sortie = get('segment_conditionnel').outputs[0]
        ok, raison = can_connect(sortie, get('export_pivot_large').inputs[0],
                                 available_fields=sortie.produced_fields)
        self.assertTrue(ok, raison)

    def test_la_sortie_est_un_ALLER_SANS_RETOUR(self):
        """Une `table` ne se rebranche pas sur une entrée `segments` : la ligne du livrable est
        une passation, elle n'a ni début ni fin. Le typage doit le refuser tout seul."""
        ok, _ = can_connect(get('export_pivot_large').outputs[0],
                            get('calcul_par_segment').inputs[0])
        self.assertFalse(ok, "une table ne doit pas pouvoir réalimenter une entrée segments")
