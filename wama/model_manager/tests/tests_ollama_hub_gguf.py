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
        platform_ref='huggingface:PaddlePaddle/PaddleOCR-VL-1.6', disk_gb=1.8, capabilities={'task': task},
        extra_info={'prospect': {
            'spec': {'kind': 'hf', 'ref': 'PaddlePaddle/PaddleOCR-VL-1.6', 'category': 'ocr',
                     'task': task},
            'own_gguf': [],                    # the canonical repository holds no GGUF
            'quant_variants': [{'repo_id': 'Mungert/PaddleOCR-VL-1.6-GGUF', 'disk_gb': 1.0,
                                'files': files}]}})


class VariantChoiceTest(TestCase):

    def test_a_gguf_of_an_ollama_run_task_installs_by_ollama(self):
        cand = _candidate('ocr')
        spec = p.spec_for_choice(cand, 'Mungert/PaddleOCR-VL-1.6-GGUF', 'PaddleOCR-VL-1.6-q4_k_m.gguf')
        self.assertEqual({'kind': 'ollama', 'ref': 'hf.co/Mungert/PaddleOCR-VL-1.6-GGUF:Q4_K_M',
                          'task': 'ocr', 'base_model': 'PaddlePaddle/PaddleOCR-VL-1.6'},
                         {k: spec[k] for k in ('kind', 'ref', 'task', 'base_model')})

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
                          recorded['base_model']))
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
                                   'base_model': 'PaddlePaddle/PaddleOCR-VL-1.6'})
        self.assertEqual({'platform_ref': 'huggingface:Mungert/PaddleOCR-VL-1.6-GGUF',
                          'base_model': 'PaddlePaddle/PaddleOCR-VL-1.6',
                          'base_model_relation': 'quantized'}, ident)

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
        user = get_user_model().objects.create_superuser('install_options_tool', password='x')
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


class SimilarKeysOnRefusalTest(TestCase):
    """Rejeu du 2026-10-10 : Albert a recomposé `reader:hf:org/dépôt` au lieu de la clé
    `proposed:hf:org/dépôt` écrite par l'utilisateur ; le refus ne disait pas laquelle existait."""

    def test_the_refusal_names_the_proposal_of_the_same_repository(self):
        from django.contrib.auth import get_user_model
        from wama import tool_api
        _candidate('ocr')
        user = get_user_model().objects.create_superuser('similar_keys', password='x')
        for out in (tool_api.install_model(user, 'reader:hf:PaddlePaddle/PaddleOCR-VL-1.6'),
                    tool_api.get_install_options(user, 'reader:hf:PaddlePaddle/PaddleOCR-VL-1.6')):
            self.assertEqual(['proposed:hf:PaddlePaddle/PaddleOCR-VL-1.6'], out['similar_keys'])

    def test_a_variant_asked_as_a_key_names_the_proposal_that_carries_it(self):
        # Thread n° 41: Albert asked `proposed:hf:<variant repo>` — refused without the owner.
        from django.contrib.auth import get_user_model
        from wama import tool_api
        _candidate('ocr')
        user = get_user_model().objects.create_superuser('variant_as_key', password='x')
        out = tool_api.install_model(user, 'proposed:hf:Mungert/PaddleOCR-VL-1.6-GGUF')
        self.assertEqual(['proposed:hf:PaddlePaddle/PaddleOCR-VL-1.6'], out['similar_keys'])
        self.assertIn('variant_ref=Mungert/PaddleOCR-VL-1.6-GGUF', out['error'])

    def test_nothing_alike_adds_nothing(self):
        """Contre-épreuve : pas de voisin, pas de champ."""
        from django.contrib.auth import get_user_model
        from wama import tool_api
        user = get_user_model().objects.create_superuser('no_similar_keys', password='x')
        out = tool_api.install_model(user, 'reader:hf:nobody/nothing')
        self.assertEqual('not_found', out['reason'])
        self.assertNotIn('similar_keys', out)


