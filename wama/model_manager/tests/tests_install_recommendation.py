"""The install RECOMMENDATION is computed once, server side, for the page and the assistant
(2026-10-29, Fabien: « régler le problème à l'installation une seule fois pour tout le monde »).

Lived case: olmOCR-2's dialog lists full BF16 weights, an FP8 repository (needs the
`compressed-tensors` library, absent), an Apple MLX repository and a GGUF run by Ollama. The page
preselected « the first quantised variant of 20 GB at most » — the MLX one, which nothing reads on
this machine — and the assistant had no recommendation at all.
"""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase, TestCase

from wama.model_manager.models import AIModel
from wama.model_manager.services import prospector as p

FP8 = 'allenai/olmOCR-2-7B-1025-FP8'
MLX = 'mlx-community/olmOCR-2-7B-1025-mlx-8bit'
GGUF = 'someone/olmOCR-2-7B-1025-GGUF'
ABSENT = ['wama_package_absent_for_this_test']


def _olmocr2(disk_gb=16.6, fp8_method='compressed-tensors'):
    fp8 = {'repo_id': FP8, 'disk_gb': 10.0, 'downloads': 900,
           'files': [{'file': 'model-00001-of-00002.safetensors', 'gb': 5.0}]}
    if fp8_method is not None:
        fp8['quant_method'] = fp8_method
    return AIModel.objects.create(
        model_key='proposed:hf:allenai/olmOCR-2-7B-1025', name='olmOCR-2-7B-1025',
        model_type='ocr', source='huggingface', is_proposed=True, proposal_kind='update',
        platform_ref='huggingface:allenai/olmOCR-2-7B-1025', disk_gb=disk_gb,
        capabilities={'task': 'ocr'},
        extra_info={'prospect': {
            'spec': {'kind': 'hf', 'ref': 'allenai/olmOCR-2-7B-1025', 'category': 'ocr',
                     'task': 'ocr'},
            'own_gguf': [],
            'quant_variants': [
                fp8,
                {'repo_id': MLX, 'disk_gb': 8.4, 'downloads': 300,
                 'files': [{'file': 'model.safetensors', 'gb': 8.4}]},
                {'repo_id': GGUF, 'disk_gb': 9.4, 'downloads': 500,
                 'files': [{'file': 'olmOCR-2-7B-1025-Q8_0.gguf', 'gb': 8.1},
                           {'file': 'mmproj-F16.gguf', 'gb': 1.3}]}]}})


def _options(cand, packages=ABSENT, card_gb=24.0):
    with patch('wama.common.services.resource_governor.total_vram_gb', return_value=card_gb), \
            patch.object(p, '_quant_packages', return_value=packages):
        return p.install_options(cand)


def _by_ref(res):
    return {(o['ref'], o['file']): o for o in res['options']}


class TheOptionsSayWhatRunsHereTest(TestCase):

    def test_an_apple_mlx_variant_does_not_run_and_says_why(self):
        mlx = _by_ref(_options(_olmocr2()))[(MLX, None)]
        self.assertFalse(mlx['runnable'])
        self.assertIn('mlx', mlx['reason'])

    def test_a_quantisation_without_its_library_does_not_run_and_names_it(self):
        fp8 = _by_ref(_options(_olmocr2()))[(FP8, None)]
        self.assertFalse(fp8['runnable'])
        self.assertIn('compressed-tensors', fp8['reason'])
        self.assertIn(ABSENT[0], fp8['reason'])

    def test_the_same_quantisation_runs_once_its_library_is_there(self):
        # Counter-check: the verdict reads the library, not the repository name.
        fp8 = _by_ref(_options(_olmocr2(), packages=[]))[(FP8, None)]
        self.assertTrue(fp8['runnable'])
        self.assertEqual('', fp8['reason'])

    def test_a_gguf_run_by_ollama_and_the_full_weights_run(self):
        options = _by_ref(_options(_olmocr2()))
        self.assertTrue(options[(GGUF, 'olmOCR-2-7B-1025-Q8_0.gguf')]['runnable'])
        self.assertTrue(options[('allenai/olmOCR-2-7B-1025', None)]['runnable'])

    def test_an_unknown_quantisation_condemns_nothing(self):
        # Permissive like `backend_missing`: what is not known does not condemn.
        fp8 = _by_ref(_options(_olmocr2(fp8_method='a-method-transformers-ignores'),
                               packages=None))[(FP8, None)]
        self.assertTrue(fp8['runnable'])


class TheRecommendationIsTheMostPreciseThatFitsTest(TestCase):

    def test_olmocr2_recommends_its_full_weights_not_the_mlx_variant(self):
        res = _options(_olmocr2())
        best = res['options'][res['recommended']]
        self.assertEqual(('full', 'allenai/olmOCR-2-7B-1025'), (best['kind'], best['ref']))
        self.assertTrue(best['fits'])

    def test_weights_too_large_for_the_card_give_way_to_the_largest_that_fits(self):
        res = _options(_olmocr2(disk_gb=54.0), packages=[])
        full = _by_ref(res)[('allenai/olmOCR-2-7B-1025', None)]
        self.assertFalse(full['fits'])
        self.assertIn('ne tient pas', full['vram_note'])
        self.assertEqual(FP8, res['options'][res['recommended']]['ref'])

    def test_nothing_fits_recommends_the_lightest_that_runs(self):
        res = _options(_olmocr2(disk_gb=54.0), card_gb=4.0)
        best = res['options'][res['recommended']]
        self.assertEqual('olmOCR-2-7B-1025-Q8_0.gguf', best['file'])

    def test_without_a_gpu_nothing_is_said_to_fit(self):
        # The governor's rule (`fits_alone`): no card, no conclusion — never « 24 GB assumed ».
        res = _options(_olmocr2(), card_gb=0.0)
        self.assertEqual({None}, {o['fits'] for o in res['options']})

    def test_an_option_that_does_not_run_is_never_recommended(self):
        res = _options(_olmocr2(disk_gb=54.0), card_gb=12.0)
        self.assertTrue(res['options'][res['recommended']]['runnable'])


