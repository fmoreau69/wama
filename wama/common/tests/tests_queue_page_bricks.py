"""Ce que la PAGE d'une file appelle — la card rendue seule, le gabarit de lot, le rangement des
orphelins, la file elle-même — par les briques COMMUNES, dans chaque app (2026-11-02).

Question de Fabien : « comment c'est possible qu'on ait des divergences de comportement sur un
code qui a déjà été porté et qui est censé être commun ? ». La grille notait VERT la présence d'un
MOT : la route `card_html`, la route `batch_template`, le nom `auto_wrap_orphans`, le nom
`build_batches_list`. Mesuré derrière ce vert :
  • onze vues `card_html` écrites à la main — `card_label` (le nom de sortie que la file donne à
    la card) n'était passé que par le composer : la card du synthesizer rafraîchie perdait le sien ;
  • sept gabarits de lot écrits à la main, sous trois noms de fichier ;
  • deux boucles de rangement des orphelins, dans des fonctions locales nommées comme la brique
    (avatarizer, converter) ;
  • une file construite à la main (converter), sans attentes de ressources, périmés, évaluation
    ni référence de lot — et la brique, elle, listait les lots publics de tout le parc pour un
    compte de VISITEUR (`visible_to` au lieu de `listable_by`).

Ce fichier tient le COMPORTEMENT, app par app, sur des témoins construits sans rien connaître
d'elles (`tests_queue_delete_contract._instance` / `_lot_de`) ; la grille tient l'adoption
(`card_html_endpoint`, `batch_template`, `auto_wrap_orphans`, `build_batches_list`).
"""
from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.urls import NoReverseMatch, reverse

from wama.common.tests.tests_element_gestures import REAL_APPS, _EveryApp

User = get_user_model()

#: Les routes de lot de l'audio de l'enhancer sont préfixées (son second domaine).
_AUDIO = 'audio_enhancer'


def _route(surface, name):
    return f'enhancer:audio_{name}' if surface == _AUDIO else f'{surface}:{name}'


class TheGridMeasuresTheCallTest(SimpleTestCase):
    """Les quatre critères mesurent l'APPEL de la brique, plus son nom : chaque app réelle y est
    verte, et une vue écrite à la main à côté de la route n'y est pas."""

    CRITERIA = ('card_html_endpoint', 'batch_template', 'auto_wrap_orphans', 'build_batches_list')

    def test_every_real_app_calls_the_bricks(self):
        from wama.common.services import conformity_checker as checker
        for key in self.CRITERIA:
            criterion = next(c for c in checker.CRITERIA if c.key == key)
            for app in REAL_APPS:
                with self.subTest(criterion=key, app=app):
                    state, evidence = criterion.fn(checker._AppFiles(app))
                    self.assertIs(True, state, evidence)

    def test_a_route_with_a_hand_written_view_is_partial(self):
        from unittest import mock

        from wama.common.services import conformity_checker as checker
        files = checker._AppFiles('reader')
        with mock.patch.object(files, 'find_code', return_value=None):
            state, evidence = checker._route_by_factory(files, r'card_html', 'make_card_view')
        self.assertEqual('partial', state)
        self.assertIn('make_card_view', evidence)


class CardViewIsTheFactorysTest(_EveryApp):
    """`card_html` par `item_views.make_card_view` : les clés que la FILE donne à une card."""

    def test_every_card_view_is_made_by_the_factory(self):
        import importlib
        for app in REAL_APPS:
            views = importlib.import_module(f'wama.{app}.views')
            names = ('card_html', 'audio_card_html') if app == 'enhancer' else ('card_html',)
            for name in names:
                with self.subTest(view=f'{app}.{name}'):
                    self.assertIn('make_card_view.<locals>',
                                  getattr(getattr(views, name), '__qualname__', ''))

    def test_a_refreshed_card_keeps_the_label_its_queue_gives_it(self):
        from wama.common.tests.tests_queue_delete_contract import _lot_de
        fleet = {s: (a, m) for s, a, m in self.fleet()}
        for surface in ('synthesizer', 'composer'):
            with self.subTest(surface=surface):
                account, model = fleet[surface]
                self.client.force_login(account)
                _lot, (card, _sister) = _lot_de(model, account, 2)
                if surface == 'synthesizer':
                    # Le nom de sortie s'affiche à la place du fichier source quand il n'y en a pas
                    # (un texte saisi, une ligne de lot) — `_synthesis_card.html`.
                    model.objects.filter(pk=card.pk).update(text_file='')
                # La ligne de lot de la card, lue sans la brique que la vue emploie (`link_row_of`) :
                # la neutraliser en contre-épreuve ne doit pas casser le témoin.
                link = next(row for row in _lot.items.all()
                            if card.pk in (getattr(row, 'synthesis_id', None),
                                           getattr(row, 'generation_id', None)))
                link.output_filename = 'consigne_sortie_unique.wav'
                link.save(update_fields=['output_filename'])
                html = self.client.get(reverse(_route(surface, 'card_html'), args=[card.pk]))
                self.assertEqual(200, html.status_code)
                self.assertIn('consigne_sortie_unique.wav', html.content.decode(),
                              'la card rafraîchie perd le nom de sortie que la file lui donne')

    def test_a_refreshed_card_knows_its_domain(self):
        from wama.common.tests.tests_queue_delete_contract import _instance
        account, model = {s: (a, m) for s, a, m in self.fleet()}['imager']
        self.client.force_login(account)
        video = _instance(model, account, generation_mode='txt2vid')
        html = self.client.get(reverse('imager:card_html', args=[video.pk])).content.decode()
        self.assertIn('data-domain="video"', html)


