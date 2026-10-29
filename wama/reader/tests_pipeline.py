"""The reader card carries a PIPELINE — `WAMA_APP_GENERATION_ROUTE §10.6`, decision of Fabien
(2026-10-13): « every application must work as a pipeline ». Until then its task read the
document then formatted it with an LLM whose failure was SWALLOWED (the raw text returned under a
« done » card, without a word), and its analysis lived in a separate task nothing called.

What is held here, and why each point:

  * three processes — read, format (optional, ON by default: it always happened), analyze
    (optional) ;
  * a failed formatting shows on ITS line, the read text stays and the card is a success ;
  * changing the language model does not read the document again (olmOCR: ~10 min to load) ;
  * the native text of a digital PDF is kept as is, as before ;
  * the launcher no longer erases what the processes rendered ; the analysis « on demand » is
    the ▶ of its process ;
  * the language model a card designates is read by ONE common brick (`llm_utils.card_llm`).
"""
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import Client, SimpleTestCase, TestCase
from django.urls import reverse

from wama.common.models import JOB_FAILURE, JOB_SUCCESS
from wama.common.services import process_runs
from wama.reader import tasks
from wama.reader.function_specs import PIPELINE
from wama.reader.models import ReadingItem
from wama.reader.tests_model_keys import _FakeOCR


class _Cards(TestCase):

    def setUp(self):
        self.user = get_user_model().objects.create_user('reader_pipeline', password='x')
        self.engine_runs, self.formats, self.analyses = 0, [], []
        self.format_error = None

    def _card(self, name='scan.png', **fields):
        fields.setdefault('backend', 'reader:doctr')
        fields.setdefault('status', 'RUNNING')
        return ReadingItem.objects.create(user=self.user, input_file=f'reader/x/input/{name}',
                                          original_filename=name, **fields)

    # ── stand-ins ──────────────────────────────────────────────────────────────────────────
    def _engine(self, key, user=None):
        self.engine_runs += 1
        return _FakeOCR()

    def _chat(self, messages, **kwargs):
        if self.format_error:
            return None, self.format_error
        self.formats.append((messages[-1]['content'], kwargs.get('model'), kwargs.get('provider')))
        return '# Extracted', None

    def _summary(self, text, **kwargs):
        self.analyses.append((text, kwargs.get('model'), kwargs.get('provider')))
        return {'summary': 'A scan.', 'key_points': ['one'], 'action_items': []}

    def _run(self, card, process=None, native=None):
        ReadingItem.objects.filter(pk=card.pk).update(status='RUNNING')
        with mock.patch('wama.common.backends.manager.backend_instance_for_key',
                        side_effect=self._engine), \
                mock.patch('wama.common.backends.ocr_base.upright_image',
                           side_effect=lambda path, folder: path, create=True), \
                mock.patch.object(tasks, '_try_direct_extraction', return_value=native or ''), \
                mock.patch.object(tasks, '_count_pdf_pages', return_value=1), \
                mock.patch('wama.common.utils.llm_utils.get_describer_model',
                           return_value='tier-llm'), \
                mock.patch('wama.common.utils.llm_utils.llm_chat', side_effect=self._chat), \
                mock.patch('wama.common.utils.llm_utils.generate_structured_summary',
                           side_effect=self._summary), \
                mock.patch('wama.common.utils.preview_utils.publish_partial_text'), \
                mock.patch('wama.common.utils.task_skeleton.close_old_connections'):
            tasks.read_document_task.run(card.pk, process)
        card.refresh_from_db()
        return card

    def _states(self, card):
        return {row.node_id: row.status for row in process_runs.lines(card)}


class ProcessesTest(_Cards):

    def _keys(self, card):
        return [s.key for s in PIPELINE.applicable(card, PIPELINE.requested_model(card))]

    def test_a_card_reads_then_formats_and_analyses_when_asked(self):
        self.assertEqual(['read', 'format'], self._keys(self._card()))
        self.assertEqual(['read', 'format', 'analyze'],
                         self._keys(self._card(generate_analysis=True)))
        self.assertEqual(['read'], self._keys(self._card(format_markdown=False)))