def _gguf_repo_candidate(files=None, projector=True):
    """A proposal whose repository IS a GGUF repository — what a targeted search writes
    (`mradermacher/PaddleOCR-VL-1.6-GGUF`, thread n° 38, 2026-10-11)."""
    prospect = {'spec': {'kind': 'hf', 'ref': 'mradermacher/PaddleOCR-VL-1.6-GGUF',
                         'category': 'ocr', 'task': 'ocr'},
                'quant_variants': []}
    if files is not None:
        prospect['own_gguf'] = files
        prospect['own_projector'] = projector
    return AIModel.objects.create(
        model_key='proposed:hf:mradermacher/PaddleOCR-VL-1.6-GGUF', name='PaddleOCR-VL-1.6-GGUF',
        model_type='ocr', source='huggingface', is_proposed=True, proposal_kind='new',
        platform_ref='huggingface:mradermacher/PaddleOCR-VL-1.6-GGUF', disk_gb=4.1, capabilities={'task': 'ocr'},
        extra_info={'prospect': prospect})


TWO_FILES = [{'file': 'PaddleOCR-VL-1.6.Q8_0.gguf', 'gb': 0.6},
             {'file': 'PaddleOCR-VL-1.6.Q4_K_M.gguf', 'gb': 0.4}]


class GgufRepositoryCandidateTest(TestCase):
    """Its "full weights" pulled the WHOLE repository through the Hub (4.1 GB, every quantisation)
    into a folder nothing reads; its own files were never offered."""

    def test_its_own_files_are_the_choices_by_ollama_and_there_is_no_full_weights(self):
        options = p.install_options(_gguf_repo_candidate(TWO_FILES))['options']
        self.assertEqual([('variant_file', 'ollama', 'PaddleOCR-VL-1.6.Q8_0.gguf'),
                          ('variant_file', 'ollama', 'PaddleOCR-VL-1.6.Q4_K_M.gguf')],
                         [(o['kind'], o['driver'], o['file']) for o in options])

    def test_choosing_one_of_its_files_pulls_it_by_ollama(self):
        cand = _gguf_repo_candidate(TWO_FILES)
        spec = p.spec_for_choice(cand, cand.hf_repo, 'PaddleOCR-VL-1.6.Q8_0.gguf')
        self.assertEqual(('ollama', 'hf.co/mradermacher/PaddleOCR-VL-1.6-GGUF:Q8_0'),
                         (spec['kind'], spec['ref']))
        self.assertIsNone(p.spec_for_choice(cand, cand.hf_repo, None))
        self.assertIsNone(p.spec_for_choice(cand, cand.hf_repo, 'not-listed.Q2_K.gguf'))

    def test_the_installed_row_is_the_canonical_model_its_card_states(self):
        # Thread n° 41: installed from the GGUF repository, the row carried the publisher's repo —
        # the benchmark (exact repository) could not match it.
        cand = _gguf_repo_candidate(TWO_FILES)
        info = dict(cand.extra_info)
        info['prospect'] = dict(info['prospect'], base_model='PaddlePaddle/PaddleOCR-VL-1.6')
        cand.extra_info = info
        spec = p.spec_for_choice(cand, cand.hf_repo, 'PaddleOCR-VL-1.6.Q8_0.gguf')
        self.assertEqual('PaddlePaddle/PaddleOCR-VL-1.6', spec['base_model'])
        # Counter-check: a merge of several bases is the canonical of none.
        info['prospect']['base_model'] = ['a/one', 'b/two']
        spec = p.spec_for_choice(cand, cand.hf_repo, 'PaddleOCR-VL-1.6.Q8_0.gguf')
        self.assertEqual('mradermacher/PaddleOCR-VL-1.6-GGUF', spec['base_model'])

    def test_the_files_are_read_once_from_the_hub_and_kept(self):
        cand = _gguf_repo_candidate(None)
        siblings = [('PaddleOCR-VL-1.6.Q8_0.gguf', 600 * 1024 ** 2),
                    ('mmproj-f16.gguf', 800 * 1024 ** 2), ('README.md', 10)]
        with patch.object(p, '_siblings', return_value=siblings):
            p.install_options(cand)
        cand.refresh_from_db()
        self.assertEqual([{'file': 'PaddleOCR-VL-1.6.Q8_0.gguf', 'gb': 0.6}],
                         cand.extra_info['prospect']['own_gguf'])
        self.assertTrue(cand.extra_info['prospect']['own_projector'])


