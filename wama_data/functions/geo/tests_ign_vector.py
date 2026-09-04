"""Tests de l'adaptation IGN → port `road_map`.

⚠ LE test de ce fichier est `InversionDesAxesTest` : l'ordre des coordonnées est le seul
écart des trois qui ne lève **aucune erreur**. Nom de champ manquant → `KeyError` ;
conteneur faux → `AttributeError` ; axes inversés → un map-matching parfaitement muet qui
rend `section_id=None` sur toute la trace, ce qu'on lirait comme « pas de route ici ».
D'où un test qui ne regarde pas la forme mais le RÉSULTAT du chaînage : la trace se recale,
ou elle ne se recale pas.

Sans Django ni réseau : `fetch_roads` est remplacé le temps du test.

    python3 wama_data/functions/geo/tests_ign_vector.py
"""
import unittest

from wama.common.catalog.data_types import DataType, TypedFrame

from ..driving.gps_map_match import map_match
from . import ign_vector

#: Un tronçon est-ouest de ~78 m, à Lyon. En BD TOPO il arrive en (lon, lat).
LAT, LON = 45.75780, 4.83200
TRONCON_LONLAT = [(4.83200, 45.75780), (4.83300, 45.75780)]


def _avec_troncons(troncons):
    """Remplace `fetch_roads` par une réponse figée (aucun appel réseau)."""
    def faux_fetch(lat, lon, radius_m=300.0):
        return troncons
    return faux_fetch


class _BaseIGN(unittest.TestCase):

    def setUp(self):
        self._vrai_fetch = ign_vector.fetch_roads

    def tearDown(self):
        ign_vector.fetch_roads = self._vrai_fetch

    def _road_map(self, troncons):
        ign_vector.fetch_roads = _avec_troncons(troncons)
        return ign_vector.road_map_frame(LAT, LON, 300.0)


class InversionDesAxesTest(_BaseIGN):

    def test_la_geometrie_sort_en_lat_lon_pas_en_lon_lat(self):
        rm = self._road_map([{"coords": TRONCON_LONLAT, "nature": "Route à 1 chaussée",
                              "nom": "Rue de la Part-Dieu", "sens": "Double", "largeur": 6.0}])
        (premier_lat, premier_lon) = rm.df.iloc[0]['geometry'][0]
        # Une latitude vaut ~45, une longitude ~4,8 : les confondre est indolore en Python
        # et fatal en géométrie.
        self.assertAlmostEqual(premier_lat, 45.75780, places=5)
        self.assertAlmostEqual(premier_lon, 4.83200, places=5)

    def test_une_trace_SUR_la_route_se_recale_bien_dessus(self):
        """Le test décisif : bout en bout, IGN → map_match. Axes inversés ⇒ la route part
        à ~4 700 km, plus rien ne matche, et AUCUNE exception n'est levée."""
        import pandas as pd
        rm = self._road_map([{"coords": TRONCON_LONLAT, "nature": None,
                              "nom": "Rue témoin", "sens": None, "largeur": None}])
        # Trace 3 m au nord de l'axe, au milieu du tronçon, cap plein est.
        trace = TypedFrame(pd.DataFrame({
            'lat': [45.75780 + 3.0 / 111320.0],
            'lon': [4.83250],
            'heading': [90.0],
        }), DataType.GEO_TRACK)

        out = map_match(trace, rm, max_dist_m=20.0)

        self.assertEqual(out.df.iloc[0]['section_id'], "Rue témoin")
        self.assertLess(out.df.iloc[0]['match_dist_m'], 5.0)
        # Cap du segment ≈ 90° (plein est) et véhicule dans le même sens ⇒ +1.
        self.assertAlmostEqual(out.df.iloc[0]['matched_bearing'], 90.0, delta=1.0)
        self.assertEqual(out.df.iloc[0]['direction'], 1)


class FormeDuPortTest(_BaseIGN):

    def test_le_type_et_les_colonnes_requises_du_port_sont_la(self):
        rm = self._road_map([{"coords": TRONCON_LONLAT, "nature": "Rond-point",
                              "nom": None, "sens": "Direct", "largeur": 5.5}])
        self.assertEqual(rm.data_type, DataType.ROAD_MAP)
        # `geometry` et `id` sont les champs REQUIS de ROAD_MAP (data_types.py).
        for champ in ('id', 'geometry', 'type', 'nom', 'sens', 'largeur_m'):
            self.assertIn(champ, rm.df.columns)

    def test_une_voie_sans_nom_recoit_quand_meme_une_section_a_elle(self):
        rm = self._road_map([
            {"coords": TRONCON_LONLAT, "nature": None, "nom": None, "sens": None, "largeur": None},
            {"coords": TRONCON_LONLAT, "nature": None, "nom": None, "sens": None, "largeur": None},
        ])
        ids = list(rm.df['id'])
        self.assertEqual(len(set(ids)), 2, "deux voies anonymes ne doivent pas fusionner")

    def test_deux_troncons_de_la_meme_rue_partagent_leur_section(self):
        rm = self._road_map([
            {"coords": TRONCON_LONLAT, "nature": None, "nom": "Rue A", "sens": None, "largeur": None},
            {"coords": [(4.83300, 45.75780), (4.83400, 45.75780)], "nature": None,
             "nom": "Rue A", "sens": None, "largeur": None},
        ])
        self.assertEqual(set(rm.df['id']), {"Rue A"})

    def test_un_troncon_degenere_est_ecarte_pas_propage(self):
        rm = self._road_map([{"coords": [(4.83200, 45.75780)], "nature": None,
                              "nom": "Point seul", "sens": None, "largeur": None}])
        self.assertEqual(len(rm.df), 0)

    def test_aucun_troncon_rend_un_frame_vide_mais_TYPE(self):
        """Zone rurale / WFS injoignable : `fetch_roads` rend []. Le port doit rester
        chaînable (colonnes présentes), sinon l'aval casse sur une absence de réseau."""
        rm = self._road_map([])
        self.assertEqual(rm.data_type, DataType.ROAD_MAP)
        self.assertEqual(len(rm.df), 0)
        self.assertIn('geometry', rm.df.columns)


class ProvenanceTest(_BaseIGN):

    def test_la_source_est_TRACEE_dans_les_meta(self):
        """Deux référentiels alimentent désormais le même port : lequel a servi doit se
        lire sur la donnée, pas se déduire du code appelant."""
        rm = self._road_map([{"coords": TRONCON_LONLAT, "nature": None, "nom": "R",
                              "sens": None, "largeur": None}])
        self.assertIn('BDTOPO', rm.meta['source'])
        self.assertEqual(rm.meta['center'], (LAT, LON))


if __name__ == '__main__':
    unittest.main(verbosity=2)
