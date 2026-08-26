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

from .dataset import (Ecart, _indice_de_prefixe, attributs_de_coordonnees, axes_declares,
                      charger, chemin, signaux_declares, situer, verifier)


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

    def test_PROVENANCE_et_CAPACITE_sont_deux_axes_et_ne_se_comparent_PAS(self):
        """⚠ Correction d'une erreur de catégorie que j'avais encodée la veille (§9decies).

        `source.type` dit d'où la donnée VIENT (rtmaps, lsl, csv, db…) ; le format du lecteur dit
        QUI SAIT L'OUVRIR (trip, tabular). Le kind `dataset` réclame en toutes lettres un
        « **reader source-agnostique** » : les deux vocabulaires sont donc **volontairement
        indépendants**, et `reader_for()` ne consulte jamais `source.type`.

        La version précédente rapportait leur différence comme une divergence « garde-fou G1 » —
        elle se déclenchait donc sur TOUT manifeste valide. **Un contrôle qui sonne toujours
        apprend à ignorer le compte-rendu.**
        """
        e = verifier(_manifeste('capteur.csv', ['capteur'], type_source='rtmaps'), self.dossier)
        self.assertTrue(e.conforme)
        self.assertEqual(e.lecteur, 'tabular')      # informatif : qui a lu
        self.assertIn('conforme', e.rendre())       # et surtout : PAS un écart

    def test_le_rendu_dit_QUI_a_lu(self):
        e = verifier(_manifeste('capteur.csv', ['capteur']), self.dossier)
        self.assertIn('tabular', e.rendre())


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


class SituerLesAxesTest(unittest.TestCase):
    """Le plan d'expérience confronté à la source — `WAMA_DATA_WORLD §13`.

    ⭐ Ces tests encodent un RELEVÉ, pas une convention : un `.trip` de 2019 range déjà ses
    coordonnées dans `MetaTripDatas`, **sans préfixe** (`scenario`, `participant_id`). Les trois
    graphies acceptées ne sont donc pas une commodité, elles sont la condition pour que WAMA
    reconnaisse les corpus qui existaient avant lui.
    """

    AXES = [{'key': 'passation', 'role': 'observation', 'source_key': 'participant_id'},
            {'key': 'scenario', 'role': 'factor', 'crosses': 'passation'},
            {'key': 'groupe', 'role': 'factor', 'contains': 'passation'}]

    def test_la_convention_wama_prefixee_est_lue(self):
        trouvees, absents = situer(self.AXES, {'axe.scenario': 'nuit'})
        self.assertEqual(trouvees['scenario'], 'nuit')

    def test_la_convention_SANS_prefixe_de_l_outil_d_origine_est_lue_aussi(self):
        trouvees, _ = situer(self.AXES, {'scenario': 'Test'})
        self.assertEqual(trouvees['scenario'], 'Test')

    def test_un_alias_declare_rattrape_un_nom_divergent(self):
        # Mesuré : l'unité d'observation se range sous `participant_id`, dont la VALEUR nomme
        # pourtant une passation (`Passation_01`).
        trouvees, _ = situer(self.AXES, {'participant_id': 'Passation_01'})
        self.assertEqual(trouvees['passation'], 'Passation_01')

    def test_le_prefixe_wama_prime_sur_la_forme_nue(self):
        trouvees, _ = situer(self.AXES, {'axe.scenario': 'nuit', 'scenario': 'jour'})
        self.assertEqual(trouvees['scenario'], 'nuit')

    def test_un_axe_sans_coordonnee_est_NOMME_pas_devine(self):
        _, absents = situer(self.AXES, {'scenario': 'Test'})
        self.assertEqual(absents, ['passation', 'groupe'])

    def test_aucun_axe_declare_ne_produit_aucun_manque(self):
        self.assertEqual(situer([], {'scenario': 'Test'}), ({}, []))

    def test_un_axe_sans_cle_est_ignore_pas_planté(self):
        self.assertEqual([a['key'] for a in axes_declares({'axes': [{'role': 'factor'},
                                                                   {'key': 'p'}]})], ['p'])


