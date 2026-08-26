"""Tests du référentiel temporel (`temporal.py`) — le cœur de WAMA Data.

POURQUOI CE FICHIER EXISTE (2026-08-21)
    Les marches A, B et C ont été validées par des scripts JETABLES, exécutés puis supprimés :
    ~800 lignes de code de cœur se sont retrouvées sans aucune protection contre la régression.
    C'est exactement le défaut qu'on corrige ici — un contrôle qui ne tourne pas au prochain
    changement n'est pas un contrôle, c'est un souvenir.

DEUX NIVEAUX, ET POURQUOI
  • **Données SYNTHÉTIQUES** pour la logique : déterministes, toujours disponibles, elles tournent
    dans toute installation. C'est le gros du fichier.
  • **Base réelle** pour ce que le synthétique ne peut pas prouver (volumes, cadences
    incommensurables, agrégation déléguée au SQL) — mais elle vit dans un dossier NON VERSIONNÉ.
    Ces contrôles se SAUTENT proprement quand elle est absente, au lieu d'échouer : un test rouge
    faute de données est un test qu'on finit par ignorer.
"""
import unittest
from pathlib import Path

from .temporal import (EXACT, NEAREST, PREVIOUS, Signal, SignalMeta, TemporalReferential)

#: Base d'expérimentation réelle, hors dépôt (dossier gitignoré). Absente = contrôles sautés.
from ..corpus import REAL_BASE, absence_reason


def signal(name, times, ends=None, rows=None, **kw):
    return Signal(SignalMeta(name=name, **kw), times, rows, ends=ends)


class ResolutionTest(unittest.TestCase):
    """`at()` rend TOUJOURS un échantillon existant — jamais une valeur interpolée."""

    def setUp(self):
        self.s = signal("s", [0.0, 1.0, 2.0, 3.0])

    def test_nearest_prend_le_plus_proche(self):
        self.assertEqual(self.s.index_at(1.4, NEAREST), 1)
        self.assertEqual(self.s.index_at(1.6, NEAREST), 2)

    def test_previous_ne_depasse_jamais_l_instant(self):
        # Sémantique d'ÉTAT : une valeur vaut jusqu'à ce qu'elle change.
        self.assertEqual(self.s.index_at(1.9, PREVIOUS), 1)
        self.assertEqual(self.s.index_at(2.0, PREVIOUS), 2)
        self.assertIsNone(self.s.index_at(-0.5, PREVIOUS))

    def test_exact_refuse_entre_deux_echantillons(self):
        self.assertEqual(self.s.index_at(2.0, EXACT), 2)
        self.assertIsNone(self.s.index_at(1.5, EXACT, tolerance=1e-9))

    def test_tolerance_borne_la_resolution(self):
        self.assertIsNone(self.s.index_at(99.0, NEAREST, tolerance=1.0))
        self.assertEqual(self.s.index_at(3.4, NEAREST, tolerance=1.0), 3)

    def test_flux_vide(self):
        self.assertIsNone(signal("vide", []).index_at(1.0))


class CadenceTest(unittest.TestCase):
    """La cadence est MESURÉE ; `fs` reste une déclaration facultative."""

    def test_cadence_mesuree(self):
        s = signal("s", [i * 0.01 for i in range(101)])
        self.assertAlmostEqual(s.measured_fs(), 100.0, places=6)

    def test_pas_variable_est_une_capacite_pas_un_defaut(self):
        regulier = signal("r", [i * 0.1 for i in range(50)])
        irregulier = signal("i", [0.0, 0.1, 0.35, 0.4, 0.9, 1.7, 1.75])
        self.assertTrue(regulier.is_regular())
        self.assertFalse(irregulier.is_regular())
        # …et un flux irrégulier reste parfaitement interrogeable :
        self.assertEqual(irregulier.index_at(0.36, NEAREST), 2)

    def test_fs_declaree_facultative(self):
        self.assertIsNone(signal("s", [0.0, 1.0]).meta.fs)
        self.assertEqual(signal("s", [0.0, 1.0], fs=50.0).meta.fs, 50.0)