class VisionProjectorTest(TestCase):
    """Measured 2026-10-11: PaddleOCR-VL-1.6 and LightOnOCR-3-4B pulled from quantisation
    repositories WITHOUT `mmproj` — Ollama answered "image input is not supported", the Reader read
    nothing, and its "auto" had picked the blind model."""

    def test_a_gguf_repository_without_projector_offers_nothing_for_an_image_task(self):
        cand = _gguf_repo_candidate(TWO_FILES, projector=False)
        self.assertEqual([], p.install_options(cand)['options'])
        self.assertIsNone(p.spec_for_choice(cand, cand.hf_repo, 'PaddleOCR-VL-1.6.Q8_0.gguf'))

    def test_installing_it_is_refused_with_the_reason(self):
        from wama.model_manager.services import model_installer as mi
        _gguf_repo_candidate(TWO_FILES, projector=False)
        with patch.object(mi, 'dispatch_install') as dispatch:
            out = mi.request_install('proposed:hf:mradermacher/PaddleOCR-VL-1.6-GGUF')
        dispatch.assert_not_called()
        self.assertEqual('not_installable', out['reason'])
        self.assertIn('mmproj', out['error'])

    def test_a_variant_repository_without_projector_is_not_offered(self):
        cand = _candidate('ocr')
        info = dict(cand.extra_info)
        prospect = dict(info['prospect'])
        prospect['quant_variants'] = prospect['quant_variants'] + [
            {'repo_id': 'someone/PaddleOCR-VL-1.6-blind-GGUF', 'disk_gb': 0.5,
             'files': [{'file': 'PaddleOCR-VL-1.6.Q8_0.gguf', 'gb': 0.5}]}]
        info['prospect'] = prospect
        cand.extra_info = info
        cand.save(update_fields=['extra_info'])
        refs = [o['ref'] for o in p.install_options(cand)['options']]
        self.assertNotIn('someone/PaddleOCR-VL-1.6-blind-GGUF', refs)
        self.assertIn('Mungert/PaddleOCR-VL-1.6-GGUF', refs)       # counter-check: it has mmproj
        self.assertIsNone(p.spec_for_choice(cand, 'someone/PaddleOCR-VL-1.6-blind-GGUF',
                                            'PaddleOCR-VL-1.6.Q8_0.gguf'))

    def test_an_unreachable_hub_freezes_nothing(self):
        # Counter-check: an outage is not a fact — nothing persisted, full weights still offered.
        cand = _gguf_repo_candidate(None)
        with patch.object(p, '_siblings', return_value=None):
            options = p.install_options(cand)['options']
        self.assertEqual(['full'], [o['kind'] for o in options])
        cand.refresh_from_db()
        self.assertNotIn('own_gguf', cand.extra_info['prospect'])


class InstallWithoutVariantTest(TestCase):

    def test_several_files_are_refused_with_the_way_to_choose(self):
        from wama.model_manager.services import model_installer as mi
        _gguf_repo_candidate(TWO_FILES)
        with patch.object(mi, 'dispatch_install') as dispatch:
            out = mi.request_install('proposed:hf:mradermacher/PaddleOCR-VL-1.6-GGUF')
        dispatch.assert_not_called()
        self.assertEqual('variant_required', out['reason'])
        self.assertIn('get_install_options', out['error'])

    def test_a_single_file_is_taken_without_asking(self):
        from wama.model_manager.services import model_installer as mi
        cand = _gguf_repo_candidate(TWO_FILES[:1])
        with patch.object(mi, 'dispatch_install', return_value=SimpleNamespace(id='t')), \
                patch.object(mi, 'disk_space_guard', return_value=None):
            out = mi.request_install(cand.model_key)
        self.assertTrue(out['started'])
        cand.refresh_from_db()
        self.assertEqual('hf.co/mradermacher/PaddleOCR-VL-1.6-GGUF:Q8_0',
                         cand.extra_info['prospect']['spec']['ref'])

    def test_full_weights_next_to_ollama_files_are_not_taken_silently(self):
        # Thread n° 42: « installe PaddleOCR-VL-1.6 » without a variant pulled 1.8 GB of full
        # weights our transformers cannot read, while the official GGUF by Ollama was offered.
        from wama.model_manager.services import model_installer as mi
        cand = _candidate('ocr')
        with patch.object(mi, 'dispatch_install') as dispatch:
            out = mi.request_install(cand.model_key)
        dispatch.assert_not_called()
        self.assertEqual('variant_required', out['reason'])

    def test_a_canonical_proposal_still_installs_its_full_weights(self):
        # Counter-check: a task no Ollama backend runs keeps its full-weights default.
        from wama.model_manager.services import model_installer as mi
        cand = _candidate('text-to-music')
        with patch.object(mi, 'dispatch_install', return_value=SimpleNamespace(id='t')), \
                patch.object(mi, 'disk_space_guard', return_value=None):
            out = mi.request_install(cand.model_key)
        self.assertTrue(out['started'])
        cand.refresh_from_db()
        self.assertEqual('hf', cand.extra_info['prospect']['spec']['kind'])


