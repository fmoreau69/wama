"""The Reader reads a printed SCORE (2026-11-08, Fabien : « l'utilisateur scanne une partition, la
partition est rendue typographiée et éditable » ; « une détection automatique avec switch
automatique, mais qui peut rester un choix de l'utilisateur »).

Guarded here, without the GPU nor the weights :
  • the page is told a score by its STAVES (`score_page`), proposed to the « Lire une partition »
    switch by the file (`Param.default_from`, property `has_staves`) ;
  • the pipeline : `read_score` takes place under the switch when a score reader is installed, and
    then the text reading and its two follow-ups do not ;
  • the glue writes the engine's MusicXML and its ABC on the card ;
  • the setting columns, downloads, edit pages and assistant tool follow.
"""
import shutil
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase, override_settings

from wama.common.tests.tests_score_input import MUSICXML_CDEF


def _page(staves: int = 0, text_rows: int = 0, rules: int = 0, size=(1200, 1600)):
    """A white page (grey array) with `staves` staves of five lines, `text_rows` rows of sparse ink
    (like text), and `rules` full-width rules spaced like a table's."""
    import numpy as np
    width, height = size
    page = np.full((height, width), 255, dtype=np.uint8)
    y = 100
    for _ in range(staves):
        for line in range(5):
            page[y + line * 12: y + line * 12 + 2, 100:1100] = 0
        y += 200
    for row in range(text_rows):
        page[y + row * 30: y + row * 30 + 12, 100:1100:9] = 0       # ink on one column in nine
    y += text_rows * 30 + 50
    for rule in range(rules):
        page[y + rule * 60: y + rule * 60 + 2, 50:1150] = 0
    return page


def _png(folder: Path, name: str, page) -> Path:
    from PIL import Image
    path = folder / name
    Image.fromarray(page).save(path)
    return path


class TheStavesTellAScorePageTest(SimpleTestCase):

    def test_staves_are_counted_and_text_or_table_rules_are_not(self):
        from wama.common.utils.score_page import count_staves
        self.assertEqual(1, count_staves(_page(staves=1)))
        self.assertEqual(3, count_staves(_page(staves=3, text_rows=4)))
        self.assertEqual(0, count_staves(_page(text_rows=20)), 'text rows ink a small part')
        self.assertEqual(0, count_staves(_page(rules=6)), 'table rules are too far apart')

    def test_the_property_proposes_the_switch_with_its_reason(self):
        from wama.common.utils.media_probe import input_property, probe_media
        with tempfile.TemporaryDirectory() as tmp:
            score = _png(Path(tmp), 'score.png', _page(staves=2))
            text = _png(Path(tmp), 'text.png', _page(text_rows=12))
            yes = input_property(probe_media(str(score)), 'has_staves', str(score))
            no = input_property(probe_media(str(text)), 'has_staves', str(text))
        self.assertEqual((True, '2 portées'), (yes['value'], yes['note'][:9]))
        self.assertIs(False, no['value'])
        self.assertIsNone(input_property({'media_type': 'audio'}, 'has_staves', '/x.wav'))
        self.assertIsNone(input_property({'media_type': 'image'}, 'has_staves'),
                          'the property reads the file : no path, no proposal')

    #: The work port as production derives it (`file_ports_for('reader', 'image')`, measured
    #: 2026-11-08) : the ports come from the catalogue's models, which the test base lacks — it
    #: falls back on a port named `work` (the anonymizer's `DocumentBirthTest` does the same).
    WORK_PORT = [{'id': 'work_file', 'group': 'travail', 'types': ['document', 'image']}]

    def test_a_dropped_score_ticks_the_reader_switch(self):
        from wama.common.utils.user_settings import input_proposals, inputs_by_port
        from wama.reader.params import PARAMS
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch('wama.common.app_registry.file_ports_for', return_value=self.WORK_PORT):
            score = _png(Path(tmp), 'score.png', _page(staves=1))
            proposals = input_proposals(PARAMS, inputs_by_port('reader', str(score)))
        self.assertIs(True, proposals['read_as_score']['value'])


