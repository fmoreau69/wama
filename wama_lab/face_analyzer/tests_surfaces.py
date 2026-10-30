"""The ANALYSIS surface of the face_analyzer (2026-10-29) — the content of a session : its video,
clock of the shared axis, and its measures image by image in synchronised curves.

Held here without a browser : the measures become ONE typed datum of the Data world
(`series.session_series` → `TypedFrame(timeseries)`), the page is served by the COMMON surface
views on a UUID key, and it is READ-ONLY (`edits=None`) — nothing is written there.
"""
import json

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse


class AnalysisSurfaceTest(TestCase):

    def setUp(self):
        from .models import AnalysisFrame, AnalysisSession
        self.user = get_user_model().objects.create_user('face_surface_owner', password='x')
        self.other = get_user_model().objects.create_user('face_surface_other', password='x')
        # A NAME is enough : the page reads its address, nothing is opened on the disk.
        self.session = AnalysisSession.objects.create(
            user=self.user, status='completed', input_file='face_analyzer/0/input/clip.mp4')
        AnalysisFrame.objects.bulk_create([AnalysisFrame(
            session=self.session, frame_number=i, timestamp=i * 0.5, face_detected=True,
            rppg_data={'heart_rate': 70 + i, 'hrv': {'rmssd': 40}},
            eye_tracking_data={'perclos': 0.25},
            emotion_data={'emotions': {'happy': 0.5}},
        ) for i in range(3)])
        args = ['face_analyzer', 'analysis', self.session.pk]
        self.page, self.data, self.save = (reverse(f'common:{name}', args=args)
                                           for name in ('surface', 'surface_data', 'surface_save'))

    def test_the_measures_become_one_timeseries_with_declared_labels(self):
        from .series import session_series
        payload = session_series(self.session).to_payload()
        self.assertEqual('timeseries', payload['data_type'])
        self.assertEqual(['time', 'heart_rate', 'hrv_rmssd', 'perclos', 'emotion_happy'],
                         payload['fields'], 'a module that rendered nothing gives no column')
        self.assertEqual([0.0, 0.5, 1.0], payload['columns']['time'])
        self.assertEqual([25.0] * 3, payload['columns']['perclos'], 'a ratio shown in percent')
        self.assertEqual({'label': 'Joie', 'unit': ''}, payload['meta']['columns']['emotion_happy'],
                         'the name the common emotion module gives')

    def test_the_owner_opens_the_page_on_its_uuid_with_the_plugins_and_their_sheet(self):
        self.assertIn(str(self.session.pk), self.page)
        self.client.force_login(self.user)
        page = self.client.get(self.page)
        self.assertEqual(200, page.status_code)
        for asset in ('brick-timeseries-chart.js', 'brick-video-view.js',
                      'uplot-1.6.32/uPlot.iife.min.js', 'uplot-1.6.32/uPlot.min.css'):
            self.assertContains(page, asset)
        self.assertContains(page, 'rel="stylesheet" href="/static/vendors/uplot-1.6.32/uPlot.min.css"')

    def test_the_data_carries_the_video_and_the_series_and_nothing_is_editable(self):
        self.client.force_login(self.user)
        data = self.client.get(self.data).json()
        self.assertTrue(data['reads']['video'].endswith('clip.mp4'))
        self.assertEqual([70, 71, 72], data['context']['series']['columns']['heart_rate'])
        self.assertFalse(data['can_edit'], 'a read-only surface : even its owner edits nothing')
        res = self.client.post(self.save, json.dumps({'value': {}}), content_type='application/json')
        self.assertEqual(405, res.status_code)

    def test_someone_else_does_not_read_a_session_that_is_not_shared(self):
        """The session does not inherit sharing : only its user lists it (`listable_by`)."""
        self.client.force_login(self.other)
        self.assertEqual(404, self.client.get(self.page).status_code)
        self.assertEqual(404, self.client.get(self.data).status_code)

    def test_a_session_without_video_says_why(self):
        type(self.session).objects.filter(pk=self.session.pk).update(input_file='')
        self.client.force_login(self.user)
        self.assertContains(self.client.get(self.page), 'Aucune vidéo dans cette session.')
        self.assertEqual(409, self.client.get(self.data).status_code)
