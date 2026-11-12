"""Les DOMAINES d'une page — onglets, bascule, barre de progression par domaine (2026-11-01).

Étape ② de l'alignement des domaines (`ROUTE §11 #42`, plan accepté par Fabien : « le domaine
n'est qu'un niveau de structure qui contient des sous-structures »). Mesuré avant : à partir de
deux domaines, l'imager et l'enhancer rebranchaient la page à la main, chacun à sa façon —
onglets Bootstrap et script de bascule à l'imager, `WamaModes` et un `switchDomain` en ligne à
l'enhancer ; la barre de progression du second domaine recopiée en HTML (sans ETA, sans marque de
brique), démarrée par un `init` écrit dans le JS de l'app ; huit pages posaient l'adresse de leur
barre à la main (`WAMA_GLOBAL_PROGRESS_URL`).

Ce que ce fichier tient :
  • la barre lit son adresse et sa clé de la déclaration (`queue_context`), par la règle de la file ;
  • la pièce rend une barre par domaine, qui démarre seule ;
  • la page d'un domaine est montrée par une pièce (`_domain_tabs.html`, `WamaModes` : volets de
    file, réglages du volet) ; depuis le 2026-11-12 le domaine se choisit AU-DESSUS de la page —
    le socle le lit de l'adresse, le retient par compte, et le titre est le sélecteur
    (`navigation.page_domain`, `_page_domain.html`) : plus de seconde ligne d'onglets ;
  • aucune page d'app ni aucun script d'app ne refait l'une ou l'autre à côté.
V8 vient de `py_mini_racer` (AGENTS.md §JS) : les tests qui l'exécutent sautent sans lui.
"""
import importlib.util
import json
import re
from pathlib import Path
from unittest import skipUnless

from django.conf import settings
from django.template.loader import render_to_string
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from wama.common import app_registry
from wama.common.services.mecanismes_scan import code_only
from wama.common.templatetags.wama_actions import queue_context
from wama.common.tests.tests_cap_from_js import FAKE_DOM
from wama.common.tests.tests_poller_js import HARNESS
from wama.common.utils.app_modes import get_domains

HAS_V8 = importlib.util.find_spec('py_mini_racer') is not None
ROOT = Path(settings.BASE_DIR)
JS = ROOT / 'wama' / 'common' / 'static' / 'common' / 'js'
REAL_APPS = sorted(a for a, s in app_registry.APP_CATALOG.items() if not s.get('sandbox'))
MULTI = [a for a in REAL_APPS if len(get_domains(a)) > 1]


def _page(app):
    path = ROOT / 'wama' / app / 'templates' / app / 'index.html'
    return code_only(f'wama/{app}/index.html', path.read_text(encoding='utf-8'))


class ProgressIsReadFromTheDeclarationTest(SimpleTestCase):
    """L'adresse et la clé de la barre d'un domaine — la règle de la file (`queue_context`)."""

    def test_domains_that_share_their_routes_read_one_answer_by_their_key(self):
        for domain in ('image', 'video'):
            ctx = queue_context('imager', domain)
            self.assertEqual(reverse('imager:global_progress'), ctx['progress_url'])
            self.assertEqual(domain, ctx['progress_key'])

    def test_a_domain_with_its_own_routes_reads_its_own_progress(self):
        audio = queue_context('enhancer', 'audio')
        self.assertEqual(reverse('enhancer:audio_global_progress'), audio['progress_url'])
        self.assertEqual('', audio['progress_key'])
        media = queue_context('enhancer', 'image_video')
        self.assertEqual(reverse('enhancer:global_progress'), media['progress_url'])
        self.assertEqual('', media['progress_key'], 'the media queue has the routes to itself')

    def test_every_app_reads_the_route_it_serves(self):
        from wama.common.manifests.codegen.urls_gen import served_route
        for app in REAL_APPS:
            with self.subTest(app=app):
                self.assertEqual(reverse(f"{app}:{served_route(app, 'global_progress')}"),
                                 queue_context(app)['progress_url'])


