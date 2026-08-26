"""Tests de la chaîne conditionnelle — `WAMA_DATA_WORLD.md §9ter.6 B`.

Les cas ne sont pas inventés : chaque classe reprend une situation LUE dans le code de l'outil
d'origine (`BIND_GUI.mlapp`, extrait le 2026-08-23) et vérifie que le portage la traite mieux,
ou au moins pas moins bien. Les trois défauts cités en tête de `conditions.py` ont chacun leur
test — sans quoi « on a corrigé » ne serait qu'une affirmation de message de commit.
"""
import unittest

from .conditions import (BOOLEEN, CONNECTEURS, NUMERIQUE, OPERATEURS, TEXTE, Condition,
                         analyser, condition_depuis_dict, evaluer, nom_chaine,
                         nom_jonction, operateurs_pour,
                         rendre, valider)


class OperateursTest(unittest.TestCase):
    """Le registre, et ce qu'il refuse."""

    def test_les_16_operateurs_d_origine_sont_couverts_par_14(self):
        # L'outil d'origine en déclare 16 (relevé ligne 5030 de son source) : 6 d'ordre, 8 de
        # texte, 2 de présence. Les deux égalités dédoublées (numérique / texte) fusionnent.
        self.assertEqual(len(OPERATEURS), 14)
        for attendu in ('<', '<=', '>', '>=', '==', '!=', 'contains', 'not_contains',
                        'startswith', 'not_startswith', 'endswith', 'not_endswith',
                        'empty', 'not_empty'):
            self.assertIn(attendu, OPERATEURS)

    def test_une_colonne_texte_ne_propose_PAS_les_comparaisons_d_ordre(self):
        # ③ en tête de `conditions.py` : c'est le filtrage que l'outil d'origine n'a pas.
        proposes = operateurs_pour(TEXTE)
        for interdit in ('<', '<=', '>', '>='):
            self.assertNotIn(interdit, proposes)
        self.assertIn('contains', proposes)

    def test_une_colonne_numerique_ne_propose_PAS_les_operateurs_de_texte(self):
        proposes = operateurs_pour(NUMERIQUE)
        self.assertNotIn('contains', proposes)
        self.assertIn('>=', proposes)

    def test_l_egalite_et_la_presence_valent_pour_toutes_les_sortes(self):
        for sorte in (NUMERIQUE, TEXTE, BOOLEEN):
            for partout in ('==', '!=', 'empty', 'not_empty'):
                self.assertIn(partout, operateurs_pour(sorte))

    def test_sorte_inconnue_refusee(self):
        with self.assertRaises(ValueError):
            operateurs_pour('date')


