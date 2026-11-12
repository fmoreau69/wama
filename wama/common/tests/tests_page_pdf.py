"""The PDF export of a page fetches its sub-resources OFF Playwright's event loop (2026-11-12).

Playwright's route handler runs inside its asyncio loop; a Django view called there raises
`SynchronousOnlyOperation` as soon as it touches the ORM — the export of the presentation answered
« Export PDF indisponible » while Chromium was fine. Found and fixed through the assistant
(Claude Code task `20261112-140730-752838`), guarded here.
"""
import asyncio

from django.contrib.auth import get_user_model
from django.test import RequestFactory, TransactionTestCase

from wama.common.services.page_pdf import make_fetcher


class FetchOffTheEventLoopTest(TransactionTestCase):
    """A TransactionTestCase: the fetch runs in another thread, which only sees committed rows."""

    def test_a_view_that_reads_the_database_is_served_inside_a_running_loop(self):
        user = get_user_model().objects.create_user('pdf_fetch', password='x')
        request = RequestFactory().get('/')
        request.user, request.session = user, {}
        fetch = make_fetcher(request)

        async def from_the_loop():
            return fetch('/common/api/notifications/')

        status, content_type, body = asyncio.run(from_the_loop())
        self.assertEqual(200, status, body[:200])
        self.assertIn('json', content_type)
        self.assertIn(b'"items"', body)

    def test_an_unknown_path_is_a_404_not_an_error(self):
        request = RequestFactory().get('/')
        request.user, request.session = get_user_model()(), {}
        self.assertEqual(404, make_fetcher(request)('/no/such/page/')[0])