class ProgressPieceRenderTest(SimpleTestCase):

    def test_a_domain_bar_carries_its_address_its_domain_and_its_queue(self):
        html = render_to_string('common/_global_progress.html',
                                {'app': 'imager', 'domain': 'video', 'queue_id': 'vq'})
        self.assertIn(f'data-progress-url="{reverse("imager:global_progress")}"', html)
        self.assertIn('data-progress-key="video"', html)
        self.assertIn('data-progress-queue="vq"', html)
        self.assertIn('data-wama-brick-domain="video"', html)
        for part in ('globalStatus', 'globalProgressStats', 'globalProgressPct',
                     'globalProgressBar', 'globalEta'):
            self.assertIn(f'id="{part}-video"', html, 'two bars on a page, two sets of ids')
        for cls in ('wama-gp-bar', 'wama-gp-stats', 'wama-gp-pct', 'wama-gp-eta'):
            self.assertIn(cls, html)

    def test_a_single_domain_bar_keeps_the_standard_ids(self):
        html = render_to_string('common/_global_progress.html', {'app': 'reader'})
        self.assertIn('id="globalProgressBar"', html)
        self.assertIn(f'data-progress-url="{reverse("reader:global_progress")}"', html)
        self.assertNotIn('data-progress-key', html)

    def test_without_the_app_the_bar_waits_for_the_page_address(self):
        """La forme d'avant (jumelles non régénérées) : aucune adresse portée."""
        html = render_to_string('common/_global_progress.html', {})
        self.assertIn('id="globalProgressBar"', html)
        self.assertNotIn('data-progress-url', html)


class EveryPageIsThePiecesTest(SimpleTestCase):
    """Aucune page d'app, aucun script d'app ne refait la bascule ni la barre à côté des pièces."""

    def test_every_app_page_mounts_the_bar_with_its_app(self):
        for app in REAL_APPS:
            with self.subTest(app=app):
                code = _page(app)
                bars = re.findall(r"include 'common/_global_progress\.html'([^%]*)%", code)
                self.assertTrue(bars, 'no progress bar')
                for bar in bars:
                    self.assertIn(f"app='{app}'", bar)
                self.assertNotIn('WAMA_GLOBAL_PROGRESS_URL', code)
                self.assertNotIn('wama-progress-track', code, 'a progress bar written by hand')

    def test_a_page_with_several_domains_has_one_bar_one_pane_and_settings_per_domain(self):
        self.assertEqual(['anonymizer', 'enhancer', 'imager'], MULTI)   # document : 2026-11-02
        for app in MULTI:
            with self.subTest(app=app):
                code = _page(app)
                self.assertIn(f"include 'common/_domain_tabs.html' with app='{app}'", code)
                self.assertNotIn('data-bs-toggle="tab"', code, 'domain tabs written by hand')
                for domain in get_domains(app):
                    d = domain['id']
                    self.assertRegex(code, rf"_global_progress\.html' with app='{app}' domain='{d}' "
                                           rf"queue_id='[\w-]+'")
                    self.assertRegex(code, rf'class="tab-pane[^"]*"[^>]*data-domain="{d}"')
                    self.assertIn(f'data-domain-settings="{d}"', code)

    def test_no_app_script_starts_a_bar_or_switches_the_domains(self):
        found = []
        for app in REAL_APPS:
            for script in sorted((ROOT / 'wama' / app / 'static').rglob('*.js')):
                rel = script.relative_to(ROOT).as_posix()
                code = code_only(rel, script.read_text(encoding='utf-8', errors='ignore'))
                for written in ('WamaGlobalProgress.init', 'bootstrap.Tab', "'shown.bs.tab'",
                                'data-domain-settings'):
                    if written in code:
                        found.append(f'{rel} : {written}')
        self.assertEqual([], found, '\n'.join(found))

    def test_the_generator_writes_the_same_line(self):
        source = (ROOT / 'wama' / 'common' / 'manifests' / 'codegen'
                  / 'templates_gen.py').read_text(encoding='utf-8')
        self.assertIn("include 'common/_global_progress.html' with app='{app}'", source)
        self.assertNotIn('window.WAMA_GLOBAL_PROGRESS_URL =', source)


