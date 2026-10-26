"""La route de l'IDENTITÉ d'un modèle — `provenance.set_identity`, par le manifeste (2026-10-22).

Tout ce que WAMA sait de l'éditeur d'un modèle (plateforme, licence, auteur, régime d'accès,
publications) se pose par `set_identity` : projection au catalogue et, pour un modèle installé,
export au corpus. Trois écarts mesurés le 2026-10-22 :
- le régime d'accès (`gated`), lu à l'installation par `huggingface_identity`, n'était recopié par
  personne — seule la passe `backfill_platform_refs --licenses` l'écrivait, en base ;
- `backfill_platform_refs` écrivait `platform_ref`, `hf_id` et les licences en base, à côté du
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
        _row('huggingface:org/closed', hf_id='org/closed')
        card = {'license': 'mit', 'author': 'org', 'platform_ref': 'huggingface:org/closed',
                'hf_id': 'org/closed', 'gated': 'manual', 'publications': [],
                'declared': {'capabilities': {}, 'engine': ''}}
        with mock.patch.object(provenance, 'huggingface_identity', return_value=card):
            provenance.record_after_install({'kind': 'hf', 'ref': 'org/closed'},
                                            ['huggingface:org/closed'])
        self.assertEqual('manual', AIModel.objects.get(model_key='huggingface:org/closed').gated)

    def test_an_unknown_regime_is_never_written(self):
        _row('huggingface:org/known', hf_id='org/known', gated='auto')
        for unknown in ('', None, False, 'oui'):
            with self.subTest(gated=unknown):
                provenance.set_identity('huggingface:org/known',
                                        {'license': 'mit', 'gated': unknown}, export=False)
                self.assertEqual('auto', AIModel.objects.get(model_key='huggingface:org/known').gated)

    def test_the_hub_placeholder_never_overwrites_a_qualified_licence(self):
        _row('huggingface:org/qualified', hf_id='org/qualified', license='cpml-1.0')
        _row('huggingface:org/blank', hf_id='org/blank')
        for key in ('huggingface:org/qualified', 'huggingface:org/blank'):
            provenance.set_identity(key, {'license': 'other'}, export=False)
        self.assertEqual('cpml-1.0', AIModel.objects.get(model_key='huggingface:org/qualified').license)
        self.assertEqual('other', AIModel.objects.get(model_key='huggingface:org/blank').license)


class BackfillGoesThroughTheManifestTest(TestCase):

    def _spy(self):
        return mock.patch.object(provenance, 'set_identity', wraps=provenance.set_identity)

    def test_a_derived_platform_ref_is_set_by_the_manifest_and_a_candidate_is_not_exported(self):
        _row('transcriber:canary-test', hf_id='nvidia/canary-test', source='transcriber')
        _row('proposed:ollama:gemma4:12b', name='gemma4:12b', source='ollama', is_proposed=True)
        with self._spy() as spy:
            call_command('backfill_platform_refs', '--ecrire', stdout=mock.MagicMock())
        calls = {c.args[0]: c for c in spy.call_args_list}
        self.assertEqual('huggingface:nvidia/canary-test',
                         AIModel.objects.get(model_key='transcriber:canary-test').platform_ref)
        self.assertEqual('ollama:gemma4',
                         AIModel.objects.get(model_key='proposed:ollama:gemma4:12b').platform_ref)
        self.assertIs(True, calls['transcriber:canary-test'].kwargs['export'])
        self.assertIs(False, calls['proposed:ollama:gemma4:12b'].kwargs['export'])

    def test_the_licence_pass_writes_the_access_regime_by_the_manifest(self):
        _row('huggingface:org/gate', hf_id='org/gate')
        card = {'license': 'apache-2.0', 'author': 'org', 'platform_ref': 'huggingface:org/gate',
                'hf_id': 'org/gate', 'gated': 'auto', 'publications': ['2601.14251'],
                'declared': {'capabilities': {}, 'engine': ''}}
        with mock.patch.object(provenance, 'huggingface_identity', return_value=card), \
                self._spy() as spy:
            call_command('backfill_platform_refs', '--licenses', '--ecrire',
                         stdout=mock.MagicMock())
        row = AIModel.objects.get(model_key='huggingface:org/gate')
        self.assertEqual(('apache-2.0', 'org', 'auto', ['2601.14251']),
                         (row.license, row.author, row.gated, row.extra_info.get('publications')))
        self.assertIn('huggingface:org/gate', [c.args[0] for c in spy.call_args_list])


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
