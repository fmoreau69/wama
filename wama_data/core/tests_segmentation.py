"""Tests du Segmenter — les 8 modes de `WAMA_DATA_WORLD.md §9ter`.

Les cas ne sont pas inventés : ils reproduisent des situations tirées des trois systèmes
confrontés (fenêtres glissantes sur une ancre, jonction de deux flux d'événements, seuil bruité
qui produirait du confetti sans hystérésis, état non refermé en fin de session).
"""
import unittest
from pathlib import Path

from .segmentation import (autour, bascules, chevauche, conditionnelle, etats, fermer, jonction,
                           ouverts, present_dans)

BASE_REELLE = (Path(__file__).resolve().parents[2]
               / "claude" / "Exemple_trip" / "RecFile_REC_20190502_144710.trip")


class AutourTest(unittest.TestCase):
    """DEUX offsets indépendants — le point où mon modèle initial était faux."""

    def test_fenetre_classique(self):
        s = autour([100.0], 0.0, 15.0)
        self.assertEqual((s[0]['start'], s[0]['end']), (100.0, 115.0))

    def test_fenetre_qui_commence_APRES_l_ancre(self):
        # Inexprimable avec une simple durée — c'est tout l'intérêt des deux offsets.
        s = autour([100.0], 15.0, 45.0)
        self.assertEqual((s[0]['start'], s[0]['end']), (115.0, 145.0))

    def test_fenetre_qui_precede_l_ancre(self):
        s = autour([100.0], -10.0, 0.0)
        self.assertEqual((s[0]['start'], s[0]['end']), (90.0, 100.0))

    def test_famille_de_fenetres_emboitees_sur_la_meme_ancre(self):
        familles = [(0, 15), (0, 60), (0, 120), (15, 45)]
        produits = {f"{a}_{b}": autour([100.0], a, b)[0] for a, b in familles}
        self.assertEqual(produits['0_15']['end'], 115.0)
        self.assertEqual(produits['0_120']['end'], 220.0)
        self.assertEqual(produits['15_45']['start'], 115.0)

    def test_nommage_et_attributs(self):
        s = autour([10.0, 20.0], 0, 5, nom='TAG',
                   attributs=[{'level': 1}, {'level': 3}])
        self.assertEqual([x['name'] for x in s], ['TAG_01', 'TAG_02'])
        self.assertEqual(s[1]['level'], 3)

    def test_origine_tracee(self):
        s = autour([10.0], 0, 5)[0]
        self.assertEqual(s['origin'], 'autour')
        self.assertEqual(s['anchor'], 10.0)

    def test_offsets_incoherents_refuses(self):
        with self.assertRaises(ValueError):
            autour([0.0], 10.0, 5.0)


