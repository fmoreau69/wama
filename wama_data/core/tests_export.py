"""Tests de l'Exporter — `WAMA_DATA_WORLD.md §9ter.5` et `§9ter.6 C`.

Chaque classe reprend une situation LUE dans le code de l'outil d'origine (`BIND_GUI.mlapp` et
`ExportTrip2Files.m`, extraits le 2026-08-23). Les cinq défauts relevés en tête de `export.py` ont
chacun leur test : sans cela, « une implémentation unique n'en a aucun » resterait une affirmation
de message de commit.

⚠ Un premier jet de ce module a été REVERTÉ (ef756b63) pour avoir supposé un pivot long → large
inexistant. `test_l_export_ne_pivote_RIEN` garde cette porte fermée.
"""
import unittest

from .export import (FORMATS, Colonne, Declaration, Fichier, Identite, Regroupement,
                     apercu, enregistrer_format, exporter, formats_disponibles,
                     formats_ecrivables, lignes, rendre)

# Un lot minimal mais réaliste : une table de situations et ses indicateurs adjoints, plus des
# méta-informations d'identité — exactement ce que §9ter.6 C dit qu'un export doit pouvoir mêler.
LOT_A = {
    'sit_0_15': [
        {'startTimecode': 10.0, 'endTimecode': 25.0, 'label': 'approche'},
        {'startTimecode': 60.0, 'endTimecode': 75.0, 'label': 'freinage'},
    ],
    'indicateurs': [
        {'vitesse_moyenne': 12.5, 'n': 150},
        {'vitesse_moyenne': 4.0, 'n': 148},
    ],
}
META_A = {'trip_id': 'REC_20190502', 'participant': 'P07', 'scenario': 'urbain'}

LOT_B = {
    'sit_0_15': [{'startTimecode': 5.0, 'endTimecode': 20.0, 'label': 'depart'}],
    'indicateurs': [{'vitesse_moyenne': 9.0, 'n': 140}],
}
META_B = {'trip_id': 'REC_20190503', 'participant': 'P08', 'scenario': 'urbain'}

DECL_SIT = Declaration(
    nom='situations',
    colonnes=(Colonne('sit_0_15', 'startTimecode'),
              Colonne('sit_0_15', 'endTimecode'),
              Colonne('indicateurs', 'vitesse_moyenne')),
    identite=Identite(('trip_id', 'participant', 'scenario')),
)


class DeclarationTest(unittest.TestCase):
    """La déclaration remplace la struct de session — et refuse ce qu'elle ne peut pas produire."""

    def test_entete_par_defaut_est_la_convention_du_livrable(self):
        # `0_15.startTimecode` — la graphie `table.variable` de l'interface d'origine.
        self.assertEqual(Colonne('0_15', 'startTimecode').titre, '0_15.startTimecode')

    def test_entete_explicite_l_emporte(self):
        self.assertEqual(Colonne('sit', 'start', entete='Début (s)').titre, 'Début (s)')

    def test_identite_en_tete_puis_ordre_declare(self):
        self.assertEqual(
            DECL_SIT.entetes(),
            ['trip_id', 'participant', 'scenario',
             'sit_0_15.startTimecode', 'sit_0_15.endTimecode', 'indicateurs.vitesse_moyenne'])

    def test_l_ordre_declare_est_une_DONNEE_pas_un_tri(self):
        inverse = Declaration(nom='x', colonnes=tuple(reversed(DECL_SIT.colonnes)),
                              identite=Identite(('trip_id',)))
        self.assertEqual(inverse.entetes()[1:],
                         ['indicateurs.vitesse_moyenne', 'sit_0_15.endTimecode',
                          'sit_0_15.startTimecode'])

    def test_entetes_en_double_refuses(self):
        # L'outil d'origine ne le voit pas : ses en-têtes sont reconstruits par chemin.
        with self.assertRaises(ValueError) as ctx:
            Declaration(nom='x', colonnes=(Colonne('t', 'v'), Colonne('t', 'v')))
        self.assertIn('double', str(ctx.exception))

    def test_declaration_sans_colonne_refusee(self):
        with self.assertRaises(ValueError):
            Declaration(nom='x', colonnes=())

    def test_decimation_est_un_PAS_donc_au_moins_1(self):
        with self.assertRaises(ValueError) as ctx:
            Declaration(nom='x', colonnes=(Colonne('t', 'v'),), decimation=0)
        self.assertIn('PAS', str(ctx.exception))

    def test_format_inconnu_refuse(self):
        with self.assertRaises(ValueError):
            Declaration(nom='x', colonnes=(Colonne('t', 'v'),), format='parquet')

    def test_sources_dans_l_ordre_de_premiere_apparition(self):
        self.assertEqual(DECL_SIT.sources, ['sit_0_15', 'indicateurs'])


