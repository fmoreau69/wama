"""
`get_item_result` — lire le CONTENU d'un résultat — et les `null` explicites à la porte des outils.

Fil Discord #43 (2026-10-12). L'utilisateur demande le texte d'un OCR terminé ; l'assistant n'a
que l'aperçu tronqué de `get_reader_status` et la face SORTIE de l'aperçu, vide pour une app
late-binding (le fichier n'existe qu'au téléchargement). Quatre tours plus tard il conclut qu'il
ne peut pas — et l'OCR, lui, avait en réalité rendu 0 caractère sur une erreur avalée
(`glm_ocr_backend`, gardé par `reader/tests_glm_ocr.py`). Les deux défauts se masquaient.

⚠ Identifiants en anglais ; commentaires et docstrings en français.
"""
from django.contrib.auth import get_user_model
from django.test import TestCase

from wama import tool_api as T


def _user(name):
    return get_user_model().objects.create_user(username=name, password='x')


def _reading(user, **fields):
    from wama.reader.models import ReadingItem
    values = {'input_file': 'users/0/temp/scan.jpg', 'original_filename': 'scan.jpg',
              'status': 'SUCCESS', 'progress': 100}
    values.update(fields)
    return ReadingItem.objects.create(user=user, **values)


class GetItemResultTest(TestCase):
    def setUp(self):
        self.me = _user('result_me')
        self.other = _user('result_other')

    def test_late_binding_result_is_rendered_like_the_download(self):
        item = _reading(self.me, result_text='Bonjour le monde')
        out = T.get_item_result(self.me, 'reader', item.pk)
        self.assertNotIn('error', out, out)
        self.assertIn('Bonjour le monde', out['text'])
        self.assertEqual(out['format'], 'txt')
        self.assertFalse(out['truncated'])

    def test_a_success_without_content_is_said_with_its_engine(self):
        """La card #1335 : SUCCESS, `result_text` vide, moteur `ollama:glm-ocr:latest`."""
        item = _reading(self.me, result_text='', used_backend='ollama:glm-ocr:latest')
        out = T.get_item_result(self.me, 'reader', item.pk)
        self.assertIn('aucun contenu', out['error'])
        self.assertIn('glm-ocr', out['error'])

    def test_another_users_item_is_refused(self):
        item = _reading(self.other, result_text='secret')
        out = T.get_item_result(self.me, 'reader', item.pk)
        self.assertEqual(out.get('error'), 'forbidden')
        self.assertNotIn('secret', str(out))

    def test_an_unfinished_item_names_its_status(self):
        item = _reading(self.me, status='RUNNING', progress=40, result_text='partiel')
        out = T.get_item_result(self.me, 'reader', item.pk)
        self.assertIn('RUNNING', out['error'])

    def test_a_binary_format_is_refused_with_the_text_formats(self):
        item = _reading(self.me, result_text='texte')
        out = T.get_item_result(self.me, 'reader', item.pk, output_format='pdf')
        self.assertIn('pdf', out['error'])
        self.assertIn('txt', out['error'])

    def test_a_long_result_is_cut_and_says_so(self):
        item = _reading(self.me, result_text='a' * (T.RESULT_TEXT_LIMIT + 50))
        out = T.get_item_result(self.me, 'reader', item.pk)
        self.assertTrue(out['truncated'])
        self.assertEqual(len(out['text']), T.RESULT_TEXT_LIMIT)
        self.assertGreater(out['total_chars'], T.RESULT_TEXT_LIMIT)

    def test_it_answers_through_the_real_door(self):
        item = _reading(self.me, result_text='par la porte')
        out = T.execute_tool('get_item_result', {'app': 'reader', 'pk': item.pk}, self.me)
        self.assertIn('par la porte', out.get('text', ''), out)


class NullArgumentsTakeTheDefaultTest(TestCase):
    """`add_to_reader(mode=None)` écrasait le défaut `'auto'` → `NOT NULL` en base."""

    def test_a_null_optional_argument_is_dropped(self):
        clean, ignored = T.sanitize_tool_args(
            'add_to_reader', {'file_path': 'users/1/temp/a.jpg', 'mode': None,
                              'backend': None, 'output_format': None})
        self.assertEqual(clean, {'file_path': 'users/1/temp/a.jpg'})
        self.assertEqual(ignored, [])

    def test_a_null_required_argument_is_kept_for_the_tool_to_refuse(self):
        """Contre-épreuve : un argument OBLIGATOIRE à `null` n'est pas effacé en silence."""
        clean, _ = T.sanitize_tool_args('add_to_reader', {'file_path': None})
        self.assertIn('file_path', clean)

    def test_a_real_value_is_never_dropped(self):
        clean, _ = T.sanitize_tool_args('add_to_reader', {'file_path': 'a.jpg', 'mode': ''})
        self.assertEqual(clean.get('mode'), '')