class ConditionTest(unittest.TestCase):
    """La déclaration atomique — ce qu'elle accepte et ce qu'elle refuse AVANT d'exécuter."""

    def test_condition_texte_contient(self):
        c = Condition(cle='C1', flux='commentaires_simu', champ='texte',
                      operator='contains', valeur='FIN', sorte=TEXTE)
        self.assertEqual(c.evaluer(['DEBUT', 'la FIN', '', None]), [False, True, False, False])

    def test_condition_numerique_seuil(self):
        c = Condition(cle='C1', champ='vitesse', operator='>=', valeur=30.0)
        self.assertEqual(c.evaluer([10.0, 30.0, 50.0]), [False, True, True])

    def test_operateur_d_ordre_sur_colonne_texte_REFUSE(self):
        # LE défaut central : l'outil d'origine l'accepte et MATLAB compare alors les codes des
        # caractères, produisant un masque plausible et faux.
        with self.assertRaises(ValueError) as ctx:
            Condition(cle='C1', champ='comment', operator='<', valeur='M', sorte=TEXTE)
        # Le message doit ORIENTER, pas seulement refuser.
        self.assertIn('contains', str(ctx.exception))

    def test_une_valeur_absente_ne_satisfait_jamais_une_comparaison(self):
        c = Condition(cle='C1', champ='vitesse', operator='<', valeur=10.0)
        self.assertEqual(c.evaluer([None, float('nan'), 5.0]), [False, False, True])

    def test_une_valeur_absente_ne_CONTIENT_rien(self):
        # `str(None)` vaudrait 'None' et contiendrait « on » : une absence se mettrait à
        # satisfaire des conditions.
        c = Condition(cle='C1', champ='txt', operator='contains', valeur='on', sorte=TEXTE)
        self.assertEqual(c.evaluer([None, 'bonjour']), [False, True])

    def test_operateur_sans_operande_refuse_une_valeur(self):
        with self.assertRaises(ValueError):
            Condition(cle='C1', champ='txt', operator='empty', valeur='x', sorte=TEXTE)

    def test_operateur_avec_operande_exige_une_valeur(self):
        with self.assertRaises(ValueError):
            Condition(cle='C1', champ='vitesse', operator='>=')

    def test_vide_et_non_vide_sont_complementaires(self):
        vals = [None, '', 'x', 0, float('nan')]
        v = Condition(cle='C1', champ='c', operator='empty', sorte=TEXTE).evaluer(vals)
        nv = Condition(cle='C2', champ='c', operator='not_empty', sorte=TEXTE).evaluer(vals)
        self.assertEqual(v, [not b for b in nv])

    def test_operateur_inconnu_refuse_en_nommant_les_disponibles(self):
        with self.assertRaises(ValueError) as ctx:
            Condition(cle='C1', champ='v', operator='≥', valeur=1)
        self.assertIn('>=', str(ctx.exception))

    def test_rendu_lisible(self):
        c = Condition(cle='C1', flux='commentaires_simu', champ='texte',
                      operator='contains', valeur='FIN', sorte=TEXTE)
        self.assertEqual(c.rendre(), 'commentaires_simu.texte contient « FIN »')


class SerialisationTest(unittest.TestCase):
    """§9ter.6 B1 affirmait « sérialisable, donc entrant dans un manifeste » — c'était faux.

    Défaut trouvé par l'audit A (§9sexies) : la propriété était promise par la docstring et
    n'existait nulle part dans le code.
    """

    def _c(self):
        return Condition(cle='C1', flux='commentaires_simu', champ='texte',
                         operator='contains', valeur='FIN', sorte=TEXTE)

    def test_aller_retour_fidele(self):
        c = self._c()
        self.assertEqual(condition_depuis_dict(c.to_dict(), sorte=TEXTE), c)

    def test_forme_JSON_pure(self):
        import json
        c = self._c()
        self.assertEqual(condition_depuis_dict(json.loads(json.dumps(c.to_dict())), sorte=TEXTE), c)

    def test_la_SORTE_n_est_PAS_serialisee(self):
        # ⚠ Délibéré : la sorte est LUE dans la donnée par l'adaptateur, jamais déclarée. La
        # sérialiser inviterait à la relire, donc à laisser une déclaration contredire la colonne
        # qu'elle décrit — le défaut même que le filtrage par sorte corrige.
        self.assertNotIn('sorte', self._c().to_dict())

    def test_une_condition_relue_est_VALIDEE(self):
        # `<` sur une colonne texte doit être refusé à la relecture comme à la construction.
        brut = {'key': 'C1', 'stream': 't', 'field': 'c', 'operator': '<', 'value': 'M'}
        with self.assertRaises(ValueError):
            condition_depuis_dict(brut, sorte=TEXTE)

    def test_l_arbre_est_DEJA_du_JSON_pur(self):
        # Rien à sérialiser : c'est un dict de dicts et de chaînes, par construction.
        import json
        arbre = {'op': 'ET', 'args': ['C1', {'op': 'NON', 'args': ['C2']}]}
        self.assertEqual(json.loads(json.dumps(arbre)), arbre)
        self.assertEqual(rendre(json.loads(json.dumps(arbre))), rendre(arbre))


