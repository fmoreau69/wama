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
        ctx.ensure_model.assert_called_once_with('huggingface:kobimusic/copisteria')
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