class SegmentsTest(unittest.TestCase):
    """Un segment a DEUX bornes — sans quoi « qui contient t ? » est indécidable."""

    def setUp(self):
        # Fenêtres EMBOÎTÉES, comme les fenêtres d'analyse réelles.
        self.courte = signal("courte", [10.0, 100.0], ends=[25.0, 115.0])
        self.longue = signal("longue", [10.0, 100.0], ends=[70.0, 160.0])
        self.ref = TemporalReferential("t")
        self.ref.add(self.courte)
        self.ref.add(self.longue)

    def test_is_segments(self):
        self.assertTrue(self.courte.is_segments)
        self.assertFalse(signal("plat", [1.0, 2.0]).is_segments)

    def test_imbrication(self):
        self.assertEqual(self.ref.segments_at(15.0), {"courte": [0], "longue": [0]})
        # Sorti de la courte, toujours dans la longue :
        self.assertEqual(self.ref.segments_at(40.0), {"courte": [], "longue": [0]})

    def test_apres_la_fin_previous_mentirait(self):
        # LE piège : PREVIOUS rend le dernier segment COMMENCÉ, même s'il est terminé.
        self.assertEqual(self.courte.index_at(500.0, PREVIOUS), 1)
        self.assertEqual(self.courte.containing(500.0), [])

    def test_chevauchement(self):
        chev = signal("c", [0.0, 5.0], ends=[10.0, 15.0])
        self.assertEqual(chev.containing(7.0), [0, 1])      # les DEUX contiennent 7

    def test_overlapping_voit_le_segment_englobant(self):
        englobant = signal("e", [0.0], ends=[1000.0])
        # `range_indices` ne verrait rien : le segment ne COMMENCE pas dans la fenêtre.
        self.assertEqual(englobant.range_indices(400.0, 500.0), (1, 1))
        self.assertEqual(englobant.overlapping(400.0, 500.0), [0])

    def test_duree(self):
        self.assertEqual(self.courte.duration_at(0), 15.0)
        self.assertIsNone(signal("plat", [1.0]).duration_at(0))


class SegmentOuvertTest(unittest.TestCase):
    """**D15** — un segment dont la fin est INCONNUE (état commencé, pas encore refermé).

    ⚠ Bug trouvé le 2026-08-24 en répondant à la question « qu'est-ce qu'un segment ouvert ? ».
    `Signal` acceptait `ends=[…, None]` **structurellement** mais `containing()` et `overlapping()`
    comparaient `None >= float` : un seul état non refermé rendait le flux **ininterrogeable**.
    Et `frames.signal_depuis_frame()` en produit — le test d'aller-retour existant vérifiait que la
    valeur SURVIT, jamais qu'on puisse l'INTERROGER.

    La convention existait déjà dans `core/segmentation.py` (`within`, `overlapping` traitent
    une fin absente comme `+∞`) ; elle n'avait pas été portée ici.
    """

    def _signal(self):
        # Un segment refermé [0,5], un état ouvert commencé à 10 et jamais refermé.
        return Signal(SignalMeta(name='sit'), [0.0, 10.0], ends=[5.0, None])

    def test_containing_APRES_le_debut_de_l_etat_ouvert(self):
        # C'est le cas qui levait : `t` postérieur au début du segment ouvert.
        self.assertEqual(self._signal().containing(12.0), [1])

    def test_containing_avant_ne_le_retient_pas(self):
        self.assertEqual(self._signal().containing(2.0), [0])

    def test_overlapping_traverse_l_etat_ouvert(self):
        self.assertEqual(self._signal().overlapping(0.0, 20.0), [0, 1])

    def test_un_etat_ouvert_COURT_ENCORE(self):
        # Sémantique de `+∞` : il contient tout instant postérieur à son début, aussi loin soit-il.
        self.assertEqual(self._signal().containing(1e9), [1])

    def test_la_fin_reste_INCONNUE_elle_n_est_pas_remplacee(self):
        # `+∞` sert aux COMPARAISONS ; la donnée, elle, reste `None`. Refermer d'office donnerait
        # une durée mesurée là où rien n'a été mesuré.
        s = self._signal()
        self.assertIsNone(s.end_at(1))
        self.assertIsNone(s.duration_at(1))

    def test_un_NaN_est_traite_comme_une_fin_inconnue(self):
        # pandas convertit un `None` mêlé à des flottants en `NaN` — la 4ᵉ face du piège connu.
        s = Signal(SignalMeta(name='x'), [0.0], ends=[float('nan')])
        self.assertEqual(s.containing(99.0), [0])

    def test_un_signal_VENU_DU_PONT_est_interrogeable(self):
        """Le chemin réel qui produisait des signaux cassés."""
        import pandas as pd

        from wama.common.catalog.data_types import DataType, TypedFrame

        from ..frames import signal_from_frame
        f = TypedFrame(pd.DataFrame({'start': [0.0, 10.0],
                                     'end': pd.Series([5.0, None], dtype=object)}),
                       DataType.SEGMENTS)
        s = signal_from_frame(f, 'sit')
        self.assertEqual(s.overlapping(0.0, 20.0), [0, 1])
        self.assertEqual(s.containing(12.0), [1])


