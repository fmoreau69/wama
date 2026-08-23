"""Tests du PONT référentiel ↔ cadres typés (`wama_data/frames.py`).

Chacun des quatre pièges documentés en tête de `frames.py` a son test — sans quoi « ce module les
traite » ne serait qu'une affirmation de docstring. Les trois premiers portent sur des faits
MESURÉS dans le code des lecteurs, pas sur des hypothèses.

Le test qui compte le plus est `PontCompletTest` : il vérifie qu'un flux chargé peut désormais
traverser une fonction du catalogue et revenir au référentiel — c'est-à-dire exactement ce que le
blocage déclaré du Référentiel (« AUCUN consommateur ») rendait impossible.
"""
import unittest

import pandas as pd

from wama.common.catalog.data_types import DataType, TypedFrame

from .core.temporal import NEAREST, PREVIOUS, Signal, SignalMeta, TemporalReferential
from .frames import (adjoindre, frame_depuis_referentiel, frame_depuis_signal,
                     signal_depuis_frame, type_par_defaut)


def _signal(nom='vitesse', times=(0.0, 1.0, 2.0, 3.0), lignes=None, ends=None, **kw):
    """Un flux à la forme RÉELLE des lecteurs : `rows` rend une liste de dicts."""
    lignes = lignes if lignes is not None else [
        {'timecode': t, 'value': 10.0 * i} for i, t in enumerate(times)]
    meta = SignalMeta(name=nom, **kw)
    return Signal(meta, list(times), rows=lambda i0, i1: lignes[i0:i1], ends=ends)


class TypeParDefautTest(unittest.TestCase):
    """Le type se déduit de la STRUCTURE, jamais d'un libellé."""

    def test_sans_fins_timeseries(self):
        self.assertEqual(type_par_defaut(_signal()), DataType.TIMESERIES)

    def test_avec_fins_segments(self):
        s = _signal(times=(0.0, 10.0), ends=[5.0, 15.0],
                    lignes=[{'startTimecode': 0.0}, {'startTimecode': 10.0}])
        self.assertEqual(type_par_defaut(s), DataType.SEGMENTS)

    def test_le_libelle_comments_n_est_PAS_consulte(self):
        # Déduire la famille de « data · 3 colonne(s) » serait prendre une TRACE pour une RÈGLE.
        s = _signal(comments='event · 3 colonne(s)')
        self.assertEqual(type_par_defaut(s), DataType.TIMESERIES)


class Piege1_TempsDeSessionTest(unittest.TestCase):
    """① Le référentiel travaille en temps de SESSION, le signal en temps LOCAL."""

    def setUp(self):
        self.ref = TemporalReferential('essai')
        self.ref.add(_signal('capteur', (0.0, 1.0, 2.0)))
        self.ref.add(_signal('video', (0.0, 1.0, 2.0)), offset=100.0)

    def test_l_offset_est_applique(self):
        f = frame_depuis_referentiel(self.ref, 'video')
        self.assertEqual(list(f.df['time']), [100.0, 101.0, 102.0])

    def test_deux_flux_d_offsets_differents_sont_alignes(self):
        a = frame_depuis_referentiel(self.ref, 'capteur')
        b = frame_depuis_referentiel(self.ref, 'video')
        self.assertEqual(list(a.df['time']), [0.0, 1.0, 2.0])
        self.assertEqual(list(b.df['time']), [100.0, 101.0, 102.0])

    def test_la_fenetre_est_lue_en_temps_de_SESSION(self):
        # Sans conversion, [100, 101] ne sélectionnerait rien dans un flux local [0, 2].
        f = frame_depuis_referentiel(self.ref, 'video', t0=100.0, t1=101.0)
        self.assertEqual(list(f.df['time']), [100.0, 101.0])

    def test_le_signal_seul_ignore_l_offset_et_c_est_ASSUME(self):
        # `frame_depuis_signal` sur un flux du référentiel perdrait son décalage : c'est pourquoi
        # `frame_depuis_referentiel` est la porte d'entrée normale.
        f = frame_depuis_signal(self.ref.get('video'))
        self.assertEqual(list(f.df['time']), [0.0, 1.0, 2.0])

    def test_le_nom_du_referentiel_est_trace(self):
        self.assertEqual(frame_depuis_referentiel(self.ref, 'capteur').meta['referentiel'], 'essai')


