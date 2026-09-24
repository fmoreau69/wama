"""Le transcriber ADOPTE l'évaluation commune (`common/services/result_evaluation`).

⚠ Contenus INVENTÉS (dépôt public) ; `MEDIA_ROOT` temporaire ; catalogue de modèles en
fixtures LOCALES — le verdict ne suit pas l'état du parc.
"""
import shutil
import tempfile

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings

from wama.transcriber.backends.manager import TranscriberBackendManager
from wama.transcriber.models import Transcript

SRT_REFERENCE = ('1\n00:00:00,000 --> 00:00:02,000\n[SPEAKER_00] Le chat dort sur le tapis.\n\n'
                 '2\n00:00:02,000 --> 00:00:04,000\n[SPEAKER_01] Oui euh je crois.\n')


class CatalogueKeyOfTheModelActuallyUsedTest(TestCase):

    def setUp(self):
        from wama.model_manager.models import AIModel
        for key in ('whisper', 'qwen3-asr-0.6b', 'qwen3-asr-1.7b', 'vibevoice-asr',
                    'pyannote-diarization'):
            AIModel.objects.create(model_key=f'transcriber:{key}', name=key, source='transcriber')

    def test_an_engine_with_one_catalogue_entry_is_that_entry(self):
        self.assertEqual('transcriber:whisper',
                         TranscriberBackendManager.catalogue_key_for('whisper', 'large-v3'))
        self.assertEqual('transcriber:vibevoice-asr',
                         TranscriberBackendManager.catalogue_key_for('vibevoice'))

    def test_the_LOADED_model_decides_between_variants_of_one_engine(self):
        self.assertEqual('transcriber:qwen3-asr-1.7b', TranscriberBackendManager.catalogue_key_for(
            'qwen_asr', 'Qwen/Qwen3-ASR-1.7B'))
        self.assertEqual('transcriber:qwen3-asr-0.6b', TranscriberBackendManager.catalogue_key_for(
            'qwen_asr', 'Qwen/Qwen3-ASR-0.6B'))

    def test_an_unknown_variant_falls_back_to_the_engine_never_to_a_guess(self):
        self.assertEqual('transcriber:qwen_asr',
                         TranscriberBackendManager.catalogue_key_for('qwen_asr', ''))


