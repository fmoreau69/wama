"""`access_cases()` — l'énumération des cas d'accès montrée par la présentation (vue 3D des droits).

Ce qui compte : la présentation affiche des décisions RÉELLES. Un compte fictif qui décide
autrement qu'un vrai compte de même profil et mêmes rôles montrerait des droits faux, avec
l'autorité d'une visualisation — d'où la confrontation à de vrais `User` ci-dessous.
"""
from django.contrib.auth.models import Group, User
from django.test import TestCase
from django.urls import reverse

from wama.accounts.models import UserProfile
from wama.accounts.permissions import (
    GROUP_PREFIX, ROLES, TIER_ORDER, access_cases, accessible,
)


class AccessCasesTests(TestCase):

    def setUp(self):
        self.cases = access_cases()

    def _account(self, name, tier, roles):
        u = User.objects.create_user(name, password='x')
        UserProfile.objects.update_or_create(user=u, defaults={'account_tier': tier})
        u.groups.add(*[Group.objects.get_or_create(name=GROUP_PREFIX + r)[0] for r in roles])
        return User.objects.get(pk=u.pk)

    def test_the_grid_covers_every_tier_times_every_role_combination(self):
        self.assertEqual(len(self.cases['role_sets']), 2 ** len(ROLES))
        self.assertEqual(self.cases['configurations'], len(TIER_ORDER) * 2 ** len(ROLES))
        self.assertEqual(len(self.cases['matrix']), len(TIER_ORDER))
        for rows in self.cases['matrix']:
            self.assertEqual(len(rows), len(self.cases['role_sets']))
            for row in rows:
                self.assertEqual(len(row), len(self.cases['apps']))

    def test_every_case_matches_the_decision_for_a_real_account(self):
        apps = [a['id'] for a in self.cases['apps']]
        self.assertTrue(apps, "aucune app : le test ne mesurerait rien")
        for t, tier in enumerate(TIER_ORDER):
            for r, roles in enumerate(self.cases['role_sets']):
                user = self._account(f'case_{t}_{r}', tier, roles)
                real = [accessible(user, 'app', a) for a in apps]
                self.assertEqual(self.cases['matrix'][t][r], real, f"{tier} + {roles}")

    def test_distinct_behaviours_never_exceed_configurations(self):
        self.assertGreaterEqual(self.cases['distinct_rows'], 1)
        self.assertLessEqual(self.cases['distinct_rows'], self.cases['configurations'])


class PresentationRoutesTests(TestCase):

    def test_the_current_presentation_and_its_access_cases_are_served(self):
        self.assertEqual(self.client.get(reverse('presentation')).status_code, 200)
        r = self.client.get(reverse('presentation_access_cases'))
        self.assertEqual(r.status_code, 200)
        self.assertIn('matrix', r.json())

    def test_the_roadmap_slide_shows_every_milestone_of_the_roadmap_document(self):
        """The timeline is DERIVED from ROADMAP.md (2026-10-13): each milestone written there
        appears on the slide, and the PDF export receives the same context as the page."""
        from django.utils.html import escape

        from wama.common.roadmap_timeline import milestones
        from wama.views import PDF_PAGES, presentation_context
        items = milestones()
        self.assertGreaterEqual(len(items), 5, "a timeline of fewer than five milestones says nothing")
        page = self.client.get(reverse('presentation')).content.decode()
        self.assertIn('id="roadmap"', page)
        for item in items:
            self.assertIn(escape(item['label']), page, f"milestone missing from the slide: {item['label']}")
        self.assertNotIn('Frise illisible', page)
        self.assertIs(PDF_PAGES['presentation']['context'], presentation_context)

    def test_the_transcription_report_is_served_with_its_three_charts(self):
        """Added to « Présentations & annexes » on 2026-10-02: a generated snapshot of the report,
        whose three charts the export had dropped — they are redrawn, none may be missing."""
        r = self.client.get(reverse('report', args=['transcription']))
        self.assertEqual(200, r.status_code)
        page = r.content.decode()
        self.assertEqual(3, page.count('<figure class="chart">'))
        self.assertNotIn('embedded content', page)
        self.assertNotIn('{%', page, 'no template syntax may leak into the page')
        self.assertEqual('/reports/transcription/', reverse('report', args=['transcription']),
                         'the address given out on 2026-10-02 stays valid')

    def test_every_declared_report_is_served_and_listed_by_the_home_menu(self):
        """The « Rapports » category is filled from the `REPORTS` declaration, like the archives:
        a report is added by its line, never by a hand-written menu entry."""
        from pathlib import Path

        from django.conf import settings
        from wama.views import REPORTS
        self.assertTrue(REPORTS)
        for slug in REPORTS:
            self.assertEqual(200, self.client.get(reverse('report', args=[slug])).status_code)
        self.assertEqual(404, self.client.get(reverse('report', args=['unknown'])).status_code)
        home = (Path(settings.BASE_DIR) / 'wama' / 'templates' / 'home.html').read_text(encoding='utf-8')
        self.assertIn("{% url 'report' r.slug %}", home)
        self.assertIn('Rapports</h6>', home)

    def test_the_architecture_runs_on_the_canvas_engine_and_its_former_version_is_archived(self):
        """Rewritten on 2026-10-03 in the style of the v2 presentation: same engine, same chrome.
        The v1 slideshow is archived, never destroyed."""
        import re

        from wama.views import ARCHIVED_PRESENTATIONS
        r = self.client.get(reverse('architecture'))
        self.assertEqual(200, r.status_code)
        page = r.content.decode()
        self.assertIn('presentation/wama-presentation.js', page)
        for element in ('id="viewport"', 'id="world"', 'id="hud-count"', 'id="btn-next"'):
            self.assertIn(element, page, 'the engine needs its chrome')
        frames = re.findall(r'<section class="frame[^"]*"[^>]*>', page)
        self.assertGreaterEqual(len(frames), 15)
        for frame in frames:
            for attribute in ('data-x=', 'data-y=', 'data-s=', 'data-title='):
                self.assertIn(attribute, frame, 'a frame without a position is skipped by the camera')
        self.assertNotIn('{%', page, 'no template syntax may leak into the page')
        self.assertIn(reverse('report', args=['transcription']), page)
        self.assertIn('architecture-2026-v1', ARCHIVED_PRESENTATIONS)
        self.assertIn(reverse('presentation_archive', args=['architecture-2026-v1']), page)

    def test_archived_presentations_stay_reachable(self):
        from wama.views import ARCHIVED_PRESENTATIONS
        self.assertTrue(ARCHIVED_PRESENTATIONS)
        for slug in ARCHIVED_PRESENTATIONS:
            self.assertEqual(self.client.get(reverse('presentation_archive', args=[slug])).status_code, 200)
        self.assertEqual(self.client.get(reverse('presentation_archive', args=['unknown'])).status_code, 404)


