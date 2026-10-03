"""The LIFE CYCLE of an element through its views — ONE contract, every app.

Contract 2 of `WAMA_VERIFICATION §8` (2026-09-26); the ownership half lives in
`tests_endpoints.AnotherUsersElementTest`. Only `synthesizer/tests.py` checked this, for itself.
For every app of the catalogue, on a witness element built by the generic factory:

  * ▶ `<app>:start` (task dispatch mocked) either starts it — RUNNING and a task id recorded —
    or REFUSES it by saying so (4xx with a message), never a silent 200 that changes nothing;
  * `<app>:progress` answers JSON the queue can read.
"""
import json
from unittest import mock

from django.test import TestCase
from django.urls import NoReverseMatch, reverse

from wama.common.tests.tests_queue_delete_contract import _instance


def _surfaces(route):
    from wama.common.app_registry import APP_CATALOG
    from wama.common.sandbox import twins_with_copied_views
    from wama.common.utils.preview_registry import PreviewRegistry
    copied = twins_with_copied_views()
    out = []
    for app, spec in APP_CATALOG.items():
        if app in copied or (spec or {}).get('sandbox'):
            continue
        try:
            reverse(f'{app}:{route}', args=[1])
        except NoReverseMatch:
            continue
        model = PreviewRegistry.get_model(app)
        if model is not None:
            out.append((app, model))
    return out


