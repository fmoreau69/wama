"""La FILE commune (`common/_queue.html`, 2026-10-20) — barre, conteneur, entrées, état vide.

Décision de Fabien du 19/10 (`ROUTE §F3b`) : la file devient une pièce unique, portée aux dix
apps et au générateur sans exception, avant d'être déclarée comme brique de page. Ce fichier tient
ce que la pièce DÉRIVE (routes, ids, ZIP de lot, icône), ce qu'elle REND (la barre avant le
conteneur, l'état vide toujours là), la bascule commune de cet état vide, et le fait qu'aucune
page ni aucun script d'app ne recompose la file à côté d'elle.
"""
import re
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from django.conf import settings
from django.template import Template
from django.template.loader import render_to_string
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from wama.common import app_registry
from wama.common.services.mecanismes_scan import code_only
from wama.common.templatetags.wama_actions import queue_context

ROOT = Path(settings.BASE_DIR)
REAL_APPS = sorted(a for a, s in app_registry.APP_CATALOG.items() if not s.get('sandbox'))
PIECE = ROOT / 'wama' / 'common' / 'templates' / 'common' / '_queue.html'
CARD = Template('<div class="wama-card" data-id="{{ elem.id }}"></div>')


def _render(**ctx):
    base = {'card_template': CARD, 'batches': [], 'q_sort': 'recent', 'q_filter': 'all',
            'queue_id': 'q'}
    return render_to_string('common/_queue.html', {**base, **ctx})


def _lot(pk, *elements):
    return {'obj': SimpleNamespace(id=pk, is_unitary=False, total=len(elements), media_type='',
                                   created_at=None),
            'items': [{'elem': SimpleNamespace(id=e), 'output_filename': ''} for e in elements],
            'success_count': 1, 'running_count': 0, 'failure_count': 0, 'has_success': True}


class QueueContextTest(SimpleTestCase):
    """What the piece reads of the app's declaration (`queue_context`)."""

    def test_routes_are_read_under_their_admitted_spellings(self):
        ctx = queue_context('anonymizer')
        self.assertEqual(reverse('anonymizer:clear_all_media'), ctx['clear_url'])
        self.assertEqual(reverse('anonymizer:download_all_media'), ctx['download_url'])
        self.assertEqual(reverse('anonymizer:start_all'), ctx['start_url'])

    def test_a_domain_with_its_own_routes_uses_them(self):
        ctx = queue_context('enhancer', 'audio')
        self.assertEqual(reverse('enhancer:audio_start_all'), ctx['start_url'])
        self.assertEqual(reverse('enhancer:audio_download_all'), ctx['download_url'])

    def test_the_download_is_narrowed_only_when_domains_share_their_routes(self):
        self.assertEqual(reverse('imager:download_all') + '?domain=video',
                         queue_context('imager', 'video')['download_url'])
        self.assertEqual(reverse('enhancer:download_all'),
                         queue_context('enhancer', 'image_video')['download_url'],
                         'the media queue of the enhancer has the routes to itself')

    def test_the_empty_icon_is_the_domain_one_else_the_app_one(self):
        self.assertEqual('fas fa-film', queue_context('imager', 'video')['empty_icon'])
        self.assertEqual(app_registry.app_identity('transcriber')['icon'],
                         queue_context('transcriber')['empty_icon'])

    def test_a_missing_route_gives_an_empty_url_never_a_guess(self):
        self.assertEqual({'start_url': '', 'clear_url': '', 'download_url': ''},
                         {k: v for k, v in queue_context('no_such_app').items() if k != 'empty_icon'})


class ServedRouteTest(SimpleTestCase):
    """ONE resolver of the route an app serves for a conventional gesture (`urls_gen.served_route`,
    revérification du 2026-10-20) : the assistant's gestures, the queue's bar and its direct
    manipulation each looped over `reverse` on their own."""

    def test_it_reads_the_admitted_spelling_behind_the_domain_prefix(self):
        from wama.common.manifests.codegen.urls_gen import served_route
        self.assertEqual('clear_all_media', served_route('anonymizer', 'clear_all'))
        self.assertEqual('audio_start_all', served_route('enhancer', 'start_all', prefix='audio_'))
        self.assertEqual('', served_route('no_such_app', 'start_all'))

    def test_the_three_callers_go_through_it(self):
        from wama import tool_api
        with mock.patch('wama.common.manifests.codegen.urls_gen.served_route',
                        return_value='') as served:
            self.assertEqual('', tool_api._route_dispo('anonymizer', 'clear_all', []))
            self.assertEqual('', queue_context('anonymizer')['clear_url'])
            from wama.common.templatetags.wama_actions import queue_dnd_attrs
            self.assertNotIn('data-dnd-reorder-url', str(queue_dnd_attrs('reader')))
        self.assertGreaterEqual(served.call_count, 3)


