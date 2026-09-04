"""Tests du référentiel OSM — et du piège d'axes SYMÉTRIQUE de celui de l'IGN.

⚠ Le risque de ce module n'est pas d'oublier l'inversion, c'est d'en AJOUTER une par
symétrie avec `ign_vector`. Overpass rend `lat`/`lon` nommés et attend son bbox en
(sud, ouest, nord, est) : les deux conventions sont l'exact opposé du WFS IGN. Une
inversion de trop ne lèverait, là encore, aucune erreur.

Sans Django ni réseau : `_overpass` est remplacé le temps du test.

    python3 -m unittest wama_data.functions.geo.tests_osm_vector
"""
import unittest

from wama.common.catalog.data_types import DataType, TypedFrame

from ..driving.gps_map_match import map_match
from . import osm_vector

LAT, LON = 45.75780, 4.83200

#: Réponse Overpass typique : géométrie en lat/lon NOMMÉS (pas des paires positionnelles).
WAY_EST_OUEST = {
    'type': 'way', 'id': 1234,
    'tags': {'highway': 'primary', 'name': 'Rue témoin', 'oneway': 'yes',
             'lanes': '2', 'maxspeed': '50'},
    'geometry': [{'lat': 45.75780, 'lon': 4.83200}, {'lat': 45.75780, 'lon': 4.83300}],
}
NODE_STOP = {'type': 'node', 'id': 77, 'lat': 45.75782, 'lon': 4.83250,
             'tags': {'highway': 'stop'}}
NODE_CROSSING = {'type': 'node', 'id': 78, 'lat': 45.75800, 'lon': 4.83210,
                 'tags': {'highway': 'crossing', 'crossing': 'marked'}}


class _BaseOSM(unittest.TestCase):

    def setUp(self):
        self._vrai = osm_vector._overpass
        self.dernieres_requetes = []

    def tearDown(self):
        osm_vector._overpass = self._vrai

    def _repond(self, elements):
        def faux(corps, lat, lon, radius_m, timeout_s=60):
            self.dernieres_requetes.append((corps, lat, lon, radius_m))
            return elements
        osm_vector._overpass = faux


class AxesOverpassTest(_BaseOSM):

    def test_le_bbox_sort_en_SUD_OUEST_NORD_EST(self):
        s, o, n, e = osm_vector._bbox_around(LAT, LON, 300.0)
        # Sud/Nord sont des LATITUDES (~45), Ouest/Est des LONGITUDES (~4,8).
        self.assertLess(s, LAT)
        self.assertGreater(n, LAT)
        self.assertLess(o, LON)
        self.assertGreater(e, LON)
        self.assertAlmostEqual((s + n) / 2, LAT, places=6)
        self.assertAlmostEqual((o + e) / 2, LON, places=6)

    def test_la_geometrie_reste_en_lat_lon_AUCUNE_inversion_ajoutee(self):
        self._repond([WAY_EST_OUEST])
        rm = osm_vector.road_map_frame(LAT, LON, 300.0)
        (premier_lat, premier_lon) = rm.df.iloc[0]['geometry'][0]
        self.assertAlmostEqual(premier_lat, 45.75780, places=5)
        self.assertAlmostEqual(premier_lon, 4.83200, places=5)

    def test_une_trace_SUR_la_voie_OSM_se_recale_bien_dessus(self):
        """Bout en bout OSM → map_match, jumeau du test décisif d'`ign_vector`."""
        import pandas as pd
        self._repond([WAY_EST_OUEST])
        rm = osm_vector.road_map_frame(LAT, LON, 300.0)
        trace = TypedFrame(pd.DataFrame({
            'lat': [45.75780 + 3.0 / 111320.0], 'lon': [4.83250], 'heading': [90.0],
        }), DataType.GEO_TRACK)

        out = map_match(trace, rm, max_dist_m=20.0)

        self.assertEqual(out.df.iloc[0]['section_id'], 'Rue témoin')
        self.assertLess(out.df.iloc[0]['match_dist_m'], 5.0)
        self.assertEqual(out.df.iloc[0]['direction'], 1)


