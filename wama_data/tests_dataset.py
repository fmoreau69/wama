"""Tests du manifeste `dataset` rendu exécutable (`wama_data/dataset.py`).

⚠ Le test qui porte ce fichier est `ChaineDeclarativeTest` : il fait le parcours COMPLET depuis
des déclarations — manifeste `dataset` → référentiel → `Vue` → fonction du catalogue →
`Declaration` d'export → fichier. C'est le premier chemin de bout en bout entièrement déclaratif
du monde Data ; sans lui, « la chaîne est exécutable » resterait une affirmation.

Les autres classes vérifient la doctrine du §9bis : **le manifeste déclare des ATTENTES,
l'importer MESURE L'ÉCART** — jamais l'inverse, qui serait circulaire.
"""
import csv
import tempfile
import unittest
from pathlib import Path

from wama.common.manifests.builtin.dataset import validate_dataset_body

from .dataset import Ecart, charger, chemin, signaux_declares, verifier


def _csv(dossier: Path, nom: str, lignes) -> Path:
    p = dossier / f"{nom}.csv"
    with p.open('w', newline='', encoding='utf-8') as fh:
        w = csv.writer(fh)
        w.writerow(['time', 'value'])
        w.writerows(lignes)
    return p


def _manifeste(ref: str, ids, type_source='csv'):
    return {'source': {'type': type_source, 'ref': ref},
            'signals': [{'id': i, 'data_type': 'timeseries'} for i in ids]}


class LectureDuManifesteTest(unittest.TestCase):

    def test_chemin_absolu_inchange(self):
        p = chemin({'source': {'ref': str(Path('/tmp/x.csv').resolve())}})
        self.assertTrue(p.is_absolute())

    def test_chemin_relatif_resolu_sous_la_RACINE_jamais_le_cwd(self):
        # Un manifeste doit être rejouable ailleurs : dépendre du cwd le rendrait valide sur une
        # machine et faux sur une autre, sans que rien ne le dise.
        p = chemin({'source': {'ref': 'sous/x.csv'}}, racine='/base')
        self.assertEqual(p, Path('/base') / 'sous' / 'x.csv')

    def test_source_sans_ref_refusee(self):
        with self.assertRaises(ValueError):
            chemin({'source': {'type': 'csv'}})

    def test_signaux_declares_dans_l_ordre(self):
        self.assertEqual(signaux_declares(_manifeste('x', ['b', 'a'])), ['b', 'a'])


