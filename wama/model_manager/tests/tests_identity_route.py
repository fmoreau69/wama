"""La route de l'IDENTITÉ d'un modèle — `provenance.set_identity`, par le manifeste (2026-10-22).

Tout ce que WAMA sait de l'éditeur d'un modèle (plateforme, licence, auteur, régime d'accès,
publications) se pose par `set_identity` : projection au catalogue et, pour un modèle installé,
export au corpus. Trois écarts mesurés le 2026-10-22 :
- le régime d'accès (`gated`), lu à l'installation par `huggingface_identity`, n'était recopié par
  personne — seule la passe `backfill_platform_refs --licenses` l'écrivait, en base ;
- `backfill_platform_refs` écrivait `platform_ref`, `hf_id` (alors) et les licences en base, à côté du
  manifeste ;
- un candidat Ollama naissait sans `platform_ref` (11 lignes), quand ceux du Hub, de GitHub et du
  scout la reçoivent de leur appelant.
"""
from unittest import mock

from django.core.management import call_command
from django.test import TestCase

from wama.model_manager.models import AIModel
from wama.model_manager.services import provenance


def _row(key, **fields):
    defaults = {'name': key, 'model_type': 'vision', 'source': key.partition(':')[0]}
    return AIModel.objects.create(model_key=key, **{**defaults, **fields})


class IdentitySetsTheAccessRegimeTest(TestCase):

    def test_an_installation_keeps_the_access_regime_read_on_the_card(self):
        _row('huggingface:org/closed', platform_ref='huggingface:org/closed')
        card = {'license': 'mit', 'author': 'org', 'platform_ref': 'huggingface:org/closed',
                'gated': 'manual', 'publications': [],
                'declared': {'capabilities': {}, 'engine': ''}}
        with mock.patch.object(provenance, 'huggingface_identity', return_value=card):
            provenance.record_after_install({'kind': 'hf', 'ref': 'org/closed'},
                                            ['huggingface:org/closed'])
        self.assertEqual('manual', AIModel.objects.get(model_key='huggingface:org/closed').gated)

    def test_an_unknown_regime_is_never_written(self):
        _row('huggingface:org/known', platform_ref='huggingface:org/known', gated='auto')
        for unknown in ('', None, False, 'oui'):
            with self.subTest(gated=unknown):
                provenance.set_identity('huggingface:org/known',
                                        {'license': 'mit', 'gated': unknown}, export=False)
                self.assertEqual('auto', AIModel.objects.get(model_key='huggingface:org/known').gated)

    def test_the_hub_placeholder_never_overwrites_a_qualified_licence(self):
        _row('huggingface:org/qualified', platform_ref='huggingface:org/qualified', license='cpml-1.0')
        _row('huggingface:org/blank', platform_ref='huggingface:org/blank')
        for key in ('huggingface:org/qualified', 'huggingface:org/blank'):
            provenance.set_identity(key, {'license': 'other'}, export=False)
        self.assertEqual('cpml-1.0', AIModel.objects.get(model_key='huggingface:org/qualified').license)
        self.assertEqual('other', AIModel.objects.get(model_key='huggingface:org/blank').license)


class BackfillGoesThroughTheManifestTest(TestCase):

    def _spy(self):
        return mock.patch.object(provenance, 'set_identity', wraps=provenance.set_identity)

    def test_a_derived_platform_ref_is_set_by_the_manifest_and_a_candidate_is_not_exported(self):
        # The derivation left is the Ollama one (`hf_id` → `platform_ref` went with the column,
        # 2026-10-27: no row carried `hf_id` without `platform_ref`).
        _row('ollama:qwen3.8:latest', name='qwen3.8:latest', source='ollama')
        _row('proposed:ollama:gemma4:12b', name='gemma4:12b', source='ollama', is_proposed=True)
        _row('transcriber:canary-test', platform_ref='huggingface:nvidia/canary-test',
             source='transcriber')
        with self._spy() as spy:
            call_command('backfill_platform_refs', '--ecrire', stdout=mock.MagicMock())
        calls = {c.args[0]: c for c in spy.call_args_list}
        self.assertEqual('ollama:qwen3.8',
                         AIModel.objects.get(model_key='ollama:qwen3.8:latest').platform_ref)
        self.assertEqual('ollama:gemma4',
                         AIModel.objects.get(model_key='proposed:ollama:gemma4:12b').platform_ref)
        self.assertIs(True, calls['ollama:qwen3.8:latest'].kwargs['export'])
        self.assertIs(False, calls['proposed:ollama:gemma4:12b'].kwargs['export'])
        # A known platform_ref is never re-derived.
        self.assertNotIn('transcriber:canary-test', calls)
        self.assertEqual('huggingface:nvidia/canary-test',
                         AIModel.objects.get(model_key='transcriber:canary-test').platform_ref)

    def test_the_licence_pass_writes_the_access_regime_by_the_manifest(self):
        _row('huggingface:org/gate', platform_ref='huggingface:org/gate')
        card = {'license': 'apache-2.0', 'author': 'org', 'platform_ref': 'huggingface:org/gate',
                'gated': 'auto', 'publications': ['2601.14251'],
                'declared': {'capabilities': {}, 'engine': ''}}
        with mock.patch.object(provenance, 'huggingface_identity', return_value=card), \
                self._spy() as spy:
            call_command('backfill_platform_refs', '--licenses', '--ecrire',
                         stdout=mock.MagicMock())
        row = AIModel.objects.get(model_key='huggingface:org/gate')
        self.assertEqual(('apache-2.0', 'org', 'auto', ['2601.14251']),
                         (row.license, row.author, row.gated, row.extra_info.get('publications')))
        self.assertIn('huggingface:org/gate', [c.args[0] for c in spy.call_args_list])


