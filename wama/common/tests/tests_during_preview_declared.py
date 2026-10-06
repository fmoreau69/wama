"""The « during » capability is DECLARED where the output is really OBSERVED while it is built.

`during_preview` (app catalogue) opens the inspector's « pendant » face; the app's worker
publishes the partial (text, current frame, audio by segment, file being written) through the
common brick. Two ways to drift, both lived:
  - an app that publishes but does not declare shows NOTHING, silently — the avatarizer on
    2026-10-06, until its declaration was added;
  - an app that declares but never publishes advertises a face that stays empty.
A second flag, `streaming`, said the same thing with no reader but an `or`: removed the same day
(Fabien: « soit il sert, soit il ne sert pas »). The emission is detected by the conformity
criterion's own reading (`_during_preview`), not by a second detector.
"""
from django.test import SimpleTestCase

from wama.common.app_registry import APP_CATALOG, app_capabilities, app_supports_during_preview
from wama.common.services import conformity_checker as cc


def _real_apps():
    return [app for app, spec in APP_CATALOG.items()
            if not (spec or {}).get('sandbox') and (spec or {}).get('conventions') is not None]


class DuringPreviewDeclaredWhereEmittedTest(SimpleTestCase):

    def test_declared_exactly_where_the_app_emits(self):
        mismatches = []
        for app in _real_apps():
            emitted = cc._during_preview(cc._AppFiles(app))[0] is True
            declared = app_supports_during_preview(app)
            if emitted != declared:
                mismatches.append(f"{app}: emits={emitted} declared={declared}")
        self.assertEqual([], mismatches,
                         'declare `during_preview` where the worker publishes, and only there')

    def test_the_fleet_is_measured(self):
        self.assertGreaterEqual(len(_real_apps()), 10)

    def test_the_removed_duplicate_flag_does_not_come_back(self):
        for app in _real_apps():
            with self.subTest(app=app):
                self.assertNotIn('streaming', app_capabilities(app))