class EcartTest(unittest.TestCase):
    """La confrontation — `probe` seul, sans charger."""

    def setUp(self):
        self._d = tempfile.TemporaryDirectory()
        self.dossier = Path(self._d.name)
        _csv(self.dossier, 'capteur', [(0.0, 1.0), (1.0, 2.0)])

    def tearDown(self):
        self._d.cleanup()

    def test_conforme_quand_tout_est_la(self):
        e = verifier(_manifeste('capteur.csv', ['capteur']), self.dossier)
        self.assertTrue(e.conforme, e.rendre())
        self.assertEqual(e.manquants, ())

    def test_un_signal_DECLARE_et_absent_est_un_MANQUANT(self):
        e = verifier(_manifeste('capteur.csv', ['capteur', 'gps']), self.dossier)
        self.assertFalse(e.conforme)
        self.assertEqual(e.manquants, ('gps',))
        self.assertIn('gps', e.rendre())

    def test_un_flux_present_NON_declare_ne_rend_PAS_non_conforme(self):
        # Asymétrie voulue : une source peut contenir plus qu'on n'en décrit. Seule la promesse
        # non tenue compte.
        e = verifier(_manifeste('capteur.csv', []), self.dossier)
        self.assertTrue(e.conforme)
        self.assertEqual(e.non_declares, ('capteur',))

    def test_source_introuvable_le_DIT(self):
        e = verifier(_manifeste('absent.csv', ['x']), self.dossier)
        self.assertFalse(e.conforme)
        self.assertTrue(any('introuvable' in n for n in e.notes), e.notes)

    def test_aucun_lecteur_pour_le_format_le_DIT(self):
        (self.dossier / 'x.inconnu').write_text('rien', encoding='utf-8')
        e = verifier(_manifeste('x.inconnu', ['x']), self.dossier)
        self.assertTrue(any('aucun lecteur' in n for n in e.notes), e.notes)

    def test_G1_le_vocabulaire_de_source_type_est_MESURE(self):
        # ⚠ `DATASET_SOURCES` dit « csv » ; le lecteur s'appelle « tabular ». Les deux vocabulaires
        # ne se recouvrent PAS — c'est le garde-fou G1, ici transformé en constat chiffrable au
        # lieu d'une intention.
        e = verifier(_manifeste('capteur.csv', ['capteur'], type_source='csv'), self.dossier)
        self.assertEqual(e.type_source, ('csv', 'tabular'))
        self.assertIn('G1', e.rendre())
        # Et ça ne rend PAS le jeu inexploitable : c'est un écart de vocabulaire, pas de donnée.
        self.assertTrue(e.conforme)

    def test_G1_TOUT_manifeste_VALIDE_porte_aujourd_hui_l_ecart(self):
        """⚠ Le constat le plus dur sur G1, et il n'était pas anticipé.

        Les deux vocabulaires ne sont pas seulement « non réconciliés » : ils sont **mutuellement
        exclusifs**. `DATASET_SOURCES` = (rtmaps, lsl, rosbag, csv, parquet, db, docs, other) ;
        les formats de lecteurs = (trip, tabular). **Aucune valeur commune.** Donc :

          • un manifeste qui nomme le lecteur réel (`tabular`) est REFUSÉ par la validation du kind ;
          • un manifeste valide (`csv`) désigne un format auquel aucun lecteur ne répond.

        Conséquence mesurable : **aucun manifeste `dataset` valide ne peut rendre « rien à
        signaler » aujourd'hui.** C'est ce test qui l'atteste ; il tombera le jour où G1 sera fermé,
        et c'est exactement ce qu'on veut d'un test de garde-fou.
        """
        from wama.common.manifests.builtin.dataset import DATASET_SOURCES

        from .sources import READERS
        self.assertEqual(set(DATASET_SOURCES) & set(READERS), set(),
                         "les deux vocabulaires se recouvrent enfin — G1 est fermé, "
                         "mettre ce test à jour")
        e = verifier(_manifeste('capteur.csv', ['capteur']), self.dossier)
        self.assertTrue(e.conforme)                 # la DONNÉE est là…
        self.assertIsNotNone(e.type_source)         # …mais le vocabulaire diverge toujours

    def test_rendu_lisible_quand_il_n_y_a_VRAIMENT_rien_a_signaler(self):
        # `source.type` est facultatif au kind (`if src.get('type') and …`). Sans lui, aucune
        # divergence de vocabulaire — c'est le seul cas où le rendu est vide aujourd'hui.
        sans_type = {'source': {'ref': 'capteur.csv'},
                     'signals': [{'id': 'capteur', 'data_type': 'timeseries'}]}
        self.assertIn('conforme', verifier(sans_type, self.dossier).rendre())


class ChargementTest(unittest.TestCase):

    def setUp(self):
        self._d = tempfile.TemporaryDirectory()
        self.dossier = Path(self._d.name)
        _csv(self.dossier, 'capteur', [(0.0, 1.0), (1.0, 2.0), (2.0, 3.0)])

    def tearDown(self):
        self._d.cleanup()

    def test_on_ne_rend_JAMAIS_le_referentiel_seul(self):
        # ① : ignorer l'écart doit être un geste délibéré, pas une distraction.
        resultat = charger(_manifeste('capteur.csv', ['capteur']), self.dossier)
        self.assertEqual(len(resultat), 2)
        ref, ecart = resultat
        self.assertEqual(ref.names, ['capteur'])
        self.assertIsInstance(ecart, Ecart)

    def test_un_ecart_n_est_PAS_une_erreur_par_defaut(self):
        # Un corpus réel est hétérogène : refuser une passation partielle rendrait le manifeste
        # inutilisable. On charge ce qui est là, on RAPPORTE le reste.
        ref, ecart = charger(_manifeste('capteur.csv', ['capteur', 'gps']), self.dossier)
        self.assertEqual(ref.names, ['capteur'])
        self.assertEqual(ecart.manquants, ('gps',))

    def test_strict_refuse_une_promesse_non_tenue(self):
        with self.assertRaises(ValueError) as ctx:
            charger(_manifeste('capteur.csv', ['capteur', 'gps']), self.dossier, strict=True)
        self.assertIn('gps', str(ctx.exception))

    def test_source_introuvable_leve_meme_sans_strict(self):
        # Distinguer « il manque un signal » (on continue) de « il n'y a rien à ouvrir » (on lève).
        with self.assertRaises(ValueError):
            charger(_manifeste('absent.csv', ['x']), self.dossier)

    def test_seuls_les_signaux_DECLARES_sont_charges(self):
        _csv(self.dossier, 'autre', [(0.0, 9.0)])
        ref, _ = charger(_manifeste('capteur.csv', ['capteur']), self.dossier)
        self.assertNotIn('autre', ref.names)

    def test_le_referentiel_est_reellement_interrogeable(self):
        ref, _ = charger(_manifeste('capteur.csv', ['capteur']), self.dossier)
        self.assertEqual(ref.span(), (0.0, 2.0))
        self.assertIsNotNone(ref.at('capteur', 1.0))


