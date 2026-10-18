"""« Envoyer vers » fait naître l'élément comme le dépôt de la card (2026-10-13).

POURQUOI CE FICHIER. Les importeurs du gestionnaire de fichiers créaient leurs éléments à la main,
hors du chemin de naissance de leur app : un fichier envoyé depuis l'arbre prenait les défauts du
modèle, jamais les préférences de son auteur (relevé du 13/10 — seul l'anonymizer passait par la
brique commune, depuis le 27/09). Le synthesizer créait même avec une langue et une voix en dur,
le converter sans les défauts de son schéma (`ROADMAP §23.2quater`), le describer sans les
propriétés de son fichier.

Le geste testé est le VRAI, des deux côtés : un DÉPÔT par la card de l'app (qui mémorise ses
réglages comme préférences de l'auteur), puis « Envoyer vers » par la route du gestionnaire
(`filemanager:api_import`). L'élément envoyé doit porter les réglages de l'élément déposé.
Contre-épreuve de chaque app : les préférences d'un auteur n'atteignent jamais l'import d'un autre.
"""
import io
import json
import shutil
import tempfile
from pathlib import Path

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

User = get_user_model()


def _png() -> bytes:
    from PIL import Image
    buffer = io.BytesIO()
    Image.new('RGB', (8, 8), (200, 30, 30)).save(buffer, format='PNG')
    return buffer.getvalue()


class SendToTestBase(TestCase):
    """Un MEDIA_ROOT jetable, un auteur et un autre utilisateur — superutilisateurs : l'accès aux
    apps (profil) n'est pas l'objet de ces tests."""

    def setUp(self):
        media = tempfile.mkdtemp(prefix='wama_send_to_')
        self.addCleanup(shutil.rmtree, media, ignore_errors=True)
        setting = override_settings(MEDIA_ROOT=media)
        setting.enable()
        self.addCleanup(setting.disable)
        self.media = Path(media)
        self.author = User.objects.create_user('send_to_author', password='x', is_staff=True,
                                               is_superuser=True)
        self.other = User.objects.create_user('send_to_other', password='x', is_staff=True,
                                              is_superuser=True)

    def _temp_file(self, user, name, content: bytes) -> str:
        rel = f'users/{user.id}/temp/{name}'
        path = self.media / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return rel

    def deposit(self, app, name, content, data, *, field='file', route='upload') -> dict:
        """Le dépôt par la card de l'app : le fichier est DÉSIGNÉ (arbre, médiathèque), avec
        l'état du volet."""
        self.client.force_login(self.author)
        payload = dict(data)
        if name:
            payload[f'{field}__designated'] = self._temp_file(self.author, name, content)
        response = self.client.post(reverse(f'{app}:{route}'), payload)
        self.assertEqual(200, response.status_code, response.content)
        return response.json()

    def send_to(self, app, user, name, content) -> dict:
        """« Envoyer vers <app> » depuis l'arbre de fichiers de `user`."""
        self.client.force_login(user)
        response = self.client.post(
            reverse('filemanager:api_import'),
            json.dumps({'path': self._temp_file(user, name, content), 'app': app}),
            content_type='application/json')
        self.assertEqual(200, response.status_code, response.content)
        body = response.json()
        self.assertTrue(body.get('imported'), body)
        return body


class SentTranscriptTest(SendToTestBase):

    #: Le volet tel que l'auteur l'a réglé au dépôt — ses clés sont les champs comparés.
    POSTED = {'enable_diarization': 'false', 'hotwords': 'Eiffel, WAMA', 'vad_mode': 'off'}  # wama:redondance-ok — valeurs CHOISIES par le test (≠ défauts), pas une recopie du schéma

    def _values(self, pk):
        from wama.transcriber.models import Transcript
        t = Transcript.objects.get(pk=pk)
        return tuple(getattr(t, f) for f in self.POSTED)

    def test_a_file_sent_to_the_transcriber_carries_the_author_preferences(self):
        deposited = self.deposit('transcriber', 'deposited.wav', b'RIFF0000WAVE', self.POSTED)
        sent = self.send_to('transcriber', self.author, 'sent.wav', b'RIFF0000WAVE')
        self.assertEqual((False, 'Eiffel, WAMA', 'off'), self._values(deposited['id']))
        self.assertEqual(self._values(deposited['id']), self._values(sent['id']))

    def test_the_preferences_of_one_author_never_reach_another(self):
        self.deposit('transcriber', 'deposited.wav', b'RIFF0000WAVE', self.POSTED)
        sent = self.send_to('transcriber', self.other, 'sent.wav', b'RIFF0000WAVE')
        diarization, hotwords, _vad = self._values(sent['id'])
        self.assertTrue(diarization, 'la diarisation reste active par défaut')
        self.assertFalse(hotwords)