class Piege2_ColonneTemporellePerimeeTest(unittest.TestCase):
    """② Les lignes portent l'axe brut, qui peut être PÉRIMÉ après ré-horodatage."""

    def test_le_temps_vient_des_times_PAS_de_la_ligne(self):
        # Cas réel : `ResamplingTS` a recalculé les instants ; la colonne `timecode` de la base,
        # rendue telle quelle par le `SELECT *`, porte encore les ANCIENNES valeurs.
        lignes = [{'timecode': 999.0, 'value': 1.0}, {'timecode': 998.0, 'value': 2.0}]
        s = _signal(times=(0.0, 0.5), lignes=lignes)
        f = frame_depuis_signal(s)
        self.assertEqual(list(f.df['time']), [0.0, 0.5])

    def test_la_colonne_d_axe_brute_est_RETIREE(self):
        # La laisser mettrait deux colonnes de temps contradictoires dans le même tableau.
        f = frame_depuis_signal(_signal())
        self.assertNotIn('timecode', f.df.columns)
        self.assertIn('time', f.df.columns)

    def test_les_bornes_brutes_de_segment_sont_retirees_aussi(self):
        lignes = [{'startTimecode': 0.0, 'endTimecode': 5.0, 'label': 'a'}]
        s = _signal(times=(0.0,), lignes=lignes, ends=[5.0])
        f = frame_depuis_signal(s)
        self.assertEqual(sorted(f.df.columns), ['end', 'label', 'start'])

    def test_les_colonnes_de_DONNEES_sont_conservees(self):
        f = frame_depuis_signal(_signal())
        self.assertEqual(list(f.df['value']), [0.0, 10.0, 20.0, 30.0])


class Piege3_ContratDesLignesTest(unittest.TestCase):
    """③ Le contrat `rows -> List[Dict]` est réel mais typé `Any` : on le VÉRIFIE."""

    def test_un_accesseur_rendant_des_tuples_echoue_CLAIREMENT(self):
        s = Signal(SignalMeta(name='x'), [0.0, 1.0], rows=lambda i0, i1: [(0.0, 1.0)][i0:i1])
        with self.assertRaises(TypeError) as ctx:
            frame_depuis_signal(s)
        self.assertIn('liste de dicts', str(ctx.exception))

    def test_un_flux_SANS_accesseur_reste_lisible(self):
        # Un flux d'événements peut n'exposer que ses instants (`rows` optionnel au contrat).
        s = Signal(SignalMeta(name='marqueurs'), [1.0, 2.0])
        f = frame_depuis_signal(s)
        self.assertEqual(list(f.df['time']), [1.0, 2.0])


class Piege4_ProvenanceTest(unittest.TestCase):
    """④ Un cadre qui revient d'un calcul n'est JAMAIS une donnée acquise."""

    def _frame(self):
        return TypedFrame(pd.DataFrame({'time': [0.0, 1.0], 'v': [1.0, 2.0]}),
                          DataType.TIMESERIES)

    def test_is_base_est_faux_et_non_negociable(self):
        s = signal_depuis_frame(self._frame(), 'v_derivee')
        self.assertFalse(s.meta.is_base)

    def test_aucun_parametre_ne_permet_de_forcer_is_base(self):
        with self.assertRaises(TypeError):
            signal_depuis_frame(self._frame(), 'x', is_base=True)

    def test_la_provenance_du_flux_source_est_tracee_a_l_aller(self):
        f = frame_depuis_signal(_signal(is_base=True))
        self.assertEqual(f.meta['source_signal'], 'vitesse')
        self.assertTrue(f.meta['is_base'])