class EvenementsTest(unittest.TestCase):
    def setUp(self):
        self.ref = TemporalReferential("t")
        self.ref.add(signal("ev", [1.0, 5.0, 9.0]))

    def test_suivant_est_strict(self):
        self.assertEqual(self.ref.next_event("ev", 5.0), 2)      # pas lui-même
        self.assertEqual(self.ref.next_event("ev", 4.9), 1)

    def test_precedent_inclut_l_instant(self):
        self.assertEqual(self.ref.previous_event("ev", 5.0), 1)

    def test_bornes(self):
        self.assertIsNone(self.ref.next_event("ev", 9.0))
        self.assertIsNone(self.ref.previous_event("ev", 0.0))


class DecimationTest(unittest.TestCase):
    """La vue décimée doit conserver l'ENVELOPPE — c'est sa raison d'être."""

    def setUp(self):
        # Signal plat avec UNE pointe isolée : le cas qu'un « 1 point sur N » perdrait.
        self.times = [i * 0.1 for i in range(1000)]
        self.values = [0.0] * 1000
        self.values[437] = 99.0          # pointe au milieu d'une tranche
        self.values[438] = -42.0
        rows = lambda i0, i1: [{"v": self.values[i]} for i in range(i0, i1)]
        self.s = signal("s", self.times, rows=rows)

    def test_tranches_bornees_et_ordinal_porte(self):
        tr = self.s.decimate(0.0, 99.9, 50)
        self.assertLessEqual(len(tr), 50)
        self.assertEqual([t["bucket"] for t in tr], sorted(t["bucket"] for t in tr))
        self.assertTrue(all(t["count"] > 0 for t in tr))

    def test_l_enveloppe_capture_la_pointe(self):
        tr = self.s.decimate_values(0.0, 99.9, 50, "v")
        gmax = max(t["max"] for t in tr if t["max"] is not None)
        gmin = min(t["min"] for t in tr if t["min"] is not None)
        self.assertEqual(gmax, 99.0)
        self.assertEqual(gmin, -42.0)

    def test_min_max_attribues_a_LA_BONNE_tranche(self):
        # Régression : un recalcul de l'ordinal depuis `t_start` donnait `b-1` par arrondi
        # flottant, et les valeurs partaient dans la tranche voisine.
        tr = self.s.decimate_values(0.0, 99.9, 50, "v")
        porteuses = [t for t in tr if t["max"] == 99.0]
        self.assertEqual(len(porteuses), 1)
        t = porteuses[0]
        self.assertLessEqual(t["i_first"], 437)
        self.assertGreaterEqual(t["i_last"], 437)

    def test_intervalle_nul_et_buckets_invalides(self):
        self.assertEqual(self.s.decimate(5.0, 5.0, 10), [])
        self.assertEqual(self.s.decimate(0.0, 10.0, 0), [])

    def test_agregation_deleguee_a_la_source(self):
        appels = []

        def extents(t0, t1, buckets, column):
            appels.append((t0, t1, buckets, column))
            return {b: (float(b), float(b) + 1) for b in range(buckets)}

        s = Signal(SignalMeta(name="d"), self.times, extents=extents)
        tr = s.decimate_values(0.0, 99.9, 10, "v")
        self.assertEqual(len(appels), 1, "la source doit être interrogée UNE fois, pas par tranche")
        self.assertEqual(tr[0]["min"], 0.0)
        self.assertEqual(tr[1]["min"], 1.0)