class RetiredOllamaRowTest(TestCase):

    def test_reinstalling_it_says_it_comes_back_by_a_proposal(self):
        # Thread n° 41: « il se téléchargera au premier usage » was told as an installation done.
        from wama.model_manager.services import model_installer as mi
        AIModel.objects.create(model_key='ollama:hf.co/a/b-GGUF:Q8_0', name='hf.co/a/b-GGUF:Q8_0',
                               model_type='ocr', source='ollama', is_downloaded=False)
        out = mi.request_install('ollama:hf.co/a/b-GGUF:Q8_0')
        self.assertEqual('no_install_location', out['reason'])
        self.assertIn('PROPOSITION', out['error'])
        self.assertNotIn('premier usage »', out['error'])


class ModelsOfAnAppTest(TestCase):
    """Thread n° 38: `list_ai_models(app='reader', include_proposed=True)` returned two rows —
    the filter was the SOURCE, and a proposal's source is the platform."""

    def test_the_proposals_of_the_task_its_selector_covers_are_listed(self):
        from django.contrib.auth import get_user_model
        from wama import tool_api
        _candidate('ocr')
        AIModel.objects.create(model_key='proposed:hf:someone/some-tts', name='some-tts',
                               model_type='speech', source='huggingface', is_proposed=True,
                               proposal_kind='new', capabilities={'task': 'text-to-speech'})
        user = get_user_model().objects.create_user('models_of_app', password='x')
        keys = [m['key'] for m in tool_api.list_ai_models(user, app='reader',
                                                          include_proposed=True)['models']]
        self.assertIn('proposed:hf:PaddlePaddle/PaddleOCR-VL-1.6', keys)
        self.assertNotIn('proposed:hf:someone/some-tts', keys)   # counter-check: another task

    def test_a_row_without_modalities_is_read_by_those_its_task_implies(self):
        # Thread n° 40: `modality='image'` dropped every proposal (none carried modalities).
        from django.contrib.auth import get_user_model
        from wama import tool_api
        _candidate('ocr')
        user = get_user_model().objects.create_user('modality_of_task', password='x')
        image = [m['key'] for m in tool_api.list_ai_models(user, task='ocr', modality='image',
                                                           include_proposed=True)['models']]
        audio = [m['key'] for m in tool_api.list_ai_models(user, task='ocr', modality='audio',
                                                           include_proposed=True)['models']]
        self.assertIn('proposed:hf:PaddlePaddle/PaddleOCR-VL-1.6', image)
        self.assertNotIn('proposed:hf:PaddlePaddle/PaddleOCR-VL-1.6', audio)   # counter-check

    def test_a_model_is_found_by_the_words_of_its_name_or_key(self):
        """2026-10-28, « installe Phonon » played by the assistant : it sent `query='phonon'`, the
        tool had no such argument, and it received the whole catalogue in key order."""
        from django.contrib.auth import get_user_model
        from wama import tool_api
        AIModel.objects.create(model_key='huggingface:gradium/phonon-40m-fr', name='Phonon 40m (français)',
                               model_type='speech', source='huggingface', is_downloaded=False)
        AIModel.objects.create(model_key='synthesizer:kokoro-onnx', name='Kokoro ONNX',
                               model_type='speech', source='synthesizer', is_downloaded=True)
        user = get_user_model().objects.create_user('models_by_name', password='x')
        by_name = [m['key'] for m in tool_api.list_ai_models(user, query='Phonon fr')['models']]
        by_key = [m['key'] for m in tool_api.list_ai_models(user, query='gradium')['models']]
        self.assertEqual(['huggingface:gradium/phonon-40m-fr'], by_name, 'every word must appear')
        self.assertEqual(['huggingface:gradium/phonon-40m-fr'], by_key)
        self.assertEqual([], tool_api.list_ai_models(user, query='phonon kokoro')['models'])


