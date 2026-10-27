"""`platform_ref` seul — le dépôt du Hub se DÉRIVE, le modèle canonique d'un GGUF a son nom (2026-10-27).

Décision de Fabien : « si `hf_id` est un résidu historique, il faut aligner et ne garder que
`platform_ref` ». Mesuré le jour même : 397 lignes sur 398 portaient la même valeur des deux côtés ;
la seule différente était un GGUF du Hub tiré par Ollama, où `hf_id` disait le modèle qu'il EST
(ce que le banc apparie) et `platform_ref` le dépôt d'où viennent ses poids. Le même fait vivait en
plus sous trois noms dans les déclarations (`hf_id`, `hf_model_id`, `model_id` du describer).

Gardé ici :
  • l'accesseur unique (`external_sources.hf_repo`, `AIModel.hf_repo`, `ModelInfo.hf_repo`) ;
  • le modèle canonique d'une quantification (`base_model` + `base_model_relation`, vocabulaire du
    Hub) — lu par le banc et la prospection, jamais pris pour la dorsale d'un adaptateur ;
  • la synchro écrit `platform_ref`, et la paire `base_model` survit à une découverte muette ;
  • le manifeste porte la paire et la projette ;
  • aucun LECTEUR de `hf_id` ne revient (relevé par AST, budget qui ne peut que descendre) ;
  • la migration `0029`.
"""
import ast
import importlib
import re
from pathlib import Path

from django.apps import apps as django_apps
from django.conf import settings
from django.test import SimpleTestCase, TestCase

from wama.common.external_sources import hf_platform_ref, hf_repo
from wama.model_manager.models import AIModel

GGUF_KEY = 'ollama:hf.co/Repack/Canon-4B-GGUF:Q6_K'
GGUF_INFO = {'base_model': 'Org/Canon-4B', 'base_model_relation': 'quantized'}


def _gguf_row(**extra):
    return AIModel.objects.create(model_key=GGUF_KEY, name='hf.co/Repack/Canon-4B-GGUF:Q6_K',
                                  model_type='ocr', source='ollama', is_downloaded=True,
                                  platform_ref='huggingface:Repack/Canon-4B-GGUF',
                                  extra_info=dict(GGUF_INFO), **extra)


class HubRepositoryAccessorTest(SimpleTestCase):

    def test_the_repository_is_read_from_a_hub_platform_ref_only(self):
        self.assertEqual('Org/Name', hf_repo('huggingface:Org/Name'))
        self.assertEqual('', hf_repo('github:Org/Name'))
        self.assertEqual('', hf_repo('ollama:glm-ocr'))
        self.assertEqual('', hf_repo(''))
        self.assertEqual('', hf_repo(None))

    def test_a_repository_writes_back_to_its_platform_ref(self):
        self.assertEqual('huggingface:Org/Name', hf_platform_ref('Org/Name'))
        self.assertEqual('', hf_platform_ref(''))
        self.assertEqual('Org/Name', hf_repo(hf_platform_ref('Org/Name')))

    def test_a_catalogue_row_derives_its_repository_and_ignores_the_residual_column(self):
        self.assertEqual('Org/Name', AIModel(platform_ref='huggingface:Org/Name').hf_repo)
        # The column is a residue nobody reads: a row carrying only it has no repository.
        self.assertEqual('', AIModel(hf_id='Org/Name').hf_repo)

    def test_a_discovery_record_derives_its_repository(self):
        from wama.model_manager.models import ModelSource, ModelType
        from wama.model_manager.services.model_registry import ModelInfo
        info = ModelInfo(id='x', name='x', model_type=ModelType.LLM, source=ModelSource.HUGGINGFACE,
                         platform_ref='huggingface:Org/Name')
        self.assertEqual('Org/Name', info.hf_repo)
        self.assertEqual('', ModelInfo(id='y', name='y', model_type=ModelType.LLM,
                                       source=ModelSource.HUGGINGFACE).hf_repo)