class JonctionTest(unittest.TestCase):
    """Début pris dans un flux, fin dans un autre."""

    def test_appariement_par_le_TEMPS_pas_par_index(self):
        # 3 débuts, 2 fins seulement, et pas d'alternance régulière : un appariement par index
        # produirait un segment à durée négative.
        s = jonction([10.0, 50.0, 90.0], [30.0, 70.0])
        self.assertEqual([(x['start'], x['end']) for x in s[:2]], [(10.0, 30.0), (50.0, 70.0)])
        self.assertTrue(all(x['end'] is None or x['end'] > x['start'] for x in s))

    def test_dernier_debut_sans_fin_reste_OUVERT(self):
        s = jonction([10.0, 90.0], [30.0])
        self.assertEqual(s[1]['end'], None)
        self.assertTrue(s[1]['open'])

    def test_fermer_dernier_ecarte_le_segment_ouvert(self):
        s = jonction([10.0, 90.0], [30.0], fermer_dernier=True)
        self.assertEqual(len(s), 1)

    def test_curseurs_de_depart(self):
        s = jonction([10.0, 50.0, 90.0], [30.0, 70.0, 110.0], depuis_debut=1)
        self.assertEqual(s[0]['start'], 50.0)

    def test_fins_anterieures_ignorees(self):
        # Une fin qui PRÉCÈDE le début ne peut pas le clore.
        s = jonction([50.0], [10.0, 80.0])
        self.assertEqual(s[0]['end'], 80.0)

    # ── Ajouts du 2026-08-23 : les deux manques relevés en §9ter.6 A ──────────────────────────

    def test_offsets_independants_sur_les_deux_bornes(self):
        # « du début du bloc moins 2 s jusqu'à la pause suivante plus 5 s » — inexprimable avant.
        s = jonction([10.0], [30.0], offset_debut=-2.0, offset_fin=5.0)
        self.assertEqual((s[0]['start'], s[0]['end']), (8.0, 35.0))

    def test_les_offsets_ne_changent_PAS_l_appariement(self):
        # Un décalage de bornes ne doit pas modifier quelle fin suit quel début : appliqué avant
        # l'appariement, un offset de -25 s ferait passer le début de 50 sous la fin de 30.
        sans = jonction([10.0, 50.0], [30.0, 70.0])
        avec = jonction([10.0, 50.0], [30.0, 70.0], offset_debut=-25.0)
        self.assertEqual([x['end'] for x in sans], [x['end'] for x in avec])
        self.assertEqual([x['start'] for x in avec], [-15.0, 25.0])

    def test_un_segment_ouvert_ne_recoit_pas_l_offset_de_fin(self):
        # `None + 5.0` lèverait ; pire, une sentinelle numérique s'y ferait décaler en silence.
        s = jonction([10.0, 90.0], [30.0], offset_fin=5.0)
        self.assertEqual(s[0]['end'], 35.0)
        self.assertIsNone(s[1]['end'])

    def test_repeter_faux_ne_produit_qu_UN_segment(self):
        # Mode par défaut de l'outil d'origine, où « Répéter sur les prochains segments » est une
        # case à cocher. Ici c'est l'inverse qui est le défaut — le cas courant n'a pas à se cocher.
        s = jonction([10.0, 50.0, 90.0], [30.0, 70.0, 110.0], repeter=False)
        self.assertEqual(len(s), 1)
        self.assertEqual((s[0]['start'], s[0]['end']), (10.0, 30.0))

    def test_repeter_faux_part_du_curseur(self):
        s = jonction([10.0, 50.0, 90.0], [30.0, 70.0, 110.0], depuis_debut=1, repeter=False)
        self.assertEqual([(x['start'], x['end']) for x in s], [(50.0, 70.0)])

    def test_repeter_vrai_est_le_comportement_historique(self):
        self.assertEqual(len(jonction([10.0, 50.0, 90.0], [30.0, 70.0, 110.0])), 3)

    def test_la_fenetre_n_est_tracee_que_si_un_offset_est_pose(self):
        self.assertNotIn('window', jonction([10.0], [30.0])[0])
        self.assertEqual(jonction([10.0], [30.0], offset_fin=5.0)[0]['window'], '0_5')


