"""Le modèle d'une génération du composer en CLÉS DE CATALOGUE (route F4b, 2026-10-01).

Le select du composer est tiré du catalogue, borné par la TÂCHE (musique / ambiance) et non plus
par la liste de l'app : un modèle de la tâche installé depuis le model manager (YuE2) y entre sans
une ligne de code. Les valeurs d'avant (`musicgen-small`, `auto-music`) restent LUES.
"""
from django.contrib.auth import get_user_model
from django.test import TestCase

from wama.composer.models import ComposerGeneration
from wama.composer.utils import model_choice as mc
from wama.model_manager.models import AIModel

YUE2 = 'huggingface:m-a-p/YuE2-3B'


class ModelChoiceTest(TestCase):

    def setUp(self):
        AIModel.objects.create(model_key=YUE2, name='YuE2 3B', model_type='music',
                               source='huggingface', vram_gb=20.0, is_available=True,
                               capabilities={'task': 'text-to-music'})
        AIModel.objects.create(model_key='huggingface:org/flux-image', name='Image',
                               model_type='diffusion', source='huggingface', vram_gb=8.0,
                               is_available=True, capabilities={'task': 'text-to-image'})
        self.user = get_user_model().objects.create_user('composer_choice', password='x')

    def test_the_old_values_are_read_as_keys(self):
        self.assertEqual('composer:musicgen-small', mc.normalize('musicgen-small'))
        self.assertEqual(mc.AUTO_MUSIC, mc.normalize('auto-music'))
        self.assertEqual(mc.AUTO_SFX, mc.normalize('auto-sfx'))
        self.assertEqual(mc.AUTO_MUSIC, mc.normalize(''))
        self.assertEqual(YUE2, mc.normalize(YUE2), 'a key of another source is kept as is')

    def test_the_type_is_derived_from_the_task_never_chosen(self):
        self.assertEqual('music', mc.generation_type('composer:musicgen-small'))
        self.assertEqual('sfx', mc.generation_type('audiogen-medium'))
        self.assertEqual('sfx', mc.generation_type(mc.AUTO_SFX))
        self.assertEqual('music', mc.generation_type(YUE2), 'read from the catalogue task')

    def test_only_the_two_tasks_are_valid(self):
        self.assertTrue(mc.is_valid(YUE2))
        self.assertTrue(mc.is_valid(mc.AUTO_SFX))
        self.assertTrue(mc.is_valid('musicgen-small'))
        self.assertFalse(mc.is_valid('huggingface:org/flux-image'))
        self.assertFalse(mc.is_valid('composer:does-not-exist'))

    def test_a_model_from_elsewhere_has_no_app_config_but_a_label(self):
        self.assertEqual({}, mc.config(YUE2))
        self.assertEqual('YuE2 3B', mc.label_of(YUE2))
        self.assertTrue(mc.config('musicgen-small'))

    def test_saving_stores_the_key_and_derives_the_type(self):
        gen = ComposerGeneration.objects.create(user=self.user, prompt='x', model='audiogen-medium')
        gen.refresh_from_db()
        self.assertEqual(('composer:audiogen-medium', 'sfx'), (gen.model, gen.generation_type))
        gen.model = YUE2
        gen.save(update_fields=['model'])
        gen.refresh_from_db()
        self.assertEqual((YUE2, 'music'), (gen.model, gen.generation_type),
                         'saving the model alone also saves the type it implies')

    def test_only_a_declared_consumer_takes_the_song_audio_to_cover(self):
        self.assertTrue(mc.consumes_melody('musicgen-melody'))
        self.assertFalse(mc.consumes_melody(YUE2))
        self.assertFalse(mc.consumes_melody(mc.AUTO_MUSIC), 'no model of the task declares work_audio yet')

    def test_a_group_auto_takes_the_song_audio_when_one_of_its_models_does(self):
        """2026-10-03 : avec « auto », un audio joint était ignoré à la création — le tirage, lui,
        savait retenir MusicGen Melody. Même règle que la partition (`consumes_input`)."""
        AIModel.objects.create(model_key='composer:musicgen-melody', name='MusicGen Melody',
                               model_type='music', source='composer', vram_gb=4.0, is_available=True,
                               capabilities={'task': 'text-to-music', 'inputs_required': ['prompt'],
                                             'inputs_optional': ['work_audio']})
        self.assertTrue(mc.consumes_melody(mc.AUTO_MUSIC))
        self.assertFalse(mc.consumes_melody(mc.AUTO_SFX), 'no sound-effect model covers a song')