class BatchTemplateIsServedByTheBrickTest(_EveryApp):
    """Le gabarit de lot par `batch_parsers.batch_template_response` : un nom de fichier, et un
    gabarit que le lecteur de l'app ACCEPTE — le geste le plus naturel est de le redéposer tel
    quel (le converter en avait un qui ne produisait rien, mesuré le 2026-08-27)."""

    #: Les apps dont l'aperçu de lot ne se fait pas par `batch_preview` — aucune aujourd'hui.
    NO_PREVIEW = set()

    def _surfaces(self):
        return [s for s in (*REAL_APPS, _AUDIO)]

    def test_each_template_is_named_after_its_app(self):
        for surface, account, _model in self.fleet():
            with self.subTest(surface=surface):
                self.client.force_login(account)
                response = self.client.get(reverse(_route(surface, 'batch_template')))
                self.assertEqual(200, response.status_code)
                self.assertIn(f'filename="batch_{surface}_template.txt"',
                              response['Content-Disposition'])

    def test_a_template_dropped_back_as_it_is_gives_an_element(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        for surface, account, _model in self.fleet():
            if surface in self.NO_PREVIEW:
                continue
            with self.subTest(surface=surface):
                self.client.force_login(account)
                text = self.client.get(reverse(_route(surface, 'batch_template'))).content
                try:
                    preview = reverse(_route(surface, 'batch_preview'))
                except NoReverseMatch:
                    self.fail(f'{surface} : aucune route `batch_preview` (le déclarer dans NO_PREVIEW)')
                body = self.client.post(preview, {'batch_file': SimpleUploadedFile(
                    f'batch_{surface}_template.txt', text, content_type='text/plain')}).json()
                self.assertGreaterEqual(body.get('count', len(body.get('items') or [])), 1, body)

    def test_formats_are_said_only_for_a_column_that_takes_a_file(self):
        from wama.common.utils.batch_parsers import batch_template_response
        sources = batch_template_response('reader', ['source'], {'source': 'a.pdf'}).content.decode()
        texts = batch_template_response('synthesizer', ['sortie', 'texte'],
                                        {'sortie': 'a.wav', 'texte': 'bonjour'}).content.decode()
        self.assertIn('Formats acceptés : ', sources)
        self.assertIn('.pdf', sources)
        self.assertNotIn('Formats acceptés', texts)

    def test_a_reader_without_the_positional_syntax_is_not_told_it(self):
        from wama.common.utils.batch_parsers import build_batch_template
        self.assertNotIn('POSITIONNEL', build_batch_template(['texte'], {}, positional=False))
        self.assertIn('POSITIONNEL', build_batch_template(['texte'], {}))


class OrphansAreWrappedByTheBrickTest(TestCase):
    """`batch_common.auto_wrap_orphans`, ses deux formes de rattachement."""

    def setUp(self):
        self.user = User.objects.create_user('orphans_brick', password='x')

    def test_a_direct_form_orphan_gets_a_lot_of_its_nature_and_a_quick_job_none(self):
        from wama.converter.models import ConversionJob
        from wama.converter.views import _auto_wrap_orphans
        queued = ConversionJob.objects.create(user=self.user, media_type='audio',
                                              input_filename='a.wav')
        quick = ConversionJob.objects.create(user=self.user, media_type='audio',
                                             input_filename='b.wav', ephemeral=True)
        _auto_wrap_orphans(self.user)
        queued.refresh_from_db()
        quick.refresh_from_db()
        self.assertIsNotNone(queued.batch)
        self.assertEqual('audio', queued.batch.media_type)
        self.assertIsNone(quick.batch, 'une conversion rapide n’entre jamais dans un lot')

    def test_a_link_form_orphan_gets_its_own_lot(self):
        from wama.avatarizer.models import AvatarJob
        from wama.avatarizer.views import _auto_wrap_orphans
        from wama.common.tests.tests_queue_delete_contract import _instance
        from wama.common.utils.batch_common import batch_of
        job = _instance(AvatarJob, self.user)
        _auto_wrap_orphans(self.user)
        self.assertTrue(batch_of(job).is_unitary)


class TheQueueIsBuiltByTheBrickTest(TestCase):
    """`batch_common.build_batches_list` : la forme à FK directe, et la règle de LISTE."""

    def setUp(self):
        self.user = User.objects.create_user('queue_brick', password='x')

    def test_the_direct_form_lists_its_jobs_in_line_order_with_the_common_counts(self):
        from wama.common.utils.batch_common import build_batches_list
        from wama.converter.models import ConversionBatch, ConversionJob
        lot = ConversionBatch.objects.create(user=self.user, media_type='image', total=2)
        second = ConversionJob.objects.create(user=self.user, batch=lot, batch_row_index=1,
                                              media_type='image', input_filename='b.png')
        first = ConversionJob.objects.create(user=self.user, batch=lot, batch_row_index=0,
                                             media_type='image', input_filename='a.png',
                                             status='SUCCESS')
        (row,) = build_batches_list(self.user, batch_model=ConversionBatch, work_attr=None)
        self.assertEqual([first.pk, second.pk], [it.pk for it in row['items']])
        self.assertEqual([first.pk, second.pk], [it.elem.pk for it in row['items']])
        for key in ('awaiting_count', 'stale_count', 'evaluation', 'reference', 'eta_ids'):
            self.assertIn(key, row)
        self.assertEqual(1, row['success_count'])

    def test_a_visitor_account_lists_only_what_it_owns(self):
        from wama.accounts.permissions import VISITOR_ACCOUNT_PREFIX
        from wama.common.utils.batch_common import build_batches_list
        from wama.converter.models import ConversionBatch, ConversionJob
        if not hasattr(ConversionBatch.objects, 'visible_to'):
            self.skipTest('le lot du converter ne se partage pas')
        other = User.objects.create_user('queue_brick_owner', password='x')
        public = ConversionBatch.objects.create(user=other, media_type='image', total=1,
                                                visibility='public')
        # La card aussi est publique : un lot reçu ne montre que ses cards visibles — sans elle,
        # le lot sortait vide par cette autre règle, et le test ne mesurait rien (contre-épreuve).
        ConversionJob.objects.create(user=other, batch=public, media_type='image',
                                     input_filename='p.png', visibility='public')
        member = User.objects.create_user('queue_brick_member', password='x')
        listed = build_batches_list(member, batch_model=ConversionBatch, work_attr=None)
        self.assertEqual([public.pk], [r['obj'].pk for r in listed],
                         'témoin : un membre voit bien le lot public')
        visitor = User.objects.create_user(f'{VISITOR_ACCOUNT_PREFIX}queuebrick', password='x')
        rows = build_batches_list(visitor, batch_model=ConversionBatch, work_attr=None)
        self.assertEqual([], [r['obj'].pk for r in rows],
                         'un visiteur héritait des lots publics de tout le parc')


class NoDroppedFileLeavesThePageTest(SimpleTestCase):
    """La garde de PAGE de `wama-app-base.js` (un fichier lâché hors d'une zone n'est pas ouvert
    par le navigateur), jouée en V8 sur le fichier SERVI : elle était écrite dans la seule page de
    l'anonymizer, avec un `stopPropagation` sur `body`."""

    def _handlers(self):
        from pathlib import Path

        from django.conf import settings
        from py_mini_racer import MiniRacer
        src = (Path(settings.BASE_DIR) / 'staticfiles/common/js/wama-app-base.js').read_text(
            encoding='utf-8')
        ctx = MiniRacer()
        ctx.eval("""
          var listeners = {};
          var window = {addEventListener: function (n, f) { (listeners[n] = listeners[n] || []).push(f); },
                        location: {pathname: '/'}, setTimeout: function () {}, setInterval: function () {}};
          var noop = function () {};
          var document = {addEventListener: noop, readyState: 'complete', body: {},
                          documentElement: {}, querySelector: function () { return null; },
                          querySelectorAll: function () { return []; },
                          getElementById: function () { return null; }};
          var global = window, localStorage = undefined, navigator = {};
          function event(types, prevented) {
            return {defaultPrevented: !!prevented, dataTransfer: {types: types}, called: false,
                    preventDefault: function () { this.called = true; }};
          }
        """)
        ctx.eval(src)
        return ctx

    def test_an_unhandled_file_drop_is_kept_from_the_browser_and_nothing_else(self):
        ctx = self._handlers()
        for name in ('dragover', 'drop'):
            with self.subTest(event=name):
                self.assertTrue(ctx.eval(f"""(function () {{ var e = event(['Files'], false);
                    listeners['{name}'].forEach(function (f) {{ f(e); }}); return e.called; }})()"""))
                self.assertFalse(ctx.eval(f"""(function () {{ var e = event(['text/plain'], false);
                    listeners['{name}'].forEach(function (f) {{ f(e); }}); return e.called; }})()"""),
                                 'un glisser qui n’est pas un fichier n’est pas touché')
                self.assertFalse(ctx.eval(f"""(function () {{ var e = event(['Files'], true);
                    e.called = false; listeners['{name}'].forEach(function (f) {{ f(e); }});
                    return e.called; }})()"""), 'une zone qui a pris le dépôt le garde')

    def test_no_app_keeps_its_own_page_guard(self):
        from pathlib import Path

        from django.conf import settings
        upload = (Path(settings.BASE_DIR) / 'wama/anonymizer/static/anonymizer/js/upload.js'
                  ).read_text(encoding='utf-8')
        self.assertNotIn('document.body.addEventListener', upload)
