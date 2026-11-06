"""The ANATOMY of a model, confronted with the files its installation brings (2026-11-06).

WHY. A row's components BECOME what is downloaded (`patterns_from_composition`), and the weighing
treats any file no component claims as "not a weight of the model". An anatomy that forgets a
piece therefore gives a PARTIAL install that nothing reported — lived on ACE-Step 1.5, whose
proposed anatomy forgot its text encoder and `silence_latent.pt`. One rule
(`model_installer.anatomy_gaps`), three places: the install, the validation of a proposal, the
catalogue map. The inventories below are the repositories measured that day.
"""
from types import SimpleNamespace
from unittest import mock

from django.test import SimpleTestCase, TestCase

from wama.model_manager.models import AIModel
from wama.model_manager.services import model_installer as mi

GB = 1024 ** 3

ACE_STEP = ['acestep-5Hz-lm-1.7B/model.safetensors', 'acestep-v15-turbo/model.safetensors',
            'acestep-v15-turbo/silence_latent.pt', 'vae/diffusion_pytorch_model.safetensors',
            'Qwen3-Embedding-0.6B/model.safetensors', 'README.md']
ACE_ANATOMY = {'components': [
    {'role': 'lm', 'pattern': 'acestep-5Hz-lm-1.7B/model.safetensors'},
    {'role': 'dit', 'pattern': 'acestep-v15-turbo/model.safetensors'},
    {'role': 'vae', 'pattern': 'vae/diffusion_pytorch_model.safetensors'}],
    'runtime': {'engine': 'ace-step'}}


def _anatomy(*patterns, engine='x', excluded=None):
    compo = {'components': [{'role': f'r{i}', 'pattern': p} for i, p in enumerate(patterns)],
             'runtime': {'engine': engine}}
    if excluded:
        compo['excluded'] = [{'pattern': p, 'reason': 'r'} for p in excluded]
    return compo


