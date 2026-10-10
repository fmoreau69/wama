"""A Hub GGUF installed BY OLLAMA through the existing install route (2026-10-10).

Measured that day: the best OCR models (PaddleOCR-VL-1.6, Chandra-OCR-2, LightOnOCR-3) have
architectures missing from our transformers 4.57 — but they are published as GGUF, and Ollama runs
them (like Qwen 3.5 / 3.6 MoE). The route had every piece but one gesture: choosing a GGUF variant
of a Hugging Face proposal downloaded the file alone, which nothing reads. When an Ollama backend
executes the model's task, the same choice now becomes `ollama pull hf.co/<repo>[:<quant>]`, run by
the Ollama branch of `install_candidate`; the catalogue row gets its task from the declared family
(`FAMILLES_OLLAMA`, read on the repository name), and `GlmOcrBackend` serves it by its key.
"""
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase, TestCase

from wama.model_manager.models import AIModel
from wama.model_manager.services import prospector as p


class GgufQuantTest(SimpleTestCase):

    def test_the_quantisation_is_read_from_the_file_name(self):
        for name, quant in (('PaddleOCR-VL-1.6-q4_k_m.gguf', 'Q4_K_M'),
                            ('chandra-ocr-2.Q4_K_M.gguf', 'Q4_K_M'),
                            ('LightOnOCR-3-1B-IQ3_M.gguf', 'IQ3_M'),
                            ('PaddleOCR-VL-1.6-bf16.gguf', 'BF16')):
            with self.subTest(name=name):
                self.assertEqual(quant, p._gguf_quant(name))

    def test_a_single_file_repository_has_no_label(self):
        # Ollama then takes the repository's default file.
        self.assertEqual('', p._gguf_quant('PaddleOCR-VL-1.6-GGUF.gguf'))


def _candidate(task='ocr'):
    files = [{'file': 'PaddleOCR-VL-1.6-q4_k_m.gguf', 'gb': 0.4},
             {'file': 'mmproj-Q8_0.gguf', 'gb': 0.6}]
    return AIModel.objects.create(
        model_key='proposed:hf:PaddlePaddle/PaddleOCR-VL-1.6', name='PaddleOCR-VL-1.6',
        model_type='ocr', source='huggingface', is_proposed=True, proposal_kind='new',
        hf_id='PaddlePaddle/PaddleOCR-VL-1.6', disk_gb=1.8, capabilities={'task': task},
        extra_info={'prospect': {
            'spec': {'kind': 'hf', 'ref': 'PaddlePaddle/PaddleOCR-VL-1.6', 'category': 'ocr',
                     'task': task},
            'quant_variants': [{'hf_id': 'Mungert/PaddleOCR-VL-1.6-GGUF', 'disk_gb': 1.0,
                                'files': files}]}})


class VariantChoiceTest(TestCase):

    def test_a_gguf_of_an_ollama_run_task_installs_by_ollama(self):
        cand = _candidate('ocr')
        spec = p.spec_for_choice(cand, 'Mungert/PaddleOCR-VL-1.6-GGUF', 'PaddleOCR-VL-1.6-q4_k_m.gguf')
        self.assertEqual({'kind': 'ollama', 'ref': 'hf.co/Mungert/PaddleOCR-VL-1.6-GGUF:Q4_K_M',
                          'task': 'ocr', 'base_hf_id': 'PaddlePaddle/PaddleOCR-VL-1.6'},
                         {k: spec[k] for k in ('kind', 'ref', 'task', 'base_hf_id')})

    def test_a_gguf_of_a_task_no_ollama_backend_runs_stays_a_hub_download(self):
        # Counter-check: MiniMax-Music3's GGUF is read by audio.cpp, not Ollama — unchanged.
        cand = _candidate('text-to-music')
        spec = p.spec_for_choice(cand, 'Mungert/PaddleOCR-VL-1.6-GGUF', 'PaddleOCR-VL-1.6-q4_k_m.gguf')
        self.assertEqual('hf', spec['kind'])
        self.assertIn('PaddleOCR-VL-1.6-q4_k_m.gguf', spec['allow_patterns'])

    def test_the_vision_projector_is_not_offered_as_a_variant(self):
        options = p.install_options(_candidate('ocr'))['options']
        files = [o['file'] for o in options if o['file']]
        self.assertEqual(['PaddleOCR-VL-1.6-q4_k_m.gguf'], files)
        self.assertEqual('ollama', options[1]['driver'])


