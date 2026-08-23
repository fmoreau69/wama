"""Tests de la FRONTIÈRE pandas de l'Exporter.

Le cœur (`core/tests_export.py`) est testé sans pandas. Ici on ne teste QUE ce que l'adaptateur
ajoute : la conversion `TypedFrame` → lignes, et l'écriture des fichiers.

⚠ Le point délicat est le `NaN`. Il traverse trois frontières successives (pandas → dicts → texte)
et la bonne réponse n'est pas la même aux trois : on le CONSERVE en dicts (pour ne pas casser le
typage numérique) et on l'écrit VIDE dans le fichier (pour ne pas fausser la relecture par un
tableur). Les deux ont leur test.
"""
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from wama.common.catalog.data_types import DataType, TypedFrame
from ...core.export import Colonne, Declaration, Identite, Regroupement, rendre
from ...core.valeurs import manquant
from .export import apercu_frames, ecrire, exporter_frames, lot_depuis_frames

FRAMES = {
    'sit_0_15': TypedFrame(pd.DataFrame({
        'start': [10.0, 60.0],
        'end': [25.0, 75.0],
        'label': ['approche', 'freinage'],
    }), DataType.SEGMENTS),
    'indicateurs': TypedFrame(pd.DataFrame({
        'vitesse_moyenne': [12.5, None],
        'n': [150, 148],
    }), DataType.TABLE),
}
META = {'trip_id': 'REC_20190502', 'participant': 'P07'}

DECL = Declaration(
    nom='situations',
    colonnes=(Colonne('sit_0_15', 'start'),
              Colonne('sit_0_15', 'label'),
              Colonne('indicateurs', 'vitesse_moyenne')),
    identite=Identite(('trip_id', 'participant')),
)


class ConversionTest(unittest.TestCase):

    def test_frames_vers_lignes(self):
        lot = lot_depuis_frames(FRAMES)
        self.assertEqual(sorted(lot), ['indicateurs', 'sit_0_15'])
        self.assertEqual(lot['sit_0_15'][0]['label'], 'approche')

    def test_un_NaN_est_CONSERVE_en_dicts_et_non_force_a_None(self):
        # Forcer `None` ici casserait le typage numérique que l'appelant peut vouloir relire ;
        # `manquant()` reconnaît les deux, comme partout à cette frontière.
        lot = lot_depuis_frames(FRAMES)
        self.assertTrue(manquant(lot['indicateurs'][1]['vitesse_moyenne']))

    def test_export_complet_depuis_des_frames(self):
        f = exporter_frames([DECL], {'A': FRAMES}, {'A': META})[0]
        self.assertEqual(f.entetes,
                         ['trip_id', 'participant', 'sit_0_15.start', 'sit_0_15.label',
                          'indicateurs.vitesse_moyenne'])
        self.assertEqual(f.nb_lignes, 2)
        self.assertEqual(f.lignes[0][:4], ['REC_20190502', 'P07', 10.0, 'approche'])

    def test_apercu_est_un_prefixe_exact_de_l_export(self):
        complet = exporter_frames([DECL], {'A': FRAMES}, {'A': META})[0]
        vu = apercu_frames([DECL], {'A': FRAMES}, {'A': META}, lignes_max=1)[0]
        self.assertEqual(vu.lignes, complet.lignes[:1])

    def test_regroupement_entre_lots(self):
        f = exporter_frames([DECL], {'A': FRAMES, 'B': FRAMES}, {'A': META, 'B': META},
                            Regroupement(lots=True))
        self.assertEqual(len(f), 1)
        self.assertEqual(f[0].nb_lignes, 4)


class EcritureTest(unittest.TestCase):

    def test_un_NaN_s_ecrit_CELLULE_VIDE_dans_le_fichier(self):
        # Écrire « nan » ferait relire la colonne comme du texte par le tableur : les moyennes
        # du chercheur deviendraient fausses sans qu'aucune ligne ne paraisse anormale.
        f = exporter_frames([DECL], {'A': FRAMES}, {'A': META})[0]
        derniere = rendre(f).strip().split('\n')[-1]
        self.assertTrue(derniere.endswith(';'), f"attendu une cellule vide en fin : {derniere!r}")

    def test_ecrire_produit_un_fichier_par_export(self):
        f = exporter_frames([DECL], {'A': FRAMES}, {'A': META})
        with tempfile.TemporaryDirectory() as d:
            chemins = ecrire(f, d)
            self.assertEqual([c.name for c in chemins], ['situations_A.csv'])
            texte = chemins[0].read_text(encoding='utf-8')
            self.assertIn('trip_id;participant;sit_0_15.start', texte)
            self.assertIn('REC_20190502;P07;10.0;approche;12.5', texte)

    def test_le_dossier_est_cree_s_il_manque(self):
        f = exporter_frames([DECL], {'A': FRAMES}, {'A': META})
        with tempfile.TemporaryDirectory() as d:
            cible = Path(d) / 'sous' / 'dossier'
            self.assertEqual(len(ecrire(f, cible)), 1)
            self.assertTrue(cible.is_dir())

    def test_un_format_non_separe_par_un_caractere_est_REFUSE_explicitement(self):
        # Rendre un CSV sous une extension `.xlsx` serait pire que refuser.
        decl = Declaration(nom='x', colonnes=(Colonne('sit_0_15', 'start'),),
                           identite=Identite(()), format='xlsx')
        f = exporter_frames([decl], {'A': FRAMES}, {'A': META})
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ValueError):
                ecrire(f, d)


class PasDeDeclarationAuCatalogueTest(unittest.TestCase):
    """L'Exporter n'est PAS au catalogue, et c'est une décision — pas un oubli.

    Ce test verrouille la décision : si quelqu'un enregistre un jour un `FunctionSpec` d'export
    sans trancher D13 ni ajouter de catégorie honnête, il échoue et l'oblige à relire le pourquoi.
    """

    def test_aucune_fonction_d_export_au_catalogue(self):
        # `catalog_dict()` rend {clé → dict}, pas {'functions': [...]} — forme LUE dans
        # `function_catalog.py:131`, pas devinée.
        from wama.common.catalog.function_catalog import catalog_dict
        cles = list(catalog_dict())
        self.assertNotIn('export', cles)
        self.assertFalse([k for k in cles if k.startswith('export_')],
                         "un puits n'a pas de FunctionCategory — voir D13 et l'en-tête du module")


if __name__ == '__main__':
    unittest.main()