class BoundedDownloadIsAcceptedTest(TestCase):
    """The piece narrows a queue's ⬇ by `?domain=` when two domains share their routes (read in
    `app_modes`) ; the view that serves it accepts only the domains given to `make_progress_views`
    (400 otherwise). Two declarations of one fact : each bounded ⬇ is CALLED here."""

    def test_every_bounded_download_is_served_not_refused(self):
        from wama.common.tests.tests_endpoints import EveryEndpointAnswersTest
        from wama.common.utils.app_modes import get_domains
        bounded = []
        for app in REAL_APPS:
            for domain in get_domains(app):
                url = queue_context(app, domain['id'])['download_url']
                if '?domain=' in url:
                    bounded.append((app, url))
        self.assertTrue(bounded, 'no bounded download left : the imager narrows its two queues')
        for app, url in bounded:
            self.client.force_login(EveryEndpointAnswersTest._account_for(self, app))
            with self.subTest(url=url):
                self.assertNotEqual(400, self.client.get(url).status_code)


class QueuePieceRenderTest(SimpleTestCase):
    """What the piece renders."""

    def test_the_bar_comes_before_the_container_and_its_ids_come_from_the_queue_id(self):
        html = _render(app='transcriber', queue_id='transcriptQueue')
        bar = html.find('id="transcriptQueue-start-all"')
        container = html.find('<div id="transcriptQueue" class="wama-queue-')
        self.assertNotEqual(-1, bar)
        self.assertNotEqual(-1, container)
        self.assertLess(bar, container, 'in a grid layout the bar would become a cell')
        for suffix in ('-clear-all', '-download-all'):
            self.assertIn(f'id="transcriptQueue{suffix}"', html)
        self.assertIn(f'data-queue-start-url="{reverse("transcriber:start_all")}"', html)
        # The queue is also a brick of the centre (`data-wama-brick`, 2026-10-28, step ④).
        self.assertRegex(html, r'id="transcriptQueue" class="wama-queue-list" data-wama-queue\s+'
                               r'data-wama-brick="queue"\s+data-wama-dnd=')

    def test_the_empty_state_is_always_rendered_and_hidden_when_entries_exist(self):
        empty = re.compile(r'<div class="empty-queue[^"]*"( hidden)?>')
        self.assertIsNone(empty.search(_render(app='reader')).group(1))
        filled = _render(app='reader', batches=[_lot(7, 1, 2)])
        self.assertEqual(' hidden', empty.search(filled).group(1))
        self.assertIn('data-id="1"', filled)

    def test_each_lot_gets_the_zip_of_its_domain(self):
        """The enhancer passed `download_url=batch_dl_url` without ever setting it : its lots had
        no ZIP at all. The piece derives it, with the domain's own routes."""
        audio = _render(app='enhancer', domain='audio', batches=[_lot(7, 1, 2)])
        self.assertIn(reverse('enhancer:audio_batch_download', args=[7]), audio)
        media = _render(app='enhancer', domain='image_video', batches=[_lot(8, 3, 4)])
        self.assertIn(reverse('enhancer:batch_download', args=[8]), media)

    def test_a_lot_route_that_does_not_exist_emits_no_url(self):
        """The opt-in to the shared lot actions is always given ; an absent route stays silent."""
        html = _render(app='reader', batches=[_lot(9, 1, 2)])
        self.assertIn(f'data-batch-delete-url="{reverse("reader:batch_delete", args=[9])}"', html)
        ghost = _render(app='no_such_app', batches=[_lot(9, 1, 2)])
        self.assertIn('batch-delete-btn', ghost)
        self.assertNotIn('data-batch-delete-url', ghost)
        self.assertNotIn('data-batch-zip', ghost)


