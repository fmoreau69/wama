"""Lecture d'une transcription produite ailleurs (`utils.transcript_documents`).

⚠ Contenus INVENTÉS : le dépôt est public, et les transcriptions réelles de l'utilisateur ne
doivent jamais y entrer — seule leur FORME est reproduite ici (en-tête d'export Sonal, labels
« Speaker N : », exports WAMA).
"""
import os
import tempfile

from django.test import SimpleTestCase

from wama.transcriber.utils.transcript_documents import (
    parse_cues, parse_speaker_turns, parse_timecode, read_transcript_document,
)

SONAL_LIKE = """=================================================================================
Entretien exporté depuis Sonal (v.2.1) le 01/01/2026 à 10:00:00
=================================================================================
exemple fictif.MP3
2 extrait(s)
*********************************************************************************
Caractéristiques :
*********************************************************************************
Observations :

*********************************************************************************

1 - 00:00 > 01:30 [ Pas de thématique]
Quelle est la question de l'extrait ?
Speaker 1 :
Le chat dort sur le tapis.
Il fait beau.
Speaker 2 :
Oui euh je crois.
2 - 01:30 > 02:10 [ Thème B]
Speaker 1 : Une phrase sur la même ligne.
"""

OTHER_TOOL_LIKE = """Titre du document fictif
Speaker 0:
Bonjour à tous.
Speaker 1:
Bonjour.
"""


class SpeechIsOnlyWhatFollowsASpeakerLabelTest(SimpleTestCase):

    def test_a_sonal_export_keeps_the_speech_and_leaves_its_header_out(self):
        doc = parse_speaker_turns(SONAL_LIKE)
        self.assertEqual(
            [('SPEAKER_01', 'Le chat dort sur le tapis. Il fait beau.'),
             ('SPEAKER_02', 'Oui euh je crois.'),
             ('SPEAKER_01', 'Une phrase sur la même ligne.')],
            [(s['speaker_id'], s['text']) for s in doc.segments])
        self.assertNotIn('Caractéristiques', doc.text)
        self.assertNotIn('Observations', doc.text)
        self.assertIn("Quelle est la question de l'extrait ?", doc.outside_speech,
                      "a line under no speaker label is kept aside, never counted")

    def test_sonal_extracts_become_coarse_windows_not_segment_times(self):
        doc = parse_speaker_turns(SONAL_LIKE)
        self.assertEqual([(0.0, 90.0, 'Pas de thématique'), (90.0, 130.0, 'Thème B')],
                         [(w['start'], w['end'], w['label']) for w in doc.windows])
        self.assertEqual([0, 0, 1], [s['window'] for s in doc.segments])
        self.assertFalse(doc.is_timed, 'a window bounds an extract, it does not time a turn')

    def test_a_title_before_the_first_label_is_not_speech(self):
        doc = parse_speaker_turns(OTHER_TOOL_LIKE)
        self.assertEqual('Bonjour à tous. Bonjour.', doc.text)
        self.assertEqual(['Titre du document fictif'], doc.outside_speech)
        self.assertEqual(['SPEAKER_00', 'SPEAKER_01'], [s['speaker_id'] for s in doc.segments])

    def test_a_document_without_any_label_is_all_speech(self):
        doc = parse_speaker_turns('Une transcription\nsans locuteurs.\n')
        self.assertEqual('Une transcription sans locuteurs.', doc.text)
        self.assertEqual([''], [s['speaker_id'] for s in doc.segments])

    def test_a_verbatim_annotation_in_brackets_is_not_a_speaker(self):
        doc = parse_speaker_turns('Speaker 0 : Alors\n[rires]\non continue.\n')
        self.assertEqual(1, len(doc.segments))
        self.assertEqual('Alors [rires] on continue.', doc.text)

    def test_a_wama_txt_export_yields_its_turns_and_not_its_summary(self):
        wama_txt = '\n'.join([
            '=' * 60, 'TRANSCRIPTION', '=' * 60, 'Texte plein que les tours répètent.', '',
            '=' * 60, 'DIARISATION — LOCUTEURS', '=' * 60,
            '[SPEAKER_00]  00:00:01.000 - 00:00:04.500', '  Premier tour.', '',
            '[Fabien]  00:00:04.500 - 00:00:09.000', '  Second tour.', '',
            '=' * 60, 'RÉSUMÉ', '=' * 60, 'Un résumé qui ne fut jamais prononcé.',
        ])
        doc = parse_speaker_turns(wama_txt)
        self.assertEqual('Premier tour. Second tour.', doc.text)
        self.assertEqual([(1.0, 4.5), (4.5, 9.0)],
                         [(s['start_time'], s['end_time']) for s in doc.segments])
        self.assertEqual(['SPEAKER_00', 'Fabien'], [s['speaker_id'] for s in doc.segments])
        self.assertIn('Un résumé qui ne fut jamais prononcé.', doc.outside_speech)


class TimedSubtitlesTest(SimpleTestCase):

    def test_a_wama_srt_export_keeps_its_times_and_speakers(self):
        srt = ('1\n00:00:01,000 --> 00:00:03,500\n[SPEAKER_00] Bonjour\nà tous.\n\n'
               '2\n00:00:03,500 --> 00:00:05,000\nSans locuteur.\n')
        doc = parse_cues(srt, 'srt')
        self.assertEqual([('SPEAKER_00', 1.0, 3.5, 'Bonjour à tous.'),
                          ('', 3.5, 5.0, 'Sans locuteur.')],
                         [(s['speaker_id'], s['start_time'], s['end_time'], s['text'])
                          for s in doc.segments])
        self.assertTrue(doc.is_timed)

    def test_a_vtt_file_reads_its_voice_tags_and_skips_its_header(self):
        vtt = ('WEBVTT\n\nNOTE une note\n\n'
               'c1\n00:01.000 --> 00:02.500 align:start\n<v Alice>Salut <b>toi</b></v>\n')
        doc = parse_cues(vtt, 'vtt')
        self.assertEqual([('Alice', 1.0, 2.5, 'Salut toi')],
                         [(s['speaker_id'], s['start_time'], s['end_time'], s['text'])
                          for s in doc.segments])

    def test_timecodes_in_every_written_form(self):
        self.assertEqual(3723.5, parse_timecode('01:02:03,500'))
        self.assertEqual(123.5, parse_timecode('02:03.5'))
        self.assertEqual(656.0, parse_timecode('10:56'))
        self.assertIsNone(parse_timecode('abc'))
        self.assertIsNone(parse_timecode('12'))


class ReadFromFileTest(SimpleTestCase):

    def _write(self, name, data: bytes):
        folder = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__('shutil').rmtree(folder, ignore_errors=True))
        path = os.path.join(folder, name)
        with open(path, 'wb') as handle:
            handle.write(data)
        return path

    def test_a_docx_goes_through_the_common_extractor(self):
        from docx import Document
        document = Document()
        for line in OTHER_TOOL_LIKE.strip().split('\n'):
            document.add_paragraph(line)
        path = self._write('fictif.docx', b'')
        document.save(path)
        self.assertEqual('Bonjour à tous. Bonjour.', read_transcript_document(path).text)

    def test_an_srt_in_windows_1252_is_still_read(self):
        path = self._write('fictif.srt', '1\n00:00:00,000 --> 00:00:01,000\nÉté.\n'.encode('cp1252'))
        self.assertEqual('Été.', read_transcript_document(path).text)

    def test_an_unsupported_extension_is_refused_by_name(self):
        path = self._write('fictif.xyz', b'x')
        with self.assertRaisesMessage(ValueError, '.xyz'):
            read_transcript_document(path)
