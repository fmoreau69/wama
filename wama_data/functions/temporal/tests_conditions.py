"""Tests de la FRONTIÈRE pandas de la chaîne conditionnelle.

Le cœur (`core/tests_conditions.py`) est testé sans pandas. Ici on ne teste QUE ce que
l'adaptateur ajoute — et sa responsabilité propre est unique : **déterminer la sorte d'une
colonne en la LISANT dans la donnée**, puisque `data_types.py` type le cadre et non la colonne.

C'est aussi ici que se vérifie le point de §9ter.6 B4 : les deux ports de sortie consomment le
MÊME masque.
"""
import unittest

import pandas as pd

from wama.common.catalog.data_types import DataType, TypedFrame
from wama.common.catalog.function_catalog import get as get_function
from ...core.conditions import BOOLEAN, NUMERIC, TEXT
from .conditions import chain_to_events, chain_to_segments, column_kind

SIGNAL = TypedFrame(pd.DataFrame({
    'time':    [0.0, 1.0, 2.0, 3.0, 4.0, 5.0],
    'vitesse': [5.0, 35.0, 40.0, 38.0, 10.0, 4.0],
    'phase':   ['init', 'roule', 'roule', 'roule', 'FIN approche', 'stop'],
    'actif':   [False, True, True, True, True, False],
}), DataType.TIMESERIES)


def _c(key, field, operator, value=None):
    d = {'key': key, 'field': field, 'operator': operator}
    if value is not None:
        d['value'] = value
    return d


class SorteTest(unittest.TestCase):
    """La seule responsabilité propre de l'adaptateur."""

    def test_colonne_numerique(self):
        self.assertEqual(column_kind(SIGNAL, 'vitesse'), NUMERIC)

    def test_colonne_texte(self):
        self.assertEqual(column_kind(SIGNAL, 'phase'), TEXT)

    def test_un_booleen_n_est_PAS_vu_comme_numerique(self):
        # En pandas, `bool` est un sous-type de `number` : tester le booléen d'abord est la seule
        # façon de ne pas proposer `>=` sur une colonne de vrai/faux.
        self.assertEqual(column_kind(SIGNAL, 'actif'), BOOLEAN)

    def test_colonne_mixte_repliee_sur_TEXTE_pas_sur_numerique(self):
        # Le repli qui refuse le plus : `contient` plutôt qu'une comparaison silencieusement fausse.
        mixte = TypedFrame(pd.DataFrame({'time': [0.0, 1.0], 'c': [1, 'deux']}),
                           DataType.TIMESERIES)
        self.assertEqual(column_kind(mixte, 'c'), TEXT)

    def test_colonne_absente_nomme_les_disponibles(self):
        with self.assertRaises(ValueError) as ctx:
            column_kind(SIGNAL, 'inexistante')
        self.assertIn('vitesse', str(ctx.exception))