class ArbreTest(unittest.TestCase):
    """L'assemblage — ① en tête : ce que `eval()` ne pouvait refuser qu'à l'exécution."""

    CLES = ['C1', 'C2', 'C3']

    def test_cle_inexistante_refusee_A_LA_DECLARATION(self):
        with self.assertRaises(ValueError) as ctx:
            valider({'op': 'ET', 'args': ['C1', 'C4']}, self.CLES)
        # Nommer le fautif ET l'emplacement — l'alerte d'origine ne disait ni l'un ni l'autre.
        self.assertIn('C4', str(ctx.exception))
        self.assertIn('ET[2]', str(ctx.exception))

    def test_arite_fausse_refusee(self):
        with self.assertRaises(ValueError) as ctx:
            valider({'op': 'NON', 'args': ['C1', 'C2']}, self.CLES)
        self.assertIn('1 argument', str(ctx.exception))

    def test_connecteur_inconnu_refuse(self):
        with self.assertRaises(ValueError):
            valider({'op': 'NAND', 'args': ['C1', 'C2']}, self.CLES)

    def test_et_ou_sont_n_aires(self):
        valider({'op': 'ET', 'args': ['C1', 'C2', 'C3']}, self.CLES)
        self.assertIsNone(CONNECTEURS['ET'].arite)

    def test_xor_reste_binaire_et_le_refuse_a_trois(self):
        # Décision assumée : à trois arguments « ou exclusif » a deux lectures incompatibles.
        with self.assertRaises(ValueError):
            valider({'op': 'XOR', 'args': ['C1', 'C2', 'C3']}, self.CLES)

    def test_noeud_malforme_refuse(self):
        with self.assertRaises(ValueError):
            valider({'operator': 'ET'}, self.CLES)
        with self.assertRaises(ValueError):
            valider({'op': 'ET', 'args': []}, self.CLES)

    def test_evaluation_combinee(self):
        m = {'C1': [True, True, False, False],
             'C2': [True, False, True, False]}
        self.assertEqual(evaluer({'op': 'ET', 'args': ['C1', 'C2']}, m),
                         [True, False, False, False])
        self.assertEqual(evaluer({'op': 'OU', 'args': ['C1', 'C2']}, m),
                         [True, True, True, False])
        self.assertEqual(evaluer({'op': 'XOR', 'args': ['C1', 'C2']}, m),
                         [False, True, True, False])
        self.assertEqual(evaluer({'op': 'NON', 'args': ['C1']}, m),
                         [False, False, True, True])

    def test_imbrication(self):
        m = {'C1': [True, False], 'C2': [False, False], 'C3': [True, True]}
        arbre = {'op': 'ET', 'args': ['C1', {'op': 'OU', 'args': ['C2', 'C3']}]}
        self.assertEqual(evaluer(arbre, m), [True, False])

    def test_masques_de_longueurs_differentes_refuses(self):
        with self.assertRaises(ValueError) as ctx:
            evaluer({'op': 'ET', 'args': ['C1', 'C2']},
                    {'C1': [True, True], 'C2': [True]})
        self.assertIn('longueurs', str(ctx.exception))

    def test_rendu_canonique(self):
        arbre = {'op': 'ET', 'args': ['C1', {'op': 'NON', 'args': ['C2']}]}
        self.assertEqual(rendre(arbre), 'ET(C1, NON(C2))')