class TheServedPageCarriesTheDomainsTest(TestCase):
    """Sur la page SERVIE : un hôte d'onglets, une barre par domaine, chacune son adresse."""

    def _get(self, app):
        from wama.common.tests.tests_endpoints import EveryEndpointAnswersTest
        self.client.force_login(EveryEndpointAnswersTest._account_for(self, app))
        r = self.client.get(reverse(f'{app}:index'))
        self.assertEqual(200, r.status_code)
        return r.content.decode(errors='replace')

    def test_each_domain_of_a_page_has_its_bar(self):
        for app in MULTI:
            with self.subTest(app=app):
                html = self._get(app)
                self.assertIn(f'data-wama-domain-tabs="{app}"', html)
                for domain in get_domains(app):
                    ctx = queue_context(app, domain['id'])
                    self.assertRegex(html, rf'id="globalStatus-{domain["id"]}"[^>]*'
                                           rf'data-progress-url="{re.escape(ctx["progress_url"])}"')

    def test_a_single_domain_page_has_one_bar_with_its_address(self):
        for app in sorted(set(REAL_APPS) - set(MULTI)):
            with self.subTest(app=app):
                html = self._get(app)
                self.assertEqual(1, html.count('data-wama-brick="global_progress"'))
                self.assertIn(f'data-progress-url="{queue_context(app)["progress_url"]}"', html)
                self.assertNotIn('data-wama-domain-tabs', html)
                self.assertNotIn('data-wama-page-domain', html, 'nothing to choose: no selector')

    def test_the_title_of_a_page_with_several_domains_is_their_selector(self):
        """2026-11-12 : un LIEN par domaine dans le titre, celui de la page marqué — et le
        premier déclaré tant que le compte n'a rien choisi."""
        for app in MULTI:
            with self.subTest(app=app):
                html = self._get(app)
                domains = get_domains(app)
                self.assertIn(f'data-wama-page-domain="{domains[0]["id"]}" data-app="{app}"', html)
                index = reverse(f'{app}:index')
                for domain in domains:
                    self.assertIn(f'href="{index}?domain={domain["id"]}"', html)
                    self.assertIn(f'data-domain-count="{domain["id"]}"', html)
                self.assertRegex(html, rf'href="{re.escape(index)}\?domain={domains[0]["id"]}" '
                                       r'aria-current="page"')
                for other in domains[1:]:
                    self.assertNotRegex(html, rf'href="{re.escape(index)}\?domain={other["id"]}" '
                                              r'aria-current="page"')

    def test_the_page_and_its_about_tab_say_what_the_domain_does(self):
        """Sous-titre et À propos PAR domaine : la phrase que le domaine déclare, et l'À propos du
        domaine de la page (celui que le compte a retenu), pas de l'app entière."""
        from wama.common.tests.tests_endpoints import EveryEndpointAnswersTest
        for app in MULTI:
            with self.subTest(app=app):
                account = EveryEndpointAnswersTest._account_for(self, app)
                self.client.force_login(account)
                second = get_domains(app)[1]
                page = self.client.get(reverse(f'{app}:index'), {'domain': second['id']})
                html = page.content.decode(errors='replace')
                self.assertIn('data-wama-page-domain-what', html)
                self.assertIn(second['description'].replace("'", '&#x27;'), html)
                about = self.client.get(reverse('common:app_about', args=[app]))
                self.assertEqual(200, about.status_code)
                self.assertIn(f'data-about-domain="{second["id"]}"',
                              about.content.decode(errors='replace'))

    def test_the_applications_menu_offers_the_domains_of_an_app_with_several(self):
        """« Arriver directement au bon domaine » : les liens du titre, dans le menu Applications."""
        from wama.common.services.navigation import domain_links
        app = MULTI[0]
        html = self._get(app)
        index = reverse(f'{app}:index')
        self.assertIn(f'id="navDomains-{app}"', html)
        for link in domain_links(app, index):
            self.assertIn(f'href="{link["url"]}" data-nav-domain="{link["id"]}"', html)
        # Contre-épreuve : une app d'un seul domaine garde son entrée simple.
        single = sorted(set(REAL_APPS) - set(MULTI))[0]
        self.assertEqual([], domain_links(single, reverse(f'{single}:index')))
        self.assertNotIn(f'id="navDomains-{single}"', html)

    def test_the_address_names_the_domain_and_the_account_keeps_it(self):
        from wama.common.models import UserAppSetting
        from wama.common.tests.tests_endpoints import EveryEndpointAnswersTest
        app = MULTI[0]
        account = EveryEndpointAnswersTest._account_for(self, app)
        self.client.force_login(account)
        index, (first, second) = reverse(f'{app}:index'), [d['id'] for d in get_domains(app)][:2]
        named = self.client.get(index, {'domain': second}).content.decode(errors='replace')
        self.assertIn(f'data-wama-page-domain="{second}"', named)
        self.assertEqual(second, UserAppSetting.objects.get(user=account, app=app, name='domain').value)
        # Sans rien dans l'adresse, la page s'ouvre sur le domaine RETENU par le compte.
        again = self.client.get(index).content.decode(errors='replace')
        self.assertIn(f'data-wama-page-domain="{second}"', again)
        # Contre-épreuve : un domaine que l'app ne déclare pas est ignoré, et rien n'est écrit.
        unknown = self.client.get(index, {'domain': 'no-such'}).content.decode(errors='replace')
        self.assertIn(f'data-wama-page-domain="{second}"', unknown)
        self.assertEqual(second, UserAppSetting.objects.get(user=account, app=app, name='domain').value)
        self.assertNotEqual(first, second)

    def test_the_arrival_of_a_file_tells_the_server_which_domain_received_it(self):
        """« Envoyer vers » retenait le domaine dans le navigateur ; il le dit au serveur."""
        from wama.common.models import UserAppSetting
        from wama.common.tests.tests_endpoints import EveryEndpointAnswersTest
        app = MULTI[0]
        account = EveryEndpointAnswersTest._account_for(self, app)
        self.client.force_login(account)
        second = get_domains(app)[1]['id']
        route = reverse('common:api_page_domain')
        self.assertEqual(200, self.client.post(route, {'app': app, 'domain': second}).status_code)
        self.assertEqual(second, UserAppSetting.objects.get(user=account, app=app, name='domain').value)
        for refused in ({'app': app, 'domain': 'no-such'}, {'app': 'no-such', 'domain': second}, {}):
            with self.subTest(refused=refused):
                self.assertEqual(400, self.client.post(route, refused).status_code)
        self.assertEqual(1, UserAppSetting.objects.filter(user=account, name='domain').count())
        self.assertIn("'/common/api/page-domain/'", (JS / 'wama-app-base.js').read_text(encoding='utf-8'))