class RetourVersSignalTest(unittest.TestCase):

    def test_aller_retour_conserve_les_instants(self):
        f = frame_depuis_signal(_signal())
        s = signal_depuis_frame(f, 'retour')
        self.assertEqual(list(s._times), [0.0, 1.0, 2.0, 3.0])
        self.assertEqual(len(s), 4)

    def test_les_segments_reviennent_avec_leurs_fins(self):
        f = TypedFrame(pd.DataFrame({'start': [0.0, 10.0], 'end': [5.0, 15.0]}),
                       DataType.SEGMENTS)
        s = signal_depuis_frame(f, 'sit')
        self.assertTrue(s.is_segments)
        self.assertEqual(s.containing(3.0), [0])

    def test_une_fin_INCONNUE_survit_a_l_aller_retour(self):
        f = TypedFrame(pd.DataFrame({'start': [0.0], 'end': pd.Series([None], dtype=object)}),
                       DataType.SEGMENTS)
        s = signal_depuis_frame(f, 'ouvert')
        self.assertIsNone(s.end_at(0))

    def test_le_lookup_suit_la_NATURE_pas_le_flux_d_origine(self):
        seg = TypedFrame(pd.DataFrame({'start': [0.0], 'end': [1.0]}), DataType.SEGMENTS)
        sig = TypedFrame(pd.DataFrame({'time': [0.0]}), DataType.TIMESERIES)
        self.assertEqual(signal_depuis_frame(seg, 'a').meta.default_lookup, PREVIOUS)
        self.assertEqual(signal_depuis_frame(sig, 'b').meta.default_lookup, NEAREST)

    def test_instants_non_croissants_REFUSES(self):
        # L'indexation par dichotomie donnerait des réponses fausses SANS erreur.
        f = TypedFrame(pd.DataFrame({'time': [5.0, 1.0]}), DataType.TIMESERIES)
        with self.assertRaises(ValueError) as ctx:
            signal_depuis_frame(f, 'x')
        self.assertIn('croissants', str(ctx.exception))

    def test_instant_manquant_REFUSE(self):
        f = TypedFrame(pd.DataFrame({'time': [0.0, None]}), DataType.TIMESERIES)
        with self.assertRaises(ValueError):
            signal_depuis_frame(f, 'x')

    def test_cadre_sans_champ_temporel_refuse_en_nommant_les_presents(self):
        f = TypedFrame(pd.DataFrame({'v': [1.0]}), DataType.TIMESERIES)
        with self.assertRaises(ValueError) as ctx:
            signal_depuis_frame(f, 'x')
        self.assertIn('v', str(ctx.exception))


class AdjoindreTest(unittest.TestCase):

    def test_le_flux_calcule_entre_au_referentiel(self):
        ref = TemporalReferential()
        ref.add(_signal('brut'))
        f = frame_depuis_referentiel(ref, 'brut')
        adjoindre(ref, 'brut_derive', f)
        self.assertIn('brut_derive', ref.names)
        self.assertFalse(ref.get('brut_derive').meta.is_base)

    def test_ecraser_un_flux_existant_est_REFUSE(self):
        # Écraser en place rendrait irrécupérable ce qui l'a produit.
        ref = TemporalReferential()
        ref.add(_signal('brut'))
        f = frame_depuis_referentiel(ref, 'brut')
        with self.assertRaises(ValueError):
            adjoindre(ref, 'brut', f)