class ChaineVersSegmentsTest(unittest.TestCase):

    def test_une_seule_condition_sans_connecteur(self):
        out = chain_to_segments(SIGNAL, conditions=[_c('C1', 'vitesse', '>=', 30.0)])
        self.assertEqual(len(out.df), 1)
        self.assertEqual((out.df.iloc[0]['start'], out.df.iloc[0]['end']), (1.0, 3.0))

    def test_deux_conditions_assemblees(self):
        out = chain_to_segments(
            SIGNAL,
            conditions=[_c('C1', 'vitesse', '>=', 30.0), _c('C2', 'phase', '==', 'roule')],
            connectors='ET(C1, C2)')
        self.assertEqual(len(out.df), 1)

    def test_operateur_de_TEXTE_disponible(self):
        # Ce que « Segments par condition » ne savait pas faire : 6 opérateurs numériques seulement.
        out = chain_to_segments(
            SIGNAL, conditions=[_c('C1', 'phase', 'contains', 'FIN')])
        self.assertEqual(len(out.df), 1)
        self.assertEqual(out.df.iloc[0]['start'], 4.0)

    def test_operateur_d_ordre_sur_colonne_texte_REFUSE_avec_la_sorte_LUE(self):
        # La sorte n'est pas déclarée, elle est lue : la déclaration ne peut pas se contredire
        # avec la donnée.
        with self.assertRaises(ValueError) as ctx:
            chain_to_segments(SIGNAL, conditions=[_c('C1', 'phase', '<', 'M')])
        self.assertIn('texte', str(ctx.exception))

    def test_une_sorte_DECLAREE_dans_le_JSON_est_IGNOREE(self):
        # Mentir sur la sorte rétablirait le défaut qu'on corrige.
        menteuse = dict(_c('C1', 'phase', '<', 'M'), kind=NUMERIC)
        with self.assertRaises(ValueError):
            chain_to_segments(SIGNAL, conditions=[menteuse])

    def test_conditions_json_en_CHAINE_acceptees(self):
        import json
        out = chain_to_segments(
            SIGNAL, conditions=json.dumps([_c('C1', 'vitesse', '>=', 30.0)]))
        self.assertEqual(len(out.df), 1)

    def test_plusieurs_conditions_sans_connecteur_REFUSEES(self):
        # « ET » n'est pas plus évident que « OU » : on ne choisit pas à la place de l'utilisateur.
        with self.assertRaises(ValueError) as ctx:
            chain_to_segments(SIGNAL, conditions=[_c('C1', 'vitesse', '>=', 30.0),
                                                     _c('C2', 'phase', '==', 'roule')])
        self.assertIn('aucun connecteur', str(ctx.exception))

    def test_cles_en_double_refusees(self):
        with self.assertRaises(ValueError) as ctx:
            chain_to_segments(SIGNAL, conditions=[_c('C1', 'vitesse', '>=', 30.0),
                                                     _c('C1', 'vitesse', '<', 5.0)],
                                 connectors='OU(C1, C1)')
        self.assertIn('double', str(ctx.exception))

    def test_json_illisible_refuse(self):
        with self.assertRaises(ValueError):
            chain_to_segments(SIGNAL, conditions='{pas du json')

    def test_liste_vide_refusee(self):
        with self.assertRaises(ValueError):
            chain_to_segments(SIGNAL, conditions=[])

    def test_nom_derive_de_l_arbre_par_defaut(self):
        out = chain_to_segments(
            SIGNAL,
            conditions=[_c('C1', 'vitesse', '>=', 30.0), _c('C2', 'phase', '==', 'roule')],
            connectors='ET(C1, C2)')
        self.assertTrue(out.df.iloc[0]['name'].startswith('et_c1_c2'))

    def test_hysteresis_transmise_au_coeur(self):
        bruite = TypedFrame(pd.DataFrame({
            'time': [i * 0.1 for i in range(20)],
            'v': [0, 9, 0, 9, 9, 9, 9, 9, 9, 9, 0, 9, 0, 0, 0, 0, 0, 0, 0, 0],
        }), DataType.TIMESERIES)
        cond = [_c('C1', 'v', '>=', 5)]
        sans = chain_to_segments(bruite, conditions=cond)
        avec = chain_to_segments(bruite, conditions=cond, gap_tolerance=0.15, min_duration=0.5)
        self.assertGreater(len(sans.df), len(avec.df))

    def test_le_cadre_produit_est_bien_typé_segments(self):
        out = chain_to_segments(SIGNAL, conditions=[_c('C1', 'vitesse', '>=', 30.0)])
        self.assertEqual(out.data_type, DataType.SEGMENTS)