@skipUnless(HAS_V8, 'py_mini_racer absent de ce venv')
class DomainSwitchTest(SimpleTestCase):
    """`WamaModes.showDomain` / `domainTabs` (wama-modes.js), exécutés en V8 sur une page factice."""

    PAGE = """
    function el(attrs) { return Object.assign({classList: classList(), style: {}, dataset: {}}, attrs); }
    var panes = [el({dataset: {domain: 'image'}}), el({dataset: {domain: 'video'}})];
    panes[0].classList.add('active'); panes[0].classList.add('show');
    var sets = [el({dataset: {domainSettings: 'image'}}), el({dataset: {domainSettings: 'video'}})];
    var badge = el({textContent: ''});
    var events = [], listeners = {}, chosen = null;
    var queueBadge = el({textContent: '12'});
    function CustomEvent(t, o) { this.type = t; this.detail = (o || {}).detail; }
    document.addEventListener = function (t, f) { (listeners[t] = listeners[t] || []).push(f); };
    document.dispatchEvent = function (e) { events.push(e.type);
        (listeners[e.type] || []).forEach(function (f) { f(e); }); };
    document.querySelectorAll = function (sel) {
        if (sel === '.tab-pane[data-domain]') return panes;
        if (sel === '[data-domain-settings]') return sets;
        if (sel === '[data-domain-count="video"]') return [badge];
        if (sel === '#queueCount') return [queueBadge];
        return []; };
    // Ce que le SOCLE rend dans le titre : le domaine choisi par le serveur (ou rien).
    document.querySelector = function (sel) {
        return sel === '[data-wama-page-domain]' ? chosen : null; };
    var host = {dataset: {wamaDomainTabs: 'imager'}, innerHTML: '',
                querySelectorAll: function () { return []; },
                querySelector: function (s) { return s.indexOf('data-domain-count') >= 0 ? badge : null; },
                addEventListener: function () {}};
    var SCHEMA = {domains: [{id: 'image', label: 'Image', modes: []},
                            {id: 'video', label: 'Vidéo', modes: []}]};
    function fetch() { return Promise.resolve({json: function () { return SCHEMA; }}); }
    """

    def setUp(self):
        from py_mini_racer import MiniRacer
        self.v8 = MiniRacer()
        self.v8.eval(FAKE_DOM + self.PAGE)
        self.v8.eval((JS / 'wama-app-base.js').read_text(encoding='utf-8'))
        self.v8.eval('var WamaApp = window.WamaApp;')   # `window` est l'objet global d'une page
        self.v8.eval((JS / 'wama-modes.js').read_text(encoding='utf-8'))

    def _js(self, expr):
        return json.loads(self.v8.eval(f'JSON.stringify({expr})'))

    STATE = ('[panes[0].classList.contains("active"), panes[1].classList.contains("active"),'
             ' sets[0].style.display, sets[1].style.display]')

    def test_showing_a_domain_shows_its_panes_and_its_settings_only(self):
        self.v8.eval("window.WamaModes.showDomain('video');")
        self.assertEqual([False, True, 'none', ''], self._js(self.STATE))

    def test_the_page_shows_the_domain_the_base_chose_without_any_tab(self):
        """2026-11-12 : le serveur choisit (adresse, sinon compte) ; la page montre, et compte."""
        self.v8.eval("chosen = {dataset: {app: 'imager', wamaPageDomain: 'video'}};"
                     " window.WamaModes.domainTabs(host);")
        self.assertEqual([False, True, 'none', ''], self._js(self.STATE))
        self.assertIn('wama:domain-change', self._js('events'))
        self.assertEqual('', self._js('host.innerHTML'), 'no second row of tabs')
        self.v8.eval("document.dispatchEvent(new CustomEvent('wama:domain-stats',"
                     " {detail: {domain: 'video', total: 7}}));")
        self.assertEqual(7, self._js('badge.textContent'), 'the count goes to the title menu')
        self.assertEqual(7, self._js('queueBadge.textContent'), 'the queue tab counts THIS domain')
        self.v8.eval("document.dispatchEvent(new CustomEvent('wama:domain-stats',"
                     " {detail: {domain: 'image', total: 5}}));")
        self.assertEqual(7, self._js('queueBadge.textContent'), 'another domain leaves it alone')
        self.assertEqual({'app': 'imager', 'domain': 'video'}, self._js('window.WamaModes.pageDomain()'))

    def test_a_page_from_a_server_not_restarted_yet_keeps_its_tabs(self):
        """Un script servi est lu aussitôt copié, le serveur web à sa relance seulement : entre
        les deux, la page n'a pas de domaine choisi — sans onglets, on ne pourrait plus en changer."""
        self.v8.eval("window.WamaModes.domainTabs(host);")
        self.assertIn('wm-domain', self._js('host.innerHTML'))
        self.assertNotIn('wm-mode', self._js('host.innerHTML'), 'the page tabs render no mode switch')
        self.assertIsNone(self._js('window.WamaModes.pageDomain()'))