class SentDescriptionTest(SendToTestBase):

    POSTED = {'output_style': 'scientific', 'output_language': 'en', 'max_length': '200'}  # wama:redondance-ok — valeurs CHOISIES par le test (≠ défauts), pas une recopie du schéma

    def _get(self, pk):
        from wama.describer.models import Description
        return Description.objects.get(pk=pk)

    def _values(self, description):
        return tuple(getattr(description, f) for f in self.POSTED)

    def test_a_file_sent_to_the_describer_carries_the_author_options_and_its_properties(self):
        deposited = self._get(self.deposit('describer', 'deposited.txt', b'Un texte.',
                                           self.POSTED)['id'])
        sent = self._get(self.send_to('describer', self.author, 'sent.txt', b'Un texte.')['id'])
        self.assertEqual(('scientific', 'en', 200), self._values(deposited))
        self.assertEqual(self._values(deposited), self._values(sent))
        self.assertTrue(sent.properties, "l'élément naît avec les propriétés de son fichier")

    def test_the_options_of_one_author_never_reach_another(self):
        self.deposit('describer', 'deposited.txt', b'Un texte.', self.POSTED)
        sent = self._get(self.send_to('describer', self.other, 'sent.txt', b'Un texte.')['id'])
        self.assertEqual(('detailed', 'fr', 500), self._values(sent))


class SentReadingTest(SendToTestBase):

    POSTED = {'mode': 'handwritten', 'output_format': 'markdown', 'language': 'de'}  # wama:redondance-ok — valeurs CHOISIES par le test (≠ défauts), pas une recopie du schéma

    def _values(self, pk):
        from wama.reader.models import ReadingItem
        item = ReadingItem.objects.get(pk=pk)
        return tuple(getattr(item, f) for f in self.POSTED)

    def test_a_file_sent_to_the_reader_carries_the_author_last_settings(self):
        deposited = self.deposit('reader', 'deposited.png', _png(), self.POSTED, field='files')
        sent = self.send_to('reader', self.author, 'sent.png', _png())
        deposited_id = deposited['created'][0]['id']
        self.assertEqual(('handwritten', 'markdown', 'de'), self._values(deposited_id))
        self.assertEqual(self._values(deposited_id), self._values(sent['id']))

    def test_the_settings_of_one_author_never_reach_another(self):
        self.deposit('reader', 'deposited.png', _png(), self.POSTED, field='files')
        sent = self.send_to('reader', self.other, 'sent.png', _png())
        self.assertEqual(('auto', 'txt', ''), self._values(sent['id']))

    def test_a_reader_twin_receives_the_file_in_its_own_tables_only(self):
        """Avant le 13/10, l'élément d'une jumelle était enveloppé dans un lot du reader SOURCE :
        Django refusait le lien et l'import échouait, en laissant un lot vide chez la source."""
        from django.apps import apps as django_apps
        from wama.common.app_registry import APP_CATALOG
        from wama.filemanager.views import importer_for
        if 'reader_01' not in APP_CATALOG or not django_apps.is_installed('wama.reader_01'):
            self.skipTest('jumelle reader_01 non enregistrée sur cette machine')
        source = self.media / 'twin_source.png'
        source.write_bytes(_png())
        result = importer_for('reader_01')(source, self.author)
        self.assertEqual('reader_01', result['app'])
        twin_item = django_apps.get_model('reader_01', 'ReadingItem')
        self.assertTrue(twin_item.objects.filter(pk=result['id'], user=self.author).exists())
        source_batch = django_apps.get_model('reader', 'BatchReadingItem')
        self.assertFalse(source_batch.objects.filter(user=self.author).exists(),
                         "l'import d'une jumelle n'écrit jamais dans sa source")