class TheScoreReadingTakesTheTextPlaceTest(SimpleTestCase):

    def _places(self, read_as_score, installed=True):
        from wama.reader.function_specs import PIPELINE
        item = SimpleNamespace(read_as_score=read_as_score, format_markdown=True,
                               generate_analysis=True, backend='auto', score_model='auto')
        with mock.patch('wama.common.utils.auto_model.task_installed', return_value=installed):
            return {spec.key for spec in PIPELINE.specs if PIPELINE.takes_place(spec, item, 'auto')}

    def test_the_switch_puts_the_score_reading_in_place_of_the_text(self):
        self.assertEqual({'read_score'}, self._places(True))
        self.assertEqual({'read', 'format', 'analyze'}, self._places(False))

    def test_without_a_score_reader_installed_the_text_is_read(self):
        self.assertEqual({'read', 'format', 'analyze'}, self._places(True, installed=False))


class TheGlueWritesTheScoreOnTheCardTest(TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='reader_score_'))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        media = override_settings(MEDIA_ROOT=str(self.tmp))
        media.enable()
        self.addCleanup(media.disable)
        self.user = get_user_model().objects.create_user('reader_score', password='x')

    def test_the_musicxml_and_its_abc_are_the_card_outputs(self):
        from wama.reader import tasks
        from wama.reader.models import ReadingItem
        page = _png(self.tmp, 'page.png', _page(staves=1))
        item = ReadingItem.objects.create(user=self.user, input_file='page.png',
                                          read_as_score=True)
        places = []

        def output_place(ext, nature='', model=''):
            rel = f'out/{len(places)}{ext}'
            places.append((ext, nature, model))
            (self.tmp / 'out').mkdir(exist_ok=True)
            return rel, str(self.tmp / rel)
        ctx = SimpleNamespace(console=lambda *a: None, progress=lambda *a, **k: None,
                              ensure_model=mock.Mock(), output_place=output_place)
        calls = {}

        def run_contract(engine, **values):
            calls.update(values)
            return MUSICXML_CDEF
        with mock.patch('wama.common.utils.auto_model.model_for_task',
                        return_value='huggingface:kobimusic/copisteria'), \
                mock.patch('wama.common.backends.manager.backend_instance_for_key',
                           return_value=object()), \
                mock.patch('wama.common.backends.manager.run_contract', side_effect=run_contract), \
                mock.patch('wama.common.backends.ocr_base.upright_image', side_effect=lambda p, d: p):
            result = tasks._read_score(item, ctx)
        from wama.common.backends.ocr_base import PAGE_ORIENTATION_KEY
        self.assertEqual([mock.call('huggingface:kobimusic/copisteria'),
                          mock.call(PAGE_ORIENTATION_KEY)], ctx.ensure_model.call_args_list,
                         'the score reader, then the classifier that uprights an image, by the route')
        self.assertEqual(str(page), calls['work_file'])
        self.assertEqual([('.musicxml', 'score', 'kobimusic/copisteria'),
                          ('.abc', 'score', 'kobimusic/copisteria')], places)
        fields = result['fields']
        self.assertEqual(MUSICXML_CDEF, (self.tmp / fields['score_musicxml']).read_text())
        abc = (self.tmp / fields['score_file']).read_text()
        self.assertIn('T:page', abc)
        self.assertIn('C D E F', abc)
        self.assertEqual(('huggingface:kobimusic/copisteria', fields['score_file']),
                         (fields['used_backend'], result['output_ref']))

    def test_without_any_score_reader_the_process_fails_in_words(self):
        from wama.reader import tasks
        from wama.reader.models import ReadingItem
        _png(self.tmp, 'page.png', _page(staves=1))
        item = ReadingItem.objects.create(user=self.user, input_file='page.png', read_as_score=True)
        ctx = SimpleNamespace(console=lambda *a: None, progress=lambda *a, **k: None)
        with mock.patch('wama.common.utils.auto_model.model_for_task', return_value=''):
            with self.assertRaisesMessage(RuntimeError, 'image-to-score'):
                tasks._read_score(item, ctx)
        from django.core.cache import cache
        step = (cache.get(f'reader_progress_{item.pk}') or {}).get('msg', '')
        self.assertTrue(step.startswith('Erreur'),
                        'the step message tells the failure, like the text reading')

    def test_a_pdf_score_needs_no_page_classifier(self):
        from wama.reader import tasks
        from wama.reader.models import ReadingItem
        (self.tmp / 'page.pdf').write_bytes(b'%PDF-1.4\n')
        item = ReadingItem.objects.create(user=self.user, input_file='page.pdf', read_as_score=True,
                                          page_count=1)
        ctx = SimpleNamespace(console=lambda *a: None, progress=lambda *a, **k: None,
                              ensure_model=mock.Mock(),
                              output_place=lambda ext, **k: (f'o{ext}', str(self.tmp / f'o{ext}')))
        with mock.patch('wama.common.utils.auto_model.model_for_task',
                        return_value='huggingface:kobimusic/copisteria'), \
                mock.patch('wama.common.backends.manager.backend_instance_for_key',
                           return_value=object()), \
                mock.patch('wama.common.backends.manager.run_contract', return_value=MUSICXML_CDEF):
            tasks._read_score(item, ctx)
        ctx.ensure_model.assert_called_once_with('huggingface:kobimusic/copisteria')

    def test_the_page_text_names_the_card_and_an_upside_down_page_is_turned(self):
        """2026-11-08, Fabien's drum pages : the orientation classifier turned a straight score
        upside down ; the page is read both ways by the OCR and the surer reading wins. The title,
        page number and « x3 » it reads reach the engine and the card."""
        from wama.reader import tasks
        from wama.reader.models import ReadingItem
        _png(self.tmp, 'page.png', _page(staves=1))
        item = ReadingItem.objects.create(user=self.user, input_file='page.png', read_as_score=True)
        straight = {'width': 1200, 'height': 1600, 'lines': [
            {'text': 'Nothing Else Matters', 'bbox': [400, 20, 800, 70], 'conf': 0.99},
            {'text': '2', 'bbox': [1150, 25, 1165, 50], 'conf': 0.9},
            {'text': 'x3', 'bbox': [600, 700, 630, 720], 'conf': 0.9}]}
        noise = {'width': 1200, 'height': 1600,
                 'lines': [{'text': 'SIOME OSIE', 'bbox': [400, 1500, 600, 1540], 'conf': 0.36}]}
        ocr = mock.Mock(read_lines=lambda path: [straight if path.endswith('_turned.png') else noise])
        calls = {}

        def run_contract(engine, **values):
            calls.update(values)
            return MUSICXML_CDEF
        ctx = SimpleNamespace(console=lambda *a: None, progress=lambda *a, **k: None,
                              ensure_model=mock.Mock(),
                              output_place=lambda ext, **k: (f'o{ext}', str(self.tmp / f'o{ext}')))
        with mock.patch('wama.common.utils.auto_model.model_for_task',
                        return_value='huggingface:kobimusic/copisteria'), \
                mock.patch('wama.common.services.ocr_process.positioned_ocr_keys',
                           return_value=['reader:doctr']), \
                mock.patch('wama.common.utils.auto_model.resolve_model_choice',
                           return_value='reader:doctr'), \
                mock.patch('wama.common.backends.manager.backend_instance_for_key',
                           side_effect=lambda key, **k: ocr if key == 'reader:doctr' else object()), \
                mock.patch('wama.common.backends.manager.run_contract', side_effect=run_contract), \
                mock.patch('wama.common.backends.ocr_base.upright_image', side_effect=lambda p, d: p), \
                mock.patch.object(tasks, '_order_lot_by_read_pages') as order:
            result = tasks._read_score(item, ctx)
        self.assertEqual(2, order.call_args.args[1]['score_page'],
                         'the lot is ordered with what the page just read')
        self.assertTrue(calls['work_file'].endswith('_turned.png'), 'the surer reading wins')
        self.assertIn(mock.call('reader:doctr'), ctx.ensure_model.call_args_list,
                      'the OCR is asked of the route like any model')
        roles = [(l['role'], l['text']) for l in calls['page_texts'][0]['lines']]
        self.assertEqual([('title', 'Nothing Else Matters'), ('page_number', '2'),
                          ('repeat_count', 'x3')], roles)
        self.assertEqual(('Nothing Else Matters', 2),
                         (result['fields']['score_title'], result['fields']['score_page']))
        self.assertIn('T:Nothing Else Matters', (self.tmp / 'o.abc').read_text())

    def test_without_an_ocr_that_places_text_the_score_is_read_without_title(self):
        from wama.reader import tasks
        from wama.reader.models import ReadingItem
        page = _png(self.tmp, 'page.png', _page(staves=1))
        item = ReadingItem.objects.create(user=self.user, input_file='page.png', read_as_score=True)
        ctx = SimpleNamespace(console=lambda *a: None, ensure_model=mock.Mock())
        with mock.patch('wama.common.services.ocr_process.positioned_ocr_keys', return_value=[]):
            self.assertEqual((str(page), None), tasks._score_page_texts(item, ctx, str(page), str(self.tmp)))
        ctx.ensure_model.assert_not_called()