@skipUnless(HAS_V8, 'py_mini_racer absent de ce venv')
class BarsStartThemselvesTest(SimpleTestCase):
    """`wama-global-progress.js` démarre chaque barre sur l'adresse qu'elle porte."""

    PAGE = """
    function part() { return {style: {}, classList: classList(), textContent: ''}; }
    function root(domain, key, active) {
        var parts = {'.wama-gp-bar': part(), '.wama-gp-stats': part(), '.wama-gp-pct': part(),
                     '.wama-gp-eta': null};
        var pane = {classList: classList()};
        if (active) pane.classList.add('active');
        return {style: {}, parts: parts, pane: pane,
                dataset: {progressUrl: '/imager/global-progress/', progressKey: key,
                          progressDomain: domain, progressQueue: domain + 'Queue'},
                querySelector: function (s) { return parts[s]; },
                closest: function () { return pane; }};
    }
    // L'onglet montré est le PREMIER : la barre du domaine caché répond après lui.
    var bars = [root('image', 'image', true), root('video', 'video', false)];
    var stats = [];
    function CustomEvent(t, o) { this.type = t; this.detail = (o || {}).detail; }
    document.dispatchEvent = function (e) { if (e.type === 'wama:domain-stats') stats.push(e.detail); };
    document.querySelectorAll = function (sel) {
        return sel.indexOf('data-progress-url') >= 0 ? bars : []; };
    """

    def setUp(self):
        from py_mini_racer import MiniRacer
        self.v8 = MiniRacer()
        self.v8.eval(FAKE_DOM + HARNESS)
        self.v8.eval((JS / 'wama-app-base.js').read_text(encoding='utf-8'))
        self.v8.eval('var WamaApp = window.WamaApp;' + self.PAGE)
        self.v8.eval((JS / 'wama-global-progress.js').read_text(encoding='utf-8'))
        self.v8.eval("answer({image: {total: 4, done: 1}, video: {total: 2, done: 2}});")

    def _js(self, expr):
        return json.loads(self.v8.eval(f'JSON.stringify({expr})'))

    def test_each_bar_reads_its_domain_from_one_answer(self):
        self.assertEqual(['/imager/global-progress/'], self._js('calls'))
        self.assertEqual(['25%', '100%'], self._js(
            "[bars[0].parts['.wama-gp-bar'].style.width, bars[1].parts['.wama-gp-bar'].style.width]"))

    def test_the_counts_of_the_page_are_those_of_the_shown_domain(self):
        self.assertEqual({'total': 4, 'done': 1, 'running': 0, 'failed': 0, 'stale': 0},
                         self._js('window.WamaQueueStats'),
                         'the hidden image queue overwrote the counts of the shown one')

    def test_each_bar_tells_the_count_of_its_domain(self):
        self.assertEqual([{'domain': 'image', 'total': 4}, {'domain': 'video', 'total': 2}],
                         self._js('stats'))