class TheQuantisationIsReadOnceTest(TestCase):

    def test_it_is_read_from_the_hub_once_and_kept(self):
        cand = _olmocr2(fp8_method=None)
        with patch.object(p, '_quant_method', return_value='compressed-tensors') as read:
            _options(cand)
            _options(cand)
        self.assertEqual([FP8], [c.args[0] for c in read.call_args_list])
        cand.refresh_from_db()
        fp8 = next(v for v in cand.extra_info['prospect']['quant_variants'] if v['repo_id'] == FP8)
        self.assertEqual('compressed-tensors', fp8['quant_method'])

    def test_a_silent_hub_freezes_nothing(self):
        cand = _olmocr2(fp8_method=None)
        with patch.object(p, '_quant_method', return_value=None):
            _options(cand)
        cand.refresh_from_db()
        fp8 = next(v for v in cand.extra_info['prospect']['quant_variants'] if v['repo_id'] == FP8)
        self.assertNotIn('quant_method', fp8)


class WhichRepositoriesAreReadTest(SimpleTestCase):

    def test_only_a_repository_that_calls_itself_quantised_is_read(self):
        self.assertTrue(p._reads_quant_method(FP8, [{'file': 'model.safetensors', 'gb': 5}]))
        self.assertFalse(p._reads_quant_method('allenai/olmOCR-2-7B-1025', None))
        self.assertFalse(p._reads_quant_method(MLX, None), 'another engine: already condemned')
        self.assertFalse(p._reads_quant_method(GGUF, None))

    def test_a_marker_is_a_word_not_a_substring(self):
        self.assertTrue(p._has_marker('mlx-community/olmocr-2-mlx-8bit', 'mlx'))
        self.assertFalse(p._has_marker('someone/complexmlxity-7b', 'mlx'))


class TheInstallRouteHoldsTheSameRuleTest(TestCase):

    def test_a_choice_that_would_not_run_is_refused_with_its_reason(self):
        from wama.model_manager.services import model_installer as mi
        cand = _olmocr2()
        with patch('wama.common.services.resource_governor.total_vram_gb', return_value=24.0), \
                patch.object(p, '_quant_packages', return_value=ABSENT), \
                patch.object(mi, 'dispatch_install') as dispatch:
            out = mi.request_install(cand.model_key, variant_ref=MLX)
        dispatch.assert_not_called()
        self.assertEqual('not_runnable', out['reason'])
        self.assertIn('mlx', out['error'])

    def test_the_recommended_choice_is_installed(self):
        # Counter-check: the full weights the recommendation names do start.
        from wama.model_manager.services import model_installer as mi
        cand = _olmocr2()
        with patch('wama.common.services.resource_governor.total_vram_gb', return_value=24.0), \
                patch.object(p, '_quant_packages', return_value=ABSENT), \
                patch.object(mi, 'dispatch_install', return_value=SimpleNamespace(id='t')), \
                patch.object(mi, 'disk_space_guard', return_value=None):
            out = mi.request_install(cand.model_key, variant_ref=cand.hf_repo)
        self.assertTrue(out['started'])

    def test_the_refusal_to_choose_names_the_recommendation(self):
        from wama.model_manager.services import model_installer as mi
        cand = _olmocr2()
        with patch('wama.common.services.resource_governor.total_vram_gb', return_value=24.0), \
                patch.object(p, '_quant_packages', return_value=ABSENT), \
                patch.object(mi, 'dispatch_install') as dispatch:
            out = mi.request_install(cand.model_key)
        dispatch.assert_not_called()
        self.assertEqual('variant_required', out['reason'])
        self.assertIn('Recommandé : variant_ref=allenai/olmOCR-2-7B-1025', out['error'])

    def test_the_assistant_receives_the_recommendation_of_the_page(self):
        from django.contrib.auth import get_user_model
        from wama import tool_api
        cand = _olmocr2()
        user = get_user_model().objects.create_superuser('install_recommendation', password='x')
        with patch('wama.common.services.resource_governor.total_vram_gb', return_value=24.0), \
                patch.object(p, '_quant_packages', return_value=ABSENT):
            out = tool_api.get_install_options(user, cand.model_key)
        best = out['options'][out['recommended']]
        self.assertEqual(('full', True), (best['kind'], best['runnable']))
        mlx = next(o for o in out['options'] if o['ref'] == MLX)
        self.assertEqual(False, mlx['runnable'])


class ThePagePreselectsTheServerRecommendationTest(SimpleTestCase):

    def test_the_page_reads_recommended_and_no_longer_its_own_threshold(self):
        page = (Path(__file__).resolve().parents[1] / 'templates' / 'model_manager'
                / 'index.html').read_text(encoding='utf-8')
        self.assertIn('mmVariantDialog(id, opts.options, opts.recommended)', page)
        self.assertNotIn('o.disk_gb <= 20', page)
        self.assertIn("o.runnable === false ? 'disabled' : ''", page)
