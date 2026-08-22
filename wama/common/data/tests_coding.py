"""Tests du CODAGE — protocole déclaré + exécution (`WAMA_DATA_WORLD.md §9ter.4`).

Les cas reproduisent des gestes réels de codage : basculer un mode de conduite (exclusion mutuelle),
coder deux sujets en parallèle, laisser un état ouvert en fin de passation, se tromper de touche et
revenir en arrière. Le dernier groupe vérifie ce qui justifie tout le module — **un codage
automatique suit exactement le même chemin qu'un codage humain**.
"""
import unittest

from .coding import (ETAT, MOD_NOMBRE, MOD_PLUSIEURS_PARMI, MOD_UN_PARMI, PONCTUEL, CodageRefuse,
                     Comportement, Modificateur, Protocole, ProtocoleInvalide, SessionCodage,
                     accord, rejouer)


def _protocole() -> Protocole:
    return Protocole(
        nom='conduite',
        comportements=(
            Comportement('AUTO', 'Conduite automatisée', ETAT, exclusif='mode', touche='a'),
            Comportement('MANUEL', 'Conduite manuelle', ETAT, exclusif='mode', touche='m'),
            Comportement('REGARD_ROUTE', 'Regard route', ETAT, touche='r'),
            Comportement('FREINAGE', 'Freinage', PONCTUEL, touche='f', modificateurs=(
                Modificateur('gravite', type=MOD_UN_PARMI, valeurs=('faible', 'fort'), requis=True),
                Modificateur('vitesse', type=MOD_NOMBRE),
            )),
        ))


class ProtocoleTest(unittest.TestCase):

    def test_code_en_double_refuse_a_la_declaration(self):
        with self.assertRaises(ProtocoleInvalide):
            Protocole('p', (Comportement('X'), Comportement('X')))

    def test_ponctuel_exclusif_refuse(self):
        # Un ponctuel n'a pas de durée : il n'y a rien à fermer, donc l'exclusion est un non-sens.
        with self.assertRaises(ProtocoleInvalide):
            Protocole('p', (Comportement('X', nature=PONCTUEL, exclusif='g'),))

    def test_nature_inconnue_refusee(self):
        with self.assertRaises(ProtocoleInvalide):
            Protocole('p', (Comportement('X', nature='duratif'),))

    def test_aller_retour_de_serialisation(self):
        p = _protocole()
        r = Protocole.depuis_dict(p.en_dict())
        self.assertEqual(r.en_dict(), p.en_dict())
        self.assertEqual(r.get('FREINAGE').modificateurs[0].valeurs, ('faible', 'fort'))

    def test_comportement_inconnu_nomme_les_declares(self):
        with self.assertRaises(CodageRefuse) as ctx:
            _protocole().get('INEXISTANT')
        self.assertIn('AUTO', str(ctx.exception))


