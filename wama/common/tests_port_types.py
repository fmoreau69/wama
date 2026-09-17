"""Les DEUX vocabulaires de types, et l'accesseur unique de chacun (2026-09-16).

POURQUOI CE FICHIER. `DataType` est une classe de CONSTANTES : elle ne s'itère pas. Faute d'un
« rends-moi le vocabulaire », la même compréhension `{v for k, v in vars(DataType).items() …}`
avait été recopiée dans CINQ modules, et j'allais en écrire une sixième. Elle vit désormais dans
`data_types.known_types()`.

Et le vocabulaire admis au TYPE D'UN PORT est plus large que les seuls types de donnée : un port
nomme une DONNÉE, une NATURE média, ou une SAISIE (`app_registry.known_port_types()`). C'est le
couple (nature, rôle) du recadrage du 2026-08-30.

⚠ CES DEUX VOCABULAIRES NE SONT PAS LE MÊME, et ces gardes tiennent précisément la frontière :
un `signals[].data_type` de manifeste `dataset` et le nœud-source du studio restent en vocabulaire
DONNÉE SEUL — les élargir serait fusionner les deux taxonomies, ce que la route réserve à un geste
dédié (`WAMA_APP_GENERATION_ROUTE §S2bis.6bis`, item B).

Les tests de CONSOMMATEURS exercent le COMPORTEMENT (validateur, vues), jamais le texte du code :
un test qui lit la source atteste une forme, pas un comportement.
"""
import ast
import json
from pathlib import Path

from django.contrib.auth import get_user_model
from django.test import RequestFactory, SimpleTestCase, TestCase

from wama.common.app_registry import MEDIA_CATEGORIES, ROLE_TOKENS, known_port_types
from wama.common.catalog.data_types import DataType, known_types

#: Racines de NOTRE code (les venvs et les copies collectées n'ont rien à dire ici).
RACINES = ('wama', 'wama_data', 'wama_lab')


def _depot() -> Path:
    import wama
    return Path(wama.__file__).resolve().parent.parent


class AccesseurDesTypesDeDonneeTest(SimpleTestCase):

    def test_l_accesseur_rend_exactement_les_constantes_de_la_classe(self):
        attendu = {v for k, v in vars(DataType).items() if k.isupper() and isinstance(v, str)}
        self.assertEqual(known_types(), attendu)
        self.assertIn(DataType.TABLE, known_types())
        self.assertTrue(known_types(), 'vocabulaire vide → tout contrôle qui le lit serait muet')

    def test_les_deux_ecritures_qui_coexistaient_donnaient_le_MEME_ensemble(self):
        """La résorption des 5 copies ne devait RIEN changer : deux prédicats circulaient
        (`k.isupper()` et `not k.startswith('_')`). Ils coïncident tant que la classe ne porte
        que des constantes — ce test le tient, et cassera le jour où l'on y mettra autre chose."""
        isupper = {v for k, v in vars(DataType).items() if k.isupper() and isinstance(v, str)}
        sans_underscore = {v for k, v in vars(DataType).items()
                           if not k.startswith('_') and isinstance(v, str)}
        self.assertEqual(isupper, sans_underscore)

    def test_aucun_module_ne_REECRIT_la_comprehension(self):
        """La 6ᵉ copie ne doit pas naître. Garde par AST — un grep verrait aussi les
        commentaires et les docstrings, et la docstring de l'accesseur CITE la compréhension."""
        fautifs = []
        for racine in RACINES:
            for fichier in (_depot() / racine).rglob('*.py'):
                if fichier.name == 'data_types.py' or 'tests_port_types' in fichier.name:
                    continue
                try:
                    arbre = ast.parse(fichier.read_text(encoding='utf-8'))
                except (OSError, SyntaxError):
                    continue
                for noeud in ast.walk(arbre):
                    if not isinstance(noeud, ast.Call) or not isinstance(noeud.func, ast.Name):
                        continue
                    if noeud.func.id != 'vars' or not noeud.args:
                        continue
                    cible = noeud.args[0]
                    if isinstance(cible, ast.Name) and cible.id in ('DataType', 'DT'):
                        fautifs.append(f'{fichier.relative_to(_depot())}:{noeud.lineno}')
        self.assertEqual(fautifs, [],
                         'vocabulaire recopié au lieu de `data_types.known_types()` : '
                         + ', '.join(fautifs))


class VocabulaireDesPortsTest(SimpleTestCase):

    def test_il_reunit_les_trois_vocabulaires_et_rien_d_autre(self):
        self.assertEqual(known_port_types(),
                         set(MEDIA_CATEGORIES) | set(ROLE_TOKENS) | known_types())

    def test_une_nature_media_et_une_saisie_y_sont_admises(self):
        """Le cas qui a déclenché la correction : `studio.image_to_3d` attend une `image` ;
        et `studio_node_ports` pose des ports `prompt` que le canvas apparie déjà."""
        self.assertIn('image', known_port_types())
        self.assertIn('prompt', known_port_types())
        self.assertIn('3d', known_port_types())

    def test_il_n_admet_PAS_une_extension_de_fichier(self):
        """Une extension n'est pas une nature : `normalize_types` la TRADUIT, elle ne la
        laisse pas passer telle quelle."""
        for jeton in ('.png', 'png', '.mp4', 'wav'):
            self.assertNotIn(jeton, known_port_types())

    def test_les_deux_taxonomies_restent_d_intersection_VIDE(self):
        """Rien n'a été fusionné : c'est la promesse faite à `ROUTE §S2bis.6bis` (item B).
        Ce test ROUGIT le jour où quelqu'un ajoute `image` aux types de donnée (ou l'inverse)
        sans que la décision d'unifier ait été prise."""
        self.assertEqual(known_types() & set(MEDIA_CATEGORIES), set())


class ConsommateursEnVocabulaireDONNEE_SEUL_Test(TestCase):
    """Les consommateurs qui parlent DONNÉE ne doivent PAS avoir été élargis au passage."""

    def test_le_manifeste_dataset_accepte_un_type_de_donnee(self):
        from wama.common.manifests.builtin.dataset import validate_dataset_body
        errs = validate_dataset_body({'source': {'ref': 'corpus/x'},
                                      'signals': [{'id': 's1', 'data_type': 'timeseries'}]})
        self.assertEqual([e for e in errs if 'taxonomie' in e], [])

    def test_le_manifeste_dataset_refuse_un_type_inconnu_ET_une_nature_media(self):
        from wama.common.manifests.builtin.dataset import validate_dataset_body
        for valeur in ('inexistant', 'image'):
            errs = validate_dataset_body({'source': {'ref': 'corpus/x'},
                                          'signals': [{'id': 's1', 'data_type': valeur}]})
            self.assertTrue([e for e in errs if 'hors taxonomie' in e],
                            f"'{valeur}' devrait être refusé aux signaux d'un dataset")

    def test_le_studio_sert_au_canvas_la_taxonomie_DONNEE(self):
        """`/studio/api/nodes/` alimente le sélecteur du nœud « Jeu de données ». Le JS ne
        recopie jamais cette liste (`wama-studio.js::installDatasetSource`) : elle vient d'ici."""
        from wama.studio.views import api_nodes
        requete = RequestFactory().get('/studio/api/nodes/')
        requete.user = get_user_model().objects.create_user('ports-taxonomie', password='x')
        contenu = json.loads(api_nodes(requete).content)
        self.assertEqual(contenu['data_types'], sorted(known_types()))
        self.assertNotIn('image', contenu['data_types'])
