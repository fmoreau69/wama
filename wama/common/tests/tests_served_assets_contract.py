"""What the browser RECEIVES is what the repository says — for every app, every JS and CSS file.

Contract 5 of `WAMA_VERIFICATION §8` (2026-09-26). `staticfiles/` is the SERVED folder; a source
edited without its copy leaves the browser on the old code with no error anywhere (a `.js` never
fails at compile time). Three apps checked it for one file each (converter, imager,
synthesizer); here, every file of every app, sandbox twins excepted.
"""
import re
from pathlib import Path

from django.test import SimpleTestCase, TestCase
from django.urls import NoReverseMatch, reverse

ROOT = Path(__file__).resolve().parents[3]


def _sources():
    """(source, served) for every JS/CSS of every app's static folder."""
    out = []
    for src in sorted(ROOT.glob('wama/*/static/*/js/*.js')) + sorted(ROOT.glob('wama/*/static/*/css/*.css')):
        rel = src.relative_to(src.parents[2])          # <app>/js/<file>
        if rel.parts[0].endswith('_01'):
            continue                                   # sandbox twin: its own regeneration cycle
        out.append((src, ROOT / 'staticfiles' / rel))
    return out


def _text(path):
    return path.read_bytes().replace(b'\r\n', b'\n')


class ServedAssetsContractTest(SimpleTestCase):

    def test_the_fleet_is_measured(self):
        self.assertGreater(len(_sources()), 50)

    def test_every_served_file_is_its_source(self):
        missing = [str(s.relative_to(ROOT)) for s, served in _sources() if not served.exists()]
        stale = [str(s.relative_to(ROOT)) for s, served in _sources()
                 if served.exists() and _text(s) != _text(served)]
        self.assertEqual([], missing, 'absent de staticfiles/ : le navigateur ne le reçoit pas')
        self.assertEqual([], stale, 'staticfiles/ diffère de la source : le navigateur a '
                                    "l'ancienne version (copier le fichier dans staticfiles/)")


#: Script tags that are DATA or templates, not code to run: V8 has nothing to parse there.
_NOT_CODE = re.compile(r'type\s*=\s*["\'](?:application/(?:json|ld\+json)|text/(?:template|html|x-template)|importmap|module)["\']', re.I)
_INLINE = re.compile(r'<script(?P<attrs>[^>]*)>(?P<body>.*?)</script>', re.S | re.I)


class EveryPageInlineScriptParsesTest(TestCase):
    """Every app page's INLINE scripts parse (V8, without running them) — a syntax error in one
    kills the whole block (panel rendering, filters, inspector) and no Python test sees it.
    It was checked for the synthesizer's page alone. ⚠ `py_mini_racer` lives in venv_win: the
    test skips elsewhere."""

    def test_every_inline_script_of_every_app_page_parses(self):
        try:
            from py_mini_racer import MiniRacer
        except ImportError:
            self.skipTest('py_mini_racer absent de ce venv : pas de V8 pour parser les pages')
        from wama.common.app_registry import APP_CATALOG
        from wama.common.tests.tests_endpoints import EveryEndpointAnswersTest
        broken, pages, blocks = [], 0, 0
        for app, spec in APP_CATALOG.items():
            if (spec or {}).get('sandbox'):
                continue
            try:
                url = reverse(f'{app}:index')
            except NoReverseMatch:
                continue
            self.client.force_login(EveryEndpointAnswersTest._account_for(self, app))
            response = self.client.get(url)
            if response.status_code != 200:
                continue
            pages += 1
            for m in _INLINE.finditer(response.content.decode('utf-8', errors='replace')):
                if 'src=' in m.group('attrs') or _NOT_CODE.search(m.group('attrs')):
                    continue
                body = m.group('body')
                if not body.strip():
                    continue
                blocks += 1
                try:
                    MiniRacer().eval('(function(){' + body + '\n})')
                except Exception as exc:
                    broken.append(f'{app} : {str(exc).splitlines()[0][:140]}')
        self.assertGreaterEqual(pages, 8, f'{pages} pages rendues seulement')
        self.assertGreater(blocks, 20, 'presque aucun script en ligne trouvé : garde affaiblie')
        self.assertEqual([], broken, 'script en ligne qui ne se PARSE pas (la page tombe) : '
                                     + ' ; '.join(broken))
