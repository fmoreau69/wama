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

from .backends.audiocpp_backend import AudioCppBackend, _snapshot_root, split_caption_lyrics


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