class QuantizedBaseTest(TestCase):

    def test_a_quantization_names_the_model_it_is(self):
        self.assertEqual('Org/Canon-4B', AIModel(extra_info=dict(GGUF_INFO)).quantized_base)

    def test_an_adapter_backbone_is_not_the_model_itself(self):
        lora = AIModel(extra_info={'base_model': 'Org/Backbone', 'model_type': 'lora'})
        self.assertEqual('', lora.quantized_base)

    def test_the_bench_pairs_a_gguf_with_its_canonical_model_but_not_a_lora_with_its_backbone(self):
        from wama.model_manager.services.benchmark_sync import _local_repos
        self.assertEqual({'repack/canon-4b-gguf', 'org/canon-4b'}, _local_repos(_gguf_row()))
        lora = AIModel(model_key='imager:lora', platform_ref='huggingface:Org/Lora',
                       extra_info={'base_model': 'Org/Backbone', 'model_type': 'lora'})
        self.assertEqual({'org/lora'}, _local_repos(lora))

    def test_prospection_counts_the_canonical_model_of_an_installed_gguf_as_ours(self):
        from wama.model_manager.services.prospector import catalogue_repos
        _gguf_row()
        AIModel.objects.create(model_key='imager:residue', name='r', model_type='diffusion',
                               source='imager', hf_id='Org/OnlyTheColumn')
        have = catalogue_repos(AIModel.objects.all())
        self.assertIn('org/canon-4b', have)
        self.assertIn('repack/canon-4b-gguf', have)
        self.assertNotIn('org/onlythecolumn', have, 'the residual column is read by nobody')

    def test_a_quantization_carries_no_backbone_footprint(self):
        from wama.model_manager.services.memory_manager import backbone_row
        AIModel.objects.create(model_key='huggingface:Org/Canon-4B', name='Canon', model_type='ocr',
                               source='huggingface', platform_ref='huggingface:Org/Canon-4B')
        self.assertIsNone(backbone_row(_gguf_row()))
        backbone = AIModel.objects.create(model_key='imager:backbone', name='b',
                                          model_type='diffusion', source='imager',
                                          platform_ref='huggingface:Org/Backbone')
        lora = AIModel(model_key='imager:lora', platform_ref='huggingface:Org/Lora',
                       extra_info={'base_model': 'Org/Backbone', 'model_type': 'lora'})
        self.assertEqual(backbone.pk, backbone_row(lora).pk)


class HubGgufIdentityNamesItsBaseTest(SimpleTestCase):

    def test_an_identical_base_adds_nothing(self):
        from wama.model_manager.services.provenance import identity_for_spec
        self.assertEqual({'platform_ref': 'huggingface:Org/Model-GGUF'},
                         identity_for_spec({'kind': 'ollama', 'ref': 'hf.co/Org/Model-GGUF:Q4_K_M',
                                            'base_model': 'org/model-gguf'}))

    def test_the_hub_identity_no_longer_carries_hf_id(self):
        from wama.model_manager.services.provenance import cloud_identity
        self.assertEqual({'platform_ref': 'huggingface:BAAI/bge-m3'},
                         cloud_identity({'aliases': ['bge-m3', 'BAAI/bge-m3']}))


class SyncWritesThePlatformRefTest(TestCase):

    def _info(self, **kw):
        from wama.model_manager.models import ModelSource, ModelType
        from wama.model_manager.services.model_registry import ModelInfo
        return ModelInfo(id='m', name='M', model_type=ModelType.SPEECH,
                         source=ModelSource.WAMA_TRANSCRIBER, **kw)

    def test_the_declared_platform_ref_reaches_the_row_and_the_column_is_not_written(self):
        from wama.model_manager.services.model_sync import ModelSyncService
        ModelSyncService()._sync_model('transcriber:m', self._info(platform_ref='huggingface:Org/M'))
        row = AIModel.objects.get(model_key='transcriber:m')
        self.assertEqual(('huggingface:Org/M', ''), (row.platform_ref, row.hf_id))

    def test_a_silent_discovery_does_not_erase_a_known_platform_ref(self):
        from wama.model_manager.services.model_sync import ModelSyncService
        AIModel.objects.create(model_key='transcriber:m', name='M', model_type='speech',
                               source='transcriber', platform_ref='huggingface:Org/M')
        ModelSyncService()._sync_model('transcriber:m', self._info())
        self.assertEqual('huggingface:Org/M',
                         AIModel.objects.get(model_key='transcriber:m').platform_ref)

    def test_the_base_model_pair_survives_a_discovery_that_does_not_know_it(self):
        from wama.model_manager.models import ModelSource, ModelType
        from wama.model_manager.services.model_registry import ModelInfo
        from wama.model_manager.services.model_sync import ModelSyncService
        _gguf_row()
        ollama = ModelInfo(id=GGUF_KEY, name='hf.co/Repack/Canon-4B-GGUF:Q6_K',
                           model_type=ModelType.OCR, source=ModelSource.OLLAMA,
                           extra_info={'ollama_id': 'abc'})
        ModelSyncService()._sync_model(GGUF_KEY, ollama)
        info = AIModel.objects.get(model_key=GGUF_KEY).extra_info
        self.assertEqual(GGUF_INFO, {k: info.get(k) for k in GGUF_INFO})
        self.assertEqual('abc', info.get('ollama_id'))

    def test_an_adapter_backbone_stays_under_the_authority_of_its_declaration(self):
        """Counter-check: without the relation, `base_model` is the app's declaration — a
        discovery that drops it is followed, not overridden by the previous value."""
        from wama.model_manager.services.model_sync import ModelSyncService
        AIModel.objects.create(model_key='transcriber:m', name='M', model_type='speech',
                               source='transcriber', extra_info={'base_model': 'Org/Old'})
        ModelSyncService()._sync_model('transcriber:m', self._info(extra_info={'path': '/p'}))
        self.assertNotIn('base_model', AIModel.objects.get(model_key='transcriber:m').extra_info)