class SessionTest(unittest.TestCase):

    def setUp(self):
        self.s = SessionCodage(_protocole(), media='passation.mp4', codeur='humain')

    def test_session_sans_media_refusee(self):
        with self.assertRaises(CodageRefuse):
            SessionCodage(_protocole(), media='')

    def test_bascule_ouvre_puis_ferme(self):
        self.s.marquer(10.0, 'REGARD_ROUTE')
        self.assertEqual(len(self.s.ouverts()), 1)
        self.s.marquer(25.0, 'REGARD_ROUTE')
        segs = self.s.segments()
        self.assertEqual((segs[0]['start'], segs[0]['end']), (10.0, 25.0))
        self.assertEqual(self.s.ouverts(), [])

    def test_exclusion_mutuelle_ferme_le_concurrent(self):
        self.s.marquer(0.0, 'MANUEL')
        self.s.marquer(30.0, 'AUTO')          # ouvrir AUTO doit fermer MANUEL
        segs = self.s.segments()
        clos = [x for x in segs if x['end'] is not None]
        self.assertEqual((clos[0]['value'], clos[0]['end']), ('MANUEL', 30.0))
        self.assertEqual(clos[0]['closed_by'], 'exclusive',
                         "une fermeture SUBIE se distingue d'une fermeture voulue")
        self.assertEqual([x['value'] for x in self.s.ouverts()], ['AUTO'])

    def test_etat_non_exclusif_survit_a_la_bascule_de_mode(self):
        self.s.marquer(0.0, 'REGARD_ROUTE')
        self.s.marquer(5.0, 'MANUEL')
        self.s.marquer(10.0, 'AUTO')
        self.assertIn('REGARD_ROUTE', [x['value'] for x in self.s.ouverts()])

    def test_ponctuel_a_une_duree_nulle(self):
        e = self.s.marquer(12.5, 'FREINAGE', modificateurs={'gravite': 'fort'})
        self.assertEqual((e['start'], e['end']), (12.5, 12.5))
        self.assertEqual(self.s.segments(), [], "un ponctuel n'est pas un état")
        self.assertEqual(len(self.s.evenements()), 1)

    def test_modificateur_requis_manquant_refuse(self):
        with self.assertRaises(CodageRefuse):
            self.s.marquer(1.0, 'FREINAGE')

    def test_modificateur_hors_valeurs_refuse(self):
        with self.assertRaises(CodageRefuse):
            self.s.marquer(1.0, 'FREINAGE', modificateurs={'gravite': 'moyen'})

    def test_modificateur_non_declare_refuse(self):
        with self.assertRaises(CodageRefuse):
            self.s.marquer(1.0, 'FREINAGE', modificateurs={'gravite': 'fort', 'meteo': 'pluie'})

    def test_modificateur_numerique_converti(self):
        e = self.s.marquer(1.0, 'FREINAGE', modificateurs={'gravite': 'fort', 'vitesse': '42'})
        self.assertEqual(e['vitesse'], 42.0)

    def test_geste_en_arriere_refuse(self):
        self.s.marquer(10.0, 'REGARD_ROUTE')
        with self.assertRaises(CodageRefuse):
            self.s.marquer(5.0, 'MANUEL')

    def test_origine_et_codeur_traces(self):
        seg = self.s.marquer(1.0, 'AUTO')
        self.assertEqual(seg['origin'], 'codage')
        self.assertEqual(seg['coder'], 'humain')
        self.assertEqual(seg['protocol'], 'conduite')
        self.assertEqual(seg['media'], 'passation.mp4')


class OuvertureExpliciteTest(unittest.TestCase):
    """La bascule convient au doigt humain ; le codage automatique exige l'explicite."""

    def setUp(self):
        self.s = SessionCodage(_protocole(), media='m.mp4')

    def test_ouvrir_deux_fois_refuse(self):
        self.s.ouvrir(0.0, 'AUTO')
        with self.assertRaises(CodageRefuse):
            self.s.ouvrir(10.0, 'AUTO')

    def test_fermer_ce_qui_n_est_pas_ouvert_refuse(self):
        with self.assertRaises(CodageRefuse):
            self.s.fermer(10.0, 'AUTO')

    def test_ouvrir_un_ponctuel_refuse(self):
        with self.assertRaises(CodageRefuse):
            self.s.ouvrir(1.0, 'FREINAGE')


class EtatOuvertTest(unittest.TestCase):
    """Ce que ni le modèle WAMA ni l'outil MATLAB ne savaient représenter (D15)."""

    def setUp(self):
        self.s = SessionCodage(_protocole(), media='m.mp4')

    def test_etat_reste_ouvert_en_fin_de_session(self):
        self.s.marquer(100.0, 'AUTO')
        seg = self.s.segments()[0]
        self.assertIsNone(seg['end'])
        self.assertTrue(seg['open'])

    def test_fermeture_de_fin_de_session_est_TRACEE(self):
        self.s.marquer(100.0, 'AUTO')
        seg = self.s.segments(fin_de_session=180.0)[0]
        self.assertEqual(seg['end'], 180.0)
        self.assertEqual(seg['closed_at'], 180.0,
                         "une durée refermée d'office n'est pas une durée observée")