class ItemLifecycleContractTest(TestCase):

    def _login_for(self, app):
        from wama.common.tests.tests_endpoints import EveryEndpointAnswersTest
        user = EveryEndpointAnswersTest._account_for(self, app)
        self.client.force_login(user)
        return user

    def test_start_starts_or_says_why_not(self):
        surfaces = _surfaces('start')
        self.assertGreaterEqual(len(surfaces), 8, [a for a, _ in surfaces])
        started, refused = [], []
        for app, model in surfaces:
            with self.subTest(app=app):
                item = _instance(model, self._login_for(app))
                with mock.patch('celery.app.task.Task.apply_async',
                                return_value=mock.Mock(id='tache-de-test')) as dispatch:
                    r = self.client.post(reverse(f'{app}:start', args=[item.pk]))
                item.refresh_from_db()
                if r.status_code == 200 and dispatch.called:
                    self.assertEqual('RUNNING', getattr(item, 'status', 'RUNNING'))
                    if hasattr(item, 'task_id'):
                        self.assertEqual('tache-de-test', item.task_id, 'task id not recorded')
                    started.append(app)
                else:
                    refused.append(f'{app} ({r.status_code})')
                    self.assertGreaterEqual(r.status_code, 400,
                                            f'200 without starting anything: {r.content[:200]!r}')
                    body = r.content.decode(errors='replace')
                    self.assertTrue(body.strip(), 'a refusal must say why')
        # Non-vacuity: a witness refused everywhere would make the contract a list of refusals.
        self.assertGreaterEqual(len(started), 5, f'started {started}, refused {refused}')

    #: Ce que rend le suivi d'UNE card, dans toutes les apps (fabrique `progress_views`, 2026-10-03).
    ITEM_KEYS = {'id', 'status', 'progress', 'error', 'error_message'}
    #: Apps pas encore passées sur la fabrique — une liste qui ne peut que DESCENDRE.
    #: Vide depuis le 2026-10-03 (soir) : le composer, dernier exempté, est passé sur la fabrique.
    NOT_YET_ON_THE_FACTORY = {}
    #: Le contrat de la barre de file (`wama-global-progress.js`), au vocabulaire COMPLET.
    QUEUE_KEYS = {'total', 'pending', 'running', 'success', 'failure', 'done', 'failed',
                  'overall_progress'}

    def test_progress_answers_json_the_queue_can_read(self):
        # `status` : la graphie du converter pour le suivi d'une card (`urls_gen.ROUTE_ALIASES`).
        surfaces = [(app, model, route) for route in ('progress', 'status')
                    for app, model in _surfaces(route)]
        self.assertGreaterEqual(len({a for a, _, _ in surfaces}), 9, surfaces)
        for app, model, route in surfaces:
            with self.subTest(app=app, route=route):
                item = _instance(model, self._login_for(app))
                r = self.client.get(reverse(f'{app}:{route}', args=[item.pk]))
                self.assertEqual(200, r.status_code, r.content[:200])
                data = json.loads(r.content)
                keys = (self.ITEM_KEYS if app not in self.NOT_YET_ON_THE_FACTORY
                        else {'progress', 'status'})
                self.assertLessEqual(keys, set(data), data)

    def test_a_page_that_shows_the_queue_bar_loads_the_component_that_feeds_it(self):
        """Le partial `_global_progress.html` sans `wama-global-progress.js` est une barre MORTE,
        sans aucune erreur : l'anonymizer est resté figé à « 0/0 terminé » jusqu'au 2026-10-03
        (trouvé au smoke navigateur des vues de progression, pas par un test)."""
        from wama.common.app_registry import APP_CATALOG
        from wama.common.sandbox import twins_with_copied_views
        copied, seen = twins_with_copied_views(), []
        for app, spec in APP_CATALOG.items():
            if app in copied or (spec or {}).get('sandbox'):
                continue
            try:
                url = reverse(f'{app}:index')
            except NoReverseMatch:
                continue
            with self.subTest(app=app):
                self._login_for(app)
                html = self.client.get(url).content.decode(errors='replace')
                if 'id="globalProgressBar"' not in html:
                    continue
                self.assertIn('common/js/wama-global-progress.js', html,
                              f'{app} montre la barre de file sans charger son composant')
                seen.append(app)
        self.assertGreaterEqual(len(seen), 10, seen)

    #: Scripts qu'une page peut recevoir DEUX fois sans dommage — chacun avec sa raison.
    IDEMPOTENT_SCRIPTS = {
        'common/js/wama-new-item-card.js': "garde anti-double-init (`wama-new-item-card.js:21`) : "
                                           "porté par la card d'entrée, qui vit aussi HORS des "
                                           "apps (médiathèque), ET par le socle d'app",
        'common/js/wama-input-slots.js': "garde par card (`wama-input-slots.js:253`, "
                                         "`slotsWired`) : porté par la card v4, qu'une page "
                                         "pose deux fois quand l'app a deux files (enhancer, "
                                         "imager)",
    }

    def test_every_app_page_loads_the_common_app_scripts_once(self):
        """Le socle JS d'app (`_app_scripts.html`) adopté par les dix apps (ROUTE §11 #25,
        2026-10-03) — il était à 0/10 : chaque gabarit recopiait ses balises, l'anonymizer avait
        oublié celle de la barre de file, et sept scripts que `base.html` charge déjà étaient
        rechargés (deux exécutions = deux écouteurs : le défaut du player audio muet du 18/08).
        Une page d'app charge le socle, et aucun script commun deux fois."""
        import re
        from collections import Counter
        from pathlib import Path
        from django.conf import settings
        from wama.common.app_registry import APP_CATALOG
        from wama.common.sandbox import twins_with_copied_views
        core = ('wama-params.js', 'wama-eta.js', 'batch-import.js', 'wama-new-item-card.js',
                'wama-import.js', 'wama-global-progress.js')
        copied, seen = twins_with_copied_views(), []
        for app, spec in APP_CATALOG.items():
            if app in copied or (spec or {}).get('sandbox'):
                continue
            source = Path(settings.BASE_DIR) / 'wama' / app / 'templates' / app / 'index.html'
            if not source.exists():
                continue
            with self.subTest(app=app):
                self.assertIn("include 'common/_app_scripts.html'",
                              source.read_text(encoding='utf-8'), f'{app} recopie ses balises')
                self._login_for(app)
                html = self.client.get(reverse(f'{app}:index')).content.decode(errors='replace')
                loaded = Counter(re.findall(r'<script src="[^"]*?/static/(common/js/[\w.-]+\.js)',
                                            html))
                for name in core:
                    self.assertIn(f'common/js/{name}', loaded, f'{app} : {name} absent')
                twice = {s: n for s, n in loaded.items()
                         if n > 1 and s not in self.IDEMPOTENT_SCRIPTS}
                self.assertEqual({}, twice, f'{app} charge des scripts communs plusieurs fois')
                seen.append(app)
        self.assertGreaterEqual(len(seen), 10, seen)

    def test_an_exemption_from_the_factory_is_still_needed(self):
        from pathlib import Path
        from django.conf import settings
        for app in self.NOT_YET_ON_THE_FACTORY:
            with self.subTest(app=app):
                views = (Path(settings.BASE_DIR) / 'wama' / app / 'views.py').read_text(
                    encoding='utf-8')
                self.assertNotIn('make_progress_views(', views,
                                 f'{app} est sur la fabrique : retirer son exemption')

    def test_the_queue_bar_speaks_the_full_contract_in_every_app(self):
        """Dix barres de file, trois formules et quatre vocabulaires jusqu'au 2026-10-03 (le JS
        commun acceptait toutes les graphies) — une seule fabrique depuis (ROUTE §11 #37)."""
        from wama.common.app_registry import APP_CATALOG
        from wama.common.sandbox import twins_with_copied_views
        copied, seen = twins_with_copied_views(), []
        for app, spec in APP_CATALOG.items():
            if app in copied or (spec or {}).get('sandbox'):
                continue
            for route in ('global_progress', 'audio_global_progress'):
                try:
                    url = reverse(f'{app}:{route}')
                except NoReverseMatch:
                    continue
                with self.subTest(app=app, route=route):
                    self._login_for(app)
                    data = json.loads(self.client.get(url).content)
                    keys = (self.QUEUE_KEYS if app not in self.NOT_YET_ON_THE_FACTORY
                            else {'total', 'done', 'overall_progress'})
                    # Une barre PAR DOMAINE (imager : image, vidéo) porte le contrat dans chacun.
                    for part in [data] + [v for v in data.values() if isinstance(v, dict)]:
                        self.assertLessEqual(keys, set(part), part)
                    seen.append(f'{app}:{route}')
        self.assertGreaterEqual(len(seen), 10, seen)