class AQuantizationInheritsItsOriginTest(TestCase):
    """2026-10-29 (Fabien: « il faut bien faire hériter la note aux versions quantisées »): a GGUF
    IS its origin model, and the bench pairs it through it (`AIModel.quantized_base`). The link was
    set only when the installation received it from the prospection ; chandra-ocr-2 in Q6_K stayed
    without a score although its card names `datalab-to/chandra-ocr-2`."""

    def test_the_card_says_which_model_a_quantization_is(self):
        tags = ['gguf', 'base_model:datalab-to/chandra-ocr-2',
                'base_model:quantized:datalab-to/chandra-ocr-2']
        self.assertEqual({'base_model': 'datalab-to/chandra-ocr-2',
                          'base_model_relation': 'quantized'},
                         provenance.quantized_base_identity(tags, 'org/chandra-ocr-2-GGUF'))
        # Counter-tests: a fine-tune is not what it IS ; two bases, none is chosen ; itself, nothing.
        self.assertEqual({}, provenance.quantized_base_identity(
            ['base_model:finetune:org/base'], 'org/tuned'))
        self.assertEqual({}, provenance.quantized_base_identity(
            ['base_model:quantized:org/a', 'base_model:quantized:org/b'], 'org/m'))
        self.assertEqual({}, provenance.quantized_base_identity(
            ['base_model:quantized:Org/M'], 'org/m'))
        # The Hub infers `quantized` from the files and may name the BASE of a fine-tune (dry run
        # of 2026-10-29): kept only when the repository carries the origin's full name.
        self.assertEqual({}, provenance.quantized_base_identity(
            ['base_model:quantized:Qwen/Qwen3-4B-Base'], 'Qwen/Qwen3-Embedding-4B-GGUF'))
        self.assertEqual({}, provenance.quantized_base_identity(
            ['base_model:quantized:mistralai/Ministral-3-8B-Base-2512'],
            'mistralai/Ministral-3-8B-Instruct-2512'))

    def test_the_card_is_read_with_the_hub_retry_of_the_prospection(self):
        """A pass over ~300 cards met 298 refusals in a row (rate limit, 2026-10-29): the card is
        read through `prospector._hub_model_info` (one retry after `Retry-After`)."""
        from types import SimpleNamespace
        info = SimpleNamespace(card_data=None, author='org', gated=False, pipeline_tag='image-to-text',
                               library_name='', tags=['base_model:quantized:org/chandra-ocr-2'])
        with mock.patch('wama.model_manager.services.prospector._hub_model_info',
                        return_value=info) as read:
            ident = provenance.huggingface_identity('org/chandra-ocr-2-GGUF')
        read.assert_called_once()
        self.assertEqual('org/chandra-ocr-2', ident['base_model'])

    def test_the_licence_pass_sets_the_origin_and_the_bench_then_pairs_through_it(self):
        _row('ollama:hf.co/org/chandra-ocr-2-GGUF:Q6_K', source='ollama',
             platform_ref='huggingface:org/chandra-ocr-2-GGUF')
        card = {'license': 'openrail', 'author': 'org',
                'platform_ref': 'huggingface:org/chandra-ocr-2-GGUF', 'gated': 'no',
                'publications': [], 'base_model': 'datalab-to/chandra-ocr-2',
                'base_model_relation': 'quantized', 'declared': {'capabilities': {}, 'engine': ''}}
        with mock.patch.object(provenance, 'huggingface_identity', return_value=card):
            call_command('backfill_platform_refs', '--licenses', '--ecrire',
                         stdout=mock.MagicMock())
        row = AIModel.objects.get(model_key='ollama:hf.co/org/chandra-ocr-2-GGUF:Q6_K')
        self.assertEqual('datalab-to/chandra-ocr-2', row.quantized_base)
        self.assertIn('datalab-to/chandra-ocr-2', row.hub_repos(), 'the bench pairs through it')


class OllamaCandidatesCarryTheirPlatformTest(TestCase):

    def _write(self, key, nom, **fields):
        from wama.model_manager.services.prospect_ollama import write_candidate
        write_candidate(key, nom=nom, model_type='llm', description='', kind='new',
                        confidence=None, extra={}, **fields)
        return AIModel.objects.get(model_key=key)

    def test_a_tag_gets_the_family_page_a_hub_gguf_its_repository(self):
        self.assertEqual('ollama:qwen3',
                         self._write('proposed:ollama:qwen3:8b', 'qwen3:8b').platform_ref)
        self.assertEqual('huggingface:org/model-GGUF',
                         self._write('proposed:ollama:hf.co/org/model-GGUF:Q4_K_M',
                                     'hf.co/org/model-GGUF:Q4_K_M').platform_ref)

    def test_what_the_caller_passes_wins_and_other_sources_are_left_alone(self):
        self.assertEqual('ollama:given', self._write('proposed:ollama:x:1', 'x:1',
                                                     platform_ref='ollama:given').platform_ref)
        self.assertEqual('', self._write('proposed:hf:org/y', 'y', source='huggingface').platform_ref)
