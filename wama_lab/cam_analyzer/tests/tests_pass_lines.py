"""Les passes du Lab SONT des lignes d'exécution communes (`common.ProcessRun`) — 2026-10-04.

`AnalysisPass` a été le modèle de `ProcessRun` (ROUTE §10.6 4.1) ; les passes y sont passées en
trois étapes (écriture en double, historique repris puis lecteurs basculés, table retirée). Ce
fichier tient ce qui en reste à garantir, en base de test : chaque geste d'une passe écrit SA
ligne (une par passe × caméra), le panneau la lit dans le vocabulaire commun, la péremption se
décide ligne par ligne, et la session emporte ses lignes quand on la duplique ou la supprime.
(Il s'appelait `tests_process_runs_mirror` à l'étape 1, quand il comparait les deux tables.)
"""
import json
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import RequestFactory, TestCase, override_settings

from wama.common.models import (JOB_FAILURE, JOB_PENDING, JOB_RUNNING, JOB_STALE, JOB_SUCCESS,
                                ProcessRun)
from wama.common.services import process_runs
from wama_lab.cam_analyzer.models import AnalysisProfile, AnalysisSession, CameraView
from wama_lab.cam_analyzer.utils import pass_tracking as pt


@override_settings(CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}})
class PassLinesTest(TestCase):

    def setUp(self):
        cache.clear()
        self.user = get_user_model().objects.create_user('pass_lines_test', password='x')
        self.profile = AnalysisProfile.objects.create(user=self.user, name='p', model_path='yolo11n.pt')
        self.session = AnalysisSession.objects.create(user=self.user, profile=self.profile)
        self.front = CameraView.objects.create(session=self.session, position='front',
                                               video_file='cam_analyzer/test/front.mp4')

    def line(self, pass_type, camera=None):
        return process_runs.line(self.session, pass_type, pt.instance_key(camera))

    def panel(self, pass_type):
        return [(r['camera'], r['status']) for r in pt.get_passes_status(self.session)
                if r['pass_type'] == pass_type]

    def test_a_per_camera_pass_writes_its_line_with_the_camera_as_instance_key(self):
        pt.mark_started(self.session, 'yolo_detect', self.profile, camera=self.front)
        run = self.line('yolo_detect', self.front)
        self.assertEqual((run.instance_key, run.status, run.process_key),
                         ('front', JOB_RUNNING, 'cam_analyzer.yolo_detect'))
        self.assertEqual(run.settings_snapshot['model_path'], 'yolo11n.pt')
        pt.mark_completed(self.session, 'yolo_detect', output_summary={'frames': 12}, camera=self.front)
        run = self.line('yolo_detect', self.front)
        self.assertEqual((run.status, run.output_summary['frames']), (JOB_SUCCESS, 12))
        self.assertIsNotNone(run.duration_s)

    def test_a_session_pass_has_an_empty_instance_key_and_keeps_its_error(self):
        pt.mark_started(self.session, 'global_tracking', self.profile)
        pt.mark_failed(self.session, 'global_tracking', 'plus de GPS')
        run = self.line('global_tracking')
        self.assertEqual((run.instance_key, run.status, run.error_message), ('', JOB_FAILURE, 'plus de GPS'))

    def test_a_relaunched_pass_keeps_the_previous_duration_and_its_size_for_the_eta(self):
        """Le panneau annonce la durée d'une passe EN COURS d'après sa dernière exécution, mise à
        l'échelle de la taille (`row_eta_seconds`) : les deux doivent survivre au relancement."""
        pt.mark_started(self.session, 'extraction', self.profile)
        pt.mark_completed(self.session, 'extraction', output_summary={'eta_size_s': 600.0})
        ProcessRun.objects.filter(node_id='extraction').update(duration_s=40.0)
        pt.mark_started(self.session, 'extraction', self.profile)
        self.assertEqual(self.line('extraction').output_summary,
                         {'previous_duration_s': 40.0, 'eta_size_s': 600.0})

    def test_staleness_and_its_cascade_reach_the_lines(self):
        pt.mark_started(self.session, 'extraction', self.profile)
        pt.mark_completed(self.session, 'extraction')
        for key in ('yolo_detect', 'yolopv2_lanes'):
            pt.mark_started(self.session, key, self.profile, camera=self.front)
            pt.mark_completed(self.session, key, camera=self.front)
        pt.mark_started(self.session, 'lane_events', self.profile)
        pt.mark_completed(self.session, 'lane_events')
        self.profile.model_path = 'yolo11x.pt'          # réglage SURVEILLÉ par yolo_detect
        self.profile.save()
        self.session.refresh_from_db()
        self.assertGreaterEqual(pt.recompute_stale(self.session), 2)
        self.assertEqual(self.line('yolo_detect', self.front).status, JOB_STALE)
        self.assertEqual(self.line('lane_events').status, JOB_STALE, "la cascade vers l'aval")
        self.assertEqual(self.line('extraction').status, JOB_SUCCESS, "l'amont n'est pas touché")

    def test_staleness_is_decided_per_camera_line(self):
        """L'avant détecté avec l'ancien modèle est périmé, l'arrière relancé avec le nouveau ne l'est
        pas — ligne par ligne (la 1ʳᵉ version de l'étape 1 périmait toutes les caméras d'un coup)."""
        rear = CameraView.objects.create(session=self.session, position='rear',
                                         video_file='cam_analyzer/test/rear.mp4')
        pt.mark_started(self.session, 'extraction', self.profile)
        pt.mark_completed(self.session, 'extraction')
        pt.mark_started(self.session, 'yolo_detect', self.profile, camera=self.front)
        pt.mark_completed(self.session, 'yolo_detect', camera=self.front)
        self.profile.model_path = 'yolo11x.pt'
        self.profile.save()
        pt.mark_started(self.session, 'yolo_detect', self.profile, camera=rear)
        pt.mark_completed(self.session, 'yolo_detect', camera=rear)
        self.session.refresh_from_db()
        pt.recompute_stale(self.session)
        self.assertEqual((self.line('yolo_detect', self.front).status, self.line('yolo_detect', rear).status),
                         (JOB_STALE, JOB_SUCCESS))

    def test_an_interrupted_calculation_and_a_cancelled_sam3_close_their_lines(self):
        pt.mark_started(self.session, 'distance', self.profile)
        self.assertEqual(pt.reconcile_interrupted_calc_passes(self.session), 1)   # aucune chaîne
        self.assertEqual((self.line('distance').status, self.line('distance').error_message),
                         (JOB_FAILURE, pt.INTERRUPTED_MESSAGE))
        pt.mark_started(self.session, 'sam3_markings', self.profile, camera=self.front)
        self.assertEqual(pt.fail_running(self.session, 'sam3_markings', 'annulée'), 1)
        self.assertEqual(self.line('sam3_markings', self.front).status, JOB_FAILURE)

    def test_the_panel_speaks_the_common_vocabulary_with_the_registry_labels(self):
        """Le panneau montre l'état de la ligne commune tel quel (`JOB_*`), une passe jamais jouée
        en `PENDING` — comme la bande des process d'une card (`AppPipeline.card_rows`) —, et le
        libellé du registre."""
        pt.mark_started(self.session, 'yolo_detect', self.profile, camera=self.front)
        pt.mark_completed(self.session, 'yolo_detect', camera=self.front)
        self.assertEqual(self.panel('yolo_detect'), [('front', JOB_SUCCESS)])
        ProcessRun.objects.filter(node_id='yolo_detect').update(status=JOB_STALE)
        self.assertEqual(self.panel('yolo_detect'), [('front', JOB_STALE)])
        self.assertEqual(self.panel('extraction'), [(None, JOB_PENDING)])
        labels = {r['pass_type']: r['label'] for r in pt.get_passes_status(self.session)}
        self.assertEqual(labels['global_tracking'], 'Tracking 360° (gids + trajectoires)')

    def test_complete_the_missing_passes_relaunches_pending_stale_and_failed_lines(self):
        """« Compléter les passes » (`run_passes` sans liste) relance ce qui n'est pas à jour : jamais
        joué (`PENDING`), périmé, en échec — rien de ce qui est en succès."""
        from wama_lab.cam_analyzer import views
        pt.mark_started(self.session, 'extraction', self.profile)
        pt.mark_completed(self.session, 'extraction')
        pt.mark_started(self.session, 'global_tracking', self.profile)
        pt.mark_failed(self.session, 'global_tracking', 'boom')
        req = RequestFactory().post('/x/', data='{}', content_type='application/json')
        req.user = self.user
        with mock.patch.object(pt, 'reconcile_interrupted_calc_passes'), \
                mock.patch.object(pt, 'launch_session_passes',
                                  return_value={'launched': [], 'queued': []}) as launch, \
                mock.patch.object(views, '_pause_live'), \
                mock.patch('wama_lab.cam_analyzer.utils.window_recompute.recompute_intersection_windows'), \
                mock.patch.object(views.DetectionFrame.objects, 'filter') as frames:
            frames.return_value.exists.return_value = True
            views.run_passes(req, self.session.id)
        asked = set(launch.call_args.args[1])
        self.assertIn('global_tracking', asked, 'en échec')
        self.assertIn('conflicts', asked, 'jamais jouée')
        self.assertNotIn('extraction', asked, 'en succès')

    def test_duplicating_a_session_copies_its_lines_and_deleting_it_forgets_them(self):
        from wama_lab.cam_analyzer import views
        pt.mark_started(self.session, 'extraction', self.profile)
        pt.mark_completed(self.session, 'extraction')
        rf = RequestFactory()
        req = rf.post('/x/')
        req.user = self.user
        new_id = json.loads(views.duplicate_session(req, self.session.id).content)['id']
        new = AnalysisSession.objects.get(pk=new_id)
        self.assertEqual(process_runs.line(new, 'extraction').status, JOB_SUCCESS)
        req = rf.post('/x/')
        req.user = self.user
        with mock.patch.object(views, '_console'):
            views.delete_session(req, new.id)
        self.assertFalse(ProcessRun.objects.filter(object_id=str(new_id)).exists())
        self.assertTrue(process_runs.lines(self.session).exists(), "l'original garde les siennes")
