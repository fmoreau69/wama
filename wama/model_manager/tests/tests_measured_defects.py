"""MEASURED DEFECTS of a model (2026-10-28, Fabien's decisions) — for EVERY model, app and task.

A model a WAMA measure catches returning a wrong result without saying so stays LISTED in the
selects, GREYED with its reason, and leaves the automatic draw — like a model without a backend.
Albert's whisper-large-v3 drops distant speech (WAMA_QUALITE, measured on 2026-10-22).

The chain held here, end to end :
  1. a measure without reference (`result_evaluation.Check` declaring a `defect_label`) catches a
     model on an input another model covered, with the SAME settings — the model alone changed ;
  2. the defect is PROPOSED to an administrator (a `model` manifest carrying `quality.defect`),
     never set by itself (`ROADMAP §16.5`, guardrail n°2) ;
  3. validating projects it onto the catalogue row (`extra_info['quality_defect']`), which sync
     keeps ; revoking the manifest ungreys ;
  4. the row's defect greys the option with its reason and keeps the model out of the draw.
"""
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import Client, SimpleTestCase, TestCase

from wama.common.manifests import proposals
from wama.common.manifests.builtin.model import (extract_model, un_write_back_model,
                                                 validate_model_body, write_back_model)
from wama.common.models import JOB_SUCCESS, ProcessRun
from wama.model_manager.models import AIModel
from wama.model_manager.services.model_quality import (declared_defect, defect_evidence,
                                                       propose_defect)

DEFECT = {'label': 'drops distant speech', 'reason': 'Measured on a distant interview.',
          'source': 'test measure, 2026-10-28'}


def _asr(model_key, *, execution='local', defect=None):
    return AIModel.objects.create(
        model_key=model_key, name=model_key.split(':', 1)[1], model_type='speech',
        source=model_key.split(':', 1)[0], vram_gb=0.0 if execution == 'cloud' else 3.0,
        is_available=True, is_downloaded=execution != 'cloud', execution=execution,
        capabilities={'task': 'transcription', 'modalities': ['audio']},
        extra_info={'quality_defect': dict(defect)} if defect else {})


def _line(object_id, model_key, value, *, short, audio='sha-a', settings=None, check='probe'):
    """A transcription line holding a measure, as `run_checks` keeps it."""
    return ProcessRun.objects.create(
        app='transcriber', object_type='Transcript', object_id=str(object_id), node_id='transcribe',
        process_key='transcriber.transcribe', status=JOB_SUCCESS, model_key=model_key,
        settings_snapshot={'backend': model_key, 'vad_mode': 'auto', **(settings or {})},
        output_summary={'checks': [{'key': check, 'value': value, 'short': short, 'input': audio}]})


class _ComparableProbe:
    """A measure that DECLARES itself comparable across models — the evidence only counts those."""

    def setUp(self):
        super().setUp()
        from wama.common.services import result_evaluation as evaluation
        probe = evaluation.Check('probe', 'Probe', lambda *a: None, defect_label='misses the probe',
                                 compares_models=True)
        patcher = mock.patch.dict(evaluation.CHECKS, {'probe': probe})
        patcher.start()
        self.addCleanup(patcher.stop)


class TheManifestCarriesADatedDefectTest(SimpleTestCase):

    def test_a_defect_needs_a_label_a_reason_and_a_dated_source(self):
        self.assertEqual([], validate_model_body({'quality': {'defect': DEFECT}}))
        undated = dict(DEFECT, source='a measure')
        self.assertTrue(validate_model_body({'quality': {'defect': undated}}))
        self.assertTrue(validate_model_body({'quality': {'defect': {'label': 'x'}}}))
        self.assertTrue(validate_model_body({'quality': {'other': 1}}))