class LignesTest(unittest.TestCase):
    """Une déclaration appliquée à un lot."""

    def test_identite_repetee_sur_chaque_ligne(self):
        out = lignes(DECL_SIT, LOT_A, META_A)
        self.assertEqual(len(out), 2)
        self.assertEqual(out[0][:3], ['REC_20190502', 'P07', 'urbain'])
        self.assertEqual(out[1][:3], ['REC_20190502', 'P07', 'urbain'])

    def test_valeurs_dans_l_ordre_declare(self):
        out = lignes(DECL_SIT, LOT_A, META_A)
        self.assertEqual(out[0][3:], [10.0, 25.0, 12.5])

    def test_l_export_ne_pivote_RIEN(self):
        # Le jet reverté (ef756b63) supposait un pivot long → large. Une table de N occurrences
        # sort en N LIGNES, jamais en une ligne de N×k colonnes.
        out = lignes(DECL_SIT, LOT_A, META_A)
        self.assertEqual(len(out), len(LOT_A['sit_0_15']))
        self.assertTrue(all(len(l) == len(DECL_SIT.entetes()) for l in out))

    def test_meta_absente_laisse_un_TROU_visible_pas_une_erreur(self):
        # Un corpus hétérogène (un lot sans participant déclaré) doit s'exporter quand même.
        out = lignes(DECL_SIT, LOT_A, {'trip_id': 'X'})
        self.assertEqual(out[0][:3], ['X', None, None])

    def test_tables_de_hauteurs_differentes_REFUSEES(self):
        # L'outil d'origine avale ce cas dans un `try … catch` à corps vide : l'export sort
        # tronqué sans un mot.
        lot = dict(LOT_A, indicateurs=[{'vitesse_moyenne': 1.0}])
        with self.assertRaises(ValueError) as ctx:
            lignes(DECL_SIT, lot, META_A)
        self.assertIn('hauteurs différentes', str(ctx.exception))

    def test_table_absente_refusee_en_nommant_les_presentes(self):
        with self.assertRaises(ValueError) as ctx:
            lignes(DECL_SIT, {'sit_0_15': []}, META_A)
        self.assertIn('indicateurs', str(ctx.exception))

    def test_champ_absent_rend_None_et_non_une_erreur(self):
        d = Declaration(nom='x', colonnes=(Colonne('sit_0_15', 'inexistant'),),
                        identite=Identite(()))
        self.assertEqual(lignes(d, LOT_A, META_A), [[None], [None]])

    def test_decimation_garde_une_ligne_sur_N(self):
        # Sémantique de l'outil d'origine : `for i = 1:sub_sampling:length` — un PAS.
        lot = {'t': [{'v': i} for i in range(10)]}
        d = Declaration(nom='x', colonnes=(Colonne('t', 'v'),), identite=Identite(()),
                        decimation=3)
        self.assertEqual(lignes(d, lot, {}), [[0], [3], [6], [9]])

    def test_la_limite_s_applique_APRES_la_decimation(self):
        # Montrer les 2 premières lignes brutes d'un export décimé au 3ᵉ ne montrerait pas
        # l'export.
        lot = {'t': [{'v': i} for i in range(10)]}
        d = Declaration(nom='x', colonnes=(Colonne('t', 'v'),), identite=Identite(()),
                        decimation=3)
        self.assertEqual(lignes(d, lot, {}, limite=2), [[0], [3]])