class SentConversionTest(SendToTestBase):

    def _job(self, pk):
        from wama.converter.models import ConversionJob
        return ConversionJob.objects.get(pk=pk)

    def _columns(self, job):
        return {f: getattr(job, f) for f in job.CHAMPS_OPTIONS}

    def _format(self):
        """Un format CHOISI qui n'est ni celui de la source ni le défaut de la nature : sans quoi
        « repris du dernier dépôt » et « défaut automatique » ne se distingueraient pas."""
        from wama.converter.utils.format_router import default_output_format, get_output_formats
        return next(f for f in get_output_formats('image')
                    if f not in ('png', default_output_format('image')))

    def test_a_file_sent_to_the_converter_gets_the_last_format_and_is_born_complete(self):
        target = self._format()
        deposited = self._job(self.deposit('converter', 'deposited.png', _png(),
                                           {'output_format': target})['id'])
        sent = self._job(self.send_to('converter', self.author, 'sent.png', _png())['id'])
        self.assertEqual(target, sent.output_format)
        # Né COMPLET (§23.2quater) : les mêmes colonnes qu'au dépôt, qui n'a posté aucune option.
        self.assertEqual(self._columns(deposited), self._columns(sent))
        self.assertTrue(any(v not in (None, '') for v in self._columns(sent).values()))

    def test_without_a_last_format_the_job_gets_the_default_of_its_nature_and_is_complete(self):
        """Il naissait SANS format (une card à régler avant de lancer) : il reçoit désormais le
        format AUTOMATIQUE de sa nature — jamais celui d'un autre auteur (2026-10-18)."""
        from wama.converter.utils.format_router import default_output_format
        deposited = self._job(self.deposit('converter', 'deposited.png', _png(),
                                           {'output_format': self._format()})['id'])
        sent = self._job(self.send_to('converter', self.other, 'sent.png', _png())['id'])
        self.assertEqual(default_output_format('image'), sent.output_format)
        self.assertNotEqual(deposited.output_format, sent.output_format,
                            "le format d'un autre auteur n'est pas repris")
        self.assertEqual(self._columns(deposited), self._columns(sent))


class SentEnhancementTest(SendToTestBase):

    FIELDS = ('denoise', 'blend_factor')

    def _values(self, pk):
        from wama.enhancer.models import Enhancement
        e = Enhancement.objects.get(pk=pk)
        return tuple(getattr(e, f) for f in self.FIELDS)

    def test_an_image_sent_to_the_enhancer_carries_the_author_preferences(self):
        deposited = self.deposit('enhancer', 'deposited.png', _png(), {
            'denoise': 'true', 'blend_factor': '0.3'})
        sent = self.send_to('enhancer', self.author, 'sent.png', _png())
        self.assertEqual((True, 0.3), self._values(deposited['id']))
        self.assertEqual(self._values(deposited['id']), self._values(sent['id']))

    def test_the_preferences_of_one_author_never_reach_another(self):
        self.deposit('enhancer', 'deposited.png', _png(), {
            'denoise': 'true', 'blend_factor': '0.3'})
        sent = self.send_to('enhancer', self.other, 'sent.png', _png())
        self.assertEqual((False, 0.0), self._values(sent['id']))


class SentSynthesisTest(SendToTestBase):

    def _synthesis(self, pk):
        from wama.synthesizer.models import VoiceSynthesis
        return VoiceSynthesis.objects.get(pk=pk)

    def _write_once(self):
        """Une synthèse saisie dans la card : ses choix deviennent les préférences de l'auteur."""
        return self.deposit('synthesizer', None, b'', {'text_content': 'Bonjour à tous.',
                                                       'language': 'en'}, route='upload_text')

    def test_a_text_file_sent_to_the_synthesizer_carries_the_author_choices(self):
        written = self._synthesis(self._write_once()['id'])
        sent = self.send_to('synthesizer', self.author, 'sent.txt', b'Hello everyone.')
        synthesis = self._synthesis(sent['synthesis_id'])
        self.assertEqual('en', written.language)
        self.assertEqual((written.language, written.tts_model, written.voice_preset),
                         (synthesis.language, synthesis.tts_model, synthesis.voice_preset))
        self.assertEqual('Hello everyone.', synthesis.text_content.strip(),
                         'le texte est extrait à la naissance, comme pour la card')

    def test_the_choices_of_one_author_never_reach_another(self):
        from wama.synthesizer.models import VoiceSynthesis
        self._write_once()
        sent = self.send_to('synthesizer', self.other, 'sent.txt', b'Hello everyone.')
        self.assertEqual(VoiceSynthesis._meta.get_field('language').default,
                         self._synthesis(sent['synthesis_id']).language)

    def test_a_synthesizer_twin_creates_in_its_own_tables_only(self):
        from django.apps import apps as django_apps
        from wama.common.app_registry import APP_CATALOG
        from wama.filemanager.views import importer_for
        if 'synthesizer_01' not in APP_CATALOG or not django_apps.is_installed('wama.synthesizer_01'):
            self.skipTest('jumelle synthesizer_01 non enregistrée sur cette machine')
        source = self.media / 'twin_source.txt'
        source.write_bytes(b'Hello twin.')
        result = importer_for('synthesizer_01')(source, self.author)
        twin = django_apps.get_model('synthesizer_01', 'VoiceSynthesis')
        self.assertTrue(twin.objects.filter(pk=result['synthesis_id'], user=self.author).exists())
        self.assertFalse(django_apps.get_model('synthesizer', 'VoiceSynthesis').objects
                         .filter(user=self.author).exists(),
                         "l'import d'une jumelle n'écrit jamais dans sa source")
