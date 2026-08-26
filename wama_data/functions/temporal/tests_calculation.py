"""Tests des ADAPTATEURS du Calculator — la frontière pandas, là où vivent les pièges.

Le cœur (`core/tests_calculation.py`) est pur : listes de flottants, aucun cadre. Ces tests-ci
couvrent ce que le cœur ne peut pas voir — la conversion depuis/vers `TypedFrame`, le nommage des
colonnes produites, et la survie des absences à l'aller-retour.

Versionnés parce qu'un smoke lancé une fois ne protège rien : c'est précisément dans cette couche
que le piège `None` → `NaN` s'est présenté trois fois avant d'être nommé.
"""
import unittest

from wama.common.catalog.data_types import DataType, TypedFrame
from wama.common.catalog.function_catalog import can_connect, get
from ...core.values import missing


def _signal(times=(0.0, 1.0, 2.0, 3.0, 4.0), values=(10.0, 20.0, 30.0, 40.0, 50.0)):
    import pandas as pd
    return TypedFrame(pd.DataFrame({'time': list(times), 'value': list(values)}), DataType.SIGNAL)


def _segments(rows):
    import pandas as pd
    df = pd.DataFrame(rows)
    if 'end' in df.columns and any(l.get('end') is None for l in rows):
        df['end'] = pd.Series([l.get('end') for l in rows], dtype=object)
    return TypedFrame(df, DataType.SEGMENTS)


class NommageTest(unittest.TestCase):

    def test_la_colonne_produite_se_deduit_des_parametres(self):
        from .calculation import calc_rolling, derived_name
        self.assertEqual(derived_name('vitesse', 'mean'), 'vitesse_mean')
        sortie = calc_rolling(_signal(), window_s=2.0, statistic='max')
        self.assertIn('value_max', sortie.df.columns)

    def test_deux_statistiques_ne_s_ecrasent_pas(self):
        # Le nom porte la statistique : sans cela la seconde passe effacerait la première.
        from .calculation import calc_rolling
        une = calc_rolling(_signal(), 2.0, 'mean')
        deux = calc_rolling(une, 2.0, 'max')
        self.assertIn('value_mean', deux.df.columns)
        self.assertIn('value_max', deux.df.columns)


class EnrichissementTest(unittest.TestCase):

    def test_l_entree_n_est_JAMAIS_mutee(self):
        # Une fonction de chaîne qui mute son entrée rend tout rejeu de la chaîne faux.
        from .calculation import calc_rolling
        signal = _signal()
        before = list(signal.df.columns)
        calc_rolling(signal, 2.0, 'mean')
        self.assertEqual(list(signal.df.columns), before)

    def test_le_type_et_les_lignes_sont_conserves(self):
        from .calculation import calc_derivative
        signal = _signal()
        sortie = calc_derivative(signal)
        self.assertEqual(sortie.data_type, signal.data_type)
        self.assertEqual(len(sortie.df), len(signal.df))

    def test_une_sortie_enrichie_se_rechaine(self):
        from .calculation import calc_derivative, calc_rolling
        sortie = calc_derivative(calc_rolling(_signal(), 2.0, 'mean'),
                                column='value_mean')
        self.assertIn('value_mean_derivative', sortie.df.columns)

    def test_une_colonne_absente_est_signalee_et_NOMME_les_disponibles(self):
        from .calculation import calc_rolling
        with self.assertRaises(ValueError) as e:
            calc_rolling(_signal(), 2.0, 'mean', column='inexistante')
        self.assertIn('time', str(e.exception))