class TheRowCarriesTheValidatedDefectTest(TestCase):

    def test_projecting_extracting_syncing_and_revoking(self):
        _asr('albert:whisper-large-v3', execution='cloud')
        manifest = extract_model('albert:whisper-large-v3')
        self.assertNotIn('quality', manifest['body'], 'no defect, nothing said')
        manifest['body']['quality'] = {'defect': DEFECT}
        write_back_model(manifest, apply=True)
        row = AIModel.objects.get(model_key='albert:whisper-large-v3')
        self.assertEqual((DEFECT['label'], DEFECT['reason']), declared_defect(row))
        out = extract_model(row.model_key)['body']
        self.assertEqual(DEFECT, out['quality']['defect'])
        self.assertNotIn('quality_defect', out['extra_info'], 'said once, under `quality`')
        # A silent manifest ungreys nothing ; the revocation does.
        silent = extract_model(row.model_key)
        silent['body'].pop('quality')
        write_back_model(silent, apply=True)
        self.assertIsNotNone(declared_defect(AIModel.objects.get(pk=row.pk)))
        un_write_back_model(silent, apply=True)
        self.assertIsNone(declared_defect(AIModel.objects.get(pk=row.pk)))

    def test_the_sync_keeps_it(self):
        from wama.model_manager.models import ModelSource, ModelType
        from wama.model_manager.services.model_registry import ModelInfo
        from wama.model_manager.services.model_sync import ModelSyncService
        _asr('transcriber:flawed-asr', defect=DEFECT)
        info = ModelInfo(id='flawed-asr', name='flawed-asr', model_type=ModelType.SPEECH,
                         source=ModelSource('transcriber'), vram_gb=3.0, extra_info={'x': 1})
        ModelSyncService()._sync_model('transcriber:flawed-asr', info)
        self.assertIsNotNone(declared_defect(AIModel.objects.get(model_key='transcriber:flawed-asr')))


class ADefectiveModelLeavesTheAutomaticDrawTest(TestCase):
    """The REMOTE model the user's key opens, preferred by the priority, is not drawn once its
    defect is on its row — the local one is. Without it, it wins (counter-proof in the test)."""

    def _draw(self):
        from wama.model_manager.services import select_model
        chosen = select_model(model_type='speech', prefer_loaded=False, vram_budget_gb=10,
                              candidates=['albert:whisper-large-v3', 'transcriber:local-asr'],
                              cloud_keys=['albert:whisper-large-v3'],
                              priority=['whisper-large-v3'])
        return chosen.model_key if chosen else None

    def test_the_validated_defect_hands_the_draw_to_the_local_model(self):
        _asr('albert:whisper-large-v3', execution='cloud', defect=DEFECT)
        _asr('transcriber:local-asr')
        self.assertEqual('transcriber:local-asr', self._draw())

    def test_without_it_the_remote_model_would_win(self):
        _asr('albert:whisper-large-v3', execution='cloud')
        _asr('transcriber:local-asr')
        self.assertEqual('albert:whisper-large-v3', self._draw())


class TheSelectGreysItWithItsReasonTest(TestCase):
    """Listing is not choosing (`INPUT_MODEL_MATCHING §2`) : the option STAYS, greyed, its short
    label in the select and its reason on hover — never the « backend absent » of another verdict."""

    def _options(self):
        user = get_user_model().objects.create_user(username='defect_select', password='x')
        client = Client()
        client.force_login(user)
        data = client.get('/model-manager/api/models/options/', {'task': 'transcription'}).json()
        return [o for g in data['groups'] for o in g['options']]

    def test_without_a_defect_the_model_is_selectable(self):
        _asr('transcriber:flawed-asr')
        self.assertIn(['transcriber:flawed-asr', 'flawed-asr'], self._options())

    def test_the_option_is_listed_disabled_with_its_own_reason(self):
        _asr('transcriber:flawed-asr', defect=DEFECT)
        _asr('transcriber:sound-asr')
        options = self._options()
        flawed = next(o for o in options if isinstance(o, dict) and o.get('value') == 'transcriber:flawed-asr')
        self.assertTrue(flawed['disabled'])
        self.assertIn(DEFECT['label'], flawed['label'])
        self.assertNotIn('backend absent', flawed['label'])
        self.assertEqual(DEFECT['reason'], flawed['title'])
        self.assertIn(['transcriber:sound-asr', 'sound-asr'], options, 'a sound model stays selectable')