class SujetsTest(unittest.TestCase):

    def setUp(self):
        self.p = Protocole('obs', (Comportement('TRAVERSE', nature=ETAT),),
                           sujets=('pieton', 'cycliste'))
        self.s = SessionCodage(self.p, media='m.mp4')

    def test_deux_sujets_tiennent_le_meme_etat(self):
        self.s.marquer(0.0, 'TRAVERSE', sujet='pieton')
        self.s.marquer(1.0, 'TRAVERSE', sujet='cycliste')
        self.assertEqual(len(self.s.ouverts()), 2)

    def test_fermer_un_sujet_ne_ferme_pas_l_autre(self):
        self.s.marquer(0.0, 'TRAVERSE', sujet='pieton')
        self.s.marquer(1.0, 'TRAVERSE', sujet='cycliste')
        self.s.marquer(5.0, 'TRAVERSE', sujet='pieton')
        self.assertEqual([x['subject'] for x in self.s.ouverts()], ['cycliste'])

    def test_sujet_requis_quand_plusieurs_declares(self):
        with self.assertRaises(CodageRefuse):
            self.s.marquer(0.0, 'TRAVERSE')

    def test_sujet_unique_implicite(self):
        s = SessionCodage(Protocole('o', (Comportement('X'),), sujets=('seul',)), media='m.mp4')
        self.assertEqual(s.marquer(0.0, 'X')['subject'], 'seul')

    def test_sujet_inconnu_refuse(self):
        with self.assertRaises(CodageRefuse):
            self.s.marquer(0.0, 'TRAVERSE', sujet='voiture')


class RetourArriereTest(unittest.TestCase):
    """Le codage temps réel produit des erreurs de doigt."""

    def setUp(self):
        self.s = SessionCodage(_protocole(), media='m.mp4')

    def test_annuler_une_ouverture(self):
        self.s.marquer(10.0, 'AUTO')
        self.s.annuler_dernier()
        self.assertEqual(self.s.ouverts(), [])

    def test_annuler_une_fermeture_ROUVRE(self):
        self.s.marquer(10.0, 'AUTO')
        self.s.marquer(20.0, 'AUTO')
        self.assertEqual(self.s.ouverts(), [])
        self.s.annuler_dernier()
        self.assertEqual([x['value'] for x in self.s.ouverts()], ['AUTO'])

    def test_annuler_un_ponctuel(self):
        self.s.marquer(1.0, 'FREINAGE', modificateurs={'gravite': 'faible'})
        self.s.annuler_dernier()
        self.assertEqual(self.s.evenements(), [])

    def test_annuler_a_vide(self):
        self.assertIsNone(self.s.annuler_dernier())

    def test_annuler_puis_recoder_au_meme_instant(self):
        self.s.marquer(10.0, 'AUTO')
        self.s.annuler_dernier()
        self.s.marquer(10.0, 'MANUEL')          # le garde-fou de monotonie ne doit pas bloquer
        self.assertEqual([x['value'] for x in self.s.ouverts()], ['MANUEL'])


class CodageAUTOMATIQUETest(unittest.TestCase):
    """LA raison d'être du module : un modèle de vision n'est qu'un codeur de plus."""

    def test_le_chemin_est_le_MEME(self):
        p = _protocole()
        gestes = [{'t': 0.0, 'code': 'MANUEL'}, {'t': 30.0, 'code': 'AUTO'},
                  {'t': 45.0, 'code': 'FREINAGE', 'modificateurs': {'gravite': 'fort'}}]
        humain, ev_h = rejouer(p, 'm.mp4', gestes, codeur='fabien', fin_de_session=60.0)
        machine, ev_m = rejouer(p, 'm.mp4', gestes, codeur='qwen3-vl', fin_de_session=60.0)

        self.assertEqual([(x['value'], x['start'], x['end']) for x in humain],
                         [(x['value'], x['start'], x['end']) for x in machine],
                         "même protocole + mêmes gestes ⇒ même sortie, quel que soit le codeur")
        self.assertEqual(humain[0]['coder'], 'fabien')
        self.assertEqual(machine[0]['coder'], 'qwen3-vl')
        self.assertEqual(len(ev_h), 1)
        self.assertEqual(len(ev_m), 1)

    def test_le_protocole_contraint_AUSSI_la_machine(self):
        # Une proposition de modèle hors éthogramme est refusée exactement comme un doigt qui glisse.
        with self.assertRaises(CodageRefuse):
            rejouer(_protocole(), 'm.mp4', [{'t': 0.0, 'code': 'HALLUCINATION'}], codeur='llm')

    def test_accord_entre_deux_codages(self):
        p = _protocole()
        a, _ = rejouer(p, 'm.mp4', [{'t': 0.0, 'code': 'MANUEL'}, {'t': 30.0, 'code': 'AUTO'}],
                       codeur='humain', fin_de_session=60.0)
        b, _ = rejouer(p, 'm.mp4', [{'t': 0.5, 'code': 'MANUEL'}, {'t': 34.0, 'code': 'AUTO'}],
                       codeur='modele', fin_de_session=60.0)
        r = accord(a, b, tolerance=1.0)
        self.assertEqual((r['matched'], r['only_a'], r['only_b']), (1, 1, 1),
                         "MANUEL apparié à 0,5 s près ; AUTO décalé de 4 s reste non apparié")
        self.assertAlmostEqual(r['mean_offset'], 0.5)

    def test_accord_tolerance_plus_large(self):
        p = _protocole()
        a, _ = rejouer(p, 'm.mp4', [{'t': 0.0, 'code': 'MANUEL'}, {'t': 30.0, 'code': 'AUTO'}],
                       fin_de_session=60.0)
        b, _ = rejouer(p, 'm.mp4', [{'t': 0.5, 'code': 'MANUEL'}, {'t': 34.0, 'code': 'AUTO'}],
                       fin_de_session=60.0)
        self.assertEqual(accord(a, b, tolerance=5.0)['matched'], 2)