class ManifestCarriesTheBasePairTest(TestCase):

    def test_the_pair_is_extracted_into_the_identity_and_out_of_extra_info(self):
        from wama.common.manifests.builtin.model import extract_model
        _gguf_row()
        body = extract_model(GGUF_KEY)['body']
        self.assertEqual(GGUF_INFO, {k: body['identity'].get(k) for k in GGUF_INFO})
        self.assertFalse(set(GGUF_INFO) & set(body['extra_info']))

    def test_a_declared_pair_is_projected_into_extra_info(self):
        from wama.common.manifests.builtin.model import write_back_model
        row = _gguf_row()
        row.extra_info = {'ollama_id': 'abc'}
        row.save()
        write_back_model({'key': GGUF_KEY, 'body': {'identity': {
            'platform_ref': 'huggingface:Repack/Canon-4B-GGUF', **GGUF_INFO}}}, apply=True)
        row.refresh_from_db()
        self.assertEqual({'ollama_id': 'abc', **GGUF_INFO}, row.extra_info)
        self.assertEqual('Org/Canon-4B', row.quantized_base)

    def test_the_pair_is_validated(self):
        from wama.common.manifests.builtin.model import validate_model_body
        self.assertEqual([], validate_model_body({'identity': dict(GGUF_INFO)}))
        self.assertTrue(validate_model_body({'identity': {'base_model': 'Org/Canon-4B'}}),
                        'a base without its relation says nothing')
        self.assertTrue(validate_model_body({'identity': {'base_model': 'Org/Canon-4B',
                                                          'base_model_relation': 'cousin'}}))
        self.assertTrue(validate_model_body({'identity': {'base_model': 'not-a-repo',
                                                          'base_model_relation': 'quantized'}}))


#: Les sites STRUCTURELS de `hf_id` qui restent, par fichier — attribut, argument nommé ou chaîne,
#: relevés par AST hors tests, migrations et jumelles. Tous appartiennent à la couche MANIFESTE
#: (`identity.hf_id` du corpus, son extraction, sa projection, ses producteurs wama-dev-ai, et la
#: copie `extra_info['hf_id']` que les manifestes portent) : ils partent avec elle, dans la session
#: des manifestes (décision de Fabien, 2026-10-27). Ce budget ne peut que DESCENDRE, et il ne garde
#: pas de marge — une marge est une autorisation d'en ajouter.
HF_ID_BUDGET = {
    'wama-dev-ai/role_utils.py': 3,
    'wama-dev-ai/run_model_manifest.py': 1,
    'wama-dev-ai/run_scout.py': 3,
    'wama/common/manifests/builtin/model.py': 4,
    'wama/model_manager/models.py': 1,
    'wama/model_manager/services/model_registry.py': 3,
}

_TWIN = re.compile(r'^[a-z_]+_\d\d$')