class TheEvidenceComparesLikeWithLikeTest(_ComparableProbe, TestCase):
    """A shortfall is the model's only when the model ALONE changed : same input, same settings."""

    def setUp(self):
        super().setUp()
        for key in ('albert:whisper-large-v3', 'transcriber:whisper'):
            _asr(key, execution='cloud' if key.startswith('albert') else 'local')

    def test_same_audio_same_settings_another_model_covered_it(self):
        _line(1, 'albert:whisper-large-v3', 0.56, short=True)
        _line(2, 'transcriber:whisper', 0.90, short=False)
        [case] = defect_evidence('albert:whisper-large-v3')
        self.assertEqual(('1', 'transcriber:whisper', 0.90), (case['object_id'], case['other_model'],
                                                              case['other_value']))
        self.assertEqual([], defect_evidence('transcriber:whisper'), 'the one that covered is sound')

    def test_no_evidence_when_something_else_than_the_model_changed(self):
        _line(1, 'albert:whisper-large-v3', 0.56, short=True, settings={'vad_mode': 'off'})
        _line(2, 'transcriber:whisper', 0.90, short=False)
        _line(3, 'albert:whisper-large-v3', 0.56, short=True, audio='sha-b')
        self.assertEqual([], defect_evidence('albert:whisper-large-v3'))

    def test_no_evidence_under_the_margin_or_when_both_fall_short(self):
        _line(1, 'albert:whisper-large-v3', 0.70, short=True)
        _line(2, 'transcriber:whisper', 0.78, short=False)
        _line(3, 'albert:whisper-large-v3', 0.40, short=True, audio='sha-b')
        _line(4, 'transcriber:whisper', 0.50, short=True, audio='sha-b')
        self.assertEqual([], defect_evidence('albert:whisper-large-v3'))

    def test_auto_is_not_a_model(self):
        """An old line carries « auto », not the model drawn : it proves nothing."""
        _line(1, 'albert:whisper-large-v3', 0.56, short=True)
        _line(2, 'auto', 0.90, short=False)
        self.assertEqual([], defect_evidence('albert:whisper-large-v3'))

    def test_a_measure_that_does_not_compare_models_proves_nothing(self):
        """Measured on 2026-10-28 : speech coverage depends on the engine's segments and on a filter
        applied to Whisper and Albert only — it would have greyed Whisper, not Albert."""
        _line(1, 'albert:whisper-large-v3', 0.10, short=True, check='speech_coverage')
        _line(2, 'transcriber:whisper', 0.95, short=False, check='speech_coverage')
        self.assertEqual([], defect_evidence('albert:whisper-large-v3'))