class SemantiqueDeControleTest(_BaseOSM):
    """Ce que l'IGN ne publie pas — la raison d'être du module."""

    def test_les_noeuds_de_controle_sont_typés_par_leur_REGLE(self):
        self._repond([NODE_STOP, NODE_CROSSING])
        nodes = osm_vector.fetch_control_nodes(LAT, LON)
        self.assertEqual({n['control'] for n in nodes}, {'stop', 'crossing'})

    def test_un_passage_a_niveau_ferroviaire_est_retenu_aussi(self):
        self._repond([{'type': 'node', 'id': 9, 'lat': LAT, 'lon': LON,
                       'tags': {'railway': 'level_crossing'}}])
        nodes = osm_vector.fetch_control_nodes(LAT, LON)
        self.assertEqual(nodes[0]['control'], 'level_crossing')

    def test_un_noeud_sans_tag_de_controle_est_ecarte(self):
        self._repond([{'type': 'node', 'id': 5, 'lat': LAT, 'lon': LON, 'tags': {}}])
        self.assertEqual(osm_vector.fetch_control_nodes(LAT, LON), [])

    def test_l_ecart_a_un_marquage_DETECTE_est_rendu_en_METRES(self):
        """Le geste visé : confronter une ligne d'arrêt détectée au `stop` déclaré."""
        self._repond([NODE_STOP])
        nodes = osm_vector.fetch_control_nodes(LAT, LON)
        # Marquage détecté ~5 m au sud du stop OSM.
        trouve = osm_vector.nearest_control(nodes, 45.75782 - 5.0 / 111320.0, 4.83250)
        self.assertIsNotNone(trouve)
        node, dist = trouve
        self.assertEqual(node['control'], 'stop')
        self.assertAlmostEqual(dist, 5.0, delta=0.3)

    def test_au_dela_du_rayon_on_rend_None_plutot_qu_un_appariement_douteux(self):
        self._repond([NODE_STOP])
        nodes = osm_vector.fetch_control_nodes(LAT, LON)
        loin = osm_vector.nearest_control(nodes, 45.75782 + 200.0 / 111320.0, 4.83250,
                                          max_dist_m=25.0)
        self.assertIsNone(loin)

    def test_les_attributs_de_circulation_arrivent_jusqu_au_port(self):
        self._repond([WAY_EST_OUEST])
        r = osm_vector.road_map_frame(LAT, LON).df.iloc[0]
        self.assertEqual(r['sens'], 'yes')
        self.assertEqual(r['lanes'], '2')
        self.assertEqual(r['maxspeed'], '50')


class RobustesseTest(_BaseOSM):

    def test_les_voies_NON_carrossables_sont_exclues_par_la_requete(self):
        self._repond([WAY_EST_OUEST])
        osm_vector.fetch_roads(LAT, LON)
        corps = self.dernieres_requetes[0][0]
        for exclu in ('footway', 'path', 'steps', 'cycleway', 'pedestrian'):
            self.assertIn(exclu, corps)

    def test_une_voie_degeneree_est_ecartee(self):
        self._repond([{'type': 'way', 'id': 2, 'tags': {'highway': 'residential'},
                       'geometry': [{'lat': LAT, 'lon': LON}]}])
        self.assertEqual(len(osm_vector.road_map_frame(LAT, LON).df), 0)

    def test_overpass_injoignable_rend_un_port_VIDE_mais_typé(self):
        """Politique d'`ign_vector` : une panne réseau ne casse jamais la chaîne."""
        self._repond([])
        rm = osm_vector.road_map_frame(LAT, LON)
        cn = osm_vector.control_nodes_frame(LAT, LON)
        self.assertEqual(rm.data_type, DataType.ROAD_MAP)
        self.assertEqual(cn.data_type, DataType.TABLE)
        self.assertEqual(len(rm.df), 0)
        self.assertIn('geometry', rm.df.columns)
        self.assertIn('control', cn.df.columns)

    def test_une_voie_sans_nom_garde_un_identifiant_STABLE_son_osm_id(self):
        self._repond([{'type': 'way', 'id': 4242, 'tags': {'highway': 'service'},
                       'geometry': [{'lat': 45.7578, 'lon': 4.8320},
                                    {'lat': 45.7578, 'lon': 4.8330}]}])
        self.assertEqual(osm_vector.road_map_frame(LAT, LON).df.iloc[0]['id'], 'osm_way_4242')

    def test_la_source_est_TRACEE_dans_les_meta(self):
        self._repond([WAY_EST_OUEST])
        self.assertEqual(osm_vector.road_map_frame(LAT, LON).meta['source'], 'osm:overpass')


if __name__ == '__main__':
    unittest.main(verbosity=2)