class BasculesTest(unittest.TestCase):
    """`masque → events` — le second port de sortie d'une condition (§9ter.6 B4)."""

    def setUp(self):
        self.times = [0.0, 1.0, 2.0, 3.0, 4.0, 5.0]
        self.masque = [False, False, True, True, False, False]

    def test_bascule_montante_datee_au_premier_echantillon_vrai(self):
        ev = bascules(self.times, self.masque)
        self.assertEqual([(e['time'], e['edge']) for e in ev], [(2.0, 'montante')])

    def test_descendantes_sur_demande(self):
        ev = bascules(self.times, self.masque, montantes=False, descendantes=True)
        self.assertEqual([(e['time'], e['edge']) for e in ev], [(4.0, 'descendante')])

    def test_les_deux_sens_ensemble(self):
        ev = bascules(self.times, self.masque, descendantes=True)
        self.assertEqual([e['edge'] for e in ev], ['montante', 'descendante'])

    def test_un_masque_vrai_des_le_debut_ne_produit_PAS_de_montante(self):
        # On n'a pas observé la transition : la dater reviendrait à la placer à un instant choisi
        # par l'acquisition, pas par le phénomène.
        ev = bascules([0.0, 1.0, 2.0], [True, True, False], descendantes=True)
        self.assertEqual([e['edge'] for e in ev], ['descendante'])

    def test_un_masque_constant_ne_produit_rien(self):
        self.assertEqual(bascules([0.0, 1.0], [True, True], descendantes=True), [])

    def test_les_bascules_ne_sont_PAS_des_segments(self):
        # Un événement n'a pas de durée — c'est ce qui distingue les deux ports.
        ev = bascules(self.times, self.masque)[0]
        self.assertNotIn('start', ev)
        self.assertNotIn('end', ev)
        self.assertEqual(ev['origin'], 'bascule')

    def test_le_MEME_masque_alimente_les_deux_ports(self):
        # Le point de §9ter.6 B4 : le mode de production ne décide plus de la nature du produit.
        seg = conditionnelle(self.times, self.masque)
        ev = bascules(self.times, self.masque)
        self.assertEqual((seg[0]['start'], seg[0]['end']), (2.0, 3.0))
        self.assertEqual(ev[0]['time'], 2.0)

    def test_longueurs_incoherentes_refusees(self):
        with self.assertRaises(ValueError):
            bascules([0.0, 1.0], [True])


class ConditionnelleTest(unittest.TestCase):
    """Hystérésis : sans elle, un seuil produit du confetti."""

    def setUp(self):
        # Signal à 10 Hz : une plage franche de 5 s, un trou d'un échantillon au milieu,
        # puis une micro-plage parasite de 0,2 s.
        self.times = [i * 0.1 for i in range(120)]
        self.masque = [False] * 120
        for i in range(10, 60):
            self.masque[i] = True
        self.masque[35] = False              # trou de 0,1 s
        for i in range(100, 102):
            self.masque[i] = True            # parasite

    def test_sans_hysteresis_le_confetti_apparait(self):
        s = conditionnelle(self.times, self.masque)
        self.assertEqual(len(s), 3, "trou et parasite produisent 3 plages")

    def test_trou_tolere_recolle(self):
        s = conditionnelle(self.times, self.masque, trou_tolere=0.25)
        self.assertEqual(len(s), 2)

    def test_duree_min_ecarte_le_parasite(self):
        s = conditionnelle(self.times, self.masque, trou_tolere=0.25, duree_min=1.0)
        self.assertEqual(len(s), 1)
        self.assertAlmostEqual(s[0]['start'], 1.0, places=6)

    def test_parametres_traces(self):
        s = conditionnelle(self.times, self.masque, trou_tolere=0.25, duree_min=1.0)[0]
        self.assertEqual(s['max_gap'], 0.25)
        self.assertEqual(s['min_duration'], 1.0)

    def test_longueurs_incoherentes_refusees(self):
        with self.assertRaises(ValueError):
            conditionnelle([0.0, 1.0], [True])


class EtatsTest(unittest.TestCase):
    """Un signal catégoriel EST une collection de segments — la conversion est ici."""

    def test_run_length(self):
        t = [0.0, 1.0, 2.0, 3.0, 4.0, 5.0]
        v = ['MANUEL', 'MANUEL', 'AUTO', 'AUTO', 'AUTO', 'MANUEL']
        s = etats(t, v)
        self.assertEqual([(x['value'], x['start'], x['end']) for x in s],
                         [('MANUEL', 0.0, 1.0), ('AUTO', 2.0, 4.0), ('MANUEL', 5.0, 5.0)])

    def test_valeur_ignoree(self):
        t = [0.0, 1.0, 2.0, 3.0]
        v = [-1, 'ROULE', 'ROULE', -1]      # -1 = « aucune section », comme dans les vraies données
        s = etats(t, v, ignorer=[-1])
        self.assertEqual(len(s), 1)
        self.assertEqual(s[0]['value'], 'ROULE')

    def test_nombre_d_echantillons_trace(self):
        s = etats([0.0, 1.0, 2.0], ['A', 'A', 'B'])
        self.assertEqual(s[0]['samples'], 2)