class IndicateursParSegmentTest(unittest.TestCase):

    def test_les_indicateurs_sont_ADJOINTS_aux_segments(self):
        from .calculation import calc_per_segment
        segments = _segments([{'start': 0.0, 'end': 1.0, 'name': 'a'}])
        sortie = calc_per_segment(segments, _signal(), statistics='mean')
        ligne = sortie.df.to_dict('records')[0]
        self.assertEqual(ligne['name'], 'a', "les champs du segment survivent")
        self.assertEqual(ligne['value_mean'], 15.0)
        self.assertEqual(sortie.data_type, DataType.SEGMENTS)

    def test_les_indicateurs_sont_PREFIXES_du_nom_du_signal_mesure(self):
        # Sans préfixe, calculer sur un second signal écraserait la première série en silence.
        from .calculation import calc_per_segment
        sortie = calc_per_segment(_segments([{'start': 0.0, 'end': 4.0}]), _signal(),
                                    statistics='mean,max')
        for attendu in ('value_mean', 'value_max'):
            self.assertIn(attendu, sortie.df.columns)

    def test_les_champs_de_service_ne_sont_PAS_prefixes(self):
        # `n`, `duree`, `tronque` décrivent le SEGMENT, pas la colonne mesurée.
        from .calculation import calc_per_segment
        sortie = calc_per_segment(_segments([{'start': 0.0, 'end': 1.0}]), _signal())
        for field in ('n', 'duration', 'truncated'):
            self.assertIn(field, sortie.df.columns)

    def test_un_segment_OUVERT_traverse_l_aller_retour_sans_se_refermer(self):
        """LE piège de cette couche : `None` mêlé à des flottants devient `NaN`, et un segment
        ouvert cesserait d'être reconnaissable comme tel."""
        from .calculation import calc_per_segment
        segments = _segments([{'start': 0.0, 'end': 1.0}, {'start': 2.0, 'end': None}])
        sortie = calc_per_segment(segments, _signal(), statistics='mean')
        rows = sortie.df.to_dict('records')
        self.assertIs(rows[1]['end'], None, "la fin inconnue survit au cadre")
        self.assertTrue(rows[1]['truncated'])
        # ⚠ On teste avec `missing()` et non `is None` : la FORME de l'absence n'est pas stable.
        # Colonne mixte (des durées et une absence) → pandas la type en flottants et l'absence
        # devient `NaN` ; colonne entièrement absente → elle reste `object` et `None` survit.
        # Les deux sont licites, aucune n'est prévisible depuis le code appelant — d'où la
        # primitive commune, seule manière de relire un cadre sans se tromper une fois sur deux.
        self.assertTrue(missing(rows[1]['duration']))
        self.assertEqual(rows[0]['duration'], 1.0)

    def test_un_segment_sans_mesure_donne_une_absence_et_non_un_zero(self):
        from .calculation import calc_per_segment
        sortie = calc_per_segment(_segments([{'start': 90.0, 'end': 99.0}]), _signal(),
                                    statistics='mean')
        ligne = sortie.df.to_dict('records')[0]
        self.assertEqual(ligne['n'], 0)
        self.assertTrue(missing(ligne['value_mean']), "pas de mesure ≠ mesure nulle")
        self.assertNotEqual(ligne['value_mean'], 0, "surtout pas un zéro crédible")

    def test_la_liste_de_statistiques_se_lit_separee_par_des_virgules(self):
        # Forme retenue parce qu'elle reste sérialisable en manifeste et éditable dans une modale.
        from .calculation import calc_per_segment
        sortie = calc_per_segment(_segments([{'start': 0.0, 'end': 4.0}]), _signal(),
                                    statistics=' mean , min ')
        self.assertIn('value_mean', sortie.df.columns)
        self.assertIn('value_min', sortie.df.columns)


class CatalogueTest(unittest.TestCase):
    """Le Calculator est-il RÉELLEMENT chaînable depuis le canvas ? Sinon il est hors pipeline."""

    CLES = ('calc_rolling', 'calc_derivative', 'calc_cumulative', 'calc_per_segment')

    def test_les_quatre_fonctions_sont_au_catalogue_et_decrites(self):
        for key in self.CLES:
            with self.subTest(fonction=key):
                spec = get(key)
                self.assertIsNotNone(spec, "absente du FUNCTION_CATALOG — donc invisible du canvas")
                self.assertTrue(spec.description.strip())
                self.assertTrue(spec.inputs and spec.outputs)
                self.assertTrue(callable(spec.fn))

    def test_les_deux_modes_portent_des_categories_DIFFERENTES(self):
        # Enrichir ne change pas la granularité, agréger si. Les confondre tromperait le canvas
        # sur ce qui reste branchable en aval.
        self.assertEqual(get('calc_rolling').category, 'enricher')
        self.assertEqual(get('calc_per_segment').category, 'aggregate')

    def test_un_segmenteur_alimente_le_calcul_par_segment(self):
        sortie = get('segment_conditional').outputs[0]
        entree = get('calc_per_segment').inputs[0]
        ok, raison = can_connect(sortie, entree, available_fields=sortie.produced_fields)
        self.assertTrue(ok, raison)

    def test_un_signal_enrichi_alimente_le_calcul_par_segment(self):
        ok, raison = can_connect(get('calc_rolling').outputs[0],
                                 get('calc_per_segment').inputs[1],
                                 available_fields=['time', 'value'])
        self.assertTrue(ok, raison)

    def test_toute_statistique_du_coeur_est_offerte_dans_la_modale(self):
        """Le lien registre → UI : une statistique ajoutée au cœur doit apparaître dans les choix,
        sinon elle existe sans être atteignable."""
        from ...core.calculation import STATISTIQUES
        choix = [p for p in get('calc_rolling').params if p.key == 'statistic'][0].choices
        self.assertEqual(sorted(choix), sorted(STATISTIQUES))
