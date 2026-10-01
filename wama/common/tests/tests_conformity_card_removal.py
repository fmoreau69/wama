"""Le critère de grille du RETRAIT d'une card suit la règle qu'il mesure (2026-10-01).

Depuis la décision D34 de `MEDIA_STORAGE_TIERING`, retirer une card LIBÈRE ses fichiers ;
`safe_delete_file` est réservé à la relance. Le critère cherchait encore `safe_delete_file` dans
les vues : cinq apps alignées étaient rouges, deux vertes par un commentaire. Depuis D35
(2026-10-02) le retrait se fait à l'échelle de la CARD (`release_card_files`) : le verbe champ
par champ seul est un PARTIEL. Mesuré ici sur des apps FICTIVES — l'état réel du parc se lit par
`check_app_conformity`.
"""
from django.test import SimpleTestCase

from wama.common.tests import tests_queue_delete_contract as contract


class CardRemovalCriterionTest(SimpleTestCase):

    _app = contract.CriteresDeLaGrilleTest._app

    def _verdict(self, views):
        f, cc = self._app({'views.py': views})
        criterion = next(c for c in cc.CRITERIA if c.key == 'release_card_file')
        return criterion.fn(f)

    def test_a_removal_at_card_level_is_green(self):
        state, evidence = self._verdict("release_card_files(item)\nitem.delete()\n")
        self.assertIs(state, True)
        self.assertIn('views.py:1', evidence)

    def test_a_field_by_field_removal_is_partial(self):
        state, evidence = self._verdict("release_card_file(item, 'input_file')\nitem.delete()\n")
        self.assertEqual(state, 'partial')
        self.assertIn('champ par champ', evidence)

    def test_one_field_released_beside_the_card_level_verb_stays_green(self):
        """Le verbe d'un champ garde son usage (remplacer une référence) : à côté du verbe de
        card, il ne rétrograde rien."""
        state, _evidence = self._verdict("release_card_file(item, 'voice_reference')\n"
                                         "release_card_files(item)\nitem.delete()\n")
        self.assertIs(state, True)

    def test_the_relaunch_verb_alone_is_red_and_says_why(self):
        """Contre-épreuve : c'est la forme que l'ancien critère tenait pour VERTE."""
        state, evidence = self._verdict("safe_delete_file(item, 'output_file')\nitem.delete()\n")
        self.assertIs(state, False)
        self.assertIn('relance', evidence)

    def test_a_comment_naming_the_brick_does_not_make_it_green(self):
        state, _evidence = self._verdict("# release_card_files(item)\n"
                                         "item.input_file.delete(save=False)\nitem.delete()\n")
        self.assertIs(state, False)

    def test_the_old_key_is_gone(self):
        from wama.common.services import conformity_checker as cc
        self.assertNotIn('safe_delete', [c.key for c in cc.CRITERIA])
