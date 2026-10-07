"""A requested TASK requires a DECLARED task (`matches_inputs`, 2026-10-07).

Until then a model with no task passed the task filter. Measured the day it changed: 255 of 259
catalogue rows declare their task; the other 4 (model-manager installs with empty capabilities)
entered selects by task — a diarizer (`pyannote`) offered as an audio-enhancement engine, once
the enhancer's select listed by task instead of by source.
"""
from types import SimpleNamespace

from django.test import SimpleTestCase, TestCase

from ..models import AIModel
from ..services.model_selector import get_registry_models, matches_inputs


def _model(**caps):
    return SimpleNamespace(capabilities=caps)


class TaskMustBeDeclaredTest(SimpleTestCase):

    def test_a_model_without_a_task_is_offered_for_no_task(self):
        self.assertFalse(matches_inputs(_model(), task='audio-enhance'))
        self.assertFalse(matches_inputs(_model(inputs_required=['work_audio']), task='ocr'))

    def test_a_model_declaring_the_task_is_offered_for_it_and_not_for_another(self):
        model = _model(task='audio-enhance', inputs_required=['work_audio'])
        self.assertTrue(matches_inputs(model, task='audio-enhance'))
        self.assertFalse(matches_inputs(model, task='ocr'))

    def test_without_a_requested_task_nothing_changes(self):
        # Counter-check: the strictness is about a REQUESTED task — input matching alone is free.
        self.assertTrue(matches_inputs(_model(inputs_required=['work_audio']),
                                       available_inputs=['work_audio']))


class SelectByTaskTest(TestCase):

    def test_a_select_by_task_leaves_out_a_model_without_a_task(self):
        for key, caps in (('enhancer:resemble', {'task': 'audio-enhance'}),
                          ('huggingface:org/diarizer', {})):
            AIModel.objects.create(model_key=key, name=key, model_type='speech',
                                   source=key.split(':')[0], is_downloaded=True, capabilities=caps)
        keys = [k for k, _ in get_registry_models(None, task='audio-enhance')[0]]
        self.assertIn('enhancer:resemble', keys)
        self.assertNotIn('huggingface:org/diarizer', keys)
