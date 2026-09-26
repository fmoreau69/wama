"""Tests du reader — ce qui lui est PROPRE.

Le contrat de la route de réglages d'un élément (FormData de la modale ⚙ ET JSON de
l'inspecteur écrits, rien de touché qui n'est pas posté, valeur hors choix ignorée) est tenu
pour TOUTES les apps par `wama/common/tests_item_settings_contract.py` depuis le 2026-09-26 : les
deux tests qui le vérifiaient ici pour le seul reader en sont retirés. Reste la spécificité du
reader : `language` vide EST une valeur (auto-détection).
"""
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse


class ItemSettingsViewTest(TestCase):

    def setUp(self):
        from django.contrib.auth.models import Group
        from wama.accounts.permissions import GROUP_PREFIX
        from wama.reader.models import ReadingItem
        self.user = get_user_model().objects.create_user('reader_settings_test', password='x')
        # Le portier `AppAccessMiddleware` doit être FRANCHI, pas contourné (leçon synthesizer,
        # /reprise §3a) : le reader est ouvert au rôle `recherche` (matrice d'accès).
        group, _ = Group.objects.get_or_create(name=f'{GROUP_PREFIX}recherche')
        self.user.groups.add(group)
        self.client.force_login(self.user)
        self.item = ReadingItem.objects.create(user=self.user, original_filename='a.pdf',
                                               language='fr')
        self.url = reverse('reader:update_settings', args=[self.item.id])

    def test_an_empty_language_means_auto_detection_and_is_written(self):
        """`language` vide EST une valeur (auto-détection, leçon du 17/08) — un FormData de
        modale le poste vide, et il doit ÉCRASER la langue posée."""
        r = self.client.post(self.url, {'backend': 'auto', 'language': ''})
        self.assertEqual(r.status_code, 200, r.content)
        self.item.refresh_from_db()
        self.assertEqual(self.item.language, '')