class AnatomyGapsTest(SimpleTestCase):

    def test_a_forgotten_encoder_and_latent_make_the_anatomy_incomplete(self):
        gaps = mi.anatomy_gaps(ACE_STEP, ACE_ANATOMY)
        self.assertEqual(['Qwen3-Embedding-0.6B/model.safetensors',
                          'acestep-v15-turbo/silence_latent.pt'], gaps['unclaimed'])
        self.assertIn('silence_latent.pt', mi.anatomy_error(gaps))
        completed = {**ACE_ANATOMY, 'components': ACE_ANATOMY['components'] + [
            {'role': 'text_encoder', 'pattern': 'Qwen3-Embedding-0.6B/*'},
            {'role': 'silence_latent', 'pattern': 'acestep-v15-turbo/silence_latent.pt'}]}
        self.assertEqual({}, mi.anatomy_gaps(ACE_STEP, completed))

    def test_variants_of_a_claimed_weight_are_set_aside_by_rule(self):
        """Precision, quantization (GGUF and ONNX export names), shard split, format twin."""
        kokoro = ['onnx/model.onnx'] + [f'onnx/model_{v}.onnx' for v in
                                         ('fp16', 'q4', 'q4f16', 'q8f16', 'quantized', 'uint8',
                                          'uint8f16')]
        self.assertEqual({}, mi.anatomy_gaps(kokoro, _anatomy('onnx/model.onnx',
                                                              engine='kokoro-onnx')))
        minimax = ['language_model_q8_0.gguf', 'language_model_q4_0.gguf',
                   'language_model_q4_k.gguf', 'language_model_bf16.gguf']
        self.assertEqual({}, mi.anatomy_gaps(minimax, _anatomy('language_model_q8_0.gguf')))
        mochi = [f'text_encoder/model-0000{i}-of-00004.safetensors' for i in range(1, 5)] + \
                [f'text_encoder/model-0000{i}-of-00002.safetensors' for i in range(1, 3)]
        self.assertEqual({}, mi.anatomy_gaps(mochi, _anatomy('text_encoder/model-*-of-00004.*')))
        plates = ['plate-v1l.onnx', 'plate-v1l.pt']
        self.assertEqual({}, mi.anatomy_gaps(plates, _anatomy('plate-v1l.onnx')))

    def test_copies_for_another_loader_are_set_aside_by_rule(self):
        pipeline = ['model_index.json', 'unet/diffusion_pytorch_model.safetensors',
                    'unet/openvino_model.bin', 'vae_decoder/model.onnx', 'sd_base.safetensors',
                    'vae/diffusion_pytorch_model.safetensors',
                    'vae/transformer/diffusion_pytorch_model.safetensors']
        gaps = mi.anatomy_gaps(pipeline, _anatomy('unet/diffusion_pytorch_model.safetensors',
                                                  'vae/diffusion_pytorch_model.safetensors',
                                                  engine='diffusers'))
        self.assertEqual({}, gaps)
        # The `transformers` conversion beside a `.nemo` (LinTO) or a `.pt` (SAM 3), and beside an
        # ONNX export whose format proves the engine (bardsai).
        self.assertEqual({}, mi.anatomy_gaps(['stt.nemo', 'model.safetensors'],
                                             _anatomy('stt.nemo', engine='nemo')))
        self.assertEqual({}, mi.anatomy_gaps(['sam3.pt', 'model.safetensors'],
                                             _anatomy('sam3.pt', engine='sam3')))
        self.assertEqual({}, mi.anatomy_gaps(['onnx/model.onnx', 'model.safetensors'],
                                             _anatomy('onnx/model.onnx', engine='onnxruntime')))

    def test_a_library_checkpoint_read_by_its_own_library_is_not_a_conversion(self):
        """Counter-case: when the declared engine IS the library, its checkpoint is no copy."""
        gaps = mi.anatomy_gaps(['speaker.pt', 'model.safetensors'],
                               _anatomy('speaker.pt', engine='transformers'))
        self.assertEqual(['model.safetensors'], gaps['unclaimed'])
        # …nor in a folder that holds no claimed weight (the ACE-Step text encoder).
        self.assertIn('Qwen3-Embedding-0.6B/model.safetensors',
                      mi.anatomy_gaps(ACE_STEP, ACE_ANATOMY)['unclaimed'])

    def test_what_no_rule_can_tell_is_stated_with_its_reason(self):
        yolo = ['face_seg.pt', 'hair_seg.pt', 'skin_seg.pt']
        self.assertEqual(['hair_seg.pt', 'skin_seg.pt'],
                         mi.anatomy_gaps(yolo, _anatomy('face_seg.pt'))['unclaimed'])
        self.assertEqual({}, mi.anatomy_gaps(yolo, _anatomy('face_seg.pt', excluded=['*'])))

    def test_a_pattern_that_designates_nothing_is_named(self):
        gaps = mi.anatomy_gaps(['renamed.pt'], _anatomy('renamed.pt', 'local_name.pt',
                                                        excluded=['gone/*']))
        self.assertEqual(['r1'], gaps['claims_nothing'])
        self.assertEqual(['gone/*'], gaps['excludes_nothing'])
        self.assertIn('r1', mi.anatomy_error(gaps))
        self.assertIn('gone/*', mi.anatomy_error(gaps))

    def test_without_a_file_pattern_there_is_nothing_to_confront(self):
        self.assertEqual({}, mi.anatomy_gaps(ACE_STEP, {}))
        self.assertEqual({}, mi.anatomy_gaps(ACE_STEP, {'components': [{'role': 'base',
                                                                         'repo': 'org/x'}]}))
        self.assertEqual('', mi.anatomy_error({}))

    def test_reading_quantization_words_does_not_change_what_a_repository_weighs(self):
        """Counter-case found at the re-check (2026-11-06): counting `q8_0` as a MARK made the
        heuristic weighing keep a small unmarked file — 0.2 GB instead of 9.2 for a MiniMax-like
        repository, an UNDER-estimate. The words feed the anatomy, not the weighing choice."""
        repo = [('language_model_q8_0.gguf', 9 * GB), ('language_model_q4_k.gguf', 3 * GB),
                ('vocoder.gguf', GB // 5)]
        weighed = mi.components_of_files(repo)
        self.assertEqual(9.0, weighed['components']['model'])

    def test_a_quantization_marker_leaves_the_base_name_of_the_weight_set(self):
        self.assertEqual(('model', 'onnx', '_q4f16'),
                         tuple(mi._weight_set_key('model_q4f16.onnx')[i] for i in (0, 3, 4)))
        self.assertEqual('language_model', mi._weight_set_key('language_model_q4_k.gguf')[0])
        self.assertEqual('model', mi._weight_set_key('model.q4k.gguf')[0])
        self.assertEqual('qwen2-vl', mi._weight_set_key('qwen2-vl.safetensors')[0],
                         "a name that merely starts with q is not a quantization")


class AnatomyInventoryTest(TestCase):

    def test_a_listed_file_from_the_models_own_repository_keeps_its_repository_name(self):
        own = {'source': 'huggingface', 'repo': 'suno/bark', 'file': 'text_2.pt'}
        other = {'source': 'huggingface', 'repo': 'org/voices', 'file': 'voices/a1b2.pt'}
        row = AIModel(model_key='synthesizer:bark', platform_ref='huggingface:suno/bark',
                      extra_info={'declared_files': [
                          {'path': 'suno/bark_v0/text_2.pt', 'size': 5, 'origin': own},
                          {'path': 'voices/Ana.pt', 'size': 1, 'origin': other}]})
        self.assertEqual([('text_2.pt', 5), ('voices/Ana.pt', 1)], mi.anatomy_inventory(row))

    def test_a_github_release_brings_the_one_asset_its_driver_placed(self):
        """The `github` driver places ONE pinned asset and never reads the anatomy: the release
        folder is what the install brought (the two `Phhofm/models` rows, unconfronted until then)."""
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as folder:
            (Path(folder) / 'x_fp32.onnx').write_bytes(b'0' * 8)
            row = AIModel(model_key='github:o/r:x', platform_ref='github:o/r/releases/tag/x',
                          extra_info={'github_release': True, 'path': folder})
            self.assertEqual([('x_fp32.onnx', 8)], mi.anatomy_inventory(row))
            compo = _anatomy('x.onnx', engine='onnxruntime')
            self.assertEqual(['r0'], mi.anatomy_gaps(mi.anatomy_inventory(row),
                                                     compo)['claims_nothing'])
        row.extra_info = {'github_release': True, 'path': folder}
        self.assertEqual([], mi.anatomy_inventory(row), 'not installed: nothing to confront')


class AnatomyGateTest(TestCase):
    """The three places that confront an anatomy refuse the same incomplete one."""

    SPEC = {'kind': 'hf', 'ref': 'ACE-Step/Ace-Step1.5', 'category': 'music',
            'composition': ACE_ANATOMY}

    def _published(self):
        return [SimpleNamespace(rfilename=f, size=GB) for f in ACE_STEP]

    def test_the_install_rejects_an_incomplete_anatomy_before_downloading(self):
        with mock.patch('wama.model_manager.services.prospector.hub_files',
                        return_value=self._published()), \
                mock.patch.object(mi, 'pull_hf_model') as pull:
            res = mi.install_from_spec(self.SPEC)
        self.assertFalse(res['ok'])
        self.assertEqual('anatomy', res['reason'])
        self.assertIn('silence_latent.pt', res['error'])
        pull.assert_not_called()

    def test_the_install_stops_when_the_hub_cannot_be_read(self):
        with mock.patch('wama.model_manager.services.prospector.hub_files', return_value=None), \
                mock.patch.object(mi, 'pull_hf_model') as pull:
            res = mi.install_from_spec(self.SPEC)
        self.assertEqual((False, 'anatomy'), (res['ok'], res['reason']))
        pull.assert_not_called()

    def test_a_complete_anatomy_installs(self):
        spec = {**self.SPEC, 'composition': {**ACE_ANATOMY, 'excluded': [
            {'pattern': 'Qwen3-Embedding-0.6B/*', 'reason': 'r'},
            {'pattern': '*/silence_latent.pt', 'reason': 'r'}]}}
        with mock.patch('wama.model_manager.services.prospector.hub_files',
                        return_value=self._published()), \
                mock.patch.object(mi, 'pull_hf_model', return_value={'ok': False, 'error': 'x'}) as pull:
            mi.install_from_spec(spec)
        pull.assert_called_once()

    def test_validating_a_proposal_rejects_what_the_plan_shows(self):
        from wama.common.manifests import proposals
        from wama.common.manifests.builtin.model import extract_model
        key = 'huggingface:ACE-Step/Ace-Step1.5'
        AIModel.objects.create(model_key=key, name='ACE-Step', model_type='music',
                               source='huggingface', platform_ref=key)
        manifest = extract_model(key)
        manifest['body']['composition'] = ACE_ANATOMY
        with mock.patch.object(mi, 'anatomy_inventory', return_value=ACE_STEP):
            obj = proposals.propose(manifest)
            shown = proposals.plan(obj)['errors']
            res = proposals.apply(obj)
        self.assertTrue(any('silence_latent.pt' in e for e in shown), shown)
        self.assertEqual((False, shown), (res['applied'], res['errors']))
        self.assertEqual({}, AIModel.objects.get(model_key=key).composition)

    def test_the_form_of_a_stated_exclusion_is_checked(self):
        from wama.common.manifests.builtin.model import validate_model_body
        ok = {'composition': {**ACE_ANATOMY, 'excluded': [{'pattern': 'a/*', 'reason': 'r'}]}}
        self.assertEqual([], validate_model_body(ok))
        for wrong in ([], [{'pattern': 'a/*'}], [{'pattern': 'a/*', 'reason': ' '}],
                      [{'pattern': 'a/*', 'reason': 'r', 'why': 'x'}]):
            self.assertTrue(validate_model_body({'composition': {**ACE_ANATOMY,
                                                                 'excluded': wrong}}), wrong)

    def test_the_catalogue_map_names_an_installed_row_with_an_incomplete_anatomy(self):
        import json
        from io import StringIO

        from django.core.management import call_command
        AIModel.objects.create(model_key='huggingface:ACE-Step/Ace-Step1.5', name='ACE-Step',
                               model_type='music', source='huggingface', is_downloaded=True,
                               platform_ref='huggingface:ACE-Step/Ace-Step1.5',
                               composition=ACE_ANATOMY)
        out = StringIO()
        with mock.patch.object(mi, 'anatomy_inventory', return_value=ACE_STEP):
            call_command('check_model_completeness', '--json', stdout=out)
        report = json.loads(out.getvalue())
        self.assertIn('huggingface:ACE-Step/Ace-Step1.5', report['axes']['anatomy_incomplete'])
        self.assertIn('silence_latent.pt',
                      report['anatomy_why']['huggingface:ACE-Step/Ace-Step1.5'])
