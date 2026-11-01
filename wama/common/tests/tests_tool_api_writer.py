"""The Writer sandbox (`writer_01`, born from scratch) is reachable from the assistant:
`add_to_writer_01` creates the element like a card deposit, and the declarative triad gives
`start_writer_01` / `get_writer_01_status` (read by `get_item_result` once it is done)."""
from django.contrib.auth.models import User
from django.test import TestCase

from wama import tool_api


class WriterToolsTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('writer_tool_user', password='x')

    def test_the_three_tools_are_registered(self):
        for name in ('add_to_writer_01', 'start_writer_01', 'get_writer_01_status'):
            self.assertIn(name, tool_api.TOOL_REGISTRY)

    def test_a_prompt_alone_creates_a_pending_document_in_a_batch(self):
        from wama.writer_01.models import WriterBatchItem, WriterDocument
        out = tool_api.add_to_writer_01(self.user, prompt='  Présenter le projet  ',
                                        document_kind='report', language='en')
        self.assertNotIn('error', out)
        doc = WriterDocument.objects.get(pk=out['item_id'])
        self.assertEqual(('Présenter le projet', 'report', 'en', 'PENDING'),
                         (doc.prompt, doc.document_kind, doc.language, doc.status))
        self.assertTrue(WriterBatchItem.objects.filter(document=doc).exists())

    def test_a_cv_is_a_document_kind_and_says_its_label_to_the_model(self):
        """2026-11-01 (Fabien) : « générer des types CV ». Le modèle reçoit le LIBELLÉ du type
        (`get_document_kind_display`, lu par les deux process), pas sa clé."""
        from wama.writer_01.models import WriterDocument
        from wama.writer_01.params import PARAMS_JSON
        out = tool_api.add_to_writer_01(self.user, prompt='Mon parcours', document_kind='cv')
        doc = WriterDocument.objects.get(pk=out['item_id'])
        self.assertEqual(('cv', 'CV'), (doc.document_kind, doc.get_document_kind_display()))
        field, = [f for f in PARAMS_JSON if f['name'] == 'document_kind']
        self.assertIn(['cv', 'CV'], field['choices'], "le panneau et la modale le proposent")

    def test_nothing_to_write_is_refused(self):
        self.assertIn('error', tool_api.add_to_writer_01(self.user, prompt='   '))

    def test_an_unknown_reference_path_is_refused_and_creates_nothing(self):
        from wama.writer_01.models import WriterDocument
        out = tool_api.add_to_writer_01(self.user, prompt='x',
                                        reference_document='users/999/nope.pdf')
        self.assertIn('error', out)
        self.assertEqual(0, WriterDocument.objects.count())

    def test_the_status_row_follows_the_element(self):
        out = tool_api.add_to_writer_01(self.user, prompt='x')
        rows = tool_api.get_writer_01_status(self.user)['jobs']
        self.assertEqual([out['item_id']], [r['id'] for r in rows])
        self.assertEqual('PENDING', rows[0]['status'])
        self.assertIsNone(rows[0]['output_url'])

    def test_another_users_element_is_not_started(self):
        other = User.objects.create_user('writer_tool_other', password='x')
        out = tool_api.add_to_writer_01(other, prompt='x')
        res = tool_api.start_writer_01(self.user, document_id=out['item_id'])
        self.assertIn('error', res)