class PageExportTests(TestCase):
    """PDF export of the home page's presentations and reports (2026-10-07): each page links `pdf/`,
    relative, and the route under it is the export — the link is written without `{% url %}` so a
    template read before the routes are reloaded gives a 404, never a 500."""

    def _exportable(self):
        from wama.views import PDF_PAGES, REPORTS
        return ([(reverse(name), entry['slides']) for name, entry in PDF_PAGES.items()]
                + [(reverse('report', args=[slug]), False) for slug in REPORTS])

    def _render_into(self, written):
        def fake(html, output_path, *, fetch, path='/', slides=False, origin=''):
            written.append((path, slides, html))
            with open(output_path, 'wb') as f:
                f.write(b'%PDF-1.4 test')
            return True
        return fake

    def setUp(self):
        import tempfile
        from unittest import mock

        from wama.common.services import page_pdf
        self.cache = tempfile.TemporaryDirectory()
        patcher = mock.patch.object(page_pdf, 'CACHE_DIR', __import__('pathlib').Path(self.cache.name))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.cache.cleanup)

    def test_every_exportable_page_links_its_pdf_and_the_route_under_it_answers(self):
        from unittest import mock

        from django.urls import resolve
        from wama import views
        written = []
        with mock.patch('wama.common.utils.html_render.render_page_to_pdf', self._render_into(written)):
            for path, slides in self._exportable():
                self.assertIn('href="pdf/"', self.client.get(path).content.decode(), path)
                self.assertIs(views.page_pdf, resolve(path + 'pdf/').func, path)
                r = self.client.get(path + 'pdf/')
                self.assertEqual(200, r.status_code, path)
                self.assertEqual('application/pdf', r['Content-Type'])
                self.assertIn('attachment', r['Content-Disposition'])
                self.assertEqual(b'%PDF-1.4 test', b''.join(r.streaming_content))
                self.assertEqual((path, slides), written[-1][:2], 'rendered at its own address, in its own mode')
        self.assertIn(True, [s for _p, s in self._exportable()], 'the canvas presentations export by step')

    def test_an_export_the_renderer_cannot_produce_says_so(self):
        from unittest import mock
        with mock.patch('wama.common.utils.html_render.render_page_to_pdf', return_value=False):
            r = self.client.get(reverse('report_pdf', args=['transcription']))
        self.assertEqual(503, r.status_code)
        self.assertEqual(404, self.client.get(reverse('report_pdf', args=['unknown'])).status_code)

    def test_the_page_is_served_its_statics_and_views_in_process(self):
        """The server never calls itself (a single worker would block): what the rendered page asks
        its origin for comes from the disk and from the Django view behind the path."""
        from django.contrib.auth.models import AnonymousUser
        from django.test import RequestFactory
        from wama.common.services.page_pdf import make_fetcher
        request = RequestFactory().get('/')
        request.user, request.session = AnonymousUser(), self.client.session
        fetch = make_fetcher(request)
        status, ctype, body = fetch('/static/presentation/wama-presentation.js?v=1')
        self.assertEqual((200, True), (status, b'window.WamaPrez' in body))
        self.assertIn('javascript', ctype)
        status, ctype, body = fetch(reverse('presentation_access_cases'))
        self.assertEqual(200, status)
        self.assertIn(b'matrix', body)
        self.assertEqual(404, fetch('/static/nothing-here.js')[0])
        self.assertEqual(404, fetch('/no/such/page/')[0])
