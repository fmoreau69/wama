"""Restes d'aperçu retirés le 2026-10-20 (REMOVAL_LEDGER R31, R158-R161) — et ce qui les remplace.

Chaque reste avait un remplaçant commun avant d'être retiré ; ces gardes tiennent les deux bouts :
le reste ne revient pas, et ce qu'il montrait est toujours servi par la preview commune.
"""
from pathlib import Path
from types import SimpleNamespace

from django.conf import settings
from django.test import SimpleTestCase, override_settings
from django.urls import NoReverseMatch, reverse

ROOT = Path(settings.BASE_DIR)
LOCMEM = {'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
                      'LOCATION': 'preview-dead-code'}}


def _read(relative):
    return (ROOT / relative).read_text(encoding='utf-8')


@override_settings(CACHES=LOCMEM)
class TranscriberPartialTextTest(SimpleTestCase):
    """R158 : le texte d'une card EN COURS n'est plus recopié dans le panneau de Speak."""

    def test_the_text_being_built_is_served_by_the_pending_face(self):
        from wama.common.utils.preview_utils import (
            _during_preview_data, clear_partial, publish_partial_text)
        publish_partial_text('transcriber', 987654, 'Bonjour à tous, ceci est un essai')
        try:
            data = _during_preview_data('transcriber', SimpleNamespace(pk=987654), None)
        finally:
            clear_partial('transcriber', 987654)
        self.assertIsNotNone(data, 'the transcriber must declare the Pending face')
        self.assertEqual('text/plain', data['mime_type'])
        self.assertTrue(data['content'].endswith('ceci est un essai'))

    def test_the_worker_publishes_through_the_brick(self):
        self.assertIn("publish_partial_text('transcriber', transcript_id, text)",
                      _read('wama/transcriber/workers.py'))

    def test_the_speak_panel_keeps_the_microphone_and_drops_the_running_card(self):
        js = _read('wama/transcriber/static/transcriber/js/index.js')
        self.assertNotIn('updateLiveTranscriptionFromQueue', js)
        self.assertNotIn('data.partial_text', js)
        # Ce que le micro affiche, lui, reste : le texte reconnu, surligné au dernier mot.
        self.assertIn('function displayTextWithHighlight(text)', js)
        self.assertIn("onText: (phrase) => { text = text ? text + '\\n' + phrase : phrase; showText(); }", js)
        self.assertEqual(js, _read('staticfiles/transcriber/js/index.js'), 'staticfiles out of sync')


class RemovedPreviewSurfacesTest(SimpleTestCase):
    """R31, R159-R161 : des surfaces d'aperçu sans lecteur, à côté de la preview commune."""

    def test_the_app_preview_routes_are_gone(self):
        for name, pk in (('anonymizer:preview_media', 1), ('describer:preview', 1),
                         ('synthesizer:preview', 1)):
            with self.subTest(route=name), self.assertRaises(NoReverseMatch):
                reverse(name, args=[pk])
        # Le remplaçant : la route commune, pour chacune des trois apps.
        for app in ('anonymizer', 'describer', 'synthesizer'):
            self.assertTrue(reverse('common:unified_preview', args=[app, 1]))

    def test_the_first_generation_panel_api_is_gone(self):
        self.assertNotIn('WAMA_RIGHT_PANEL', _read('wama/templates/base.html'))
        self.assertFalse((ROOT / 'wama/filemanager/templates/filemanager/right_panel.html').exists())
        # L'hôte d'aperçu du volet reste : c'est lui que l'inspecteur remplit.
        self.assertIn('id="preview-container"', _read('wama/templates/base.html'))

    def test_the_page_level_leftovers_are_gone(self):
        self.assertNotIn('id="previewModal"', _read('wama/synthesizer/templates/synthesizer/index.html'))
        self.assertNotIn('_mpInjectImage', _read('wama/imager/templates/imager/index.html'))
        self.assertNotIn("describer:preview", _read('wama/describer/templates/describer/index.html'))
