"""The readable result of each process of the transcriber (`ROUTE §F3b`, faces of the pipeline,
2026-10-12).

The enriched TXT export (`workers._save_output_files`) has long written one section per process —
transcription, speakers, summary, coherence. Those sections are now ALSO the readable result of
their process (`ProcessSpec.result`), read by the common preview as faces. Held here : the export
is byte for byte what it was (golden written against the code before the sections were split),
and each section reader gives the body of its section, or nothing when the process left nothing.
"""
from django.contrib.auth import get_user_model
from django.test import TestCase

from wama.transcriber.models import Transcript, TranscriptSegment

SEP = '=' * 60

GOLDEN_FULL = '\n'.join([
    SEP, 'TRANSCRIPTION', SEP, 'Bonjour à tous.', '',
    SEP, 'DIARISATION — LOCUTEURS', SEP,
    '[SPEAKER_00]  00:01.000 - 00:04.500', '  Bonjour', '',
    '[Inconnu]  00:04.500 - 00:09.000', '  à tous.', '',
    SEP, 'COMPTE-RENDU DE RÉUNION', SEP, 'Un résumé.', '',
    'Points clés :', '  • a', '  • b', '', 'Actions :', '  • c', '',
    SEP, 'VÉRIFICATION DE COHÉRENCE', SEP, 'Score : 82/100', '',
    'Problèmes détectés :', '  • n1', '  • n2', '',
    'Version corrigée proposée :', '-' * 40, 'Bonjour à tous !', '',
])

GOLDEN_TEXT_ONLY = '\n'.join([SEP, 'TRANSCRIPTION', SEP, 'Bonjour à tous.', ''])


class ResultSectionsTest(TestCase):

    def setUp(self):
        self.user = get_user_model().objects.create_user('result_sections_owner', password='x')

    def _transcript(self, **kw):
        kw.setdefault('text', 'Bonjour à tous.')
        return Transcript.objects.create(user=self.user, audio='transcriber/input/a.wav', **kw)

    def _full(self):
        t = self._transcript(summary='Un résumé.', summary_type='meeting',
                             key_points=['a', 'b'], action_items=['c'], coherence_score=82,
                             coherence_notes='n1\n\nn2', coherence_suggestion='Bonjour à tous !')
        TranscriptSegment.objects.create(transcript=t, speaker_id='SPEAKER_00', start_time=1.0,
                                         end_time=4.5, text='Bonjour', order=0)
        TranscriptSegment.objects.create(transcript=t, speaker_id='', start_time=4.5,
                                         end_time=9.0, text='à tous.', order=1)
        return t

    def test_the_enriched_export_is_unchanged(self):
        from wama.transcriber.utils.transcript_documents import enriched_text
        self.assertEqual(GOLDEN_FULL, enriched_text(self._full()))
        self.assertEqual(GOLDEN_TEXT_ONLY, enriched_text(self._transcript()))

    def test_each_section_reader_gives_the_body_of_its_section(self):
        from wama.transcriber.utils import transcript_documents as docs
        t = self._full()
        self.assertEqual('Bonjour à tous.', docs.transcription_text(t))
        self.assertEqual('[SPEAKER_00]  00:01.000 - 00:04.500\n  Bonjour\n\n'
                         '[Inconnu]  00:04.500 - 00:09.000\n  à tous.', docs.diarization_text(t))
        # The summary is markdown (`result_format`) : its key points and actions are real lists,
        # the way the transcriber's own result modal showed them — the export keeps its bullets.
        self.assertEqual('Un résumé.\n\n### Points clés\n- a\n- b\n\n### Actions à mener\n- c',
                         docs.summary_text(t))
        # The coherence is the REPORT of the common brick, set against the text it checked.
        self.assertEqual({'score': 82, 'level': 'success', 'notes': ['n1', 'n2'],
                          'suggestion': 'Bonjour à tous !', 'original': 'Bonjour à tous.'},
                         docs.coherence_report(t))

    def test_a_process_that_left_nothing_has_no_readable_result(self):
        from wama.transcriber.utils import transcript_documents as docs
        t = self._transcript()
        self.assertIsNone(docs.diarization_text(t), 'no speaker named : nothing to show')
        self.assertIsNone(docs.summary_text(t))
        self.assertIsNone(docs.coherence_report(t))
        self.assertIsNone(docs.transcription_text(self._transcript(text='')))
