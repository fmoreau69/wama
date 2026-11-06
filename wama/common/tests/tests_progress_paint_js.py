"""The common painter of a progress block rendered in JS — `WamaApp.paintProgress` /
`progressBlockHtml` (2026-11-06).

The form of `common/_card_progress.html` (badge, bar, %, ETA) for what the server does not render
as a template. It was written once, in the assistant's chat (its line of a job); the card of a
model being installed in the model manager is its second reader, so it moved to the common brick.
Played on the SERVED file in V8 (AGENTS.md §JS), with a host that answers the block's selectors.
"""
import importlib.util
import json
from pathlib import Path
from unittest import skipUnless

from django.conf import settings
from django.test import SimpleTestCase

from wama.common.tests.tests_cap_from_js import FAKE_DOM

HAS_V8 = importlib.util.find_spec('py_mini_racer') is not None
SERVED = Path(settings.BASE_DIR) / 'staticfiles' / 'common' / 'js'

HOST = r"""
function part() {
  var classes = {};
  return { className: '', textContent: '', style: {},
           classList: { toggle: function (c, on) { classes[c] = !!on; } },
           has: function (c) { return !!classes[c]; } };
}
function host() {
  var parts = { '.status-badge': part(), '.progress-text': part(), '.wama-progress-fill': part(),
                '.wama-eta': null };
  return { parts: parts, querySelector: function (s) { return parts[s]; } };
}
function paint(job) {
  var h = host(), pct = window.WamaApp.paintProgress(h, job, 'test:' + job.status);
  var fill = h.parts['.wama-progress-fill'];
  return [pct, h.parts['.status-badge'].textContent, h.parts['.progress-text'].textContent,
          fill.style.width, fill.has('active'), fill.has('is-frozen')];
}
"""


@skipUnless(HAS_V8, 'py_mini_racer absent de ce venv')
class PaintProgressTest(SimpleTestCase):

    def setUp(self):
        from py_mini_racer import MiniRacer
        self.v8 = MiniRacer()
        self.v8.eval(FAKE_DOM + "\ndocument.cookie = ''; var navigator = {}; var localStorage = "
                     "{getItem: function () { return null; }, setItem: function () {}};")
        self.v8.eval((SERVED / 'wama-app-base.js').read_text(encoding='utf-8'))
        self.v8.eval(HOST)

    def _js(self, expr):
        return json.loads(self.v8.eval(f'JSON.stringify({expr})'))

    def test_a_running_job_is_painted_like_its_card(self):
        label = self._js("window.WamaApp.statusLabel('RUNNING')")
        self.assertEqual([42, label, '42%', '42%', True, False],
                         self._js("paint({status: 'RUNNING', progress: 42})"))

    def test_a_success_is_full_and_a_failure_frozen(self):
        self.assertEqual(100, self._js("paint({status: 'SUCCESS', progress: 7, terminal: true, "
                                       "ok: true})")[0])
        self.assertEqual([12, True], [self._js("paint({status: 'FAILURE', progress: 12, "
                                               "terminal: true})")[i] for i in (0, 5)])

    def test_the_block_has_what_the_painter_reads_and_the_name_its_reader_gives(self):
        html = self._js("window.WamaApp.progressBlockHtml('wama-assistant-job-name')")
        for cls in ('status-badge', 'progress-text', 'wama-progress-fill', 'wama-eta',
                    'wama-assistant-job-name'):
            self.assertIn(cls, html)
        self.assertIn('wama-progress-name', self._js("window.WamaApp.progressBlockHtml()"))

    def test_its_two_readers_paint_through_it(self):
        """Counter-proof against a copy: the chat and the model manager card call the brick, and
        neither writes the bar again."""
        chat = (SERVED / 'wama-assistant-chat.js').read_text(encoding='utf-8')
        page = (Path(settings.BASE_DIR) / 'wama' / 'model_manager' / 'templates' / 'model_manager'
                / 'index.html').read_text(encoding='utf-8')
        for text in (chat, page):
            self.assertIn('WamaApp.paintProgress(', text)
            self.assertIn('WamaApp.progressBlockHtml(', text)
        self.assertNotIn("fill.style.width = pct + '%'", chat)