class AllerRetourDesCoordonneesTest(unittest.TestCase):
    """⭐ L'aller-retour COMPLET des coordonnées d'axes : écrites dans le conteneur, relues par
    `situer()`. Sans lui, « le `.wdat` porte son rangement » resterait une affirmation.

    C'est le quick win ④ (`WAMA_DATA_WORLD §13.12`), et il ne demandait **aucun changement de
    schéma** : `Contexte.attributs` alimente déjà `WamaMeta`, et les quatre lecteurs exposent déjà
    `SourceInfo.attributes`.
    """

    AXES = [{'key': 'passation', 'role': 'observation'},
            {'key': 'scenario', 'role': 'factor', 'crosses': 'passation'}]

    def test_la_forme_canonique_est_prefixee(self):
        self.assertEqual(attributs_de_coordonnees({'passation': 'P01'}),
                         {'axe.passation': 'P01'})

    def test_une_valeur_absente_devient_une_chaine_vide_pas_None(self):
        # `WamaMeta.value` est du TEXT : y écrire None donnerait 'None' à la relecture.
        self.assertEqual(attributs_de_coordonnees({'groupe': None}), {'axe.groupe': ''})

    def test_ecrites_dans_un_wdat_elles_sont_RELUES(self):
        from .containers import Contexte, ecrire
        from .core.temporal import Signal, SignalMeta, TemporalReferential
        from . import sources

        ref = TemporalReferential(name='essai')
        ref.add(Signal(SignalMeta(name='vitesse'), [0.0, 0.1],
                       lambda i0, i1: [{'time': 0.0, 'v': 1.0}, {'time': 0.1, 'v': 2.0}][i0:i1]))

        coords = {'passation': 'Passation_01', 'scenario': 'nuit'}
        with tempfile.TemporaryDirectory() as d:
            cible = Path(d) / 'essai.wdat'
            ecrire(ref, cible, contexte=Contexte(
                auteur='test', attributs=attributs_de_coordonnees(coords)))

            trouvees, absents = situer(self.AXES, sources.probe(cible).attributes)

        self.assertEqual(trouvees, coords)
        self.assertEqual(absents, [])

    def test_les_metas_TECHNIQUES_ne_sont_jamais_prises_pour_des_axes(self):
        # `WamaMeta` est un espace PARTAGÉ : `format`, `schema_version`, `created_at` y vivent.
        # C'est la raison d'être du préfixe (D21) — sans lui, un axe nommé `format` les capterait.
        axes = [{'key': 'format', 'role': 'observation'}]
        trouvees, absents = situer(axes, {'format': 'wdat', 'axe.format': 'A4'})
        self.assertEqual(trouvees, {'format': 'A4'})
        self.assertEqual(absents, [])


class EcartDesAxesTest(unittest.TestCase):
    """L'écart PORTE les axes — et un axe sans coordonnée n'est jamais un verdict."""

    def test_un_axe_sans_coordonnee_ne_rend_PAS_l_ecart_non_conforme(self):
        # Tous les axes ne sont pas des coordonnées de conteneur : une fenêtre d'analyse indexe
        # des LIGNES. Sonner dessus ferait sonner le contrôle sur tout manifeste correct.
        e = Ecart(axes_sans_coordonnee=('fenetre',))
        self.assertTrue(e.conforme)

    def test_le_rendu_montre_les_coordonnees_situees(self):
        e = Ecart(coordonnees=(('scenario', 'Test'),))
        self.assertIn('scenario=Test', e.rendre())

    def test_le_rendu_nomme_les_axes_sans_coordonnee(self):
        e = Ecart(axes_sans_coordonnee=('groupe',))
        self.assertIn('groupe', e.rendre())


class IndiceDePrefixeTest(unittest.TestCase):
    """⚠ Défaut RÉEL du lecteur `.trip`, mesuré le 2026-08-26 (D31) : `probe()` liste des noms de
    TABLE (`data_X`), `read()` rend des signaux au nom du CATALOGUE (`X`). Un auteur de manifeste
    lit le catalogue — il écrira donc toujours la mauvaise forme. On NOMME la cause au lieu
    d'annoncer « tout est absent » sur un fichier qui contient tout."""

    def test_un_ecart_total_recouvert_par_un_prefixe_est_EXPLIQUE(self):
        notes = _indice_de_prefixe(('CADISP', 'BIOPAC_MP150'),
                                   {'event_CADISP', 'data_BIOPAC_MP150'})
        self.assertEqual(len(notes), 1)
        self.assertIn('PRÉFIXÉ', notes[0])
        # L'exemple montré est le PREMIER manquant, dans l'ordre du manifeste.
        self.assertIn('event_CADISP', notes[0])

    def test_l_exemple_traverse_les_familles(self):
        notes = _indice_de_prefixe(('BIOPAC_MP150',), {'data_BIOPAC_MP150'})
        self.assertIn('data_BIOPAC_MP150', notes[0])

    def test_un_manque_REEL_ne_declenche_aucun_indice(self):
        # Si un seul des manquants n'est pas recouvert, l'explication serait fausse : on se tait.
        self.assertEqual(_indice_de_prefixe(('CADISP', 'ABSENT_PARTOUT'), {'event_CADISP'}), ())

    def test_aucun_manquant_aucun_indice(self):
        self.assertEqual(_indice_de_prefixe((), {'data_X'}), ())


if __name__ == '__main__':
    unittest.main()
