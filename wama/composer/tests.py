"""
Composer — backend COMPOSÉ audio.cpp (premier modèle multi-composants, MiniMax-Music3).

CE QUE CES TESTS PROTÈGENT. Le backend ne code AUCUNE anatomie : il lit la déclaration
(`AIModel.composition`, posée par le manifeste `model`) et la traduit en invocation du
binaire. Ces tests couvrent tout ce qui se prouve SANS binaire ni GPU — la génération
réelle est une validation humaine (hôte fragile : jamais de charge GPU lancée par une
session, cf. reference_wsl_gpu_windows_update_regression).
"""
from pathlib import Path

from django.test import TestCase

from wama.model_manager.models import AIModel

from .backends.audiocpp_backend import (AudioCppBackend, _snapshot_root,
                                        ensure_engine_default_aliases, split_caption_lyrics)


class DecoupageCaptionParolesTest(TestCase):
    """Le prompt unique du composer porte description PUIS paroles taguées (contrat Music3)."""

    def test_les_paroles_commencent_au_premier_tag_de_section(self):
        prompt = ("A bright pop rock song, female vocal.\n"
                  "[verse] City lights are shining low.\n"
                  "[chorus] Turn it up tonight.")
        caption, lyrics = split_caption_lyrics(prompt)
        self.assertEqual(caption, "A bright pop rock song, female vocal.")
        self.assertTrue(lyrics.startswith('[verse]'))
        self.assertIn('[chorus]', lyrics)

    def test_sans_tag_de_paroles_la_generation_part_en_instrumental(self):
        # Les paroles sont REQUISES par le moteur : [instrumental] est la convention pour
        # ne pas en chanter — annoncé dans la description du modèle, pas de magie cachée.
        caption, lyrics = split_caption_lyrics("Ambient piano, slow tempo.")
        self.assertEqual(caption, "Ambient piano, slow tempo.")
        self.assertEqual(lyrics, '[instrumental]')

    def test_un_prompt_vide_reste_utilisable(self):
        caption, lyrics = split_caption_lyrics("")
        self.assertTrue(caption)
        self.assertEqual(lyrics, '[instrumental]')


