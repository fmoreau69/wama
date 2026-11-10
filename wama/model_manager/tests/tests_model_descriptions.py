"""DESCRIPTIONS of the catalogue (2026-10-29, Fabien: « à l'installation des modèles on a pas
forcément les descriptions courtes et longues », then « l'exploration de sources externes (même
web) peut permettre de combler les trous de description à minima »).

Measured that day on 666 rows: 27 generic sweep texts (« Snapshot HF … »), 14 « Ollama LLM (x GB) »,
~488 remote rows reduced to « <provider> — modèle distant (<type>) ». The sync rewrote the generic
text at every pass, so a real description could not survive; OpenRouter's own description was
thrown away. Three remedies: the sync never replaces a real description by a filler, and marks the
filler it writes; the provider's description is kept; the marked rows are filled from the model
card (or the web), summarised — in English since 2026-11-08, WAMA's source language —, the source
recorded. The fillers themselves are written in English since 2026-11-09.
"""
import re
from unittest import mock

from django.test import SimpleTestCase, TestCase

from wama.model_manager.models import (DESCRIPTION_PLACEHOLDER_KEY, DESCRIPTION_SOURCE_KEY,
                                       AIModel, ModelSource, ModelType)
from wama.model_manager.services import model_descriptions as md
from wama.model_manager.services.model_registry import ModelInfo
from wama.model_manager.services.model_sync import ModelSyncService

KEY = 'huggingface:org/some-ocr'
FILLER = 'Installed HuggingFace snapshot (ocr/Fam), catalogued by the generic scan of installed models.'


def _info(description=FILLER, placeholder=True, extra=None):
    return ModelInfo(id='org/some-ocr', name='some-ocr', model_type=ModelType('ocr'),
                     source=ModelSource('huggingface'), description=description,
                     description_short='Snapshot HF some-ocr', is_downloaded=True,
                     description_placeholder=placeholder, extra_info=dict(extra or {}))


class TheSyncKeepsARealDescriptionTest(TestCase):

    def test_a_filler_is_written_marked_on_a_row_that_has_nothing(self):
        ModelSyncService()._sync_model(KEY, _info())
        row = AIModel.objects.get(model_key=KEY)
        self.assertEqual(FILLER, row.description)
        self.assertTrue(row.extra_info[DESCRIPTION_PLACEHOLDER_KEY])

    def test_a_real_description_survives_the_filler_and_its_source_stays(self):
        ModelSyncService()._sync_model(KEY, _info())
        AIModel.objects.filter(model_key=KEY).update(
            description='Lit les documents imprimés.', description_short='OCR imprimé',
            extra_info={DESCRIPTION_SOURCE_KEY: {'origin': 'fiche'}})
        ModelSyncService()._sync_model(KEY, _info())
        row = AIModel.objects.get(model_key=KEY)
        self.assertEqual(('Lit les documents imprimés.', 'OCR imprimé'),
                         (row.description, row.description_short))
        self.assertNotIn(DESCRIPTION_PLACEHOLDER_KEY, row.extra_info)
        self.assertEqual({'origin': 'fiche'}, row.extra_info[DESCRIPTION_SOURCE_KEY])

    def test_a_discovery_that_knows_still_writes_its_description(self):
        # Counter-check: an app's declaration is not a filler — it keeps the authority it had.
        ModelSyncService()._sync_model(KEY, _info())
        AIModel.objects.filter(model_key=KEY).update(description='ancienne', extra_info={})
        ModelSyncService()._sync_model(KEY, _info(description='Déclaré par son app.',
                                                  placeholder=False))
        row = AIModel.objects.get(model_key=KEY)
        self.assertEqual('Déclaré par son app.', row.description)
        self.assertNotIn(DESCRIPTION_PLACEHOLDER_KEY, row.extra_info)