class ReferentielTest(unittest.TestCase):
    def setUp(self):
        self.ref = TemporalReferential("session")
        self.ref.add(signal("rapide", [i * 0.01 for i in range(1001)]))    # 100 Hz, 0→10 s
        self.ref.add(signal("lent", [i * 1.0 for i in range(6)]))          # 1 Hz, 0→5 s

    def test_span_union_et_intersection(self):
        self.assertEqual(self.ref.span(), (0.0, 10.0))
        self.assertEqual(self.ref.common_span(), (0.0, 5.0))

    def test_snapshot_un_echantillon_par_flux(self):
        snap = self.ref.snapshot(2.5)
        self.assertEqual(snap["rapide"], 250)
        self.assertIn(snap["lent"], (2, 3))

    def test_l_ecart_suit_la_cadence(self):
        # La preuve qu'on n'interpole pas : l'écart au plus proche est borné par le demi-pas.
        for name, demi_pas in (("rapide", 0.005), ("lent", 0.5)):
            s = self.ref.get(name)
            i = self.ref.at(name, 2.4321)
            self.assertLessEqual(abs(s.time_at(i) - 2.4321), demi_pas * 1.001, name)

    def test_offset_media(self):
        ref = TemporalReferential("m")
        ref.add(signal("video", [0.0, 1.0, 2.0]), offset=-0.65)
        # Un instant de session est traduit dans le temps propre du média.
        self.assertEqual(ref.at("video", 0.35), 1)
        self.assertEqual(ref.span(), (-0.65, 1.35))

    def test_flux_inconnu_message_utile(self):
        with self.assertRaises(KeyError) as ctx:
            self.ref.get("absent")
        self.assertIn("rapide", str(ctx.exception))

    def test_doublon_refuse(self):
        with self.assertRaises(ValueError):
            self.ref.add(signal("rapide", [0.0]))


@unittest.skipUnless(REAL_BASE.exists(), absence_reason())
class BaseReelleTest(unittest.TestCase):
    """Ce que le synthétique ne peut pas prouver : volumes, cadences incommensurables, SQL."""

    @classmethod
    def setUpClass(cls):
        from .. import sources
        cls.ref = sources.load(REAL_BASE,
                               streams=["data_BIOPAC_MP150", "data_PUPIL_GLASSES_gaze",
                                        "situation_0_15", "situation_0_60"])

    def test_cadences_incommensurables_coexistent(self):
        rapide = self.ref.get("BIOPAC_MP150").measured_fs()
        lent = self.ref.get("PUPIL_GLASSES_gaze").measured_fs()
        self.assertGreater(rapide / lent, 5, "aucune grille commune : rien n'est rééchantillonné")

    def test_fenetres_reelles_imbriquees(self):
        courte = self.ref.get("0_15")
        t = courte.time_at(0) + 5.0
        dans = self.ref.segments_at(t)
        self.assertEqual(dans["0_15"], [0])
        self.assertEqual(dans["0_60"], [0])
        # 30 s après le début : sorti de la fenêtre de 15 s, toujours dans celle de 60 s.
        dans2 = self.ref.segments_at(courte.time_at(0) + 30.0)
        self.assertEqual(dans2["0_15"], [])
        self.assertEqual(dans2["0_60"], [0])

    def test_decimation_sur_volume_reel(self):
        s = self.ref.get("BIOPAC_MP150")
        self.assertGreater(len(s), 1_000_000)
        lo, hi = s.span
        tr = self.ref.decimate_values("BIOPAC_MP150", lo, hi, 200, "ecg")
        self.assertEqual(len(tr), 200)
        self.assertTrue(all(t["min"] is not None for t in tr))
        self.assertTrue(all(t["min"] <= t["max"] for t in tr))


if __name__ == "__main__":
    unittest.main(verbosity=2)
