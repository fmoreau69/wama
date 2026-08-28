"""Tests des ENVELOPPES de segmentation — ce que le catalogue déclare et fait circuler.

⚠ POURQUOI CE FICHIER (trou ② de `WAMA_DATA_WORLD.md §11.9`, mesuré le 2026-08-26). Le cœur de
`join()` portait curseurs, offsets et « répéter » depuis le début — mais l'enveloppe ne les
DÉCLARAIT pas, et l'UI se génère des `ParamSpec` : l'écran « Double » n'aurait eu ni offsets, ni
curseurs, ni case « Répéter ». Ces tests gardent la DÉCLARATION, pas la logique (elle est testée
dans `core/tests_segmentation.py`) — une capacité non déclarée est une capacité invisible, et
rien d'autre ne le signale.
"""
import unittest

import pandas as pd

from wama.common.catalog.data_types import DataType, TypedFrame
from wama.common.catalog.function_catalog import get

from .segmentation import segments_join, segments_margins


def _events(times):
    return TypedFrame(pd.DataFrame({'time': times}), DataType.EVENTS)


class JonctionEnveloppeTest(unittest.TestCase):

    def test_curseurs_offsets_et_repeter_traversent_l_enveloppe(self):
        s = segments_join(_events([10.0, 50.0, 90.0]), _events([30.0, 70.0, 110.0]),
                              skip_starts=1, offset_start=-2.0, offset_end=5.0)
        self.assertEqual([(r['start'], r['end']) for r in s.df.to_dict('records')],
                         [(48.0, 75.0), (88.0, 115.0)])

    def test_repeter_decoche_ne_produit_que_le_segment_des_curseurs(self):
        s = segments_join(_events([10.0, 50.0, 90.0]), _events([30.0, 70.0, 110.0]),
                              repeat=False)
        self.assertEqual(len(s.df), 1)

    def test_les_cinq_parametres_du_coeur_sont_DECLARES(self):
        # ⚠ LE test du trou ② : c'est la déclaration qui génère l'écran « Double ».
        cles = {p.key for p in get('segment_join').params}
        for attendu in ('offset_start', 'offset_end', 'skip_starts', 'skip_ends', 'repeat'):
            self.assertIn(attendu, cles)


class MargesEnveloppeTest(unittest.TestCase):

    def test_les_marges_traversent_et_une_fin_ouverte_SURVIT_au_cadre(self):
        zone = TypedFrame(pd.DataFrame([{'start': 10.0, 'end': 20.0},
                                        {'start': 30.0, 'end': None}]), DataType.SEGMENTS)
        s = segments_margins(zone, before=1.0, after=2.0)
        rows = s.df.to_dict('records')
        self.assertEqual((rows[0]['start'], rows[0]['end']), (9.0, 22.0))
        self.assertEqual(rows[1]['start'], 29.0)
        self.assertIsNone(rows[1]['end'])




class AppariementEnveloppeTest(unittest.TestCase):
    """`event_pairing` — le compte rendu de consistance voyage avec le cadre."""

    def test_le_defaut_de_consistance_est_RENDU_lignes_et_meta(self):
        from .segmentation import events_pairing
        apparitions = _events([0.0, 10.0, 20.0])
        detections = _events([2.0, 22.0])
        out = events_pairing(apparitions, detections)
        rows = out.df.to_dict('records')
        self.assertEqual([r['matched'] for r in rows], [True, False, True])
        self.assertIsNone(rows[1]['end'])
        self.assertEqual(out.meta['pairing']['unmatched_starts'], 1)
        self.assertEqual(out.meta['pairing']['unpaired_ends'], [])
        self.assertEqual(out.data_type, DataType.SEGMENTS)

    def test_la_duree_est_le_temps_de_detection_et_se_filtre(self):
        # La chaîne complète du cas : appariement → filtre sur la durée de détection.
        from .conditions import filter_segments
        from .segmentation import events_pairing
        out = events_pairing(_events([0.0, 10.0]), _events([0.5, 13.0]))
        lentes = filter_segments(out, conditions=[{'key': 'C1', 'field': 'duration',
                                                   'operator': '>=', 'value': 2.0}])
        self.assertEqual(list(lentes.df['start']), [10.0])

    def test_declare_au_catalogue(self):
        self.assertIsNotNone(get('event_pairing'), "event_pairing absent du catalogue")


if __name__ == '__main__':
    unittest.main()