class TheMeasureProposesTheAdminValidatesTest(_ComparableProbe, TestCase):
    """The measure never greys by itself : it PROPOSES ; an administrator's validation projects."""

    def setUp(self):
        super().setUp()
        _asr('albert:whisper-large-v3', execution='cloud')
        _asr('transcriber:whisper')
        _line(1, 'albert:whisper-large-v3', 0.56, short=True)
        _line(2, 'transcriber:whisper', 0.90, short=False)

    def test_a_proposal_waits_and_nothing_is_greyed_until_validated(self):
        obj = propose_defect('albert:whisper-large-v3')
        self.assertTrue(obj.is_pending)
        defect = obj.body['quality']['defect']
        self.assertEqual('misses the probe', defect['label'], "the check's declared label")
        self.assertRegex(defect['source'], r'20\d\d-\d\d-\d\d')
        row = AIModel.objects.get(model_key='albert:whisper-large-v3')
        self.assertIsNone(declared_defect(row), 'proposing greys nothing')
        _line(3, 'albert:whisper-large-v3', 0.50, short=True, audio='sha-b')
        _line(4, 'transcriber:whisper', 0.95, short=False, audio='sha-b')
        again = propose_defect(row.model_key)
        self.assertEqual(obj.pk, again.pk, 'one pending proposal, refreshed — not one per measure')
        self.assertIn('2 cas', again.body['quality']['defect']['reason'])
        self.assertTrue(proposals.apply(again)['applied'])
        self.assertIsNotNone(declared_defect(AIModel.objects.get(pk=row.pk)))
        self.assertIsNone(propose_defect(row.model_key), 'already validated')

    def test_no_evidence_no_proposal(self):
        self.assertIsNone(propose_defect('transcriber:whisper'))

    def test_a_measure_below_the_floor_asks_for_a_proposal(self):
        """`run_checks` hands a short result to `propose_defect` — and a sound one does not."""
        from wama.common.services import result_evaluation as evaluation
        item, row = mock.Mock(pk=7), mock.Mock(status=JOB_SUCCESS, task_id='', model_key='albert:x')
        spec = mock.Mock(key='transcribe', label='', checks=('probe',))
        pipeline = mock.Mock(specs=[spec], rows=lambda i: {'transcribe': row})
        for short, compares, asked in ((True, True, ['albert:x']), (False, True, []), (True, False, [])):
            calls = []
            probe = evaluation.Check('probe', 'Probe', lambda *a: {'value': 0.5, 'short': short},
                                     defect_label='misses', compares_models=compares)
            with mock.patch.dict(evaluation.CHECKS, {'probe': probe}), \
                    mock.patch('wama.common.services.process_pipeline.pipeline_of', return_value=pipeline), \
                    mock.patch('wama.model_manager.services.model_quality.propose_defect', calls.append):
                evaluation.run_checks('transcriber', item)
            self.assertEqual(asked, calls)


class PastResultsAreMeasuredByTheSameRouteTest(TestCase):
    """`measure_checks` : the results produced before the measures existed get theirs, through
    `run_checks` — counted without `--apply`, and only the lines still without measures."""

    def test_counting_writes_nothing_and_apply_measures_the_unmeasured_only(self):
        from io import StringIO

        from django.core.management import call_command
        from wama.transcriber.models import Transcript
        user = get_user_model().objects.create_user(username='measure_owner', password='x')
        fresh = Transcript.objects.create(user=user)
        measured = Transcript.objects.create(user=user)
        for item, summary in ((fresh, {}), (measured, {'checks': [{'key': 'speech_coverage'}]})):
            ProcessRun.objects.create(app='transcriber', object_type='Transcript',
                                      object_id=str(item.pk), node_id='transcribe',
                                      process_key='transcriber.transcribe', status=JOB_SUCCESS,
                                      output_summary=summary)
        played = []
        with mock.patch('wama.common.services.result_evaluation.run_checks',
                        side_effect=lambda app, item: played.append(item.pk) or [{}]):
            out = StringIO()
            call_command('measure_checks', app=['transcriber'], stdout=out)
            self.assertEqual([], played)
            self.assertIn('1 élément(s)', out.getvalue())
            call_command('measure_checks', app=['transcriber'], apply=True, stdout=StringIO())
        self.assertEqual([fresh.pk], played)


class EveryAppsModelFieldsAreKnownTest(SimpleTestCase):
    """The comparison sets aside EVERY setting that chooses a model, not the first : measured on
    2026-10-28, five apps declare several (the describer three — speech, vision, language) ; with
    the first alone, a vision model change would read as « other settings »."""

    def test_an_app_with_several_model_selectors_names_them_all(self):
        from wama.common.utils.auto_model import catalog_field, catalog_fields
        self.assertEqual(['asr_model', 'vision_model', 'llm_model'],
                         [f['name'] for f in catalog_fields('describer')])
        for app in ('avatarizer', 'composer', 'reader', 'transcriber'):
            with self.subTest(app=app):
                names = [f['name'] for f in catalog_fields(app)]
                self.assertIn(catalog_field(app)['name'], names)
                self.assertEqual(len(names), len(set(names)))
