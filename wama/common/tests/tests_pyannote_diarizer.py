"""Le diariseur pyannote sert DEUX pipelines (2026-09-30) : 3.1 et son successeur community-1.

Aucun modèle réel n'est chargé : `Pipeline.from_pretrained` est simulé.

⚠ Identifiants en anglais ; commentaires et docstrings en français.
"""
from unittest import mock

from django.test import SimpleTestCase

from wama.common.backends.pyannote_diarizer import (
    DEFAULT_MODEL, PyannoteDiarizerBackend,
)


class ModelChoiceTest(SimpleTestCase):

    def test_nothing_asked_keeps_the_pipeline_used_until_now(self):
        self.assertEqual('speaker-diarization-3.1', DEFAULT_MODEL)
        self.assertEqual(DEFAULT_MODEL, PyannoteDiarizerBackend.model_id_for(None))

    def test_a_catalogue_key_or_a_repository_names_the_pipeline(self):
        for asked in ('speaker-diarization-community-1',
                      'huggingface:pyannote/speaker-diarization-community-1',
                      'pyannote/speaker-diarization-community-1'):
            self.assertEqual('speaker-diarization-community-1',
                             PyannoteDiarizerBackend.model_id_for(asked), asked)

    def test_an_unknown_name_falls_back_to_the_default(self):
        self.assertEqual(DEFAULT_MODEL, PyannoteDiarizerBackend.model_id_for('pyannote/other'))


class LoadingTest(SimpleTestCase):

    def _loaded(self, backend, model):
        pipeline = mock.MagicMock(name=f'pipeline-{model}')
        with mock.patch('pyannote.audio.Pipeline.from_pretrained', return_value=pipeline) as load, \
                mock.patch('torch.cuda.is_available', return_value=False):
            self.assertTrue(backend.load(model=model))
        return load

    def test_the_requested_pipeline_is_loaded_from_its_catalogue_folder(self):
        """community-1 was installed by prospection: its folder comes from its catalogue KEY —
        declaring it in MODEL_PATHS took it out of the generic scan (2026-10-01)."""
        from pathlib import Path
        from django.conf import settings
        self.assertNotIn('diarization_community', settings.MODEL_PATHS['speech'])
        backend = PyannoteDiarizerBackend()
        snapshot = Path('/models/speech/community/models--pyannote--c1/snapshots/abc')
        with mock.patch('wama.common.utils.model_components.installed_snapshot',
                        return_value=snapshot) as found, \
                mock.patch('pathlib.Path.mkdir'):
            load = self._loaded(backend, 'speaker-diarization-community-1')
        found.assert_called_once_with('huggingface:pyannote/speaker-diarization-community-1')
        self.assertEqual('pyannote/speaker-diarization-community-1', load.call_args.args[0])
        self.assertEqual(str(Path('/models/speech/community')), load.call_args.kwargs['cache_dir'])

    def test_the_app_declared_pipeline_keeps_its_declared_folder(self):
        from django.conf import settings
        load = self._loaded(PyannoteDiarizerBackend(), 'speaker-diarization-3.1')
        self.assertEqual(str(settings.MODEL_PATHS['speech']['diarization']),
                         load.call_args.kwargs['cache_dir'])

    def test_asking_again_reuses_it_asking_the_other_one_switches(self):
        backend = PyannoteDiarizerBackend()
        self._loaded(backend, 'speaker-diarization-3.1')
        again = self._loaded(backend, 'speaker-diarization-3.1')
        again.assert_not_called()
        switched = self._loaded(backend, 'speaker-diarization-community-1')
        switched.assert_called_once()
        self.assertEqual('speaker-diarization-community-1', backend._model_id)