class ProposalCapabilitiesTest(SimpleTestCase):

    def test_a_proposal_carries_what_its_task_implies(self):
        from wama.model_manager.models import default_inputs_for
        caps = p._task_capabilities({'languages': ['fr']}, 'ocr')
        self.assertEqual({**default_inputs_for('ocr'), 'task': 'ocr', 'languages': ['fr']}, caps)
        self.assertIn('image', caps['modalities'])

    def test_a_changed_task_does_not_inherit_the_old_modalities(self):
        # A VLM ranked on an OCR benchmark is proposed as OCR: its describer inputs go.
        from wama.model_manager.models import default_inputs_for
        before = p._task_capabilities({}, 'image-text-to-text')
        after = p._task_capabilities(before, 'ocr')
        self.assertEqual(default_inputs_for('ocr').get('inputs_required'),
                         after.get('inputs_required'))

    def test_no_task_no_guess(self):
        self.assertEqual({'languages': ['fr']}, p._task_capabilities({'languages': ['fr']}, ''))


class SearchGivesCatalogKeysTest(TestCase):

    def test_a_repository_already_proposed_comes_back_with_its_key(self):
        from django.contrib.auth import get_user_model
        from wama import tool_api
        _candidate('ocr')
        user = get_user_model().objects.create_superuser('search_keys', password='x')
        nothing_written = {'ok': True, 'query': 'q', 'created': 0, 'updated': 0, 'already': 0,
                           'skipped': 5, 'total': 0, 'refs': []}
        with patch.object(p, 'seed_hf_search', return_value=nothing_written):
            out = tool_api.search_models(user, 'PaddleOCR-VL-1.6')
            other = tool_api.search_models(user, 'Chandra-OCR-2')
        self.assertEqual(['proposed:hf:PaddlePaddle/PaddleOCR-VL-1.6'],
                         [m['key'] for m in out['catalog']])
        self.assertEqual([], other['catalog'])                  # counter-check: no match

    def test_a_word_the_catalogue_does_not_hold_does_not_hide_the_rest(self):
        # Thread n° 40: « PaddleOCR-VL-1.6 Ollama » returned nothing — no row holds « ollama ».
        from django.contrib.auth import get_user_model
        from wama import tool_api
        _candidate('ocr')
        user = get_user_model().objects.create_superuser('search_extra_word', password='x')
        nothing_written = {'ok': True, 'refs': []}
        with patch.object(p, 'seed_hf_search', return_value=nothing_written):
            out = tool_api.search_models(user, 'PaddleOCR-VL-1.6 Ollama')
        self.assertEqual(['proposed:hf:PaddlePaddle/PaddleOCR-VL-1.6'],
                         [m['key'] for m in out['catalog']])

    def test_a_hub_refusal_still_gives_the_catalogue_keys(self):
        from django.contrib.auth import get_user_model
        from wama import tool_api
        _candidate('ocr')
        user = get_user_model().objects.create_superuser('search_hub_down', password='x')
        refused = {'ok': False, 'error': 'HfHubHTTPError: 429 Client Error: Too Many Requests'}
        with patch.object(p, 'seed_hf_search', return_value=refused):
            out = tool_api.search_models(user, 'PaddleOCR-VL-1.6')
        self.assertIn('429', out['error'])
        self.assertEqual(['proposed:hf:PaddlePaddle/PaddleOCR-VL-1.6'],
                         [m['key'] for m in out['catalog']])
