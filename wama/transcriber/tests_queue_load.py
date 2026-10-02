"""Ce que coûte la page du transcriber à charger (2026-10-02 / 10-03, mesuré sur le serveur en service).

CE QUE CES GARDES TIENNENT :
- la FILE ne lit pas les segments des transcriptions (`Transcript.QUEUE_DEFERRED_FIELDS`, différés
  par `batch_common.build_batches_list`) : 0,405 s pour 23 cards avec, 0,005 s sans ;
- la PROGRESSION GLOBALE, interrogée toutes les 2 à 3 s, est UNE requête sur `status` et
  `progress` : elle chargeait chaque transcription entière (0,48-0,70 s par appel).
"""
from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from wama.transcriber.models import Transcript


def _reads_segments(queries):
    return [q['sql'] for q in queries
            if 'transcriber_transcript' in q['sql'] and '"segments_json"' in q['sql']]


class QueueLoadTest(TestCase):

    def setUp(self):
        self.user = get_user_model().objects.create_superuser('queue_load', password='x')
        self.client.force_login(self.user)
        segments = [{'start_time': i, 'end_time': i + 1, 'text': 'mot ' * 20} for i in range(200)]
        Transcript.objects.create(user=self.user, audio='transcriber/input/a.wav', status='PENDING',
                                  progress=0, segments_json=segments)
        Transcript.objects.create(user=self.user, audio='transcriber/input/b.wav', status='RUNNING',
                                  progress=50, segments_json=segments)

    def test_the_queue_page_does_not_read_the_segments(self):
        self.client.get(reverse('transcriber:index'))          # enveloppe les orphelines
        with CaptureQueriesContext(connection) as queries:
            response = self.client.get(reverse('transcriber:index'))
        self.assertEqual(200, response.status_code)
        self.assertEqual([], _reads_segments(queries.captured_queries))

    def test_the_global_progress_is_one_light_query(self):
        with CaptureQueriesContext(connection) as queries:
            data = self.client.get(reverse('transcriber:global_progress')).json()
        self.assertEqual((2, 1, 1, 25), (data['total'], data['pending'], data['running'],
                                         data['overall_progress']))
        on_transcripts = [q['sql'] for q in queries.captured_queries
                          if 'FROM "transcriber_transcript"' in q['sql']]
        self.assertEqual(1, len(on_transcripts), on_transcripts)
        self.assertEqual([], _reads_segments(queries.captured_queries))