class ChaineDeclarativeTest(unittest.TestCase):
    """⚠ LE test : manifeste → référentiel → Vue → fonction → export, sans une ligne impérative."""

    def setUp(self):
        self._d = tempfile.TemporaryDirectory()
        self.dossier = Path(self._d.name)
        _csv(self.dossier, 'vitesse',
             [(float(i), 40.0 if 3 <= i <= 6 else 5.0) for i in range(12)])

    def tearDown(self):
        self._d.cleanup()

    def test_le_manifeste_declare_est_VALIDE_par_son_kind(self):
        # La déclaration utilisée ici doit passer la validation officielle du kind, sinon le test
        # prouverait un chemin que le corpus n'accepterait pas.
        self.assertEqual(validate_dataset_body(_manifeste('vitesse.csv', ['vitesse'])), [])

    def test_de_la_DECLARATION_au_FICHIER(self):
        from .core.export import Colonne, Declaration, Identite, rendre
        from .functions.io.export import exporter_frames
        from .vue import ColonneDerivee, Piste, Vue, appliquer

        # ① le jeu — une déclaration
        ref, ecart = charger(_manifeste('vitesse.csv', ['vitesse']), self.dossier)
        self.assertTrue(ecart.conforme, ecart.rendre())

        # ② ce qu'on regarde — une déclaration
        vue = Vue(nom='exploration', pistes=(Piste('vitesse'),),
                  derivees=(ColonneDerivee('calcul_glissant', 'vitesse',
                                           {'fenetre_s': 2.0, 'colonne': 'value'}),))
        resultat = appliquer(vue, ref)
        self.assertIn('value_moyenne', resultat.tables['vitesse'].df.columns)

        # ③ ce qu'on livre — une déclaration
        decl = Declaration(
            nom='livrable',
            colonnes=(Colonne('vitesse', 'time'), Colonne('vitesse', 'value'),
                      Colonne('vitesse', 'value_moyenne')),
            identite=Identite(('trip_id',)))
        fichiers = exporter_frames([decl], {'A': resultat.tables}, {'A': {'trip_id': 'ESSAI'}})

        texte = rendre(fichiers[0])
        self.assertTrue(texte.startswith(
            'trip_id;vitesse.time;vitesse.value;vitesse.value_moyenne'))
        self.assertEqual(len(texte.strip().split('\n')), 13)   # en-tête + 12 lignes

    def test_les_TROIS_declarations_font_l_aller_retour_JSON(self):
        # Le corollaire de §9quater.5 : ce qu'on persiste, c'est la déclaration. Si l'une des
        # trois ne survivait pas à un aller-retour, la chaîne ne serait pas rejouable.
        import json

        from .core.export import Colonne, Declaration, Identite, declaration_depuis_dict
        from .vue import Piste, Vue, depuis_dict

        manifeste = _manifeste('vitesse.csv', ['vitesse'])
        vue = Vue(nom='v', pistes=(Piste('vitesse'),))
        decl = Declaration(nom='d', colonnes=(Colonne('vitesse', 'time'),),
                           identite=Identite(()))

        self.assertEqual(json.loads(json.dumps(manifeste)), manifeste)
        self.assertEqual(depuis_dict(json.loads(json.dumps(vue.to_dict()))), vue)
        self.assertEqual(declaration_depuis_dict(json.loads(json.dumps(decl.to_dict()))), decl)


if __name__ == '__main__':
    unittest.main()
