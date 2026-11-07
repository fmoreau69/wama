"""Un JSON injecté dans un `<script>` ne peut plus fermer son bloc (audit de sécurité du 2026-11-06).

La classe de défaut : `const schema = {{ params_json|safe }};` pose le texte tel quel ; une donnée
saisie par un utilisateur (nom de voix, licence, libellé) contenant `</script>` fermait le bloc et
ce qui suivait s'exécutait chez qui ouvrait la page. 164 injections dans 27 gabarits le
2026-11-07, toutes portées vers `|script_json` (`common/templatetags/wama_json.py`).

Gardes : la brique échappe sans changer la valeur ; AUCUN gabarit (ni celui que génère
`templates_gen` pour une app née d'un manifeste) ne pose plus un `|safe` dans un `<script>`.
"""
import json
import pathlib
import re
from unittest import mock

from django.conf import settings
from django.template import Context, Template
from django.test import SimpleTestCase

from wama.common.templatetags.wama_json import script_json_text

ROOTS = ('wama', 'wama_lab', 'wama_data')
SCRIPT = re.compile(r'<script\b[^>]*>(.*?)</script>', re.S | re.I)
SAFE_VAR = re.compile(r'\{\{((?:(?!\}\}).)*?\|\s*safe\b(?:(?!\}\}).)*)\}\}', re.S)
HOSTILE = '</script><script>alert(1)</script><!-- &  '


def safe_in_scripts(text):
    """Les `{{ …|safe }}` situés DANS un bloc `<script>` du texte d'un gabarit."""
    return [v.group(1).strip() for block in SCRIPT.finditer(text)
            for v in SAFE_VAR.finditer(block.group(1))]


class ScriptJsonFilterTest(SimpleTestCase):

    def test_a_json_string_cannot_close_its_script_and_reads_back_unchanged(self):
        payload = json.dumps([{'label': HOSTILE, 'value': 'a<b && c>d'}])
        out = script_json_text(payload)
        for forbidden in ('<', '>', '&', ' '):
            self.assertNotIn(forbidden, out)
        self.assertEqual(json.loads(out), json.loads(payload))

    def test_a_python_value_is_serialised_then_escaped(self):
        out = script_json_text({'name': HOSTILE})
        self.assertNotIn('</script>', out)
        self.assertEqual(json.loads(out), {'name': HOSTILE})

    def test_the_rendered_page_keeps_the_hostile_name_inside_the_string(self):
        from wama.common.utils import voice_options
        hostile = [{'label': 'x', 'options': [{'value': 'v', 'label': HOSTILE}]}]
        with mock.patch.object(voice_options, 'get_voice_groups', return_value=hostile):
            groups = voice_options.voice_groups_json(None)
        page = Template('{% load wama_json %}<script>var g = {{ g|default:"[]"|script_json }};'
                        '</script>').render(Context({'g': groups}))
        self.assertEqual(page.count('</script>'), 1, 'seule la balise du gabarit ferme le bloc')
        body = page[len('<script>var g = '):page.index(';</script>')]
        self.assertEqual(json.loads(body), hostile)


class NoSafeJsonInScriptsTest(SimpleTestCase):

    def test_no_template_puts_a_safe_value_inside_a_script(self):
        base = pathlib.Path(settings.BASE_DIR)
        found = []
        for root in ROOTS:
            for path in (base / root).rglob('*.html'):
                if 'staticfiles' in path.parts:
                    continue
                for var in safe_in_scripts(path.read_text(encoding='utf-8', errors='replace')):
                    found.append(f'{path.relative_to(base).as_posix()}: {var}')
        self.assertEqual(found, [], 'remplacer `|safe` par `|script_json` ({% load wama_json %}) '
                                    'ou passer la valeur par `json_script`')

    def test_the_generated_index_of_an_app_uses_the_brick(self):
        from wama.common.manifests.codegen.templates_gen import render_index
        from wama.common.manifests.ingest import extract
        src, _reason = render_index(extract('app', 'converter'))
        if isinstance(src, dict):                      # forme à plusieurs fichiers du générateur
            src = src.get('index.html')
        self.assertTrue(src)
        self.assertEqual(safe_in_scripts(src), [])
        self.assertIn('|script_json', src)
        self.assertRegex(src, r'\{%\s*load\b[^%]*\bwama_json\b')

    def test_the_scanner_sees_the_forms_it_must_refuse(self):
        sample = ("<script>var a = {{ x|safe }}; var b = {{ y|default:'{}'|safe }};</script>"
                  '<div>{{ html|safe }}</div>')
        self.assertEqual(safe_in_scripts(sample), ['x|safe', "y|default:'{}'|safe"])
