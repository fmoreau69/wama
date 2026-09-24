"""Tests du reader — nés du portage de la modale ⚙ sur le cycle commun (2026-09-24).

Le fichier n'existait pas : le reader était couvert par la grille (adoption), les scénarios
nocturnes (gestes) et ses tests de moteur (`tests_glm_ocr`, `tests_table_transformer`), jamais
par un test de comportement de vue. La vue d'enregistrement des réglages d'un élément a DEUX
appelants aux formes différentes — l'inspecteur poste du JSON, la modale ⚙ commune poste un
FormData — et c'est exactement le genre d'écart qu'un scénario navigateur ne voit que sur l'un
des deux chemins.
"""
import json

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse


class ItemSettingsViewTest(TestCase):
    """`update_settings` lit les DEUX formes par le lecteur commun `read_settings_payload`."""

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

    def test_the_settings_modal_form_data_is_written_like_the_inspector_json(self):
        r = self.client.post(self.url, {'backend': 'doctr', 'mode': 'printed',
                                        'output_format': 'markdown', 'language': 'en'})
        self.assertEqual(r.status_code, 200, r.content)
        self.item.refresh_from_db()
        self.assertEqual((self.item.backend, self.item.mode, self.item.output_format, self.item.language),
                         ('doctr', 'printed', 'markdown', 'en'))
        self.assertEqual(r.json()['id'], self.item.id, 'la réponse est la card à jour')

        r = self.client.post(self.url, data=json.dumps({'mode': 'handwritten'}),
                             content_type='application/json')
        self.assertEqual(r.status_code, 200, r.content)
        self.item.refresh_from_db()
        self.assertEqual((self.item.mode, self.item.backend), ('handwritten', 'doctr'),
                         'le JSON de l’inspecteur ne touche que ce qu’il poste')

    def test_an_empty_language_means_auto_detection_and_is_written(self):
        """`language` vide EST une valeur (auto-détection, leçon du 17/08) — un FormData de
        modale le poste vide, et il doit ÉCRASER la langue posée."""
        r = self.client.post(self.url, {'backend': 'auto', 'language': ''})
        self.assertEqual(r.status_code, 200, r.content)
        self.item.refresh_from_db()
        self.assertEqual(self.item.language, '')

    def test_a_value_outside_the_model_choices_is_ignored_not_written(self):
        r = self.client.post(self.url, {'backend': 'not-an-engine'})
        self.assertEqual(r.status_code, 200, r.content)
        self.item.refresh_from_db()
        self.assertEqual(self.item.backend, 'auto')
