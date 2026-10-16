"""Le résultat INSTANTANÉ de la saisie — capacité `instant_preview` (2026-10-16, CARD_DESIGN
§11.11 D bis ; le Translator « à la DeepL », décision de Fabien).

UNE source : la route `instant` déclarée au manifeste. La vue générée joue la glu de l'app
(`tasks.instant_result`) sur un élément NON enregistré — rien en file, rien en base ; la card ne
montre sa zone que pour une app qui déclare la capacité.
"""
import ast
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.test import SimpleTestCase


def _composer_with_instant():
    """Le composer (app réelle à consigne) déclarant le résultat instantané, comme le fera le
    Translator : la capacité ET la route."""
    from wama.common.manifests.ingest import extract
    manifest = extract('app', 'composer')
    body = manifest['body']
    body.setdefault('capabilities', {})['instant_preview'] = True
    endpoints = body['processing'].setdefault('endpoints', [])
    if 'instant' not in endpoints:
        endpoints.append('instant')
    return manifest


def _function(src, name):
    return next((n for n in ast.parse(src).body
                 if isinstance(n, ast.FunctionDef) and n.name == name), None)


class InstantResultDeclarationTest(SimpleTestCase):

    def test_the_capability_without_its_route_is_refused(self):
        from wama.common.manifests.builtin.app import validate_app_body
        errors = validate_app_body({'capabilities': {'instant_preview': True},
                                    'processing': {'endpoints': ['index']}})
        self.assertTrue(any('instant' in e for e in errors), errors)
        self.assertFalse(any('instant' in e for e in validate_app_body(
            {'capabilities': {'instant_preview': True},
             'processing': {'endpoints': ['index', 'instant']}})))

    def test_the_capability_travels_to_the_catalogue_like_the_live_input(self):
        from wama.common.manifests.builtin.app import (DECLARED_ONLY_CAPABILITY_FIELDS,
                                                       _capabilities_target)
        self.assertIn('instant_preview', DECLARED_ONLY_CAPABILITY_FIELDS)
        self.assertIs(True, _capabilities_target(
            {'body': {'capabilities': {'instant_preview': True}}})['instant_preview'])

    def test_the_route_is_conventional(self):
        from wama.common.manifests.codegen.urls_gen import ROUTE_TABLE
        self.assertEqual(('instant/', 'views.instant'), ROUTE_TABLE['instant'])


class InstantResultGenerationTest(SimpleTestCase):

    def test_the_generated_view_plays_the_glue_on_an_unsaved_item(self):
        from wama.common.manifests.codegen.views_gen import render_views
        src, reason = render_views(_composer_with_instant())
        self.assertIsNotNone(src, reason)
        view = _function(src, 'instant')
        self.assertIsNotNone(view, 'la vue instant déclarée n’a pas été rendue')
        code = ast.unparse(view)
        self.assertIn('instant_result', code)
        self.assertIn("request.POST.get('instant_text')", code)
        # La saisie se pose APRÈS la cascade des réglages : une consigne déclarée en RÉGLAGE (le
        # Translator, comme le Writer) serait sinon écrasée par sa valeur enregistrée.
        self.assertIn('kwargs.update(_cols)', code)
        self.assertGreater(code.index("] = text"), code.index('kwargs.update(_cols)'))
        # Une erreur du modèle se DIT dans la zone (502), jamais un 500 muet.
        self.assertIn('status=502', code)
        # Rien en file, rien en base : ni création, ni enregistrement, ni tâche.
        for forbidden in ('.objects.create(', '.save(', '.delay(', 'apply_async'):
            self.assertNotIn(forbidden, code)

    def test_the_glue_hole_is_emitted_only_when_the_route_is_declared(self):
        from wama.common.manifests.codegen.tasks_gen import render_tasks
        from wama.common.manifests.ingest import extract
        src, reason = render_tasks(_composer_with_instant())
        self.assertIsNotNone(src, reason)
        self.assertIsNotNone(_function(src, 'instant_result'))
        plain, _ = render_tasks(extract('app', 'composer'))
        self.assertIsNone(_function(plain or '', 'instant_result'))


class InstantResultCardTest(SimpleTestCase):

    def test_the_card_zone_appears_only_for_a_declaring_app(self):
        from wama.common.templatetags.wama_actions import instant_result_url
        self.assertEqual('', instant_result_url('reader'))       # ne déclare pas la capacité
        with mock.patch('wama.common.app_registry.app_instant_preview', return_value=True), \
                mock.patch('django.urls.reverse', return_value='/translator_02/instant/'):
            self.assertEqual('/translator_02/instant/', instant_result_url('translator_02'))

    def test_the_brick_parses_in_v8(self):
        """Un .js ne casse jamais à la compilation : V8 fait foi (AGENTS.md §JS) — parse sans
        exécuter, la brique touchant au DOM."""
        from py_mini_racer import MiniRacer
        src = (Path(settings.BASE_DIR) / 'wama/common/static/common/js/wama-instant.js').read_text(
            encoding='utf-8')
        MiniRacer().eval('(function(){' + src + '\n})')
        served = Path(settings.BASE_DIR) / 'staticfiles/common/js/wama-instant.js'
        self.assertEqual(src, served.read_text(encoding='utf-8'), 'copie servie désynchronisée')
