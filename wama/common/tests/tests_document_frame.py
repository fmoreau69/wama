"""Le CADRE ISOLÉ d'un document rendu est une brique commune : `WamaMediaPreview.documentFrameHtml`
(2026-10-29, passation de la session « Aperçu » du 28/10 — `PROJECT_STATUS §PALIER 2026-10-28
« APERÇU ④ »`).

La règle « un document HTML se montre dans un `<iframe sandbox>` sans AUCUNE permission » s'écrivait
trois fois : l'aperçu en ligne (`renderInline`), la visionneuse et la brique `html_preview` des
surfaces. Elle vit dans la brique seule ; ce qui varie (cadre inerte dans une card, classe, style,
`referrerpolicy`, titre) est une option.

V8 embarqué (`py_mini_racer`) : la fonction pure extraite et exécutée seule, le module entier parsé.

⚠ Identifiants en anglais, noms de tests compris ; commentaires et docstrings en français.
"""
import json
import re
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

ROOT = Path(settings.BASE_DIR)
PREVIEW = 'common/static/common/js/media-preview.js'
HTML_BRICK = 'common/static/common/js/surfaces/brick-html-preview.js'


def _source(rel):
    return (ROOT / 'wama' / rel).read_text(encoding='utf-8')


def _extract(src, name):
    match = re.search(r'\n    function ' + name + r'\(.*?\n    }\n', src, re.S)
    return match.group(0) if match else None


class DocumentFrameTest(SimpleTestCase):

    def setUp(self):
        try:
            from py_mini_racer import MiniRacer
        except ImportError:
            self.skipTest('py_mini_racer absent de ce venv : pas de V8 pour exécuter la brique')
        src = _source(PREVIEW)
        self.ctx = MiniRacer()
        self.ctx.eval('(function(){' + src + '\n})')            # parse du module ENTIER
        parts = [_extract(src, f) for f in ('escapeHtml', 'documentFrameHtml')]
        self.assertTrue(all(parts), 'une fonction du cadre a disparu ou changé de forme')
        self.ctx.eval(''.join(parts))

    def _frame(self, url, opts=None):
        return self.ctx.eval('documentFrameHtml(%s, %s)' % (json.dumps(url), json.dumps(opts or {})))

    def test_the_frame_grants_no_permission_at_all(self):
        html = self._frame('/media/x/doc.html')
        self.assertTrue(html.startswith('<iframe src="/media/x/doc.html" sandbox=""'), html)
        self.assertNotIn('allow-', html)

    def test_an_inert_frame_leaves_the_gestures_to_the_page(self):
        html = self._frame('/m/d.html', {'style': 'height:220px;', 'inert': True})
        self.assertIn('style="height:220px;pointer-events:none;"', html)
        self.assertNotIn('pointer-events', self._frame('/m/d.html', {'style': 'height:220px;'}))

    def test_what_varies_is_an_option(self):
        html = self._frame('', {'className': 'wama-viewer-frame', 'referrerPolicy': 'no-referrer',
                                'title': 'Aperçu du document'})
        self.assertNotIn('src=', html)                      # la brique pose l'adresse ensuite
        self.assertIn('class="wama-viewer-frame"', html)
        self.assertIn('referrerpolicy="no-referrer"', html)
        self.assertIn('title="Aperçu du document"', html)

    def test_addresses_and_labels_are_escaped(self):
        html = self._frame('/m/a"b.html', {'title': '<x>'})
        self.assertIn('src="/m/a&quot;b.html"', html)
        self.assertIn('title="&lt;x&gt;"', html)


class TheIsolationRuleLivesInOnePlaceTest(SimpleTestCase):
    """Les trois lieux appellent la brique, et aucun ne réécrit la règle à côté."""

    def test_the_three_places_call_the_brick(self):
        preview = _source(PREVIEW)
        self.assertIn('media = documentFrameHtml(url, {', preview)           # aperçu en ligne
        self.assertIn("return documentFrame(data.url, { className: 'wama-viewer-frame", preview)
        self.assertIn('global.WamaMediaPreview.documentFrame(', _source(HTML_BRICK))

    def test_no_common_script_writes_a_sandbox_by_itself(self):
        """Un `sandbox` posé à la main, hors de la brique : la règle redevient une recopie. Le code
        seul est lu (`mecanismes_scan.code_only`) : un commentaire qui NOMME la règle n'en est pas
        une écriture."""
        from wama.common.services.mecanismes_scan import code_only
        pattern = re.compile(r"""setAttribute\(\s*['"]sandbox|<iframe[^>]*\bsandbox""")
        found = []
        for path in (ROOT / 'wama').rglob('*.js'):
            rel = path.relative_to(ROOT).as_posix()
            if '/vendors/' in rel or re.search(r'/[a-z]+_\d\d/', rel) or rel == 'wama/' + PREVIEW:
                continue                                    # tierces, jumelles, la brique elle-même
            text = code_only(rel, path.read_text(encoding='utf-8', errors='replace'))
            if pattern.search(text):
                found.append(rel)
        self.assertEqual([], found)
        self.assertEqual(1, _source(PREVIEW).count("' sandbox=\"\"'"), 'une seule écriture du cadre')

    def test_the_served_copies_match_the_sources(self):
        for rel in (PREVIEW, HTML_BRICK):
            served = ROOT / 'staticfiles' / rel.replace('/static/', '/', 1).split('/', 1)[1]
            if not served.exists():
                self.skipTest('pas de copie servie dans cet arbre')
            self.assertEqual((ROOT / 'wama' / rel).read_bytes(), served.read_bytes(), rel)