class ThePagesOfAScoreNameTheirLotTest(TestCase):
    """« Plusieurs pages qui se suivent d'une même partition forment un lot, le titre est écrit en
    haut d'une des pages » (Fabien, 2026-11-08) — in any order."""

    def setUp(self):
        from wama.reader.models import BatchReadingItem, BatchReadingItemLink, ReadingItem
        self.tmp = Path(tempfile.mkdtemp(prefix='reader_score_lot_'))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        media = override_settings(MEDIA_ROOT=str(self.tmp))
        media.enable()
        self.addCleanup(media.disable)
        self.user = get_user_model().objects.create_user('reader_score_lot', password='x')
        self.batch = BatchReadingItem.objects.create(user=self.user, total=3)
        self.pages = []
        for row, (title, number) in enumerate((('', 3), ('Nothing Else Matters', None),
                                               ('', 2))):
            item = ReadingItem.objects.create(user=self.user, read_as_score=True, status='SUCCESS',
                                              original_filename=f'IMG_{row}.jpg', score_file=f'out/{row}.abc',
                                              score_title=title, score_page=number)
            BatchReadingItemLink.objects.create(batch=self.batch, reading=item, row_index=row)
            self.pages.append(item)

    def test_the_title_read_on_any_page_names_the_lot(self):
        from wama.common.services.batch_identity import identity_of, rename
        identity = identity_of(self.batch)
        self.assertEqual(('Nothing Else Matters', 'content'), (identity['title'], identity['kind']))
        rename(self.batch, 'Concert de juin')
        self.assertEqual('Concert de juin', identity_of(self.batch)['title'], 'a given name wins')

    def test_each_page_card_carries_the_title_and_its_page_number(self):
        from wama.reader.views import _shown_title
        first, titled, second = self.pages
        self.assertEqual('Nothing Else Matters — p. 3', _shown_title(first))
        self.assertEqual('Nothing Else Matters', _shown_title(titled))
        self.assertEqual('Nothing Else Matters — p. 2', _shown_title(second, self.pages))

    def test_the_pages_line_up_by_the_page_number_read(self):
        """Fabien, 2026-11-08 : « réordonner seul ». The page that carries the title and no number
        opens the work ; the page just read enters with what it read, not yet written."""
        from wama.common.services.batch_identity import order_by_read_pages
        from wama.common.utils.batch_common import batch_elements
        from wama.reader.models import ReadingItem
        first, titled, second = self.pages              # rows : p.3, title, p.2
        self.assertTrue(order_by_read_pages(self.batch, ReadingItem))
        self.assertEqual([titled.pk, second.pk, first.pk],
                         [e.pk for e in batch_elements(self.batch, ReadingItem)])
        self.assertFalse(order_by_read_pages(self.batch, ReadingItem), 'already in order')
        first.score_page = 1                             # just read, not yet saved
        self.assertTrue(order_by_read_pages(self.batch, ReadingItem, current=first))
        self.assertEqual(first.pk, batch_elements(self.batch, ReadingItem)[0].pk)

    def test_the_glue_orders_the_lot_of_the_page_it_read(self):
        from wama.common.utils.batch_common import batch_elements
        from wama.reader import tasks
        from wama.reader.models import ReadingItem
        first, titled, second = self.pages
        messages = []
        ctx = SimpleNamespace(console=messages.append)
        tasks._order_lot_by_read_pages(first, {'score_file': 'out/0.abc', 'score_page': 4}, ctx)
        self.assertEqual([titled.pk, second.pk, first.pk],
                         [e.pk for e in batch_elements(self.batch, ReadingItem)])
        self.assertIn('rangées', messages[0])

    def test_a_lot_without_any_page_read_does_not_move(self):
        from wama.common.services.batch_identity import order_by_read_pages
        from wama.reader.models import ReadingItem
        ReadingItem.objects.filter(pk__in=[p.pk for p in self.pages]).update(score_title='',
                                                                            score_page=None)
        self.assertFalse(order_by_read_pages(self.batch, ReadingItem))

    def test_a_page_that_lost_its_score_loses_its_title(self):
        from wama.common.services.batch_identity import identity_of
        for item in self.pages:
            item.score_file = None
            item.save(update_fields=['score_file'])
        self.assertEqual('', self.pages[1].read_title)
        self.assertIsNone(self.pages[0].read_page)
        self.assertNotEqual('content', identity_of(self.batch)['kind'])