class RegroupementTest(unittest.TestCase):
    """① Les quatre modes sont deux axes — vérifié sur les quatre combinaisons."""

    LOTS = {'A': LOT_A, 'B': LOT_B}
    METAS = {'A': META_A, 'B': META_B}
    DECL_2 = Declaration(
        nom='autre',
        colonnes=(Colonne('sit_0_15', 'startTimecode'),
                  Colonne('sit_0_15', 'endTimecode'),
                  Colonne('indicateurs', 'vitesse_moyenne')),
        identite=Identite(('trip_id', 'participant', 'scenario')),
    )

    def _exporter(self, **axes):
        return exporter([DECL_SIT, self.DECL_2], self.LOTS, self.METAS, Regroupement(**axes))

    def test_normal_un_fichier_par_declaration_et_par_lot(self):
        f = self._exporter()
        self.assertEqual(sorted(x.nom for x in f),
                         ['autre_A', 'autre_B', 'situations_A', 'situations_B'])

    def test_concat_trip_un_fichier_par_declaration(self):
        f = self._exporter(lots=True)
        self.assertEqual(sorted(x.nom for x in f), ['autre', 'situations'])
        self.assertEqual({x.nb_lignes for x in f}, {3})     # 2 lignes de A + 1 de B

    def test_concat_event_situation_un_fichier_par_lot(self):
        f = self._exporter(declarations=True)
        self.assertEqual(sorted(x.nom for x in f), ['A', 'B'])

    def test_concat_all_un_seul_fichier(self):
        f = self._exporter(lots=True, declarations=True)
        self.assertEqual([x.nom for x in f], ['export'])
        self.assertEqual(f[0].nb_lignes, 6)                 # 2 déclarations × (2 + 1) lignes

    def test_les_quatre_modes_d_origine_sont_les_quatre_combinaisons(self):
        vus = {Regroupement(lots=l, declarations=d).mode_origine
               for l in (False, True) for d in (False, True)}
        self.assertEqual(vus, {'normal', 'concat_trip', 'concat_event_situation', 'concat_all'})

    def test_concat_all_n_OUBLIE_aucune_declaration(self):
        # ② Le `concat_all` d'origine accumule dans la mauvaise variable : seule la DERNIÈRE
        # déclaration de chaque trip survit. Ici les deux doivent être présentes.
        f = self._exporter(lots=True, declarations=True)[0]
        self.assertEqual(f.nb_lignes, 6, "les deux déclarations doivent survivre, pas la dernière")

    def test_le_nom_de_fichier_ne_depend_PAS_du_dernier_tour_de_boucle(self):
        # ② `concat_all` et `concat_trip` lisent `i_trip`/`i_fic` après la fin de leur boucle.
        un_lot = exporter([DECL_SIT], {'A': LOT_A}, self.METAS, Regroupement(lots=True))
        deux_lots = exporter([DECL_SIT], self.LOTS, self.METAS, Regroupement(lots=True))
        self.assertEqual([x.nom for x in un_lot], [x.nom for x in deux_lots])

    def test_concatener_des_declarations_aux_COLONNES_DIFFERENTES_est_refuse(self):
        # ② L'outil d'origine garde l'en-tête de la dernière et empile les données de toutes.
        autre = Declaration(nom='z', colonnes=(Colonne('sit_0_15', 'label'),),
                            identite=Identite(('trip_id',)))
        with self.assertRaises(ValueError) as ctx:
            exporter([DECL_SIT, autre], self.LOTS, self.METAS, Regroupement(declarations=True))
        self.assertIn('mêmes colonnes', str(ctx.exception))

    def test_l_entete_decrit_bien_les_lignes(self):
        for f in self._exporter(lots=True, declarations=True):
            self.assertTrue(all(len(l) == len(f.entetes) for l in f.lignes))

    def test_ordre_reproductible(self):
        a = [x.lignes for x in self._exporter(lots=True)]
        b = [x.lignes for x in self._exporter(lots=True)]
        self.assertEqual(a, b)


class ApercuTest(unittest.TestCase):
    """④ L'aperçu EST l'export borné — pas un second chemin."""

    def test_apercu_borne_le_nombre_de_lignes(self):
        f = apercu([DECL_SIT], {'A': LOT_A}, {'A': META_A}, lignes_max=1)
        self.assertEqual(f[0].nb_lignes, 1)

    def test_apercu_et_export_donnent_LES_MEMES_lignes(self):
        # Le test qui interdit à l'aperçu de mentir : ses lignes sont un préfixe exact.
        complet = exporter([DECL_SIT], {'A': LOT_A}, {'A': META_A})[0]
        vu = apercu([DECL_SIT], {'A': LOT_A}, {'A': META_A}, lignes_max=1)[0]
        self.assertEqual(vu.entetes, complet.entetes)
        self.assertEqual(vu.lignes, complet.lignes[:1])