class EveryQueueIsThePieceTest(SimpleTestCase):
    """No page and no script of an app composes the queue beside the piece."""

    def _pages(self):
        for app in REAL_APPS:
            page = ROOT / 'wama' / app / 'templates' / app / 'index.html'
            if page.exists():
                yield app, page, code_only(f'wama/{app}/index.html', page.read_text(encoding='utf-8'))

    def test_every_app_page_mounts_the_piece_and_writes_no_queue_by_hand(self):
        mounted, by_hand = {}, []
        for app, page, code in self._pages():
            mounted[app] = code.count("include 'common/_queue.html'")
            for written in ('class="wama-queue-', "'common/_queue_toolbar.html'",
                            "'common/_queue_entry.html'", 'queue_dnd_attrs'):
                if written in code:
                    by_hand.append(f'{page.relative_to(ROOT)} : {written}')
        self.assertEqual([], by_hand, '\n'.join(by_hand))
        self.assertEqual(10, len(mounted), mounted)
        self.assertTrue(all(mounted.values()), mounted)
        self.assertEqual(12, sum(mounted.values()), 'imager and enhancer have one queue per domain')

    def test_the_grid_reads_the_pieces_of_the_queue_through_the_piece(self):
        """Seven criteria read a piece of the queue in the app's files ; once the piece holds it,
        each must accept the inclusion as its proof — `layout` turned red on the ten apps the
        day of the port, before it read the piece (2026-10-20)."""
        from wama.common.services import conformity_checker as checker
        criteria = (checker._queue_piece, checker._queue_entry, checker._queue_toolbar,
                    checker._queue_actions_common, checker._eta_batch,
                    dict((c.key, c.fn) for c in checker.CRITERIA)['batch_card_common'],
                    dict((c.key, c.fn) for c in checker.CRITERIA)['layout'])
        states = {(app, i): fn(checker._AppFiles(app))[0]
                  for app in REAL_APPS for i, fn in enumerate(criteria)}
        self.assertEqual({k: True for k in states}, states)

    def test_the_generator_writes_the_same_line(self):
        source = (ROOT / 'wama' / 'common' / 'manifests' / 'codegen'
                  / 'templates_gen.py').read_text(encoding='utf-8')
        self.assertIn("include 'common/_queue.html'", source)
        self.assertNotIn("include 'common/_queue_toolbar.html'", source)
        self.assertNotIn("include 'common/_queue_entry.html'", source)

    def test_no_app_script_writes_an_empty_state(self):
        found = []
        for app in REAL_APPS:
            for script in sorted((ROOT / 'wama' / app / 'static').rglob('*.js')):
                rel = script.relative_to(ROOT).as_posix()
                code = code_only(rel, script.read_text(encoding='utf-8', errors='ignore'))
                for written in ('empty-queue', 'empty-state', 'emptyState', 'no-jobs-msg', 'emptyHint'):
                    if written in code:
                        found.append(f'{rel} : {written}')
        self.assertEqual([], found, '\n'.join(found))


class EmptyStateToggleTest(SimpleTestCase):
    """`wama-queue.js` shows the empty state when the last card leaves and hides it when one
    arrives — run in V8 against a minimal fake page (the script touches nothing else here)."""

    FAKE_PAGE = r'''
    var observed = [], storage = {};
    var empty = { hidden: false };
    var queue = { hasCard: false,
        querySelector: function (sel) {
            if (sel === ':scope > .empty-queue') return empty;
            if (sel === '.wama-card') return this.hasCard ? {} : null;
            return null; },
        classList: { contains: function () { return false; } } };
    function MutationObserver(cb) { this.observe = function () { observed.push(cb); }; }
    var document = { readyState: 'complete', cookie: '', head: { appendChild: function () {} },
        getElementById: function () { return null; },
        createElement: function () { return {}; },
        addEventListener: function () {},
        querySelector: function () { return null; },
        querySelectorAll: function (sel) { return sel === '[data-wama-queue]' ? [queue] : []; } };
    var window = this, localStorage = { getItem: function () { return null; }, setItem: function () {} };
    var sessionStorage = { getItem: function () { return null; }, removeItem: function () {} };
    '''

    def _run(self, served):
        from py_mini_racer import MiniRacer
        ctx = MiniRacer()
        ctx.eval(self.FAKE_PAGE)
        ctx.eval(served)
        return ctx

    def test_the_empty_state_follows_the_cards(self):
        served = (ROOT / 'staticfiles' / 'common' / 'js' / 'wama-queue.js').read_text(encoding='utf-8')
        source = (ROOT / 'wama' / 'common' / 'static' / 'common' / 'js'
                  / 'wama-queue.js').read_text(encoding='utf-8')
        self.assertEqual(source, served, 'staticfiles/ serves another wama-queue.js')
        ctx = self._run(served)
        self.assertEqual(1, ctx.eval('observed.length'), 'the queue is not observed')
        self.assertFalse(ctx.eval('empty.hidden'), 'an empty queue must show its message')
        ctx.eval('queue.hasCard = true; observed[0]();')
        self.assertTrue(ctx.eval('empty.hidden'), 'a card arrived : the message must go')
        ctx.eval('queue.hasCard = false; observed[0]();')
        self.assertFalse(ctx.eval('empty.hidden'), 'the last card left : the message must come back')
