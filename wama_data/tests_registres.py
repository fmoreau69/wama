"""Tests des CAPACITÉS AGRÉGATIVES du monde Data au registre des registres.

Doctrine : `WAMA_DATA_WORLD.md §9quinquies` — la MÉTHODE (importer, exporter) est universelle et
s'écrit une fois ; les TYPES qu'elle sait traiter s'AGRÈGENT, comme on ajoute un modèle IA.

⚠ Ce fichier existe surtout pour le RAFRAÎCHISSEUR DES LECTEURS, qui a trois pièges connus et dont
la première version — écrite puis jetée le 2026-08-23 — les avait tous les trois. Un `reload` du
paquet `sources` **vide le registre** au lieu de le recharger : `_register_builtins()` repeuple via
`from . import trip, tabular`, or ces modules sont déjà en cache, donc l'import est un no-op.
Le test `test_le_rafraichissement_ne_VIDE_pas_le_registre` est là pour ça, et rien d'autre.
"""
import unittest

from wama.common.registries import REGISTRES, etat


class DeclarationTest(unittest.TestCase):
    """Le monde POUSSE ses registres vers le substrat ; le substrat ne tire jamais."""

    def test_les_deux_registres_du_monde_sont_declares(self):
        for cle in ('lecteurs_data', 'formats_export_data'):
            self.assertIn(cle, REGISTRES, f"{cle} absent du registre des registres")

    def test_le_substrat_n_IMPORTE_aucun_monde(self):
        """Les inscrire dans `common/registries_builtin.py` ferait dépendre le substrat du monde —
        le défaut corrigé lors du déport, réintroduit par la porte d'à côté.

        ⚠ L'invariant est l'ABSENCE D'IMPORT, pas l'absence du mot. Première version de ce test :
        elle interdisait la chaîne `wama_data` et échouait sur une PROSE — `source="apps.py:ready()`
        de chaque monde — `wama_data`, `wama_lab.cam_analyzer`…"`, qui est de la documentation et
        ne crée aucune dépendance. Un test qui vérifie un PROXY au lieu de la PROPRIÉTÉ échoue sur
        du correct, et c'est la même erreur que « prendre une trace pour une règle ».
        """
        import ast
        import inspect

        from wama.common import registries_builtin
        arbre = ast.parse(inspect.getsource(registries_builtin))
        importes = set()
        for n in ast.walk(arbre):
            if isinstance(n, ast.Import):
                importes.update(a.name for a in n.names)
            elif isinstance(n, ast.ImportFrom) and n.module:
                importes.add(n.module)
        mondes = [m for m in importes if m.split('.')[0] in ('wama_data', 'wama_lab')]
        self.assertEqual(mondes, [], f"le substrat importe un monde : {mondes}")

    def test_le_registre_des_lecteurs_pointe_le_kind_dataset(self):
        self.assertEqual(REGISTRES['lecteurs_data'].manifest_kind, 'dataset')

    def test_les_formats_de_sortie_ne_pointent_AUCUN_kind(self):
        # Et c'est juste : 3 des 7 pages catalogue ne correspondent à aucun kind (relevé du
        # 22/08 en tête de `registries.py`). `manifest_kind` est un LIEN facultatif, pas la clé.
        self.assertEqual(REGISTRES['formats_export_data'].manifest_kind, '')


class ComptageTest(unittest.TestCase):

    def test_les_lecteurs_sont_comptes(self):
        from .sources import READERS
        self.assertEqual(REGISTRES['lecteurs_data'].compter(), len(READERS))
        self.assertGreaterEqual(len(READERS), 2)      # trip + tabular

    def test_les_formats_sont_comptes(self):
        from .core.export import FORMATS
        self.assertEqual(REGISTRES['formats_export_data'].compter(), len(FORMATS))

    def test_l_etat_general_les_expose(self):
        cles = {e['cle'] for e in etat()}
        self.assertIn('lecteurs_data', cles)
        self.assertIn('formats_export_data', cles)


class RafraichissementLecteursTest(unittest.TestCase):
    """Le piège central : recharger sans vider."""

    def test_le_rafraichissement_ne_VIDE_pas_le_registre(self):
        # ⚠ LE test de ce fichier. Un `importlib.reload(sources)` naïf rendrait 0 lecteur, et le
        # compte-rendu annoncerait fièrement « ok ».
        from .sources import READERS
        avant = set(READERS)
        res = REGISTRES['lecteurs_data'].rafraichir()
        self.assertTrue(res.ok, res.messages)
        self.assertEqual(set(READERS), avant, "des lecteurs ont disparu au rechargement")
        self.assertGreaterEqual(res.total, 2)

    def test_deux_passages_donnent_le_MEME_etat(self):
        # Idempotence : c'est le contrôle générique des catalogues, et il a déjà attrapé un
        # rafraîchisseur qui annonçait « 10 retirés » à chaque passage sans que rien ne disparaisse.
        from .sources import READERS
        REGISTRES['lecteurs_data'].rafraichir()
        premier = set(READERS)
        deuxieme = REGISTRES['lecteurs_data'].rafraichir()
        self.assertEqual(set(READERS), premier)
        self.assertEqual(deuxieme.ajoutes, 0)
        self.assertEqual(deuxieme.retires, 0)

    def test_les_lecteurs_restent_FONCTIONNELS_apres_rechargement(self):
        # Recharger des modules recrée les classes : un registre repeuplé d'objets cassés
        # passerait le comptage et échouerait au premier import réel.
        REGISTRES['lecteurs_data'].rafraichir()
        from .sources import supported_extensions
        self.assertIn('.trip', supported_extensions())


class RafraichissementFormatsTest(unittest.TestCase):

    def test_le_rafraichissement_ne_perd_PAS_les_formats_natifs(self):
        # Purger ici perdrait les formats du cœur, que rien ne réenregistrerait — d'où l'absence
        # volontaire de purge (`enregistrer_format` est idempotent, `register_reader` non).
        from .core.export import FORMATS
        avant = set(FORMATS)
        res = REGISTRES['formats_export_data'].rafraichir()
        self.assertTrue(res.ok, res.messages)
        self.assertEqual(set(FORMATS), avant)

    def test_le_compte_rendu_dit_la_DETTE(self):
        res = REGISTRES['formats_export_data'].rafraichir()
        # « n/m format(s) réellement écrivable(s) » — l'écart déclaré/écrivable est la dette.
        self.assertTrue(any('écrivable' in m for m in res.messages), res.messages)


if __name__ == '__main__':
    unittest.main()