class ChaineVersEventsTest(unittest.TestCase):
    """Le SECOND port du même masque (§9ter.6 B4)."""

    COND = [{'key': 'C1', 'field': 'vitesse', 'operator': '>=', 'value': 30.0}]

    def test_bascule_montante(self):
        out = chain_to_events(SIGNAL, conditions=self.COND)
        self.assertEqual(list(out.df['time']), [1.0])
        self.assertEqual(list(out.df['edge']), ['montante'])

    def test_bascule_descendante_sur_demande(self):
        out = chain_to_events(SIGNAL, conditions=self.COND,
                                 rising=False, falling=True)
        self.assertEqual(list(out.df['time']), [4.0])

    def test_le_cadre_produit_est_bien_typé_events(self):
        out = chain_to_events(SIGNAL, conditions=self.COND)
        self.assertEqual(out.data_type, DataType.EVENTS)

    def test_aucune_bascule_rend_un_cadre_VIDE_mais_bien_forme(self):
        # Un cadre vide sans colonnes casserait le chaînage en aval de façon illisible.
        plat = TypedFrame(pd.DataFrame({'time': [0.0, 1.0], 'v': [1.0, 1.0]}),
                          DataType.TIMESERIES)
        out = chain_to_events(plat, conditions=[_c('C1', 'v', '>=', 0.0)])
        self.assertEqual(len(out.df), 0)
        self.assertIn('edge', out.df.columns)

    def test_les_DEUX_ports_consomment_le_MEME_masque(self):
        # Le point de §9ter.6 B4 : le mode de production ne décide plus de la nature du produit.
        seg = chain_to_segments(SIGNAL, conditions=self.COND)
        ev = chain_to_events(SIGNAL, conditions=self.COND)
        self.assertEqual(seg.df.iloc[0]['start'], ev.df.iloc[0]['time'])


class DeclarationsTest(unittest.TestCase):
    """Les deux fonctions sont bien AU CATALOGUE — sans quoi elles sont inchaînables (G1/G3)."""

    def test_les_deux_fonctions_sont_enregistrees(self):
        for key in ('segment_condition_chain', 'event_condition_chain'):
            self.assertIsNotNone(get_function(key), f"{key} absente du catalogue")

    def test_les_ports_de_sortie_different(self):
        self.assertEqual(get_function('segment_condition_chain').outputs[0].data_type,
                         DataType.SEGMENTS)
        self.assertEqual(get_function('event_condition_chain').outputs[0].data_type,
                         DataType.EVENTS)

    def test_l_aide_des_conditions_ENUMERE_les_operateurs_disponibles(self):
        # Dérivée du registre, jamais recopiée : une aide recopiée dérive du code qu'elle décrit.
        aide = next(p for p in get_function('segment_condition_chain').params
                    if p.key == 'conditions').description
        self.assertIn('contains', aide)
        self.assertIn('>=', aide)




