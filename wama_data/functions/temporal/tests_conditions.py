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
from ...core.conditions import BOOLEEN, NUMERIQUE, TEXTE
from .conditions import chain_to_events, chain_to_segments, sorte_de_colonne

SIGNAL = TypedFrame(pd.DataFrame({
    'time':    [0.0, 1.0, 2.0, 3.0, 4.0, 5.0],
    'vitesse': [5.0, 35.0, 40.0, 38.0, 10.0, 4.0],
    'phase':   ['init', 'roule', 'roule', 'roule', 'FIN approche', 'stop'],
    'actif':   [False, True, True, True, True, False],
}), DataType.TIMESERIES)


def _c(cle, champ, operator, valeur=None):
    d = {'key': cle, 'field': champ, 'operator': operator}
    if valeur is not None:
        d['value'] = valeur
    return d


class SorteTest(unittest.TestCase):
    """La seule responsabilité propre de l'adaptateur."""

    def test_colonne_numerique(self):
        self.assertEqual(sorte_de_colonne(SIGNAL, 'vitesse'), NUMERIQUE)

    def test_colonne_texte(self):
        self.assertEqual(sorte_de_colonne(SIGNAL, 'phase'), TEXTE)

    def test_un_booleen_n_est_PAS_vu_comme_numerique(self):
        # En pandas, `bool` est un sous-type de `number` : tester le booléen d'abord est la seule
        # façon de ne pas proposer `>=` sur une colonne de vrai/faux.
        self.assertEqual(sorte_de_colonne(SIGNAL, 'actif'), BOOLEEN)

    def test_colonne_mixte_repliee_sur_TEXTE_pas_sur_numerique(self):
        # Le repli qui refuse le plus : `contient` plutôt qu'une comparaison silencieusement fausse.
        mixte = TypedFrame(pd.DataFrame({'time': [0.0, 1.0], 'c': [1, 'deux']}),
                           DataType.TIMESERIES)
        self.assertEqual(sorte_de_colonne(mixte, 'c'), TEXTE)

    def test_colonne_absente_nomme_les_disponibles(self):
        with self.assertRaises(ValueError) as ctx:
            sorte_de_colonne(SIGNAL, 'inexistante')
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
        menteuse = dict(_c('C1', 'phase', '<', 'M'), sorte=NUMERIQUE)
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
        for cle in ('segment_condition_chain', 'event_condition_chain'):
            self.assertIsNotNone(get_function(cle), f"{cle} absente du catalogue")

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


if __name__ == '__main__':
    unittest.main()
