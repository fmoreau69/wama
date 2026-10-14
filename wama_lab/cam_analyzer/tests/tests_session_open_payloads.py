"""Les deux réponses lourdes de l'ouverture d'une session — détections par caméra et courbe de
proximité — sont calculées par la base depuis le 2026-10-14. Elles doivent rendre EXACTEMENT ce
que rendait le calcul Python d'avant, reproduit ici comme référence."""
import json

from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase

from wama_lab.cam_analyzer import views
from wama_lab.cam_analyzer.models import AnalysisSession, CameraView, DetectionFrame

FRAMES = [
    (0, 0.0, []),
    (1, 0.4, [{'class_name': 'car', 'proximity': 0.12345, 'bbox': [1, 2, 3.5, 4]}]),
    (2, 0.9, [{'class_name': 'piéton', 'proximity': 0.5}, {'class_name': 'truck'}]),
    (3, 1.2, [{'class_name': 'bus', 'proximity': 1}]),
    (4, 2.7, [{'class_name': 'car', 'proximity': 0.0004999}, {'class_name': 'car', 'proximity': None}]),
    (5, 3.1, [{'class_name': 'car', 'proximity': 0.33333333333}]),
    (6, 9.5, [{'class_name': 'car', 'proximity': 0.9}]),        # au-delà de la durée : hors courbe
]


def reference_frames(camera, start, end):
    """La vue d'avant : les images décodées puis réencodées par Python."""
    return list(DetectionFrame.objects.filter(camera=camera, frame_number__gte=start, frame_number__lt=end)
                .order_by('frame_number').values('frame_number', 'timestamp', 'detections'))


def reference_series(camera, num_bins):
    """La boucle d'avant, une proximité `None` en moins (elle la faisait échouer)."""
    series = [0.0] * num_bins
    for frame in DetectionFrame.objects.filter(camera=camera).order_by('frame_number'):
        bin_idx = int(frame.timestamp / 1.0)
        if 0 <= bin_idx < num_bins:
            max_prox = max((d.get('proximity') or 0 for d in frame.detections), default=0)
            if max_prox > series[bin_idx]:
                series[bin_idx] = round(max_prox, 3)
    return series


class SessionOpenPayloadsTest(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user('open-payloads-test', password='x')
        self.session = AnalysisSession.objects.create(user=self.user, name='t')
        self.camera = CameraView.objects.create(session=self.session, position='front',
                                                video_file='x.mp4', duration=5.0, fps=10.0,
                                                width=1920, height=1080)
        DetectionFrame.objects.bulk_create(
            DetectionFrame(camera=self.camera, frame_number=n, timestamp=t, detections=d)
            for n, t, d in FRAMES)

    def _get(self, view, path='/', **kw):
        request = RequestFactory().get(path)
        request.user = self.user
        return view(request, session_id=self.session.pk, **kw)

    def test_detections_are_the_stored_frames_unchanged(self):
        response = self._get(views.get_detections, '/?start=0&end=999999', camera_id=self.camera.pk)
        self.assertEqual(response['Content-Type'], 'application/json')
        self.assertEqual(json.loads(response.content), {
            'camera_id': self.camera.pk, 'position': 'front', 'fps': 10.0, 'width': 1920,
            'height': 1080, 'frames': reference_frames(self.camera, 0, 999999)})

    def test_detections_keep_the_requested_frame_range(self):
        response = self._get(views.get_detections, '/?start=2&end=5', camera_id=self.camera.pk)
        frames = json.loads(response.content)['frames']
        self.assertEqual([f['frame_number'] for f in frames], [2, 3, 4])
        self.assertEqual(frames, reference_frames(self.camera, 2, 5))

    def test_detections_of_a_camera_without_frames_are_an_empty_list(self):
        DetectionFrame.objects.all().delete()
        response = self._get(views.get_detections, camera_id=self.camera.pk)
        self.assertEqual(json.loads(response.content)['frames'], [])

    def test_proximity_curve_matches_the_python_loop(self):
        data = json.loads(self._get(views.get_analytics_data).content)
        timeline = data['proximity_timeline']
        self.assertEqual(timeline['timestamps'], [0.0, 1.0, 2.0, 3.0, 4.0, 5.0])
        self.assertEqual(timeline['series']['front'], reference_series(self.camera, 6))
        self.assertEqual(timeline['series']['front'], [0.5, 1.0, 0.0, 0.333, 0.0, 0.0])
