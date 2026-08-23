"""Tests des prédicats spatiaux — et du cas `cam_analyzer` reproduit de bout en bout.

⚠ LE test de ce fichier est `CasCamAnalyzerTest` : il refait, avec les briques génériques du monde
Data, ce que `cam_analyzer::find_intersection_windows` fait aujourd'hui en code dédié. C'est lui
qui atteste que le portage annoncé (`WAMA_DATA_WORLD.md §9septies`) est possible — sans quoi
« on pourra le porter plus tard » ne serait qu'une intention.
"""
import unittest

import pandas as pd

from wama.common.catalog.data_types import DataType, TypedFrame
from wama.common.catalog.function_catalog import get

from ...core.segmentation import conditionnelle, masque_hysteresis
from .spatial import distance_a_point

#: Un carrefour et une trace qui l'approche, le traverse et s'en éloigne — 1 point/s.
CARREFOUR = (45.75000, 4.85000)


def _trace(offsets_lat):
    """Trace géolocalisée : `offsets_lat` en degrés depuis le carrefour (1° ≈ 111 km)."""
    return TypedFrame(pd.DataFrame({
        'time': [float(i) for i in range(len(offsets_lat))],
        'lat': [CARREFOUR[0] + o for o in offsets_lat],
        'lon': [CARREFOUR[1]] * len(offsets_lat),
    }), DataType.GEO_TRACK)


#: ~0,0009° ≈ 100 m ; ~0,00027° ≈ 30 m ; ~0,00036° ≈ 40 m.
LOIN, DEDANS, FRONTIERE = 0.0009, 0.00027, 0.00036


class DistanceAPointTest(unittest.TestCase):

    def test_la_colonne_est_ADJOINTE_et_nommee_du_POINT(self):
        out = distance_a_point(_trace([0.0, LOIN]), *CARREFOUR, nom='carrefour_nord')
        self.assertIn('distance_carrefour_nord', out.df.columns)
        # ENRICHER : mêmes lignes, une colonne de plus (§9quater.4).
        self.assertEqual(len(out.df), 2)
        self.assertIn('lat', out.df.columns)

    def test_les_distances_sont_justes(self):
        out = distance_a_point(_trace([0.0, LOIN]), *CARREFOUR, nom='c')
        d = list(out.df['distance_c'])
        self.assertAlmostEqual(d[0], 0.0, delta=0.01)
        self.assertAlmostEqual(d[1], 100.0, delta=1.0)

    def test_le_nom_est_NORMALISE_par_la_brique_commune(self):
        out = distance_a_point(_trace([0.0]), *CARREFOUR, nom='Carrefour Nord (RD1)')
        self.assertIn('distance_carrefour_nord_rd1', out.df.columns)

    def test_un_point_SANS_NOM_est_refuse(self):
        # Deux distances à deux points différents écraseraient la même colonne.
        with self.assertRaises(ValueError) as ctx:
            distance_a_point(_trace([0.0]), *CARREFOUR)
        self.assertIn('nommer', str(ctx.exception))

    def test_deux_points_donnent_deux_colonnes(self):
        out = distance_a_point(_trace([0.0, LOIN]), *CARREFOUR, nom='nord')
        out = distance_a_point(out, 45.76, 4.86, nom='sud')
        self.assertIn('distance_nord', out.df.columns)
        self.assertIn('distance_sud', out.df.columns)

    def test_l_entree_n_est_PAS_mutee(self):
        t = _trace([0.0])
        distance_a_point(t, *CARREFOUR, nom='c')
        self.assertNotIn('distance_c', t.df.columns)

    def test_colonne_geographique_absente_refusee(self):
        t = TypedFrame(pd.DataFrame({'time': [0.0], 'x': [1.0]}), DataType.GEO_TRACK)
        with self.assertRaises(ValueError):
            distance_a_point(t, *CARREFOUR, nom='c')

    def test_elle_est_DECLAREE_au_catalogue_comme_ENRICHER(self):
        from wama.common.catalog.function_catalog import FunctionCategory
        spec = get('distance_a_point')
        self.assertIsNotNone(spec)
        # ENRICHER ⇒ la règle de §9quater.4 la garde DANS la table. C'est ce qui rend la
        # combinaison avec un prédicat temporel possible.
        self.assertEqual(spec.category, FunctionCategory.ENRICHER)


class CasCamAnalyzerTest(unittest.TestCase):
    """⚠ LE test : la zone à rayon autour d'un carrefour, refaite en briques génériques."""

    def test_zone_a_rayon_reproduite_sans_code_dedie(self):
        # Approche, traversée, éloignement. Rayon d'analyse : 40 m.
        trace = _trace([LOIN, LOIN, DEDANS, DEDANS, DEDANS, LOIN, LOIN])
        avec = distance_a_point(trace, *CARREFOUR, nom='carrefour')
        d = list(avec.df['distance_carrefour'])
        masque = [x is not None and x <= 40.0 for x in d]
        segs = conditionnelle(list(avec.df['time']), masque)
        self.assertEqual(len(segs), 1)
        self.assertEqual((segs[0]['start'], segs[0]['end']), (2.0, 4.0))

    def test_le_GPS_qui_TREMBLE_sur_la_frontiere_ne_coupe_PAS(self):
        # Le défaut que `exit_distance_factor` corrige chez cam_analyzer : sans hystérésis de
        # VALEUR, ce passage unique se découpe en plusieurs.
        trace = _trace([LOIN, DEDANS, FRONTIERE, DEDANS, FRONTIERE, DEDANS, LOIN])
        avec = distance_a_point(trace, *CARREFOUR, nom='carrefour')
        d = list(avec.df['distance_carrefour'])
        temps = list(avec.df['time'])

        seuil_simple = conditionnelle(temps, [x <= 39.0 for x in d])
        avec_hyst = conditionnelle(temps, masque_hysteresis(d, 39.0, 60.0))

        self.assertGreater(len(seuil_simple), 1, "le cas de test doit bien produire du confetti")
        self.assertEqual(len(avec_hyst), 1)
        self.assertEqual((avec_hyst[0]['start'], avec_hyst[0]['end']), (1.0, 5.0))

    def test_spatial_ET_temporel_dans_la_MEME_chaine(self):
        """Ce qu'un « mode spatial » séparé n'aurait jamais permis (§9septies)."""
        from ..temporal.conditions import chaine_vers_segments

        trace = _trace([LOIN, DEDANS, DEDANS, DEDANS, LOIN])
        avec = distance_a_point(trace, *CARREFOUR, nom='carrefour')
        # Une vitesse, pour que la condition temporelle ait de quoi mordre.
        avec.df['vitesse'] = [50.0, 10.0, 35.0, 40.0, 50.0]

        segs = chaine_vers_segments(
            avec,
            conditions=[{'cle': 'C1', 'champ': 'distance_carrefour',
                         'operateur': '<=', 'valeur': 40.0},
                        {'cle': 'C2', 'champ': 'vitesse', 'operateur': '>=', 'valeur': 30.0}],
            connecteurs='ET(C1, C2)')
        # Seuls les instants 2 et 3 satisfont les DEUX — dans la zone ET assez vite.
        self.assertEqual(len(segs.df), 1)
        self.assertEqual((segs.df.iloc[0]['start'], segs.df.iloc[0]['end']), (2.0, 3.0))


if __name__ == '__main__':
    unittest.main()