class SaisieTest(unittest.TestCase):
    """② en tête : le texte est une SAISIE et un AFFICHAGE, jamais le modèle."""

    CLES = ['C1', 'C2', 'C3', 'C4', 'C5', 'C6']

    def test_forme_de_l_outil_d_origine_acceptee(self):
        # `fusion_connecteur` émet exactement cette graphie : préfixe, espaces libres, virgules.
        self.assertEqual(analyser('ET (C1 , C2)', self.CLES),
                         {'op': 'ET', 'args': ['C1', 'C2']})

    def test_imbrication_profonde(self):
        arbre = analyser('NON(OU(C1, XOR(C5, C6)))', self.CLES)
        self.assertEqual(rendre(arbre), 'NON(OU(C1, XOR(C5, C6)))')

    def test_deux_saisies_differemment_espacees_donnent_LE_MEME_arbre(self):
        # C'est le point : le modèle est l'arbre, donc deux saisies équivalentes se comparent.
        a = analyser('ET(C1,C2)', self.CLES)
        b = analyser('  ET  ( C1 , C2 )  ', self.CLES)
        self.assertEqual(a, b)

    def test_separateur_espace_accepte_comme_la_virgule(self):
        self.assertEqual(analyser('ET(C1 C2)', self.CLES), analyser('ET(C1, C2)', self.CLES))

    def test_l_exemple_affiche_par_l_outil_d_origine_est_REFUSE(self):
        # ② : son interface montre `NON(C1 ET C2 OU(C4 XOR (C5 ET C6)))` — de l'infixe — alors
        # que son propre `eval()` n'exécute que du préfixe. L'exemple est un contre-exemple ;
        # l'accepter ici propagerait la confusion au lieu de la lever.
        with self.assertRaises(ValueError):
            analyser('NON(C1 ET C2 OU(C4 XOR (C5 ET C6)))', self.CLES)

    def test_parenthese_non_refermee_refusee_en_le_disant(self):
        with self.assertRaises(ValueError) as ctx:
            analyser('ET(C1, C2', self.CLES)
        self.assertIn('refermée', str(ctx.exception))

    def test_connecteur_sans_parentheses_oriente_l_utilisateur(self):
        with self.assertRaises(ValueError) as ctx:
            analyser('ET', self.CLES)
        self.assertIn('ET(C1, C2)', str(ctx.exception))

    def test_cle_inconnue_refusee_a_la_saisie(self):
        with self.assertRaises(ValueError):
            analyser('ET(C1, C9)', self.CLES)

    def test_texte_en_trop_refuse(self):
        with self.assertRaises(ValueError):
            analyser('ET(C1, C2) C3', self.CLES)

    def test_saisie_vide_refusee(self):
        with self.assertRaises(ValueError):
            analyser('   ', self.CLES)

    def test_condition_seule_est_un_arbre_valide(self):
        self.assertEqual(analyser('C1', self.CLES), 'C1')

    def test_aller_retour_texte_arbre_texte(self):
        for texte in ('C1', 'ET(C1, C2)', 'NON(C1)', 'OU(C1, ET(C2, C3))', 'XOR(C1, C2)'):
            self.assertEqual(rendre(analyser(texte, self.CLES)), texte)


class NomDeriveTest(unittest.TestCase):
    """Le nom se dérive des paramètres — même règle que `nom_produit()` du Calculator."""

    def test_nom_de_jonction_reproduit_la_graphie_d_origine(self):
        # `app.tddTable1.Value(1:3) '_' app.tddTable2.Value(1:3) '_' inf2 '_' sup2`
        self.assertEqual(nom_jonction('debut_bloc', 'fin_bloc', 0, 0), 'deb_fin_0_0')

    def test_les_offsets_non_entiers_sont_conserves(self):
        self.assertEqual(nom_jonction('debut', 'fin', -2.5, 10), 'deb_fin_-2.5_10')

    def test_deux_reglages_differents_ne_peuvent_pas_partager_un_nom(self):
        self.assertNotEqual(nom_jonction('debut', 'fin', 0, 15),
                            nom_jonction('debut', 'fin', 0, 45))

    def test_nom_de_chaine_derive_de_l_arbre_pas_du_texte(self):
        cles = ['C1', 'C2']
        self.assertEqual(nom_chaine(analyser('ET(C1,C2)', cles)),
                         nom_chaine(analyser('ET ( C1 , C2 )', cles)))
        self.assertEqual(nom_chaine(analyser('ET(C1,C2)', cles)), 'et_c1_c2')


if __name__ == '__main__':
    unittest.main()