def hf_id_sites(root: Path) -> dict:
    """{fichier: nombre de sites structurels de `hf_id`} — la mesure que `HF_ID_BUDGET` fige."""
    found = {}
    for base in ('wama', 'wama_lab', 'wama_data', 'wama-dev-ai'):
        for path in (root / base).rglob('*.py'):
            parts = path.relative_to(root).parts
            if ('migrations' in parts or '__pycache__' in parts or 'tests' in parts
                    or path.name == 'tests.py' or path.name.startswith(('tests_', 'test_'))
                    or any(_TWIN.match(part) for part in parts)):
                continue
            try:
                tree = ast.parse(path.read_text(encoding='utf-8'))
            except SyntaxError:
                continue
            n = sum(1 for node in ast.walk(tree) if (
                (isinstance(node, ast.Attribute) and node.attr == 'hf_id')
                or (isinstance(node, ast.keyword) and node.arg
                    and (node.arg == 'hf_id' or node.arg.startswith('hf_id__')))
                or (isinstance(node, ast.Constant) and isinstance(node.value, str)
                    and (node.value in ('hf_id', 'hf_model_id') or node.value.startswith('hf_id__')))))
            if n:
                found[path.relative_to(root).as_posix()] = n
    return found


class NoReaderOfHfIdComesBackTest(SimpleTestCase):

    def test_hf_id_lives_only_in_the_manifest_layer_and_the_budget_has_no_slack(self):
        measured = hf_id_sites(Path(settings.BASE_DIR))
        over = {f: n for f, n in measured.items() if n > HF_ID_BUDGET.get(f, 0)}
        self.assertEqual({}, over, "`hf_id` is back: read `platform_ref` (`hf_repo`) or "
                                   "`quantized_base`, declare `platform_ref`")
        slack = {f: (HF_ID_BUDGET[f], measured.get(f, 0)) for f in HF_ID_BUDGET
                 if measured.get(f, 0) < HF_ID_BUDGET[f]}
        self.assertEqual({}, slack, 'lower HF_ID_BUDGET to the measure')


class MigrationNamesTheFactsTest(TestCase):
    """`model_manager/0029` : le canonique d'un GGUF et la clé des variantes des candidats."""

    def _module(self):
        return importlib.import_module('wama.model_manager.migrations.0029_hf_id_facts_to_their_names')

    def test_a_gguf_whose_hf_id_differs_gets_its_base_model_pair(self):
        row = AIModel.objects.create(model_key=GGUF_KEY, name='g', model_type='ocr', source='ollama',
                                     platform_ref='huggingface:Repack/Canon-4B-GGUF',
                                     hf_id='Org/Canon-4B', extra_info={'ollama_id': 'abc'})
        self._module().facts_under_their_names(django_apps, None)
        row.refresh_from_db()
        self.assertEqual({'ollama_id': 'abc', **GGUF_INFO}, row.extra_info)
        self._module().facts_back_to_hf_id(django_apps, None)
        row.refresh_from_db()
        self.assertEqual({'ollama_id': 'abc'}, row.extra_info)

    def test_rows_that_are_not_a_hub_gguf_are_left_alone(self):
        same = AIModel.objects.create(model_key='ollama:hf.co/Org/Same-GGUF:Q4', name='s',
                                      model_type='ocr', source='ollama',
                                      platform_ref='huggingface:Org/Same-GGUF', hf_id='org/same-gguf')
        other = AIModel.objects.create(model_key='imager:other', name='o', model_type='diffusion',
                                       source='imager', platform_ref='huggingface:Org/A',
                                       hf_id='Org/B')
        self._module().facts_under_their_names(django_apps, None)
        for row in (same, other):
            row.refresh_from_db()
            self.assertNotIn('base_model', row.extra_info or {}, row.model_key)

    def test_the_variants_of_a_candidate_are_keyed_by_repo_id_and_back(self):
        cand = AIModel.objects.create(
            model_key='proposed:hf:Org/Big', name='Big', model_type='llm', source='huggingface',
            is_proposed=True, extra_info={'prospect': {'quant_variants': [
                {'hf_id': 'Repack/Big-GGUF', 'disk_gb': 4.0}]}})
        self._module().facts_under_their_names(django_apps, None)
        cand.refresh_from_db()
        self.assertEqual([{'repo_id': 'Repack/Big-GGUF', 'disk_gb': 4.0}],
                         cand.extra_info['prospect']['quant_variants'])
        self._module().facts_back_to_hf_id(django_apps, None)
        cand.refresh_from_db()
        self.assertEqual([{'hf_id': 'Repack/Big-GGUF', 'disk_gb': 4.0}],
                         cand.extra_info['prospect']['quant_variants'])
