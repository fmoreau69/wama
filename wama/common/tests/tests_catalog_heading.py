"""A catalog page is named like its MENU ENTRY, at one place (2026-10-16, asked by Fabien : « fais le
petit chantier d'uniformisation »). Measured that day : ten templates passed the header a title and
an icon RECOPIED from their menu entry — the icon identical ten times out of ten, the title in three
variants for the same page (« Licences » in the menu, « Catalogue des licences » as title, « - » or
« — » in the tab). The header now reads them from the declaration (`page_heading` →
`app_registry.account_page_of`)."""
import re
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import RequestFactory, SimpleTestCase, TestCase
from django.urls import resolve, reverse

from wama.common.app_registry import account_page_of, account_pages

ROOT = Path(settings.BASE_DIR)
HEADER = "common/_catalog_header.html"


def _templates_with_the_header():
    found = {}
    for path in [*ROOT.glob('wama/**/templates/**/*.html'), *ROOT.glob('wama_*/**/templates/**/*.html')]:
        text = path.read_text(encoding='utf-8', errors='replace')
        calls = re.findall(r"\{% include '" + re.escape(HEADER) + r"'([^%]*)%\}", text)
        if calls:
            found[path.relative_to(ROOT).as_posix()] = calls
    return found


class NoTemplateRecopiesItsMenuEntryTest(SimpleTestCase):

    def test_a_menu_page_passes_neither_title_nor_icon(self):
        found = _templates_with_the_header()
        self.assertGreaterEqual(len(found), 10, 'the instrument sees the catalog pages')
        offenders = [f'{tpl} : {call.strip()}' for tpl, calls in found.items() for call in calls
                     if re.search(r'\b(titre|icone)=', call) and not tpl.endswith('doc_read.html')]
        self.assertEqual([], offenders, 'a catalog page names itself through its menu entry')

    def test_the_tab_title_is_not_written_by_hand_either(self):
        literal = []
        for tpl in _templates_with_the_header():
            if tpl.endswith('doc_read.html'):
                continue
            text = (ROOT / tpl).read_text(encoding='utf-8')
            block = re.search(r'\{% block title %\}(.*?)\{% endblock %\}', text, re.S)
            if block and 'page_heading' not in block.group(1):
                literal.append(f'{tpl} : {block.group(1).strip()}')
        self.assertEqual([], literal)

    def test_an_explicit_title_still_wins_for_a_page_outside_the_menu(self):
        from wama.common.templatetags.wama_catalog import page_heading
        request = RequestFactory().get(reverse('common:licenses_catalog'))
        request.resolver_match = resolve(request.path)
        context = {'request': request}
        self.assertEqual({'label': 'AGENTS.md', 'icon': 'fa-file-lines'},
                         page_heading(context, 'AGENTS.md', 'fa-file-lines'))
        menu = account_page_of('common:licenses_catalog')
        self.assertEqual({'label': menu['label'], 'icon': menu['icon']}, page_heading(context))
        self.assertIsNone(account_page_of(''))
        self.assertIsNone(account_page_of('common:no_such_page'))


class EveryCatalogPageShowsItsMenuEntryTest(TestCase):

    def test_heading_and_tab_follow_the_declaration(self):
        self.client.force_login(get_user_model().objects.create_superuser('heading', password='x'))
        checked = 0
        for page in account_pages():
            if not page['url_name']:
                continue
            with self.subTest(page=page['key']):
                response = self.client.get(reverse(page['url_name']))
                if response.status_code != 200:
                    continue
                html = response.content.decode('utf-8', 'replace')
                if 'wama-cat-header' not in html:
                    continue                    # a page without the catalog header
                checked += 1
                heading = re.search(r'class="wama-cat-header[^"]*">\s*<h2[^>]*>(.*?)</h2>', html, re.S).group(1)
                self.assertIn(f'fas {page["icon"]}', heading)
                self.assertIn(page['label'], heading)
                self.assertIn(f'<title>{page["label"]} — WAMA</title>', re.sub(r'\s+', ' ', html))
        self.assertGreaterEqual(checked, 10, 'every catalog page of the menu was measured')