class GenericTextsAreMarkedTest(SimpleTestCase):

    def test_the_remote_filler_is_marked_and_a_provider_description_is_not(self):
        from wama.model_manager.services.cloud_models import model_info_for
        bare = model_info_for('openrouter', {'id': 'org/m', 'name': 'M', 'type': 'text-generation'})
        said = model_info_for('openrouter', {'id': 'org/m', 'name': 'M', 'type': 'text-generation',
                                             'description': 'A model that writes.'})
        self.assertTrue(bare.description_placeholder)
        self.assertFalse(said.description_placeholder)
        self.assertEqual('A model that writes.', said.description)

    def test_the_listing_keeps_the_provider_description(self):
        from wama.model_manager.services import cloud_models as cm
        listing = {'data': [{'id': 'org/m', 'name': 'M', 'description': '  Writes code.  ',
                             'architecture': {'input_modalities': ['text'],
                                              'output_modalities': ['text']}}]}
        response = mock.Mock(status_code=200, json=lambda: listing)
        response.raise_for_status = lambda: None
        with mock.patch('requests.get', return_value=response):
            items = cm.list_remote_models('openrouter', api_key='k')
        self.assertEqual('Writes code.', items[0]['description'])


class FillingTest(TestCase):

    def _filler_row(self):
        ModelSyncService()._sync_model(KEY, _info())
        AIModel.objects.filter(model_key=KEY).update(platform_ref='huggingface:org/some-ocr')
        return AIModel.objects.get(model_key=KEY)

    def test_a_marked_row_is_filled_from_its_card_and_says_so(self):
        row = self._filler_row()
        summary = {'short': 'Lit les documents.', 'long': 'Un OCR. Il lit des pages.'}
        with mock.patch.object(md, 'card_text', return_value='# Some OCR\nReads documents.'), \
                mock.patch.object(md, 'summarize', return_value=(summary, 'ollama:x')):
            results = md.describe_rows(apply=True)
        self.assertEqual(['fiche'], [r.get('origin') for r in results])
        row.refresh_from_db()
        self.assertEqual(('Un OCR. Il lit des pages.', 'Lit les documents.'),
                         (row.description, row.description_short))
        self.assertNotIn(DESCRIPTION_PLACEHOLDER_KEY, row.extra_info)
        self.assertEqual('fiche', row.extra_info[DESCRIPTION_SOURCE_KEY]['origin'])
        self.assertEqual([], md.rows_to_describe(), 'nothing left to fill')

    def test_a_quantisation_without_a_card_is_described_by_its_origin_s_card(self):
        # Re-read on 2026-10-30: chandra-ocr-2's GGUF repository has no readable card.
        row = self._filler_row()
        row.extra_info = {**row.extra_info, 'base_model': 'org/origin',
                          'base_model_relation': 'quantized'}
        summary = {'short': 'Lit.', 'long': 'Lit des pages.'}
        cards = {'org/some-ocr': '', 'org/origin': '# Origin\nReads pages.'}
        with mock.patch.object(md, 'card_text', side_effect=lambda repo: cards[repo]), \
                mock.patch.object(md, 'summarize', return_value=(summary, 'm')) as summarize:
            out = md.describe(row, web=False)
        self.assertEqual('fiche', out['origin'])
        self.assertEqual('# Origin\nReads pages.', summarize.call_args.args[1])

    def test_without_card_nor_web_nothing_is_guessed(self):
        row = self._filler_row()
        with mock.patch.object(md, 'card_text', return_value=''), \
                mock.patch.object(md, 'summarize') as summarize:
            out = md.describe(row, apply=True, web=False)
        summarize.assert_not_called()
        self.assertIn('skipped', out)
        row.refresh_from_db()
        self.assertEqual(FILLER, row.description)

    def test_the_dry_run_writes_nothing(self):
        row = self._filler_row()
        summary = {'short': 'Lit.', 'long': 'Lit des pages.'}
        with mock.patch.object(md, 'card_text', return_value='text'), \
                mock.patch.object(md, 'summarize', return_value=(summary, 'ollama:x')):
            md.describe(row)
        row.refresh_from_db()
        self.assertEqual(FILLER, row.description)


class TheMarkStaysOutOfTheCorpusTest(SimpleTestCase):
    """The mark is machine state (the sync sets and lifts it) — measured on 2026-10-30, a recycled
    worker exported it into ten `albert__*` manifests. Where the description comes from is a
    fact, and stays."""

    def test_the_mark_is_dropped_and_the_source_is_kept(self):
        from wama.common.management.commands.manifest_export import _sans_etat_machine
        kept = _sans_etat_machine({DESCRIPTION_PLACEHOLDER_KEY: True,
                                   DESCRIPTION_SOURCE_KEY: {'origin': 'fiche'}})
        self.assertEqual({DESCRIPTION_SOURCE_KEY: {'origin': 'fiche'}}, kept)