class EnsemblistesTest(unittest.TestCase):
    """« Présent dans » — réutilisé à l'export, donc une opération à part entière."""

    def setUp(self):
        self.ref = [{'start': 0.0, 'end': 100.0}, {'start': 200.0, 'end': 300.0}]

    def test_inclusion_stricte(self):
        segs = [{'start': 10.0, 'end': 20.0},      # dedans
                {'start': 0.0, 'end': 100.0},      # bornes égales → exclu en strict
                {'start': 150.0, 'end': 160.0}]    # dehors
        self.assertEqual(len(present_dans(segs, self.ref)), 1)
        self.assertEqual(len(present_dans(segs, self.ref, strict=False)), 2)

    def test_chevauchement_n_exige_pas_l_inclusion(self):
        segs = [{'start': 90.0, 'end': 150.0}]     # à cheval sur la borne
        self.assertEqual(len(present_dans(segs, self.ref)), 0)
        self.assertEqual(len(chevauche(segs, self.ref)), 1)

    def test_segment_ouvert_traite_comme_infini(self):
        segs = [{'start': 10.0, 'end': None}]
        self.assertEqual(len(present_dans(segs, self.ref)), 0)
        self.assertEqual(len(chevauche(segs, self.ref)), 1)


class OuvertsTest(unittest.TestCase):
    """Un état commencé et non refermé — ce que le modèle ne savait pas représenter (D15)."""

    def test_reperage(self):
        segs = [{'start': 0.0, 'end': 10.0}, {'start': 20.0, 'end': None}]
        self.assertEqual(len(ouverts(segs)), 1)

    def test_fermeture_EXPLICITE_et_tracee(self):
        segs = fermer([{'start': 20.0, 'end': None}], 99.0)
        self.assertEqual(segs[0]['end'], 99.0)
        self.assertEqual(segs[0]['closed_at'], 99.0,
                         "une durée refermée d'office n'a pas le statut d'une durée observée")

    def test_fermeture_ne_touche_pas_aux_segments_clos(self):
        segs = fermer([{'start': 0.0, 'end': 10.0}], 99.0)
        self.assertEqual(segs[0]['end'], 10.0)
        self.assertNotIn('closed_at', segs[0])


@unittest.skipUnless(BASE_REELLE.exists(),
                     f"base d'expérimentation absente ({BASE_REELLE.name}) — hors dépôt")
class BaseReelleTest(unittest.TestCase):
    """Reproduire les fenêtres RÉELLES d'une campagne à partir de ses événements."""

    def test_les_fenetres_reelles_se_reproduisent(self):
        from .. import sources
        ref = sources.load(BASE_REELLE, streams=["event_finTag_finDep_pieton_voiture",
                                                 "situation_0_15", "situation_15_45"])
        ancres = [ref.get("finTag_finDep_pieton_voiture").time_at(i)
                  for i in range(len(ref.get("finTag_finDep_pieton_voiture")))]

        for nom, o1, o2 in (("0_15", 0, 15), ("15_45", 15, 45)):
            attendu = ref.get(nom)
            produit = autour(ancres, o1, o2)
            self.assertEqual(len(produit), len(ancres))
            # Chaque segment réel doit se retrouver parmi les segments produits.
            starts = {round(p['start'], 3) for p in produit}
            for i in range(len(attendu)):
                self.assertIn(round(attendu.time_at(i), 3), starts,
                              f"{nom} : segment réel non reproduit")


if __name__ == "__main__":
    unittest.main(verbosity=2)