class AdaptateurDePortsTest(unittest.TestCase):
    """La couche qui traduit un cadre pandas en gestes — et le piege `NaN` qui s'y loge.

    ⚠ TROISIEME occurrence du meme piege dans cette couche, d'ou une regression versionnee : un
    cadre porte une colonne par modificateur de TOUT le protocole, remplie de `NaN` sur les lignes
    que ce modificateur ne concerne pas. `NaN` n'etant ni `None` ni faux, il traversait le filtre
    d'absence et faisait refuser CHAQUE geste comme portant un modificateur non declare.
    """

    def setUp(self):
        from .functions.temporal.coding import codage_rejouer
        from .data_types import DataType, TypedFrame
        import pandas as pd
        self.codage_rejouer, self.DataType, self.TypedFrame, self.pd = (
            codage_rejouer, DataType, TypedFrame, pd)
        self.proto = _protocole().en_dict()

    def _frame(self, rows):
        return self.TypedFrame(self.pd.DataFrame(rows), self.DataType.EVENTS,
                               meta={'media': 'm.mp4'})

    def test_colonne_de_modificateur_vide_sur_les_autres_lignes(self):
        # `gravite` ne concerne que FREINAGE ; pandas la remplit de NaN pour AUTO.
        out = self.codage_rejouer(
            self._frame([{'time': 0.0, 'value': 'AUTO'},
                         {'time': 5.0, 'value': 'FREINAGE', 'gravite': 'fort'}]),
            protocole=self.proto, fin_de_session=10.0)
        self.assertEqual(len(out.df), 1, "AUTO ne doit pas etre refuse a cause d'un NaN")

    def test_un_modificateur_REELLEMENT_hors_protocole_reste_refuse(self):
        # Le garde-fou qui arrete une hallucination de modele ne doit pas tomber avec le correctif.
        with self.assertRaises(CodageRefuse):
            self.codage_rejouer(
                self._frame([{'time': 0.0, 'value': 'AUTO', 'meteo': 'pluie'}]),
                protocole=self.proto)

    def test_la_fin_inconnue_survit_a_l_aller_retour_pandas(self):
        out = self.codage_rejouer(self._frame([{'time': 0.0, 'value': 'AUTO'}]),
                                  protocole=self.proto)
        self.assertIsNone(out.df.iloc[0]['end'],
                          "un etat ouvert doit rester None, jamais devenir NaN")

    def test_manquant_reconnait_les_deux_formes_d_absence(self):
        from .functions.temporal.segmentation import manquant
        self.assertTrue(manquant(None))
        self.assertTrue(manquant(float('nan')))
        self.assertFalse(manquant(0.0), "zero est une VALEUR, pas une absence")
        self.assertFalse(manquant(''))


class ModificateurMultipleTest(unittest.TestCase):

    def test_plusieurs_parmi(self):
        p = Protocole('p', (Comportement('X', nature=PONCTUEL, modificateurs=(
            Modificateur('causes', type=MOD_PLUSIEURS_PARMI, valeurs=('a', 'b', 'c')),)),))
        s = SessionCodage(p, media='m.mp4')
        self.assertEqual(s.marquer(0.0, 'X', modificateurs={'causes': ['a', 'c']})['causes'],
                         ['a', 'c'])
        with self.assertRaises(CodageRefuse):
            s.marquer(1.0, 'X', modificateurs={'causes': ['a', 'z']})


if __name__ == "__main__":
    unittest.main(verbosity=2)