class ReadingRunTest(_Cards):

    def test_each_process_has_its_line_and_the_read_text_is_kept_raw(self):
        card = self._run(self._card(generate_analysis=True))
        self.assertEqual('SUCCESS', card.status)
        self.assertEqual({'read': JOB_SUCCESS, 'format': JOB_SUCCESS, 'analyze': JOB_SUCCESS},
                         self._states(card))
        self.assertEqual(('extracted text', '# Extracted'), (card.raw_result, card.result_text))
        self.assertEqual('extracted text', self.formats[0][0], 'the READ text is formatted')
        self.assertEqual('# Extracted', self.analyses[0][0], 'the analysis reads the final text')
        self.assertIn('A scan.', card.analysis)

    def test_a_reading_cut_at_its_first_pass_shows_a_badge_until_a_clean_reading(self):
        """2026-10-29, decision of Fabien: the engine cut a looping reading at its first pass —
        the card SAYS it next to the word count (the cut can be wrong both ways). Checked on the
        SERVED page, and a later clean reading takes the badge away."""
        cut = _FakeOCR()
        cut.cut_pages = [2]
        self._engine = lambda key, user=None: cut
        card = self._run(self._card())
        notices = process_runs.line(card, 'read').output_summary.get('notices')
        self.assertEqual(['ocr_loop_cut'], [n['key'] for n in notices])
        self.assertIn('(page 2)', notices[0]['title'])
        # The access gate is CROSSED, not bypassed (`AppAccessMiddleware`, lesson of the
        # synthesizer): the reader is open to the `recherche` role.
        from django.contrib.auth.models import Group
        from wama.accounts.permissions import GROUP_PREFIX
        self.user.groups.add(Group.objects.get_or_create(name=f'{GROUP_PREFIX}recherche')[0])
        client = Client()
        client.force_login(self.user)
        served = client.get(reverse('reader:index'))
        self.assertEqual(200, served.status_code)
        page = served.content.decode()
        self.assertIn('wama-chip--warning', page)
        self.assertIn('Lecture coupée', page)

        self._engine = lambda key, user=None: _FakeOCR()
        card = self._run(card)
        self.assertEqual([], process_runs.line(card, 'read').output_summary.get('notices'))
        self.assertNotIn('Lecture coupée', client.get(reverse('reader:index')).content.decode())

    def test_a_failed_formatting_shows_on_its_line_and_keeps_the_read_text(self):
        self.format_error = 'Ollama is down'
        card = self._run(self._card())
        self.assertEqual('SUCCESS', card.status)
        self.assertEqual(JOB_FAILURE, self._states(card)['format'])
        self.assertEqual('extracted text', card.result_text)

    def test_changing_the_language_model_does_not_read_the_document_again(self):
        card = self._run(self._card(generate_analysis=True))
        ReadingItem.objects.filter(pk=card.pk).update(llm_model='ollama:qwen3.8:latest')
        card.refresh_from_db()
        self.assertEqual({'format', 'analyze'}, PIPELINE.refresh(card))
        self._run(card)
        self.assertEqual(1, self.engine_runs, 'the document was read once')
        self.assertEqual(('qwen3.8:latest', 'ollama'), self.formats[-1][1:])
        self.assertEqual(('qwen3.8:latest', 'ollama'), self.analyses[-1][1:])

    def test_the_native_text_of_a_digital_pdf_is_kept_as_is(self):
        card = self._run(self._card('doc.pdf'), native='Native text.')
        self.assertEqual(('fitz_direct', 'Native text.'), (card.used_backend, card.result_text))
        self.assertEqual((0, []), (self.engine_runs, self.formats))

    def test_the_analysis_replayed_alone_keeps_the_text(self):
        card = self._run(self._card(generate_analysis=True))
        card = self._run(card, process='analyze')
        self.assertEqual((1, 1, 2), (self.engine_runs, len(self.formats), len(self.analyses)))
        self.assertEqual('# Extracted', card.result_text)


class ViewsTest(_Cards):

    def setUp(self):
        super().setUp()
        from django.contrib.auth.models import Group

        from wama.accounts.permissions import GROUP_PREFIX
        for role in ('communication', 'recherche'):     # the profiles that open the reader
            self.user.groups.add(Group.objects.get_or_create(name=f'{GROUP_PREFIX}{role}')[0])
        self.client = Client(HTTP_HOST='localhost')
        self.client.force_login(self.user)

    def test_the_launcher_no_longer_erases_what_the_processes_rendered(self):
        from wama.reader.views import _reset_for_relaunch
        card = self._run(self._card(generate_analysis=True))
        _reset_for_relaunch(card)
        self.assertTrue(card.result_text and card.raw_result and card.analysis)

    def test_the_analysis_on_demand_is_the_play_of_its_process(self):
        card = self._run(self._card())
        ReadingItem.objects.filter(pk=card.pk).update(status='SUCCESS')
        with mock.patch.object(tasks.read_document_task, 'apply_async',
                               return_value=mock.Mock(id='t-1')) as launch:
            response = self.client.post(reverse('reader:analyze', args=[card.pk]))
        self.assertEqual(200, response.status_code, response.content)
        self.assertEqual({'process': 'analyze'}, launch.call_args.kwargs['kwargs'])
        card.refresh_from_db()
        self.assertTrue(card.generate_analysis)
        self.assertEqual('# Extracted', card.result_text, 'the text is kept')

    def test_a_switched_off_analysis_is_not_served(self):
        card = self._run(self._card(generate_analysis=True))
        ReadingItem.objects.filter(pk=card.pk).update(generate_analysis=False)
        data = self.client.get(reverse('reader:progress', args=[card.pk])).json()
        self.assertEqual('', data['analysis'])
        self.assertIn('processes', data, 'the strip of processes follows the treatment')


class CardLanguageModelTest(SimpleTestCase):
    """The common reading of a card's `llm_model` select — the describer and the reader."""

    def test_auto_keeps_the_app_behaviour_and_a_key_designates_a_local_model(self):
        from wama.common.utils.llm_utils import card_llm
        self.assertEqual(('tier', None), card_llm('auto', auto=lambda: 'tier'))
        self.assertEqual(('', None), card_llm('auto'))
        self.assertEqual(('gemma4:12b', 'ollama'), card_llm('ollama:gemma4:12b'))

    def test_a_remote_model_is_refused_rather_than_called_with_the_instance_key(self):
        from wama.common.utils.llm_utils import card_llm
        with self.assertRaises(ValueError):
            card_llm('albert:gpt-oss-120b', owner='le Reader')
