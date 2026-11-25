"""The lane passes of a session, read as marks (`ROUTE §10.7.14 ㉑`, 2026-11-25).

What is PROPER to the app : the rows are stored per camera (`LaneEvent`), the track is read for the
whole session, in the order of time, each pass naming its intersection window by its rank. The
contract of a stated track (common names, registry, manifest) is held once, by
`wama/common/tests/tests_marks.py`.
"""
from django.contrib.auth.models import User
from django.test import TestCase

from wama.common.catalog import marks
from wama_lab.cam_analyzer.models import AnalysisSession, CameraView, LaneEvent


class LanePassesOfASessionTest(TestCase):

    @classmethod
    def setUpTestData(cls):
        user = User.objects.create_user('lane_marks')
        cls.session = AnalysisSession.objects.create(user=user, name='s', intersection_windows=[
            {'name': 'A', 't_enter': 0.0, 't_exit': 10.0},
            {'name': 'B', 't_enter': 20.0, 't_exit': 30.0}])
        cls.front = CameraView.objects.create(session=cls.session, position='front')
        cls.rear = CameraView.objects.create(session=cls.session, position='rear')
        other = AnalysisSession.objects.create(user=user, name='other')
        elsewhere = CameraView.objects.create(session=other, position='front')
        rows = ((cls.front, 7, 1, True, 21.0, 24.0, 1, 'car'),
                (cls.rear, 9, 0, False, 2.0, 5.0, 0, 'truck'),
                (cls.front, 7, 2, False, 12.0, 14.0, -1, 'car'),
                # Entré AVANT la fenêtre B, rattaché à elle par son milieu (la règle du calcul) :
                # seul son rang le dit, la contenance de son début ne la trouverait pas.
                (cls.front, 8, 1, False, 18.0, 23.0, 1, 'bus'),
                (elsewhere, 1, 0, True, 1.0, 2.0, -1, 'car'))
        for camera, track, lane, own, enter, leave, window, name in rows:
            LaneEvent.objects.create(camera=camera, track_id=track, lane_id=lane,
                                     in_shuttle_lane=own, t_enter=enter, t_exit=leave,
                                     intersection_window_idx=window, class_name=name)

    def test_the_passes_of_every_camera_are_read_in_the_order_of_time(self):
        passes = marks.read_track(self.session, 'lane_passes')
        self.assertEqual([(2.0, 5.0), (12.0, 14.0), (18.0, 23.0), (21.0, 24.0)],
                         [(p['start'], p['end']) for p in passes])
        self.assertEqual([self.rear.id, self.front.id, self.front.id, self.front.id],
                         [p['camera'] for p in passes])
        self.assertEqual({'start': 2.0, 'end': 5.0, 'track_id': 9, 'lane': 0,
                          'in_shuttle_lane': False, 'object': 'truck', 'camera': self.rear.id,
                          'origin': 'lane_events', 'parent': 0}, passes[0])

    def test_a_pass_names_its_window_by_its_rank_and_none_outside_of_any(self):
        self.assertEqual([0, None, 1, 1],
                         [p['parent'] for p in marks.read_track(self.session, 'lane_passes')])

    def test_the_window_of_a_session_gives_its_passes_and_says_the_one_that_overflows(self):
        _span, found = marks.read_span(self.session, key='windows', rank=1)
        self.assertEqual([(18.0, 23.0, False), (21.0, 24.0, True)],
                         [(p['mark']['start'], p['mark']['end'], p['inside'])
                          for p in found['lane_passes']])
