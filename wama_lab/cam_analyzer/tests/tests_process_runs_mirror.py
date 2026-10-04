"""Passes du Lab → lignes d'exécution COMMUNES (`common.ProcessRun`), étape 1 : ÉCRITURE EN DOUBLE
(2026-10-03, décision de Fabien ; ROUTE §10.6 4.1).

`AnalysisPass` a été le modèle de `ProcessRun`. Tant que les lecteurs lisent encore `AnalysisPass`
(étape 2 à venir), chaque écriture d'une passe doit écrire AUSSI sa ligne commune, avec le même
état traduit dans le vocabulaire `JOB_*` : ce test joue le cycle de vie d'une passe et vérifie,
à chaque geste, que les deux tables disent la même chose.
"""
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import RequestFactory, TestCase, override_settings

from wama.common.models import ProcessRun
from wama.common.services import process_runs
from wama_lab.cam_analyzer.models import AnalysisPass, AnalysisProfile, AnalysisSession, CameraView
from wama_lab.cam_analyzer.utils import pass_tracking as pt


@override_settings(CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}})
class ProcessRunMirrorTest(TestCase):

    def setUp(self):
        cache.clear()
        self.user = get_user_model().objects.create_user('pass_mirror_test', password='x')
        self.profile = AnalysisProfile.objects.create(user=self.user, name='p', model_path='yolo11n.pt')
        self.session = AnalysisSession.objects.create(user=self.user, profile=self.profile)
        self.front = CameraView.objects.create(session=self.session, position='front',
                                               video_file='cam_analyzer/test/front.mp4')

    def line(self, pass_type, camera=None):
        return process_runs.line(self.session, pass_type, pt.instance_key(camera))

    def assert_mirrored(self):
        """Chaque ligne du Lab a sa ligne commune, au même état (traduit), même photo, même erreur."""
        rows = list(AnalysisPass.objects.filter(session=self.session).select_related('camera'))
        self.assertTrue(rows)
        for row in rows:
            run = self.line(row.pass_type, row.camera)
            self.assertIsNotNone(run, row.pass_type)
            self.assertEqual(run.status, pt.common_status(row.status), row.pass_type)
            self.assertEqual(run.settings_snapshot, row.parameters or {}, row.pass_type)
            self.assertEqual(run.error_message, row.error_message or '', row.pass_type)
            self.assertEqual(run.process_key, pt.process_key(row.pass_type))
        self.assertEqual(process_runs.lines(self.session).count(), len(rows))

    def test_a_per_camera_pass_writes_its_common_line_with_the_camera_as_instance_key(self):
        pt.mark_started(self.session, 'yolo_detect', self.profile, camera=self.front)
        run = self.line('yolo_detect', self.front)
        self.assertEqual(run.instance_key, 'front')
        self.assertEqual(run.status, 'RUNNING')
        self.assertEqual(run.settings_snapshot['model_path'], 'yolo11n.pt')
        self.assert_mirrored()
        pt.mark_completed(self.session, 'yolo_detect', output_summary={'frames': 12}, camera=self.front)
        self.assertEqual(self.line('yolo_detect', self.front).output_summary['frames'], 12)
        self.assert_mirrored()

    def test_a_session_pass_has_an_empty_instance_key_and_keeps_its_error(self):
        pt.mark_started(self.session, 'global_tracking', self.profile)
        pt.mark_failed(self.session, 'global_tracking', 'plus de GPS')
        run = self.line('global_tracking')
        self.assertEqual((run.instance_key, run.status, run.error_message), ('', 'FAILURE', 'plus de GPS'))
        self.assert_mirrored()

    def test_staleness_and_its_cascade_reach_the_common_lines(self):
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
        self.assertEqual(self.line('yolo_detect', self.front).status, 'STALE')
        self.assertEqual(self.line('lane_events').status, 'STALE', "la cascade vers l'aval")
        self.assertEqual(self.line('extraction').status, 'SUCCESS', "l'amont n'est pas touché")
        self.assert_mirrored()

    def test_staleness_is_decided_per_camera_line(self):
        """L'avant détecté avec l'ancien modèle est périmé, l'arrière relancé avec le nouveau ne l'est
        pas — ligne par ligne, comme le Lab (la 1ʳᵉ version périmait toutes les caméras d'un coup)."""
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
                         ('STALE', 'SUCCESS'))
        self.assert_mirrored()

    def test_an_interrupted_calculation_and_a_cancelled_sam3_close_both_lines(self):
        pt.mark_started(self.session, 'distance', self.profile)
        self.assertEqual(pt.reconcile_interrupted_calc_passes(self.session), 1)   # aucune chaîne
        self.assertEqual(self.line('distance').error_message, pt.INTERRUPTED_MESSAGE)
        pt.mark_started(self.session, 'sam3_markings', self.profile, camera=self.front)
        self.assertEqual(pt.fail_running(self.session, 'sam3_markings', 'annulée'), 1)
        self.assertEqual(self.line('sam3_markings', self.front).status, 'FAILURE')
        self.assert_mirrored()

    def test_a_common_line_that_cannot_be_written_never_breaks_the_pass(self):
        def start(*args, **kwargs):                 # une vraie fonction : `safely` journalise son nom
            raise RuntimeError('base commune')
        with mock.patch.object(process_runs, 'start', start):
            pt.mark_started(self.session, 'depth', self.profile)
        self.assertEqual(AnalysisPass.objects.get(session=self.session, pass_type='depth').status, 'running')

    def test_the_backfill_gives_a_line_to_an_older_pass_and_leaves_existing_lines_alone(self):
        """Étape 2a : une passe jouée AVANT l'écriture en double n'a pas de ligne commune — les
        lecteurs basculés la verraient « jamais jouée ». La reprise la crée ; une ligne déjà
        écrite fait foi (son résumé n'est pas réécrit) ; rejouer ne crée rien."""
        from django.utils import timezone
        AnalysisPass.objects.create(session=self.session, pass_type='extraction', status='completed',
                                    parameters={'fps': 10}, output_summary={'frames': 3},
                                    completed_at=timezone.now(), duration_s=4.0)
        pt.mark_started(self.session, 'yolo_detect', self.profile, camera=self.front)
        pt.mark_completed(self.session, 'yolo_detect', camera=self.front)
        ProcessRun.objects.filter(node_id='yolo_detect').update(output_summary={'kept': True})
        self.assertEqual(pt.backfill_common_lines([self.session]), 1)
        run = self.line('extraction')
        self.assertEqual((run.status, run.output_summary, run.duration_s), ('SUCCESS', {'frames': 3}, 4.0))
        self.assertEqual(self.line('yolo_detect', self.front).output_summary, {'kept': True})
        self.assertEqual(pt.backfill_common_lines([self.session]), 0, 'rejouable')
        self.assertEqual(process_runs.lines(self.session).count(), 2)

    def test_the_panel_reads_the_common_lines(self):
        """Étape 2b : l'état affiché vient de la ligne COMMUNE (retraduit pour le panneau) — une
        ligne commune périmée seule suffit à afficher « stale »."""
        pt.mark_started(self.session, 'yolo_detect', self.profile, camera=self.front)
        pt.mark_completed(self.session, 'yolo_detect', camera=self.front)
        ProcessRun.objects.filter(node_id='yolo_detect').update(status='STALE')
        rows = [r for r in pt.get_passes_status(self.session) if r['pass_type'] == 'yolo_detect']
        self.assertEqual([(r['camera'], r['status']) for r in rows], [('front', 'stale')])
        extraction = next(r for r in pt.get_passes_status(self.session) if r['pass_type'] == 'extraction')
        self.assertEqual(extraction['status'], 'never', 'une passe sans ligne reste « jamais jouée »')

    def test_duplicating_a_session_copies_its_lines_and_deleting_it_forgets_them(self):
        from wama_lab.cam_analyzer import views
        pt.mark_started(self.session, 'extraction', self.profile)
        pt.mark_completed(self.session, 'extraction')
        rf = RequestFactory()
        req = rf.post('/x/')
        req.user = self.user
        new_id = __import__('json').loads(views.duplicate_session(req, self.session.id).content)['id']
        new = AnalysisSession.objects.get(pk=new_id)
        self.assertEqual(process_runs.line(new, 'extraction').status, 'SUCCESS')
        req = rf.post('/x/')
        req.user = self.user
        with mock.patch.object(views, '_console'):
            views.delete_session(req, new.id)
        self.assertFalse(ProcessRun.objects.filter(object_id=str(new_id)).exists())
        self.assertTrue(process_runs.lines(self.session).exists(), "l'original garde les siennes")