class CardReaderTest(SimpleTestCase):
    """The card is read by THE reader of a repository file (`prospector.hub_raw_file`), shared
    with the licence and the configuration readers."""

    def test_the_card_comes_without_its_yaml_header(self):
        page = mock.Mock(status_code=200, text='---\nlicense: mit\n---\n# Model\nReads pages.')
        with mock.patch('wama.model_manager.services.prospector.hub_raw_file',
                        return_value=page) as read:
            self.assertEqual('# Model\nReads pages.', md.card_text('org/model'))
        self.assertEqual(('org/model', 'README.md'), read.call_args.args)

    def test_a_silent_or_refused_hub_gives_no_card(self):
        with mock.patch('wama.model_manager.services.prospector.hub_raw_file', return_value=None):
            self.assertEqual('', md.card_text('org/model'))
        with mock.patch('wama.model_manager.services.prospector.hub_raw_file',
                        return_value=mock.Mock(status_code=401, text='gated')):
            self.assertEqual('', md.card_text('org/model'))


class SummarizeTest(SimpleTestCase):

    def _answer(self, text):
        with mock.patch('wama.common.utils.llm_utils.modele_par_defaut', return_value='m'), \
                mock.patch('wama.common.utils.llm_utils.llm_chat', return_value=(text, None)):
            return md.summarize('M', 'source', 'fiche')[0]

    def test_a_valid_answer_gives_both_texts_and_a_bounded_short_line(self):
        out = self._answer('{"short": "' + 'x' * 300 + '", "long": "Une phrase."}')
        self.assertEqual(md.SHORT_CHARS, len(out['short']))
        self.assertEqual('Une phrase.', out['long'])

    def test_an_empty_or_off_topic_answer_gives_nothing(self):
        self.assertIsNone(self._answer('{}'))
        self.assertIsNone(self._answer('pas du JSON'))

    def test_the_description_is_asked_in_english_the_source_language(self):
        """English is WAMA's source language, French a translation (Fabien, 2026-08-30 — ROADMAP
        §10.A, MANIFEST_SPEC §1) : the instruction asks for English and is written in English."""
        prompt = md.PROMPT.format(short=md.SHORT_CHARS, name='M', origin='fiche', text='t')
        self.assertIn('write in English', prompt)
        self.assertNotIn('français', prompt)


class ProspectionWritesItsStandInsInEnglishTest(SimpleTestCase):
    """A proposed model carries a stand-in description until its card describes it
    (« [ocr] 386 downloads… », `PROSPECTION_PIPELINE` point 6). The revalidation of 2026-11-09
    found 179 proposals still in French in the catalogue: the prospection templates had been left
    out of the English rewrite. Read at the source — every string handed to `description=`, to a
    `'description'` key or to `desc` in the prospection modules —, so a new template is held too."""

    FRENCH = re.compile(
        r"[éèàùçêâôîû]|\b(le|la|les|des|du|par|pour|avec|une|est|sur|dans|sous|il y a)\b", re.I)

    def _templates(self, module):
        import ast
        import inspect
        tree = ast.parse(inspect.getsource(module))

        def text(node):
            return ''.join(n.value for n in ast.walk(node)
                           if isinstance(n, ast.Constant) and isinstance(n.value, str))
        for node in ast.walk(tree):
            if isinstance(node, ast.keyword) and (node.arg or '').startswith('description'):
                yield node.value.lineno, text(node.value)
            elif isinstance(node, ast.Dict):
                for key, value in zip(node.keys, node.values):
                    if isinstance(key, ast.Constant) and key.value == 'description':
                        yield value.lineno, text(value)
            elif isinstance(node, ast.Assign) and any(
                    isinstance(t, ast.Name) and t.id == 'desc' for t in node.targets):
                yield node.lineno, text(node.value)

    def test_every_stand_in_description_is_english(self):
        from wama.model_manager.services import prospect_agents, prospect_ollama, prospector
        found, french = 0, []
        for module in (prospector, prospect_ollama, prospect_agents):
            for line, template in self._templates(module):
                found += bool(template.strip())
                if self.FRENCH.search(template):
                    french.append(f"{module.__name__}:{line} : {template!r}")
        self.assertEqual([], french)
        self.assertGreaterEqual(found, 8, 'the reading no longer sees the templates')

    def test_the_labels_a_template_interpolates_are_english_too(self):
        """The Ollama template was English on 2026-11-09 and its 31 proposals still read
        « [LLM généraliste (describer, assistant)] … »: it interpolates the role's `label`, a datum
        the template reading cannot see (2026-11-10)."""
        from wama.common.management.commands.check_identifier_language import is_french
        from wama.model_manager.services.benchmark_sync import SOURCES
        from wama.model_manager.services.prospect_ollama import ROLES
        labels = {**{f'ollama:{key}': role['label'] for key, role in ROLES.items()},
                  **{f"leaderboard:{source['key']}": source['label'] for source in SOURCES}}
        # A label has no stopword to catch: « Traduction (translator) » passed the pattern. The
        # words also go through WAMA's French detector, the identifiers' blacklist.
        french = {key: label for key, label in labels.items()
                  if self.FRENCH.search(label)
                  or is_french('_'.join(re.findall(r'[^\W\d_]+', label)).lower())}
        self.assertEqual({}, french)


