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
        return Transcript.objects.create(
            user=self.user, audio='users/0/transcriber/input/fictif.wav', status='SUCCESS',
            used_backend='whisper', model_key='transcriber:whisper', text=text,
            segments_json=[{'text': text, 'start_time': 0.0, 'end_time': 4.0}], **kw)

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

    def test_the_transcriber_declares_the_capability_that_opens_the_port(self):
        from wama.common.app_registry import studio_node_ports
        ports = {p['id']: p for p in studio_node_ports('transcriber')['inputs']}
        self.assertIn('reference_result', ports)
        self.assertEqual(['document'], ports['reference_result']['types'])
