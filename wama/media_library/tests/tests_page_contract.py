"""La page médiathèque DÉRIVE ses onglets des natures et offre le menu contextuel COMMUN (2026-09-29).

  • Les icônes d'onglets étaient écrites dans le gabarit, nature par nature : « Parole
    enregistrée » et « Objet 3D » s'affichaient sans icône. Elles viennent désormais de la
    déclaration (`natures.py`) — une nature ajoutée a son onglet complet sans toucher la page.
  • Le clic droit ouvre `WamaCardMenu` avec les entrées lues sur la rangée de la card
    (`btn-group-actions`, contrat des cards de file) : aucune liste d'entrées propre à la page.
"""
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from wama.media_library.natures import ASSET_NATURES


class MediaLibraryPageContractTest(TestCase):

    def test_every_declared_nature_has_its_tab_with_its_icon(self):
        user = get_user_model().objects.create_user('page_contract', password='x')
        self.client.force_login(user)
        page = self.client.get(reverse('media_library:index')).content.decode('utf-8')
        for key, nature in ASSET_NATURES.items():
            with self.subTest(nature=key):
                self.assertIn(f'data-type="{key}"', page)
                tab = page.split(f'data-type="{key}"', 1)[1].split('</a>', 1)[0]
                self.assertIn(nature.icon, tab, f'onglet {key} sans son icône déclarée')

    def test_the_page_adds_through_the_common_input_card(self):
        """La zone « Ajouter » propre est remplacée par la card d'entrée commune ; la page n'a pas
        de volet (`VOLET_AUCUN`), la card n'y renvoie donc pas au « volet de droite »."""
        user = get_user_model().objects.create_user('page_card', password='x')
        self.client.force_login(user)
        page = self.client.get(reverse('media_library:index')).content.decode('utf-8')
        self.assertIn('id="mlNewItem"', page)
        self.assertIn('id="mlDropZone"', page)
        self.assertNotIn('id="uploadZoneWrap"', page)
        self.assertNotIn('Réglages : volet de droite', page)

    def test_the_asset_card_uses_the_common_action_row_and_menu(self):
        js = (Path(settings.BASE_DIR) / 'wama' / 'media_library' / 'static' / 'media_library'
              / 'js' / 'media-library.js').read_text(encoding='utf-8')
        self.assertIn('card-actions-overlay btn-group-actions', js)
        self.assertIn('WamaCardMenu.entreesCompletes(card, [card])', js)