class FenetreTest(unittest.TestCase):

    def test_la_fenetre_restreint_les_lignes(self):
        f = frame_depuis_signal(_signal(), t0=1.0, t1=2.0)
        self.assertEqual(list(f.df['time']), [1.0, 2.0])
        self.assertEqual(f.meta['fenetre'], (1.0, 2.0))

    def test_sans_fenetre_on_prend_tout(self):
        self.assertEqual(len(frame_depuis_signal(_signal()).df), 4)

    def test_restriction_de_champs(self):
        lignes = [{'timecode': 0.0, 'a': 1, 'b': 2}]
        f = frame_depuis_signal(_signal(times=(0.0,), lignes=lignes), champs=['a'])
        self.assertEqual(sorted(f.df.columns), ['a', 'time'])

    def test_le_champ_canonique_survit_a_la_restriction(self):
        # C'est lui qui rend le cadre chaînable : le retirer casserait tout port typé.
        lignes = [{'timecode': 0.0, 'a': 1}]
        f = frame_depuis_signal(_signal(times=(0.0,), lignes=lignes), champs=[])
        self.assertIn('time', f.df.columns)

    def test_flux_vide_rend_un_cadre_bien_forme(self):
        s = Signal(SignalMeta(name='vide'), [])
        f = frame_depuis_signal(s)
        self.assertEqual(len(f.df), 0)
        self.assertIn('time', f.df.columns)


class PontCompletTest(unittest.TestCase):
    """LE test du chantier : un flux chargé traverse une fonction du catalogue et revient.

    C'est exactement ce que le blocage déclaré du Référentiel — « AUCUN consommateur » — rendait
    impossible avant ce module.
    """

    def test_referentiel_vers_fonction_vers_referentiel(self):
        from .functions.temporal.calculation import calcul_glissant

        ref = TemporalReferential('session')
        lignes = [{'timecode': i * 0.5, 'value': float(i % 3)} for i in range(12)]
        ref.add(_signal('capteur', tuple(i * 0.5 for i in range(12)), lignes=lignes))

        cadre = frame_depuis_referentiel(ref, 'capteur')
        lisse = calcul_glissant(cadre, fenetre_s=1.0, colonne='value')
        self.assertIn('value_moyenne', lisse.df.columns)

        adjoindre(ref, 'capteur_lisse', lisse)
        self.assertIn('capteur_lisse', ref.names)
        # Le flux dérivé est interrogeable comme n'importe quel autre — c'est le but.
        self.assertIsNotNone(ref.at('capteur_lisse', 2.0))
        self.assertFalse(ref.get('capteur_lisse').meta.is_base)

    def test_referentiel_vers_SEGMENTATION_vers_referentiel(self):
        from .functions.temporal.conditions import chaine_vers_segments

        ref = TemporalReferential('session')
        lignes = [{'timecode': float(i), 'value': 40.0 if 2 <= i <= 5 else 5.0}
                  for i in range(10)]
        ref.add(_signal('vitesse', tuple(float(i) for i in range(10)), lignes=lignes))

        cadre = frame_depuis_referentiel(ref, 'vitesse')
        segs = chaine_vers_segments(
            cadre, conditions=[{'cle': 'C1', 'champ': 'value',
                                'operateur': '>=', 'valeur': 30.0}])
        self.assertEqual(len(segs.df), 1)

        adjoindre(ref, 'survitesse', segs)
        # Un segment adjoint répond bien à « quelle situation contient cet instant ? »
        self.assertEqual(ref.containing('survitesse', 3.0), [0])

    def test_l_offset_survit_a_l_aller_retour(self):
        from .functions.temporal.calculation import calcul_derivee

        ref = TemporalReferential()
        lignes = [{'timecode': float(i), 'value': float(i)} for i in range(5)]
        ref.add(_signal('decale', tuple(float(i) for i in range(5)), lignes=lignes),
                offset=1000.0)

        cadre = frame_depuis_referentiel(ref, 'decale')
        self.assertEqual(cadre.df['time'].iloc[0], 1000.0)
        derive = calcul_derivee(cadre, colonne='value')
        # Le flux dérivé est DÉJÀ en temps de session : on l'ajoute donc SANS offset, sinon on
        # décalerait deux fois.
        adjoindre(ref, 'decale_derivee', derive)
        self.assertEqual(ref.get('decale_derivee').span[0], 1000.0)
        self.assertEqual(ref.span()[0], 1000.0)


if __name__ == '__main__':
    unittest.main()