class ResolutionPackageTest(TestCase):
    """`--model` attend la RACINE du package = le snapshot HF courant (refs/main)."""

    def test_la_racine_du_package_se_resout_par_refs_main(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            depot = Path(tmp) / 'models--audio-cpp--MiniMax-Music3-GGUF'
            (depot / 'snapshots' / 'rev42').mkdir(parents=True)
            (depot / 'refs').mkdir()
            (depot / 'refs' / 'main').write_text('rev42')
            racine = _snapshot_root(tmp, 'audio-cpp/MiniMax-Music3-GGUF')
            self.assertEqual(racine, depot / 'snapshots' / 'rev42')

    def test_un_package_absent_rend_None_pas_une_exception(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(_snapshot_root(tmp, 'audio-cpp/Absent'))


class AliasDefautsMoteurTest(TestCase):
    """
    audio.cpp ouvre ses composants PAR DÉFAUT avant d'appliquer les session options
    (défaut moteur, vécu 2026-08-28 : « missing …language_model_q4_0.gguf » alors que la
    Q8 déclarée était installée et l'override passé). Le backend pose donc des alias.
    """

    def setUp(self):
        import tempfile
        self.tmp = tempfile.TemporaryDirectory()
        self.racine = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)
        try:
            (self.racine / '_probe').symlink_to('_cible')
        except OSError:
            self.skipTest("liens symboliques indisponibles sur cet hôte")
        self.compo = {'components': [
            {'role': 'language_model', 'pattern': 'language_model_q8_0.gguf'},
            {'role': 'flow_transformer', 'pattern': 'transformer_q8_0.gguf'},
            {'role': 'rvq_depth_decoder', 'pattern': 'rvq_depth_decoder_q8_0.gguf'},
            {'role': 'vocoder', 'pattern': 'vocoder.gguf'},
        ]}

    def test_l_alias_du_defaut_moteur_pointe_vers_la_variante_declaree(self):
        (self.racine / 'language_model_q8_0.gguf').write_bytes(b'q8')
        (self.racine / 'transformer_q8_0.gguf').write_bytes(b'q8')
        ensure_engine_default_aliases(self.racine, 'minimax_music3', self.compo)
        alias = self.racine / 'language_model_q4_0.gguf'
        self.assertTrue(alias.is_symlink())
        self.assertEqual(alias.read_bytes(), b'q8')
        self.assertTrue((self.racine / 'transformer_q4_0.gguf').is_symlink())

    def test_relancer_ne_change_rien_et_un_defaut_deja_present_est_respecte(self):
        (self.racine / 'language_model_q8_0.gguf').write_bytes(b'q8')
        (self.racine / 'language_model_q4_0.gguf').write_bytes(b'vraie q4')
        ensure_engine_default_aliases(self.racine, 'minimax_music3', self.compo)
        ensure_engine_default_aliases(self.racine, 'minimax_music3', self.compo)
        # Une VRAIE q4 installée n'est jamais écrasée par un alias.
        self.assertEqual((self.racine / 'language_model_q4_0.gguf').read_bytes(), b'vraie q4')

    def test_une_variante_declaree_absente_ne_pose_pas_d_alias_mort(self):
        ensure_engine_default_aliases(self.racine, 'minimax_music3', self.compo)
        self.assertFalse((self.racine / 'language_model_q4_0.gguf').exists())

    def test_une_famille_inconnue_du_contournement_est_un_no_op(self):
        (self.racine / 'language_model_q8_0.gguf').write_bytes(b'q8')
        ensure_engine_default_aliases(self.racine, 'autre_famille', self.compo)
        self.assertFalse((self.racine / 'language_model_q4_0.gguf').exists())


class GateVramModeDepannageTest(TestCase):
    """
    Mode dépannage GPU (WAMA_GPU_SAFE_MODE, crash hôte du 28/08 pendant la montée en
    charge Music3) : le sous-processus ne se lance que si la VRAM MESURÉE suffit —
    sinon erreur DITE, jamais une superposition silencieuse.
    """

    def _prepare(self, tmp):
        AIModel.objects.create(
            model_key='composer:minimax-music3', name='MiniMax-Music3',
            model_type='music', source='composer',
            composition={'components': [{'role': 'language_model',
                                         'pattern': 'language_model_q8_0.gguf'}],
                         'runtime': {'engine': 'audio-cpp', 'family': 'minimax_music3'}})
        depot = Path(tmp) / 'models--audio-cpp--MiniMax-Music3-GGUF'
        (depot / 'snapshots' / 'rev1').mkdir(parents=True)
        (depot / 'refs').mkdir()
        (depot / 'refs' / 'main').write_text('rev1')

    def test_sans_vram_mesuree_la_generation_est_refusee_en_le_disant(self):
        import tempfile
        from unittest import mock
        from django.test import override_settings
        with tempfile.TemporaryDirectory() as tmp:
            self._prepare(tmp)
            config = {'cache_dir': tmp, 'hf_id': 'audio-cpp/MiniMax-Music3-GGUF',
                      'backend': 'audiocpp', 'vram_gb': 13.0}
            with override_settings(WAMA_GPU_SAFE_MODE=True), \
                 mock.patch.dict('wama.composer.utils.model_config.COMPOSER_MODELS',
                                 {'minimax-music3': config}), \
                 mock.patch.dict('os.environ', {'AUDIOCPP_BINARY': __file__}), \
                 mock.patch('wama.common.services.resource_governor.wait_for_free_vram',
                            return_value=(False, 0.7)), \
                 mock.patch('subprocess.run') as run:
                with self.assertRaises(RuntimeError) as cm:
                    AudioCppBackend().generate(
                        model_id='minimax-music3', prompt='x', duration=10,
                        output_path=str(Path(tmp) / 'out.wav'))
            self.assertIn('mode dépannage GPU', str(cm.exception))
            self.assertIn('0.7', str(cm.exception))
            run.assert_not_called()


class CompositionRequiseTest(TestCase):
    """Le backend n'invente jamais l'anatomie : composition absente = erreur DITE."""

    def test_une_composition_absente_est_une_erreur_actionnable(self):
        AIModel.objects.create(model_key='composer:minimax-music3', name='MiniMax-Music3',
                               model_type='music', source='composer')
        with self.assertRaises(RuntimeError) as cm:
            AudioCppBackend().generate(
                model_id='minimax-music3', prompt='x', duration=10,
                output_path='/tmp/nulle-part.wav')
        self.assertIn('composition non déclarée', str(cm.exception))
        self.assertIn('manifeste', str(cm.exception))

    def test_la_composition_declaree_est_lue_sur_la_ligne_d_app(self):
        AIModel.objects.create(
            model_key='composer:minimax-music3', name='MiniMax-Music3',
            model_type='music', source='composer',
            composition={'components': [{'role': 'language_model',
                                         'pattern': 'language_model_q8_0.gguf'}],
                         'runtime': {'engine': 'audio-cpp', 'family': 'minimax_music3'}})
        compo = AudioCppBackend()._composition('minimax-music3')
        self.assertEqual(compo['runtime']['family'], 'minimax_music3')
        self.assertEqual(compo['components'][0]['pattern'], 'language_model_q8_0.gguf')