class FiltreOccurrencesTest(unittest.TestCase):
    """Trou ③ de §11.9 — la même chaîne appliquée à des lignes qui EXISTENT déjà."""

    def _events(self, rows):
        import pandas as pd
        return TypedFrame(pd.DataFrame(rows), DataType.EVENTS)

    def _segments(self, rows):
        import pandas as pd
        df = pd.DataFrame(rows)
        if 'end' in df.columns and any(r.get('end') is None for r in rows):
            df['end'] = pd.Series([r.get('end') for r in rows], dtype=object)
        return TypedFrame(df, DataType.SEGMENTS)

    def test_filtrer_des_occurrences_par_texte(self):
        # La bascule [Data|Event] de l'écran d'origine : « le commentaire contient FIN ».
        from .conditions import filter_events
        ev = self._events([{'time': 1.0, 'comment': 'debut bloc'},
                           {'time': 2.0, 'comment': 'FIN de bloc'},
                           {'time': 3.0, 'comment': 'pause'}])
        out = filter_events(ev, conditions=[{'key': 'C1', 'field': 'comment',
                                             'operator': 'contains', 'value': 'FIN'}])
        self.assertEqual(list(out.df['time']), [2.0])
        self.assertEqual(out.data_type, DataType.EVENTS)

    def test_garder_les_situations_de_plus_d_une_minute(self):
        # Le cas posé par Fabien, mot pour mot — et `duration` n'est PAS une colonne du cadre.
        from .conditions import filter_segments
        segs = self._segments([{'start': 0.0, 'end': 30.0, 'name': 'courte'},
                               {'start': 100.0, 'end': 180.0, 'name': 'longue'}])
        out = filter_segments(segs, conditions=[{'key': 'C1', 'field': 'duration',
                                                 'operator': '>=', 'value': 60.0}])
        self.assertEqual(list(out.df['name']), ['longue'])
        self.assertNotIn('duration', out.df.columns, "un filtre sélectionne, il n'enrichit pas")

    def test_un_segment_OUVERT_est_rejete_par_une_condition_numerique_sur_la_duree(self):
        # Une durée inconnue ne satisfait pas « > 60 » — et ne satisfait pas « < 60 » non plus.
        from .conditions import filter_segments
        segs = self._segments([{'start': 0.0, 'end': 90.0}, {'start': 100.0, 'end': None}])
        garde = filter_segments(segs, conditions=[{'key': 'C1', 'field': 'duration',
                                                   'operator': '>=', 'value': 60.0}])
        self.assertEqual(list(garde.df['start']), [0.0])

    def test_un_segment_OUVERT_se_selectionne_par_l_operateur_empty(self):
        from .conditions import filter_segments
        segs = self._segments([{'start': 0.0, 'end': 90.0}, {'start': 100.0, 'end': None}])
        les_ouverts = filter_segments(segs, conditions=[{'key': 'C1', 'field': 'duration',
                                                     'operator': 'empty'}])
        self.assertEqual(list(les_ouverts.df['start']), [100.0])

    def test_vitesse_moyenne_par_COMPOSITION_avec_le_calculator(self):
        # « Garder les situations à vitesse moyenne > 30 » = calc_per_segment PUIS le filtre.
        import pandas as pd
        from .calculation import calc_per_segment
        from .conditions import filter_segments
        signal = TypedFrame(pd.DataFrame({'time': [0.0, 1.0, 2.0, 10.0, 11.0, 12.0],
                                          'value': [50.0, 40.0, 45.0, 10.0, 12.0, 8.0]}),
                            DataType.SIGNAL)
        segs = self._segments([{'start': 0.0, 'end': 2.0}, {'start': 10.0, 'end': 12.0}])
        avec = calc_per_segment(segs, signal, statistics='mean')
        out = filter_segments(avec, conditions=[{'key': 'C1', 'field': 'value_mean',
                                                 'operator': '>', 'value': 30.0}])
        self.assertEqual(list(out.df['start']), [0.0])

    def test_l_entree_n_est_pas_mutee_et_l_arbre_logique_s_applique(self):
        from .conditions import filter_events
        ev = self._events([{'time': 1.0, 'v': 10.0, 'txt': 'a'},
                           {'time': 2.0, 'v': 50.0, 'txt': 'FIN'},
                           {'time': 3.0, 'v': 50.0, 'txt': 'b'}])
        out = filter_events(ev,
                            conditions=[{'key': 'C1', 'field': 'v', 'operator': '>=', 'value': 30},
                                        {'key': 'C2', 'field': 'txt', 'operator': 'contains',
                                         'value': 'FIN'}],
                            connectors='ET(C1, C2)')
        self.assertEqual(list(out.df['time']), [2.0])
        self.assertEqual(len(ev.df), 3)

    def test_les_filtres_sont_DECLARES_au_catalogue(self):
        # ⚠ La leçon du trou ② : une capacité non déclarée est invisible de l'UI générée.
        from wama.common.catalog.function_catalog import get
        for key in ('event_filter', 'segment_filter', 'event_within'):
            self.assertIsNotNone(get(key), f"{key} absent du catalogue")


class EvenementsDansContexteTest(unittest.TestCase):
    """Le point « mineur » de §11.9, câblé : la restriction Situation sur une sortie ÉVÉNEMENTS."""

    def test_seuls_les_instants_DANS_la_situation_survivent(self):
        import pandas as pd
        from .segmentation import events_within
        ev = TypedFrame(pd.DataFrame({'time': [5.0, 15.0, 25.0]}), DataType.EVENTS)
        ref = TypedFrame(pd.DataFrame({'start': [10.0], 'end': [20.0]}), DataType.SEGMENTS)
        out = events_within(ev, ref)
        self.assertEqual(list(out.df['time']), [15.0])

    def test_une_fin_OUVERTE_contient_tout_instant_posterieur(self):
        import pandas as pd
        from .segmentation import events_within
        ev = TypedFrame(pd.DataFrame({'time': [5.0, 500.0]}), DataType.EVENTS)
        ref = TypedFrame(pd.DataFrame([{'start': 10.0, 'end': None}]), DataType.SEGMENTS)
        out = events_within(ev, ref)
        self.assertEqual(list(out.df['time']), [500.0])


if __name__ == '__main__':
    unittest.main()