class ConsoleByDomainTest(TestCase):
    """2026-11-12 : la Console de la page d'un domaine ne mêle plus les lignes d'un autre — une
    ligne porte le domaine de l'élément traité, posé par le squelette à l'ouverture de la tâche."""

    def setUp(self):
        import uuid
        from wama.common.utils import console_utils
        # Un tampon par test : celui d'un compte survit au test (cache du processus).
        self.USER = 10 ** 9 + uuid.uuid4().int % 10 ** 9
        self.console = console_utils
        self.addCleanup(console_utils.set_line_domain, '')
        console_utils.set_line_domain('')
        console_utils.push_console_line(self.USER, 'whole app', app='imager')
        console_utils.set_line_domain('video')
        console_utils.push_console_line(self.USER, 'a video line', app='imager')
        console_utils.set_line_domain('image')
        console_utils.push_console_line(self.USER, 'an image line', app='imager')

    def _shown(self, **kwargs):
        return [line['msg'] for line in self.console.get_console_lines(self.USER, **kwargs)
                if line['msg'] in ('whole app', 'a video line', 'an image line')]

    def test_the_page_of_a_domain_shows_its_lines_and_those_of_the_whole_app(self):
        self.assertEqual(['whole app', 'an image line'], self._shown(app='imager', domain='image'))
        self.assertEqual(['whole app', 'a video line'], self._shown(app='imager', domain='video'))

    def test_without_a_domain_or_across_all_apps_nothing_is_set_aside(self):
        every = ['whole app', 'a video line', 'an image line']
        self.assertEqual(every, self._shown(app='imager'))
        self.assertEqual(every, self._shown(app='all', domain='image'))

    def test_a_line_can_name_its_domain_and_a_task_never_inherits_the_last_one(self):
        self.console.push_console_line(self.USER, 'an image line', app='imager', domain='image')
        self.console.set_line_domain('')                     # ce que fait la tâche suivante
        self.console.push_console_line(self.USER, 'whole app', app='imager')
        last = self.console.get_console_lines(self.USER, app='imager')[-1]
        self.assertEqual(('whole app', ''), (last['msg'], last['domain']))

    def test_the_skeleton_sets_it_and_the_page_asks_for_it(self):
        skeleton = (ROOT / 'wama' / 'common' / 'utils' / 'task_skeleton.py').read_text(encoding='utf-8')
        self.assertIn("set_line_domain(element_domain(item) if has_domain_tabs(app_id) else '')", skeleton)
        script = (JS / 'console.js').read_text(encoding='utf-8')
        self.assertIn("params.push('domain=' + encodeURIComponent(chosen.dataset.wamaPageDomain));", script)
        self.client.force_login(__import__('django.contrib.auth', fromlist=['x']).get_user_model()
                                .objects.create_user('console_domain', password='x'))
        answer = self.client.get(reverse('common:console'), {'app': 'imager', 'domain': 'image'})
        self.assertEqual(200, answer.status_code)