class OllamaBranchPullsTheChosenNameTest(TestCase):

    def test_install_candidate_pulls_the_hub_name_and_records_its_task(self):
        from wama.model_manager.services import model_installer as mi
        cand = _candidate('ocr')
        spec = p.spec_for_choice(cand, 'Mungert/PaddleOCR-VL-1.6-GGUF', 'PaddleOCR-VL-1.6-q4_k_m.gguf')
        info = dict(cand.extra_info)
        info['prospect'] = dict(info['prospect'], spec=spec)
        cand.extra_info = info
        cand.save(update_fields=['extra_info'])
        with patch.object(mi, 'pull_ollama_model', return_value={'ok': True}) as pull, \
                patch.object(mi, 'record_provenance', return_value={}) as record:
            res = mi.install_candidate(cand)
        pull.assert_called_once()
        self.assertEqual('hf.co/Mungert/PaddleOCR-VL-1.6-GGUF:Q4_K_M', pull.call_args.args[0])
        recorded = record.call_args.args[0]
        self.assertEqual(('ollama', 'hf.co/Mungert/PaddleOCR-VL-1.6-GGUF:Q4_K_M', 'ocr',
                          'PaddlePaddle/PaddleOCR-VL-1.6'),
                         (recorded['kind'], recorded['ref'], recorded['task'],
                          recorded['base_hf_id']))
        self.assertTrue(res['ok'])

    def test_an_ollama_library_candidate_still_pulls_its_own_name(self):
        # Counter-check: a candidate from the Ollama library carries no descriptor.
        from wama.model_manager.services import model_installer as mi
        cand = AIModel.objects.create(model_key='proposed:ollama:qwen3.8:latest',
                                      name='qwen3.8:latest', model_type='llm', source='ollama',
                                      is_proposed=True, proposal_kind='new',
                                      extra_info={'prospect': {'kind': 'new'}})
        with patch.object(mi, 'pull_ollama_model', return_value={'ok': True}) as pull, \
                patch.object(mi, 'record_provenance', return_value={}):
            mi.install_candidate(cand)
        self.assertEqual('qwen3.8:latest', pull.call_args.args[0])


class HubGgufIdentityTest(SimpleTestCase):

    def test_it_comes_from_the_gguf_repository_and_is_the_canonical_model(self):
        from wama.model_manager.services.provenance import identity_for_spec
        ident = identity_for_spec({'kind': 'ollama', 'ref': 'hf.co/Mungert/PaddleOCR-VL-1.6-GGUF:Q4_K_M',
                                   'base_hf_id': 'PaddlePaddle/PaddleOCR-VL-1.6'})
        self.assertEqual({'platform_ref': 'huggingface:Mungert/PaddleOCR-VL-1.6-GGUF',
                          'hf_id': 'PaddlePaddle/PaddleOCR-VL-1.6'}, ident)

    def test_a_library_tag_keeps_its_ollama_identity(self):
        from wama.model_manager.services.provenance import identity_for_spec
        self.assertEqual({'platform_ref': 'ollama:glm-ocr'},
                         identity_for_spec({'kind': 'ollama', 'ref': 'glm-ocr:latest'}))


class DeclaredFamilyOfAHubGgufTest(SimpleTestCase):

    def test_the_family_is_read_on_the_repository_name(self):
        from wama.model_manager.services.model_registry import ModelRegistry, _ollama_family
        self.assertEqual('paddleocr-vl-1.6-gguf',
                         _ollama_family('hf.co/Mungert/PaddleOCR-VL-1.6-GGUF:Q4_K_M'))
        self.assertEqual('glm-ocr', _ollama_family('glm-ocr:latest'))
        caps = ModelRegistry._capacites_canoniques({'completion', 'vision'},
                                                   'hf.co/Mungert/PaddleOCR-VL-1.6-GGUF:Q4_K_M')
        self.assertEqual('ocr', caps['task'])

    def test_an_undeclared_hub_gguf_stays_a_chat_model(self):
        # Counter-check: no declaration, no guess.
        from wama.model_manager.services.model_registry import ModelRegistry
        caps = ModelRegistry._capacites_canoniques({'completion'},
                                                   'hf.co/someone/Some-Chat-7B-GGUF:Q4_K_M')
        self.assertEqual('text-generation', caps['task'])


class OllamaOcrBackendAvailabilityTest(SimpleTestCase):

    def test_available_when_the_daemon_answers_whatever_ocr_model_it_holds(self):
        from wama.common.backends.glm_ocr_backend import GlmOcrBackend
        from wama.common.utils import ollama_host
        with patch.object(ollama_host._MoteurOllama, 'missing_packages', return_value=[]):
            self.assertTrue(GlmOcrBackend.is_available())
        with patch.object(ollama_host._MoteurOllama, 'missing_packages',
                          return_value=['démon Ollama injoignable']):
            self.assertFalse(GlmOcrBackend.is_available())


class InstallOptionsToolTest(TestCase):

    def test_the_assistant_reads_the_choices_of_the_page(self):
        from django.contrib.auth import get_user_model
        from wama import tool_api
        _candidate('ocr')
        user = get_user_model().objects.create_user('install_options_tool', password='x')
        out = tool_api.get_install_options(user, 'proposed:hf:PaddlePaddle/PaddleOCR-VL-1.6')
        self.assertTrue(out['choice'])
        self.assertEqual(['full', 'variant_file'], [o['kind'] for o in out['options']])
        self.assertEqual('ollama', out['options'][1]['driver'])

    def test_the_read_tool_does_not_write(self):
        # get_ai_model is open to every account: it must not call the Hub nor write the proposal.
        from django.contrib.auth import get_user_model
        from wama import tool_api
        _candidate('ocr')
        user = get_user_model().objects.create_user('read_only_model', password='x')
        with patch.object(p, 'install_options') as options:
            out = tool_api.get_ai_model(user, 'proposed:hf:PaddlePaddle/PaddleOCR-VL-1.6')
        options.assert_not_called()
        self.assertNotIn('install_options', out)