class TranscriberEvaluationTest(TestCase):

    def setUp(self):
        self.media = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.media, True)
        override = override_settings(MEDIA_ROOT=self.media)
        override.enable()
        self.addCleanup(override.disable)
        self.user = User.objects.create_user('transcriber_evaluation', password='x')
        self.client.force_login(self.user)

    def _transcript(self, text='le chat dort sur le tapis oui je crois', **kw):
        fields = {'audio': 'users/0/transcriber/input/fictif.wav', 'status': 'SUCCESS',
                  'used_backend': 'whisper', 'model_key': 'transcriber:whisper', 'text': text,
                  'segments_json': [{'text': text, 'start_time': 0.0, 'end_time': 4.0}]}
        fields.update(kw)
        return Transcript.objects.create(user=self.user, **fields)

    def _attach(self, item, content=SRT_REFERENCE, name='reference.srt'):
        return self.client.post(f'/common/api/result-reference/transcriber/element/{item.pk}/',
                                {'file': SimpleUploadedFile(name, content.encode('utf-8'))}).json()

    def test_the_asr_output_is_measured_against_an_srt_reference(self):
        answer = self._attach(self._transcript())
        wer = answer['item']['metrics'][0]
        self.assertTrue(answer['ok'])
        self.assertEqual(('wer', 1, 10), (wer['metric'], wer['deletions'], wer['reference_length']),
                         '« euh » is spoken in the reference and missing from the output')
        self.assertEqual('transcriber:whisper', answer['item']['model_key'])
        self.assertEqual({'format': 'srt', 'turns': 2, 'timed': True, 'windows': 0,
                          'outside_speech': 0}, answer['item']['reading'])

    def test_a_human_correction_never_changes_what_is_measured(self):
        """The correction overwrites `text` — the MEASURE must keep reading the ASR output."""
        from wama.common.services.result_evaluation import evaluate, item_evaluation
        item = self._transcript()
        self._attach(item)
        item.refresh_from_db()                     # the reference was posted through the API
        before = item_evaluation('transcriber', item)['metrics'][0]['value']
        item.text = 'le chat dort sur le tapis oui euh je crois'
        item.corrected_segments_json = [{'text': item.text}]
        item.save()
        evaluate('transcriber', item)
        self.assertEqual(before, item_evaluation('transcriber', item)['metrics'][0]['value'])

    def test_a_sonal_docx_is_a_reference_too(self):
        from docx import Document
        import io
        document = Document()
        for line in ('Entretien exporté depuis Sonal (v.2.1)', '1 - 00:00 > 00:04 [ Thème]',
                     'Titre ajouté par l’utilisateur', 'Speaker 1 :',
                     'Le chat dort sur le tapis oui je crois'):
            document.add_paragraph(line)
        buffer = io.BytesIO()
        document.save(buffer)
        item = self._transcript()
        answer = self.client.post(
            f'/common/api/result-reference/transcriber/element/{item.pk}/',
            {'file': SimpleUploadedFile('sonal.docx', buffer.getvalue())}).json()
        self.assertEqual(0.0, answer['item']['metrics'][0]['value'],
                         'the extract title and the export header are not speech')
        self.assertEqual(2, answer['item']['reading']['outside_speech'])

    def test_a_relaunch_forgets_the_measure_and_keeps_the_reference(self):
        from wama.common.services.result_evaluation import item_evaluation
        from wama.transcriber.views import _reset_for_relaunch
        item = self._transcript()
        self._attach(item)
        item.refresh_from_db()
        _reset_for_relaunch(item)
        item.save()
        view = item_evaluation('transcriber', item)
        self.assertTrue(view['pending'], 'the reference waits for the new result')
        self.assertEqual('', item.model_key)

    def _import(self, item, content, name):
        return self.client.post(f'/common/api/result-import/transcriber/{item.pk}/',
                                {'file': SimpleUploadedFile(name, content)}).json()

    def test_an_existing_timed_result_becomes_the_card_result_and_is_compared(self):
        """The other tool's transcription is measured like a model — the comparison the lab needs."""
        from wama.common.services.result_evaluation import batch_evaluation
        from wama.transcriber.models import TranscriptSegment
        whisper = self._transcript()
        external = self._transcript(text='', status='PENDING')
        answer = self._import(external, SRT_REFERENCE.encode(), 'autre_outil.srt')
        self.assertTrue(answer['ok'], answer)
        external.refresh_from_db()
        self.assertEqual(('SUCCESS', 'external:autre_outil', 'externe'),
                         (external.status, external.model_key, external.used_backend))
        self.assertEqual(2, TranscriptSegment.objects.filter(transcript=external).count(),
                         'a timed document is written like an ASR output (rows, hence SRT)')
        reference = SimpleUploadedFile('ref.srt', SRT_REFERENCE.encode())
        from wama.common.services.result_evaluation import attach_reference
        attach_reference('transcriber', [whisper, external], reference)
        summary = batch_evaluation('transcriber', [whisper, external])
        self.assertEqual(['external:autre_outil', 'transcriber:whisper'],
                         [m['model_key'] for m in summary['models']],
                         'identical to the reference: the external result ranks first')
        self.assertTrue(summary['comparable'])

    def test_an_untimed_result_invents_no_time(self):
        from wama.transcriber.models import TranscriptSegment
        item = self._transcript(text='', status='PENDING')
        answer = self._import(item, 'Titre\nSpeaker 0:\nBonjour à tous.\n'.encode(), 'outil.txt')
        self.assertTrue(answer['ok'], answer)
        item.refresh_from_db()
        self.assertEqual([{'speaker_id': 'SPEAKER_00', 'start_time': None, 'end_time': None,
                           'text': 'Bonjour à tous.'}], item.segments_json)
        self.assertFalse(TranscriptSegment.objects.filter(transcript=item).exists())

    def test_a_document_without_speech_is_refused_and_left_nowhere(self):
        item = self._transcript()
        answer = self.client.post(f'/common/api/result-import/transcriber/{item.pk}/',
                                  {'file': SimpleUploadedFile('vide.srt', b'WEBVTT\n')})
        self.assertEqual(400, answer.status_code)
        self.assertIn('aucune parole', answer.json()['reason'])
        item.refresh_from_db()
        self.assertFalse(item.work_result.name)

    def test_relaunching_a_card_with_an_existing_result_REIMPORTS_it(self):
        from wama.transcriber.views import _task_for
        from wama.transcriber.workers import (import_existing_result_task,
                                              transcribe_without_preprocessing)
        item = self._transcript()
        self.assertIs(transcribe_without_preprocessing, _task_for(item))
        self._import(item, SRT_REFERENCE.encode(), 'autre.srt')
        item.refresh_from_db()
        self.assertIs(import_existing_result_task, _task_for(item),
                      '▶ must not run the ASR in place of the existing result')
        # The task opens with `close_old_connections()` (Celery hygiene) — it would close the
        # TEST connection; the gesture under test is the re-import, not the hygiene.
        from unittest.mock import patch
        with patch('wama.transcriber.workers.close_old_connections'):
            self.assertEqual({'ok': True}, import_existing_result_task(item.pk))

    @override_settings(CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
                                           'LOCATION': 'transcriber-agreement-tests'}})
    def test_engines_on_the_same_audio_are_compared_without_reference(self):
        """M1 on timed segments, both ways; an untimed existing result is « not compared »."""
        from wama.common.services.result_evaluation import batch_agreement
        audio = 'users/0/transcriber/input/meme_audio.wav'
        whisper = self._transcript('le chat dort sur le tapis', audio=audio,
                                   segments_json=[{'text': 'le chat dort sur le tapis',
                                                   'start_time': 0.0, 'end_time': 3.0}])
        other = self._transcript('le chien dort sur le tapis', audio=audio,
                                 model_key='transcriber:vibevoice-asr',
                                 segments_json=[{'text': 'le chien dort sur le tapis',
                                                 'start_time': 0.0, 'end_time': 3.0}])
        untimed = self._transcript('le chat dort', audio=audio, model_key='external:outil',
                                   segments_json=[{'text': 'le chat dort', 'start_time': None,
                                                   'end_time': None}])
        group = batch_agreement('transcriber', [whisper, other, untimed])['groups'][0]
        by_key = {e['model_key']: e for e in group['engines']}
        self.assertGreater(by_key['transcriber:whisper']['isolation'], 0)
        self.assertEqual(by_key['transcriber:whisper']['isolation'],
                         by_key['transcriber:vibevoice-asr']['isolation'], 'symmetric')
        self.assertIsNone(by_key['external:outil']['isolation'])
        self.assertEqual((3, 1), (group['pairs'], group['comparable_pairs']))
        self.assertIsNone(batch_agreement('transcriber', [whisper, self._transcript(
            audio='users/0/transcriber/input/autre.wav')]), 'different audios: nothing to compare')

    # ── Étage A de l'alignement : un texte sans temps s'ancre sur les mots de l'ASR ──────────
    AUDIO = 'users/0/transcriber/input/entretien_fictif.wav'
    WORDS = [{'word': ' ' + w, 'start': s, 'end': e, 'probability': 0.9}
             for w, s, e in (('le', 0.0, 0.2), ('chien', 0.2, 0.6), ('dort', 0.6, 1.0),
                             ('oui', 2.0, 2.3), ('je', 2.3, 2.5), ('crois', 2.5, 3.0))]
    SONAL = ('Entretien exporté depuis Sonal (v.2.1)\n1 - 00:00 > 00:05 [ Thème]\n'
             'Titre ajouté par l’utilisateur\nSpeaker 1 :\nLe chat dort.\nSpeaker 2 :\n'
             'Oui euh je crois.\n')

    def _whisper_card(self):
        return self._transcript('le chien dort oui je crois', audio=self.AUDIO,
                                segments_json=[{'text': 'le chien dort oui je crois',
                                                'start_time': 0.0, 'end_time': 3.0,
                                                'words': self.WORDS}])

    def test_an_untimed_existing_result_is_anchored_on_a_sibling_asr(self):
        from wama.transcriber.models import TranscriptSegment
        self._whisper_card()
        imported = self._transcript('', status='PENDING', audio=self.AUDIO, segments_json=None)
        answer = self._import(imported, self.SONAL.encode(), 'export_sonal.txt')
        self.assertTrue(answer['ok'], answer)
        imported.refresh_from_db()
        first, second = imported.segments_json
        self.assertEqual((0.0, 1.0), (first['start_time'], first['end_time']))
        self.assertEqual('estimated', first['words'][1]['timing'], '« chat » where « chien » was heard')
        self.assertEqual((2.0, 3.0), (second['start_time'], second['end_time']))
        self.assertEqual('interpolated', second['words'][1]['timing'], '« euh » was not heard')
        self.assertEqual(2, TranscriptSegment.objects.filter(transcript=imported).count(),
                         'anchored = timed: written like an ASR output')

    def test_a_card_anchors_on_its_OWN_asr_before_the_import_replaces_it(self):
        card = self._whisper_card()
        self._import(card, self.SONAL.encode(), 'export_sonal.txt')
        card.refresh_from_db()
        self.assertEqual(0.0, card.segments_json[0]['start_time'])
        self.assertTrue(card.model_key.startswith('external:'))

    def test_relaunching_keeps_the_anchors_and_reimports_with_times(self):
        from unittest.mock import patch
        from wama.transcriber.views import _reset_for_relaunch
        from wama.transcriber.workers import import_existing_result_task
        card = self._whisper_card()
        self._import(card, self.SONAL.encode(), 'export_sonal.txt')
        card.refresh_from_db()
        _reset_for_relaunch(card)
        card.save()
        with patch('wama.transcriber.workers.close_old_connections'):
            self.assertEqual({'ok': True}, import_existing_result_task(card.pk))
        card.refresh_from_db()
        self.assertEqual((2.0, 3.0), (card.segments_json[1]['start_time'],
                                      card.segments_json[1]['end_time']))

    def test_the_transcriber_declares_the_capability_that_opens_the_port(self):
        from wama.common.app_registry import studio_node_ports
        ports = {p['id']: p for p in studio_node_ports('transcriber')['inputs']}
        self.assertIn('reference_result', ports)
        self.assertEqual(['document'], ports['reference_result']['types'])