class RenduTest(unittest.TestCase):
    """Le rendu texte — et ce qu'il refuse d'écrire."""

    def test_csv_separe_par_point_virgule(self):
        f = exporter([DECL_SIT], {'A': LOT_A}, {'A': META_A})[0]
        texte = rendre(f)
        self.assertTrue(texte.startswith(
            'trip_id;participant;scenario;sit_0_15.startTimecode'))
        self.assertIn('REC_20190502;P07;urbain;10.0;25.0;12.5', texte)

    def test_une_absence_rend_une_cellule_VIDE_jamais_None(self):
        # Écrire « None » ferait relire la colonne comme du texte par le tableur : les moyennes
        # du chercheur deviennent fausses sans qu'aucune ligne ne paraisse anormale.
        f = Fichier(nom='x', entetes=['a', 'b'], lignes=[[1, None]])
        self.assertEqual(rendre(f), 'a;b\n1;\n')

    def test_un_separateur_dans_une_valeur_est_protege(self):
        f = Fichier(nom='x', entetes=['a'], lignes=[['gauche;droite']])
        self.assertEqual(rendre(f), 'a\n"gauche;droite"\n')

    def test_un_guillemet_est_double(self):
        f = Fichier(nom='x', entetes=['a'], lignes=[['dit "oui"']])
        self.assertIn('"dit ""oui"""', rendre(f))

    def test_tsv_separe_par_tabulation(self):
        f = Fichier(nom='x', entetes=['a', 'b'], lignes=[[1, 2]], format='tsv')
        self.assertEqual(rendre(f), 'a\tb\n1\t2\n')

    def test_xlsx_et_mat_refuses_par_le_coeur(self):
        # Rendre un CSV sous une extension `.xlsx` serait pire que refuser.
        for fmt in ('xlsx', 'mat'):
            with self.assertRaises(ValueError):
                rendre(Fichier(nom='x', entetes=['a'], lignes=[[1]], format=fmt))

    def test_les_formats_declares_couvrent_ceux_du_livrable(self):
        # §9ter.5 : « formats : .csv, .txt, .xlsx, .mat » (+ .tsv du chemin script).
        for attendu in ('csv', 'txt', 'xlsx', 'mat', 'tsv'):
            self.assertIn(attendu, FORMATS)


class RegistreDeFormatsTest(unittest.TestCase):
    """Les formats de sortie sont une CAPACITÉ AGRÉGATIVE, pas une liste figée (§9quinquies).

    Même modèle que le registre de lecteurs de l'Importer : la méthode d'export est universelle,
    les formats s'ajoutent sans toucher le moteur.
    """

    def tearDown(self):
        FORMATS.pop('zzz', None)

    def test_declare_n_est_pas_ecrivable(self):
        # LA distinction qui porte le modèle : `xlsx` est une cible légitime du livrable (§9ter.5)
        # mais son écrivain demande une bibliothèque. Le taire ferait croire qu'il n'existe pas ;
        # l'accepter en silence écrirait un CSV sous une extension `.xlsx`.
        self.assertIn('xlsx', formats_disponibles())
        self.assertNotIn('xlsx', formats_ecrivables())

    def test_l_ecart_entre_declares_et_ecrivables_est_LA_dette_mesurable(self):
        dette = set(formats_disponibles()) - set(formats_ecrivables())
        self.assertEqual(dette, {'xlsx', 'mat'})

    def test_ajouter_un_format_ne_touche_PAS_le_moteur(self):
        enregistrer_format('zzz', separateur='|', description='essai')
        f = Fichier(nom='x', entetes=['a', 'b'], lignes=[[1, 2]], format='zzz')
        self.assertEqual(rendre(f), 'a|b\n1|2\n')

    def test_un_adaptateur_peut_FOURNIR_l_ecrivain_d_un_format_declare(self):
        # C'est le geste attendu : l'extension existe déjà, l'adaptateur apporte le comportement.
        enregistrer_format('zzz', ecrivain=lambda fic: f"<{fic.nom}>")
        self.assertEqual(rendre(Fichier(nom='ok', entetes=[], lignes=[], format='zzz')), '<ok>')
        self.assertIn('zzz', formats_ecrivables())

    def test_un_format_JAMAIS_enregistre_est_refuse_en_nommant_les_declares(self):
        with self.assertRaises(ValueError) as ctx:
            rendre(Fichier(nom='x', entetes=[], lignes=[], format='parquet'))
        self.assertIn('csv', str(ctx.exception))

    def test_un_format_declare_SANS_ecrivain_le_dit_explicitement(self):
        with self.assertRaises(ValueError) as ctx:
            rendre(Fichier(nom='x', entetes=['a'], lignes=[[1]], format='mat'))
        self.assertIn('aucun écrivain', str(ctx.exception))

    def test_la_declaration_accepte_tout_format_DECLARE(self):
        # Refuser `xlsx` à la déclaration interdirait de décrire un export du livrable.
        Declaration(nom='x', colonnes=(Colonne('t', 'v'),), format='xlsx')


if __name__ == '__main__':
    unittest.main()