class TheCorpusSpeaksEnglishTest(SimpleTestCase):
    """Names and descriptions of the versioned corpus (`manifests/models/`) are English — every
    text WAMA writes there. The rewrite of 2026-11-09 read the descriptions, the names were
    translated the next day, and four short descriptions of the transcriber (« Qwen3-ASR 0.6B —
    rapide, context biasing, 30 langues ») slipped past both: no accent, no stopword, only a word
    the identifiers' blacklist knows (2026-11-10).

    A remote provider's own name and description are its words, not WAMA's: they are read only
    when WAMA wrote them (its filler « <source> — remote model (…) », or a description summarised
    by `describe_models`, which records its `description_source`)."""

    FRENCH = ProspectionWritesItsStandInsInEnglishTest.FRENCH
    #: Words of the identifiers' blacklist that are English as well, in a WAMA text of the corpus.
    ENGLISH_HOMOGRAPHS = {'categories', 'ensemble', 'pose'}
    #: Proper nouns: Phonon's four voices have French first names.
    PROPER_NOUNS = ('Noémie',)

    def _wama_texts(self, data):
        from wama.common import external_sources
        from wama.model_manager.services.cloud_models import UNLISTABLE_PROTOCOLS
        source = data['key'].partition(':')[0]
        known = {s.key: s for s in external_sources.SOURCES}
        provider = known.get(source)
        listed = (provider is not None and provider.kind == 'llm'
                  and provider.protocol not in UNLISTABLE_PROTOCOLS)
        described = 'description_source' in ((data.get('body') or {}).get('extra_info') or {})
        texts = {} if listed else {'name': data.get('name') or ''}
        short = ((data.get('body') or {}).get('identity') or {}).get('description_short') or ''
        for field, text in (('description', data.get('description') or ''), ('description_short', short)):
            if not listed or described or (text.startswith(f'{provider.label} — ')):
                texts[field] = text
        return texts

    def _is_french(self, text):
        from wama.common.management.commands.check_identifier_language import is_french
        for noun in self.PROPER_NOUNS:
            text = text.replace(noun, '')
        return bool(self.FRENCH.search(text)) or any(
            is_french(word.lower()) for word in re.findall(r'[^\W\d_]+', text)
            if word.lower() not in self.ENGLISH_HOMOGRAPHS)

    def test_every_name_and_description_wama_writes_is_english(self):
        import json
        from pathlib import Path

        from django.conf import settings
        paths = sorted((Path(settings.BASE_DIR) / 'manifests' / 'models').glob('*.json'))
        self.assertGreater(len(paths), 100, 'the corpus is not where the guard reads it')
        french, read = [], 0
        for path in paths:
            for field, text in self._wama_texts(json.loads(path.read_text(encoding='utf-8'))).items():
                read += bool(text)
                if self._is_french(text):
                    french.append(f'{path.name} [{field}] {text[:90]!r}')
        self.assertEqual([], french)
        self.assertGreater(read, 300, 'the guard no longer reads the texts')

    def test_the_guard_sees_a_french_text_without_accent_nor_stopword(self):
        """Counter-proof kept in the suite: the poorest case the corpus held."""
        self.assertTrue(self._is_french('Qwen3-ASR 0.6B — rapide, context biasing, 30 langues'))
        self.assertFalse(self._is_french('Qwen3-ASR 0.6B — fast, context biasing, 30 languages'))
