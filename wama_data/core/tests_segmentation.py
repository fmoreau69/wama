"""Tests du Segmenter — les 8 modes de `WAMA_DATA_WORLD.md §9ter`.

Les cas ne sont pas inventés : ils reproduisent des situations tirées des trois systèmes
confrontés (fenêtres glissantes sur une ancre, jonction de deux flux d'événements, seuil bruité
qui produirait du confetti sans hystérésis, état non refermé en fin de session).
"""
import unittest
from pathlib import Path

from .segmentation import (autour, bascules, chevauche, conditionnelle, etats, fermer, jonction,
                           marges, marges_spatiales, masque_hysteresis, ouverts, present_dans)

from ..corpus import BASE_REELLE, raison_absence


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
        s = autour([10.0, 20.0], 0, 5, name='TAG',
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
        s = jonction([10.0, 90.0], [30.0], drop_last_open=True)
        self.assertEqual(len(s), 1)

    def test_curseurs_de_depart(self):
        s = jonction([10.0, 50.0, 90.0], [30.0, 70.0, 110.0], skip_starts=1)
        self.assertEqual(s[0]['start'], 50.0)

    def test_fins_anterieures_ignorees(self):
        # Une fin qui PRÉCÈDE le début ne peut pas le clore.
        s = jonction([50.0], [10.0, 80.0])
        self.assertEqual(s[0]['end'], 80.0)

    # ── Ajouts du 2026-08-23 : les deux manques relevés en §9ter.6 A ──────────────────────────

    def test_offsets_independants_sur_les_deux_bornes(self):
        # « du début du bloc moins 2 s jusqu'à la pause suivante plus 5 s » — inexprimable avant.
        s = jonction([10.0], [30.0], offset_start=-2.0, offset_end=5.0)
        self.assertEqual((s[0]['start'], s[0]['end']), (8.0, 35.0))

    def test_les_offsets_ne_changent_PAS_l_appariement(self):
        # Un décalage de bornes ne doit pas modifier quelle fin suit quel début : appliqué avant
        # l'appariement, un offset de -25 s ferait passer le début de 50 sous la fin de 30.
        sans = jonction([10.0, 50.0], [30.0, 70.0])
        avec = jonction([10.0, 50.0], [30.0, 70.0], offset_start=-25.0)
        self.assertEqual([x['end'] for x in sans], [x['end'] for x in avec])
        self.assertEqual([x['start'] for x in avec], [-15.0, 25.0])

    def test_un_segment_ouvert_ne_recoit_pas_l_offset_de_fin(self):
        # `None + 5.0` lèverait ; pire, une sentinelle numérique s'y ferait décaler en silence.
        s = jonction([10.0, 90.0], [30.0], offset_end=5.0)
        self.assertEqual(s[0]['end'], 35.0)
        self.assertIsNone(s[1]['end'])

    def test_repeter_faux_ne_produit_qu_UN_segment(self):
        # Mode par défaut de l'outil d'origine, où « Répéter sur les prochains segments » est une
        # case à cocher. Ici c'est l'inverse qui est le défaut — le cas courant n'a pas à se cocher.
        s = jonction([10.0, 50.0, 90.0], [30.0, 70.0, 110.0], repeat=False)
        self.assertEqual(len(s), 1)
        self.assertEqual((s[0]['start'], s[0]['end']), (10.0, 30.0))

    def test_repeter_faux_part_du_curseur(self):
        s = jonction([10.0, 50.0, 90.0], [30.0, 70.0, 110.0], skip_starts=1, repeat=False)
        self.assertEqual([(x['start'], x['end']) for x in s], [(50.0, 70.0)])

    def test_repeter_vrai_est_le_comportement_historique(self):
        self.assertEqual(len(jonction([10.0, 50.0, 90.0], [30.0, 70.0, 110.0])), 3)

    def test_la_fenetre_n_est_tracee_que_si_un_offset_est_pose(self):
        self.assertNotIn('window', jonction([10.0], [30.0])[0])
        self.assertEqual(jonction([10.0], [30.0], offset_end=5.0)[0]['window'], '0_5')


class HysteresisDeValeurTest(unittest.TestCase):
    """Le déclencheur de Schmitt — hystérésis de VALEUR, que le cœur n'avait pas.

    ⚠ Vient d'une MESURE : `cam_analyzer::find_intersection_windows` fusionne deux fenêtres de
    proximité « si la navette n'a jamais dépassé `exit_distance_factor × radius` », c'est-à-dire
    si elle n'est jamais vraiment sortie. Sans ce mécanisme, porter cam_analyzer sur le Segmenter
    serait une régression.
    """

    def test_un_seul_seuil_se_comporte_comme_un_seuil_simple(self):
        vals = [50.0, 30.0, 50.0]
        self.assertEqual(masque_hysteresis(vals, 40.0, 40.0), [False, True, False])

    def test_le_tremblement_sur_la_frontiere_ne_coupe_PAS(self):
        # Le cas cam_analyzer : rayon 40 m, sortie à 60 m. Le GPS oscille autour de 40 sans
        # jamais s'éloigner — un seuil unique découperait ce passage en trois.
        vals = [80.0, 38.0, 42.0, 39.0, 43.0, 37.0, 90.0]
        simple = masque_hysteresis(vals, 40.0, 40.0)
        double = masque_hysteresis(vals, 40.0, 60.0)
        self.assertEqual(simple, [False, True, False, True, False, True, False])
        self.assertEqual(double, [False, True, True, True, True, True, False])

    def test_une_sortie_FRANCHE_referme(self):
        self.assertEqual(masque_hysteresis([38.0, 70.0, 38.0], 40.0, 60.0),
                         [True, False, True])

    def test_sens_inverse_pour_une_grandeur_qui_MONTE(self):
        # Une vitesse : on entre à 30, on ne sort qu'en dessous de 20.
        vals = [10.0, 32.0, 25.0, 15.0]
        self.assertEqual(masque_hysteresis(vals, 30.0, 20.0, operator='>='),
                         [False, True, True, False])

    def test_une_valeur_ABSENTE_maintient_l_etat(self):
        # Un trou GPS n'est ni une entrée ni une sortie ; le traiter comme « dehors » couperait
        # un passage à chaque perte de fix.
        self.assertEqual(masque_hysteresis([38.0, None, float('nan'), 38.0], 40.0, 60.0),
                         [True, True, True, True])
        self.assertEqual(masque_hysteresis([90.0, None, 90.0], 40.0, 60.0),
                         [False, False, False])

    def test_hysteresis_incoherente_REFUSEE(self):
        # Sortir plus tôt qu'on entre n'est pas une hystérésis : c'est un piège silencieux.
        with self.assertRaises(ValueError) as ctx:
            masque_hysteresis([1.0], 40.0, 20.0)
        self.assertIn('seuil_sortie', str(ctx.exception))
        with self.assertRaises(ValueError):
            masque_hysteresis([1.0], 30.0, 40.0, operator='>=')

    def test_operateur_inconnu_refuse(self):
        with self.assertRaises(ValueError):
            masque_hysteresis([1.0], 1.0, 1.0, operator='!=')

    def test_il_se_compose_avec_conditionnelle(self):
        # Les deux hystérésis sont complémentaires : valeur d'abord, temps ensuite.
        times = [float(i) for i in range(7)]
        vals = [80.0, 38.0, 42.0, 39.0, 43.0, 37.0, 90.0]
        m = masque_hysteresis(vals, 40.0, 60.0)
        segs = conditionnelle(times, m, min_duration=2.0)
        self.assertEqual(len(segs), 1)
        self.assertEqual((segs[0]['start'], segs[0]['end']), (1.0, 5.0))


class BasculesTest(unittest.TestCase):
    """`masque → events` — le second port de sortie d'une condition (§9ter.6 B4)."""

    def setUp(self):
        self.times = [0.0, 1.0, 2.0, 3.0, 4.0, 5.0]
        self.masque = [False, False, True, True, False, False]

    def test_bascule_montante_datee_au_premier_echantillon_vrai(self):
        ev = bascules(self.times, self.masque)
        self.assertEqual([(e['time'], e['edge']) for e in ev], [(2.0, 'montante')])

    def test_descendantes_sur_demande(self):
        ev = bascules(self.times, self.masque, rising=False, falling=True)
        self.assertEqual([(e['time'], e['edge']) for e in ev], [(4.0, 'descendante')])

    def test_les_deux_sens_ensemble(self):
        ev = bascules(self.times, self.masque, falling=True)
        self.assertEqual([e['edge'] for e in ev], ['montante', 'descendante'])

    def test_un_masque_vrai_des_le_debut_ne_produit_PAS_de_montante(self):
        # On n'a pas observé la transition : la dater reviendrait à la placer à un instant choisi
        # par l'acquisition, pas par le phénomène.
        ev = bascules([0.0, 1.0, 2.0], [True, True, False], falling=True)
        self.assertEqual([e['edge'] for e in ev], ['descendante'])

    def test_un_masque_constant_ne_produit_rien(self):
        self.assertEqual(bascules([0.0, 1.0], [True, True], falling=True), [])

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
        s = conditionnelle(self.times, self.masque, gap_tolerance=0.25)
        self.assertEqual(len(s), 2)

    def test_duree_min_ecarte_le_parasite(self):
        s = conditionnelle(self.times, self.masque, gap_tolerance=0.25, min_duration=1.0)
        self.assertEqual(len(s), 1)
        self.assertAlmostEqual(s[0]['start'], 1.0, places=6)

    def test_parametres_traces(self):
        s = conditionnelle(self.times, self.masque, gap_tolerance=0.25, min_duration=1.0)[0]
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
        s = etats(t, v, ignore=[-1])
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


@unittest.skipUnless(BASE_REELLE.exists(), raison_absence())
class BaseReelleTest(unittest.TestCase):
    """Reproduire les fenêtres RÉELLES d'une campagne à partir de ses événements."""

    def test_les_fenetres_reelles_se_reproduisent(self):
        from .. import sources
        ref = sources.load(BASE_REELLE, streams=["event_finTag_finDep_pieton_voiture",
                                                 "situation_0_15", "situation_15_45"])
        ancres = [ref.get("finTag_finDep_pieton_voiture").time_at(i)
                  for i in range(len(ref.get("finTag_finDep_pieton_voiture")))]

        for name, o1, o2 in (("0_15", 0, 15), ("15_45", 15, 45)):
            attendu = ref.get(name)
            produit = autour(ancres, o1, o2)
            self.assertEqual(len(produit), len(ancres))
            # Chaque segment réel doit se retrouver parmi les segments produits.
            starts = {round(p['start'], 3) for p in produit}
            for i in range(len(attendu)):
                self.assertIn(round(attendu.time_at(i), 3), starts,
                              f"{name} : segment réel non reproduit")


class MargesTest(unittest.TestCase):
    """Le mode « Simple » appliqué à une SITUATION — deux bornes à décaler, pas une ancre."""

    def test_elargit_les_deux_bornes_independamment(self):
        s = marges([{'start': 100.0, 'end': 160.0}], before=5.0, after=10.0)
        self.assertEqual((s[0]['start'], s[0]['end']), (95.0, 170.0))

    def test_retrecir_est_une_marge_negative(self):
        s = marges([{'start': 100.0, 'end': 160.0}], before=-10.0, after=-10.0)
        self.assertEqual((s[0]['start'], s[0]['end']), (110.0, 150.0))

    def test_un_segment_qui_s_inverse_en_retrecissant_est_ecarte(self):
        # Même geste que duree_min : la contrainte déclarée vaut filtre. Le second segment
        # (60 s) survit, le premier (10 s) s'inverse et disparaît.
        s = marges([{'start': 100.0, 'end': 110.0}, {'start': 200.0, 'end': 260.0}],
                   before=-10.0, after=-10.0)
        self.assertEqual(len(s), 1)
        self.assertEqual(s[0]['start'], 210.0)

    def test_une_fin_OUVERTE_le_reste(self):
        s = marges([{'start': 100.0, 'end': None}], before=5.0, after=10.0)
        self.assertEqual(s[0]['start'], 95.0)
        self.assertIsNone(s[0]['end'])

    def test_l_origine_d_avant_la_marge_survit_dans_source(self):
        seg = autour([100.0], 0.0, 15.0)[0]
        s = marges([seg], before=5.0)[0]
        self.assertEqual(s['origin'], 'marges')
        self.assertEqual(s['source'], 'autour')

    def test_les_attributs_du_segment_sont_preserves(self):
        s = marges([{'start': 10.0, 'end': 20.0, 'name': 'S_01', 'level': 3}], after=1.0)[0]
        self.assertEqual((s['name'], s['level']), ('S_01', 3))


class MargesSpatialesTest(unittest.TestCase):
    """« 50 m avant l'entrée de zone » — la marge lue sur l'abscisse curviligne, pas sur l'horloge."""

    # Trace régulière : un échantillon par seconde, 10 m parcourus par échantillon.
    TIMES = [float(t) for t in range(11)]           # 0 … 10 s
    ABS = [10.0 * t for t in range(11)]             # 0 … 100 m

    def test_la_marge_rendue_vaut_AU_MOINS_la_marge_demandee(self):
        s = marges_spatiales([{'start': 5.0, 'end': 7.0}], self.TIMES, self.ABS,
                             before_m=25.0, after_m=15.0)[0]
        # 25 m avant l'abscisse 50 → cible 25 → dernier échantillon ≤ 25 = t=2 (20 m) : 30 m rendus.
        # 15 m après l'abscisse 70 → cible 85 → premier échantillon ≥ 85 = t=9 (90 m) : 20 m rendus.
        self.assertEqual((s['start'], s['end']), (2.0, 9.0))

    def test_les_bornes_rendues_sont_des_echantillons_EXISTANTS(self):
        s = marges_spatiales([{'start': 5.0, 'end': 7.0}], self.TIMES, self.ABS,
                             before_m=1.0, after_m=1.0)[0]
        self.assertIn(s['start'], self.TIMES)
        self.assertIn(s['end'], self.TIMES)

    def test_une_cible_au_dela_de_la_trace_est_bornee_a_la_donnee(self):
        # La marge s'arrête où la donnée s'arrête — pas d'instant inventé au-delà de la trace.
        s = marges_spatiales([{'start': 5.0, 'end': 7.0}], self.TIMES, self.ABS,
                             before_m=1000.0, after_m=1000.0)[0]
        self.assertEqual((s['start'], s['end']), (0.0, 10.0))

    def test_un_trou_gps_est_ignore_par_la_recherche(self):
        abscisses = list(self.ABS)
        abscisses[2] = None                          # t=2 sans fix
        s = marges_spatiales([{'start': 5.0, 'end': 7.0}], self.TIMES, abscisses,
                             before_m=25.0, after_m=15.0)[0]
        # Le dernier échantillon VALIDE ≤ 25 m n'est plus t=2 mais t=1 (10 m) : 40 m rendus.
        self.assertEqual((s['start'], s['end']), (1.0, 9.0))

    def test_une_fin_OUVERTE_le_reste(self):
        s = marges_spatiales([{'start': 5.0, 'end': None}], self.TIMES, self.ABS, before_m=25.0)[0]
        self.assertEqual(s['start'], 2.0)
        self.assertIsNone(s['end'])

    def test_une_trace_sans_position_valide_est_refusee(self):
        with self.assertRaises(ValueError):
            marges_spatiales([{'start': 0.0, 'end': 1.0}], [0.0, 1.0], [None, None], before_m=1.0)

    def test_l_origine_est_tracee_avec_la_fenetre_en_metres(self):
        s = marges_spatiales([{'start': 5.0, 'end': 7.0}], self.TIMES, self.ABS, after_m=10.0)[0]
        self.assertEqual(s['origin'], 'marges_spatiales')
        self.assertEqual(s['window'], '0_10_m')


if __name__ == "__main__":
    unittest.main(verbosity=2)