class TheCardFollowsTheScoreTest(TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='reader_score_card_'))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        media = override_settings(MEDIA_ROOT=str(self.tmp))
        media.enable()
        self.addCleanup(media.disable)
        self.user = get_user_model().objects.create_user('reader_score_card', password='x')

    def _score_item(self):
        from wama.reader.models import ReadingItem
        (self.tmp / 'out').mkdir(exist_ok=True)
        (self.tmp / 'out/s.abc').write_text('X:1\nK:C\nCDEF|\n', encoding='utf-8')
        (self.tmp / 'out/s.musicxml').write_text(MUSICXML_CDEF, encoding='utf-8')
        return ReadingItem.objects.create(user=self.user, read_as_score=True, status='SUCCESS',
                                          score_file='out/s.abc', score_musicxml='out/s.musicxml')

    def test_the_setting_columns_come_from_the_schema(self):
        from wama.reader.views import SETTINGS_FIELDS
        self.assertIn('read_as_score', SETTINGS_FIELDS)
        self.assertIn('score_model', SETTINGS_FIELDS)
        self.assertNotIn('quality_intent', SETTINGS_FIELDS, 'a user setting, not a column')

    def test_a_score_downloads_as_abc_and_musicxml_only(self):
        from wama.common.utils.export_formats import available_formats
        from wama.reader.views import build_reading_bytes
        from wama.reader.models import ReadingItem
        item = self._score_item()
        self.assertEqual(('abc', b'X:1\nK:C\nCDEF|\n'), build_reading_bytes(item, 'abc'))
        self.assertEqual('musicxml', build_reading_bytes(item, 'musicxml')[0])
        self.assertEqual(['abc', 'musicxml'], available_formats('reader', item))
        text = ReadingItem(user=self.user, result_text='bonjour')
        self.assertEqual(['txt', 'md', 'pdf', 'docx'], available_formats('reader', text))

    def test_each_nature_opens_its_own_edit_page(self):
        from wama.common.surfaces import load_all, surface as get_surface
        load_all()
        from wama.reader.models import ReadingItem
        score, text = get_surface('reader', 'score'), get_surface('reader', 'text')
        item = self._score_item()
        self.assertEqual((True, ''), score.can_open(item))
        self.assertFalse(text.can_open(item)[0])
        read = ReadingItem(user=self.user, result_text='# Titre\n\ntexte', status='SUCCESS')
        self.assertEqual((True, ''), text.can_open(read))
        self.assertIn('Lire une partition', score.can_open(read)[1])
        self.assertTrue(score.text_value, 'the ABC file is edited as text, its versions kept')

    def test_a_ticked_page_without_a_score_reader_is_corrected_as_text(self):
        """The switch alone does not make a score : without a model of the task the page is read
        as a text (`takes_place`), and both pages say so — one rule, `holds_score`."""
        from wama.common.surfaces import load_all, surface as get_surface
        load_all()
        from wama.reader.models import ReadingItem
        read = ReadingItem(user=self.user, read_as_score=True, result_text='# Titre\n\ntexte',
                           status='SUCCESS')
        with mock.patch('wama.common.utils.auto_model.task_installed', return_value=False):
            self.assertEqual((True, ''), get_surface('reader', 'text').can_open(read))
            refused = get_surface('reader', 'score').can_open(read)
        self.assertEqual(False, refused[0])
        self.assertIn('Aucun modèle', refused[1])

    def test_the_assistant_status_carries_the_score(self):
        from wama.tool_api import TRIAD_SPECS
        fields = TRIAD_SPECS['reader']['status_fields']
        self.assertEqual('score_file', fields['score_url']['attr'])
        self.assertEqual('read_as_score', fields['read_as_score'])

    def test_the_reader_page_serves_the_switch_and_the_score_model(self):
        from django.urls import reverse
        from wama.accounts.permissions import DEFAULT_APP_ACCESS, GROUP_PREFIX
        from django.contrib.auth.models import Group
        for role in (DEFAULT_APP_ACCESS.get('reader') or {}).get('roles', []):
            self.user.groups.add(Group.objects.get_or_create(name=f'{GROUP_PREFIX}{role}')[0])
        self.client.force_login(self.user)
        html = self.client.get(reverse('reader:index')).content.decode('utf-8')
        self.assertIn('read_as_score', html)
        self.assertIn('has_staves', html)
        self.assertIn('score_model', html)
