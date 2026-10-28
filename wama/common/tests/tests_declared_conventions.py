"""Plus aucun booléen de conformité écrit à la main que rien ne mesure (2026-10-16).

Demande de Fabien : *« peux-tu poursuivre sur ce qui est écrit à la main »*. La page `/apps/`
additionne aux critères mesurés les clés DÉCLARÉES de `_conv(...)` que rien ne mesure ; il en
restait huit qui comptaient dans le score — cinq boutons, `multi_format_download`,
`cross_app_options`, `save_profile` —, et deux d'entre elles mentaient ailleurs (`eta_batch`
la veille, `cross_app_options` au converter). Chacune est désormais MESURÉE : sous son nom, par le
mécanisme d'un critère, ou par un critère qui la COUVRE (`covers`). Restent des DONNÉES déclarées,
non comptées (`export_binding`, `export_formats`) : elles décrivent l'app, elles ne la jugent pas.
"""
from pathlib import Path
from unittest.mock import patch

from django.test import SimpleTestCase, TestCase

from wama.common import app_registry
from wama.common.services import conformity_checker as checker

REAL_APPS = sorted(a for a, s in app_registry.APP_CATALOG.items() if not s.get('sandbox'))


def _measured_keys():
    return ({c.key for c in checker.CRITERIA}
            | {c.mechanism for c in checker.CRITERIA if c.mechanism}
            | {k for c in checker.CRITERIA for k in c.covers})


class NoHandWrittenConformityTest(SimpleTestCase):

    def test_every_scored_declared_key_is_measured(self):
        """Une clé déclarée qui COMPTE (booléen ou « partiel ») doit être mesurée — sinon la page
        affiche une affirmation que rien ne vérifie. Le remède n'est jamais d'ajouter une
        exemption ici : on écrit le critère, ou on déclare ce qu'il couvre (`covers`)."""
        unmeasured = {}
        for app in REAL_APPS:
            for key, value in (app_registry.APP_CATALOG[app].get('conventions') or {}).items():
                if (isinstance(value, bool) or value == 'partial') and key not in _measured_keys():
                    unmeasured.setdefault(key, []).append(app)
        self.assertEqual({}, unmeasured)

    def test_a_covered_key_names_a_real_declared_key(self):
        """Contre-épreuve de forme : un `covers` mal orthographié rendrait la liaison inerte."""
        declared = set(app_registry._conv())
        typos = {c.key: k for c in checker.CRITERIA for k in c.covers if k not in declared}
        self.assertEqual({}, typos)

    def test_the_page_ignores_a_declared_key_a_criterion_covers(self):
        catalog = {'appx': {'conventions': {'download_btn': False}}}
        data = {'apps': {'appx': {'conv': {'download_wiring': True}}},
                'criteria': {'download_wiring': {'covers': ['download_btn']}}, 'generated_at': 'now'}
        with patch.object(app_registry, 'APP_CATALOG', catalog), \
                patch.dict(app_registry._CONFORMITY_REPORT, {'data': data, 'mtime': 1.0}), \
                patch('pathlib.Path.stat', return_value=type('S', (), {'st_mtime': 1.0})()):
            s = app_registry.get_conformity_summary()['appx']
        self.assertEqual((100, []), (s['pct'], s['issues']))


class MultiFormatDownloadIsDerivedTest(SimpleTestCase):
    def test_it_says_what_the_download_button_brick_renders(self):
        """La règle est CELLE de la brique ⬇ (formats déclarés → menu, aucun → lien), lue ici
        sur son rendu — pas une seconde règle écrite à côté (revérification du 2026-10-17 : la
        dérivation disait « plus d'un format », la brique « au moins un »)."""
        from django.template.loader import render_to_string

        from wama.common.utils.export_formats import entries
        for formats in ((), ('txt',), ('txt', 'pdf')):
            html = render_to_string('common/_download_button.html',
                                    {'url': '/x/', 'ready': True, 'formats': entries(formats)})
            menu = 'dropdown' in html
            derived = app_registry._conv(export_formats=formats)['multi_format_download']
            self.assertEqual(menu, bool(derived), formats)


class OutputSettingsCriterionTest(SimpleTestCase):
    """`output_settings` (ex-`cross_app_options`) : réglages de sortie COMMUNS déclarés ⇒ process
    « Sortie » commun. Applicabilité lue au schéma, jamais au nom de l'app."""

    def _fake(self, tmp, params, specs):
        (tmp / 'params.py').write_text(params, encoding='utf-8')
        (tmp / 'function_specs.py').write_text(specs, encoding='utf-8')
        files = checker._AppFiles('fake')
        files.root = tmp
        return files

    def test_declared_without_the_output_process_is_red_and_nothing_declared_is_not_applicable(self):
        import tempfile
        for params, specs, expected in (
                ("P = output_format_params('image')\n", "PIPELINE = [render_spec()]\n", False),
                ("P = output_format_params('image')\n", "PIPELINE = [output_spec(depends_on=('r',))]\n", True),
                ("C = get_output_formats('video')\n", "PIPELINE = [output_spec()]\n", True),
                ("# output_format_params('image') raconté\nP = []\n", "PIPELINE = []\n", None)):
            with tempfile.TemporaryDirectory() as d:
                state, _ = checker._output_settings(self._fake(Path(d), params, specs))
            self.assertIs(state, expected, (params, specs))

    def test_on_the_ten_apps_it_agrees_with_what_was_declared_except_the_converter(self):
        """Le déclaré disait vrai pour cinq apps ; le converter était déclaré vrai alors que son
        format de sortie EST son process (« devrait être N/A », relevé le 2026-08-17). L'avatarizer
        est passé de « sans objet » à VRAI le 2026-10-28 (D5 : format et qualité de sortie, au
        process « Visage et sortie » déclaré par `output_spec`)."""
        states = {a: checker._output_settings(checker._AppFiles(a))[0] for a in REAL_APPS}
        self.assertEqual({'anonymizer': True, 'avatarizer': True, 'composer': True, 'converter': None,
                          'describer': None, 'enhancer': True, 'imager': True, 'reader': None,
                          'synthesizer': True, 'transcriber': None}, states)


class SettingsProfilesCriterionTest(SimpleTestCase):
    def test_only_the_converter_offers_profiles_today_and_it_is_optional_elsewhere(self):
        """État au 2026-10-16 ; le portage au commun (`ROADMAP §22.5`) fera changer ce test —
        c'est voulu : il dit ce qui EST, la feuille de route dit ce qui vient."""
        states = {a: checker._settings_profiles(checker._AppFiles(a))[0] for a in REAL_APPS}
        self.assertEqual({a: (True if a == 'converter' else None) for a in REAL_APPS}, states)


class ConventionCriteriaTest(SimpleTestCase):
    """Les quatre conventions que les dix apps tenaient sans critère (2026-10-17, une fois le
    balayage d'adoption corrigé) : chacune ROUGIT sur une fausse app qui s'en écarte."""

    def _fake(self, tmp, files):
        for rel, text in files.items():
            path = tmp / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding='utf-8')
        app = checker._AppFiles('fake')
        app.root = tmp
        return app

    def _state(self, fn, files):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            return fn(self._fake(Path(d), files))[0]

    def test_each_convention_turns_red_when_an_app_departs_from_it(self):
        cases = (
            (checker._pipeline_declared, {'function_specs.py': 'PIPELINE = register_app_pipeline(_APP, ())\n'}, True),
            (checker._pipeline_declared, {'function_specs.py': '# register_app_pipeline( raconté\n'}, False),
            (checker._media_paths, {'models.py': "f = FileField(upload_to=upload_to_user_input('x'))\n"}, True),
            (checker._media_paths, {'models.py': "f = FileField(upload_to='x/input/')\n"}, False),
            (checker._media_paths, {'models.py': 'class A: pass\n'}, None),
            (checker._static_versioning, {'templates/x/index.html': "{% static_v 'x/js/i.js' %}"}, True),
            (checker._static_versioning, {'templates/x/index.html': "{% static 'x/js/i.js' %}"}, False),
            (checker._fm_notify, {'templates/x/index.html': "{% include 'common/_global_progress.html' %}",
                                  'static/x/i.js': '// WamaFM.processed() raconté\n'}, True),
            (checker._fm_notify, {'templates/x/index.html': "{% include 'common/_global_progress.html' %}",
                                  'static/x/i.js': 'if (window.WamaFM) WamaFM.processed();\n'}, False),
        )
        for fn, files, expected in cases:
            with self.subTest(fn=fn.__name__, files=files):
                self.assertIs(self._state(fn, files), expected)

    def test_queue_actions_turn_red_when_the_bar_is_wired_by_the_app(self):
        """▶ / 🗑 de FILE (2026-10-17) : `start_all`/`clear_all` ne lisaient que la route, verts
        10/10 sur dix handlers recopiés. Chaque écart du câblage commun doit rougir."""
        bar = ("{% include 'common/_queue_toolbar.html' with q_sort=q_sort start_id='go' "
               "clear_id='wipe' download_id='dl' show_download=True ARGS %}")
        urls = ("{% url 'x:start_all' as q_start_url %}{% url 'x:clear_all' as q_clear_url %}"
                "{% url 'x:download_all' as q_download_url %}")
        wired = "app='x' start_url=q_start_url clear_url=q_clear_url download_url=q_download_url"
        page = urls + bar.replace('ARGS', wired)
        piece = ("{% include 'common/_queue.html' with app='x' queue_id='xq' batches=batches_list "
                 "card_template='x/_c.html' %}")
        cases = (
            ({'templates/x/index.html': urls + bar.replace('ARGS', '')}, False),
            ({'templates/x/index.html': bar.replace('ARGS', wired)}, False),     # variables jamais posées
            ({'templates/x/index.html': page}, True),
            ({'templates/x/index.html': page.replace(' download_url=q_download_url', '')}, False),
            ({'templates/x/index.html': page.replace("app='x' ", '')}, False),  # ⬇ sans formats déclarés
            ({'templates/x/index.html': page.replace('show_download=True', 'show_download=False')
              .replace(' download_url=q_download_url', '')}, True),             # pas de ⬇ : rien à exiger
            ({'templates/x/index.html': page,
              'static/x/i.js': "document.getElementById('go').addEventListener('click', f);\n"}, 'partial'),
            ({'templates/x/index.html': page,
              'static/x/i.js': "document.getElementById('dl').disabled = !ok;\n"}, 'partial'),
            ({'templates/x/index.html': page,
              'static/x/i.js': "WamaGlobalProgress.init({ url: u, download: 'dl' });\n"}, True),
            ({'templates/x/index.html': page,
              'static/x/i.js': "// l'ancien handler de 'go' est retiré\n"}, True),
            ({'templates/x/index.html': '<p>pas de file</p>'}, None),
            # La FILE commune (2026-10-20) dérive ses URLs ; reste qu'aucun JS n'en lise les ids.
            ({'templates/x/index.html': piece}, True),
            ({'templates/x/index.html': piece,
              'static/x/i.js': "document.getElementById('xq-clear-all').onclick = f;\n"}, 'partial'),
            ({'templates/x/index.html': piece,
              'static/x/i.js': "WamaGlobalProgress.init({ url: u, download: 'xq-download-all' });\n"}, True),
        )
        for files, expected in cases:
            with self.subTest(files=files):
                self.assertEqual(expected, self._state(checker._queue_actions_common, files))

    def test_the_ten_apps_wire_their_queue_bars_through_the_brick(self):
        self.assertEqual({a: True for a in REAL_APPS},
                         {a: checker._queue_actions_common(checker._AppFiles(a))[0] for a in REAL_APPS})

    def test_the_ten_apps_hold_the_four_conventions(self):
        for fn in (checker._pipeline_declared, checker._media_paths, checker._static_versioning,
                   checker._fm_notify):
            with self.subTest(fn=fn.__name__):
                self.assertEqual({a: True for a in REAL_APPS},
                                 {a: fn(checker._AppFiles(a))[0] for a in REAL_APPS})


class QueueBarRenderedWiringTest(TestCase):
    """Sur la page RENDUE de chaque app, chaque ▶ et 🗑 de file porte l'URL que lit la brique
    (2026-10-17). Le critère `queue_actions_common` lit le gabarit ; ici on lit ce que reçoit le
    navigateur — un `{% url … as %}` posé hors du bloc de la barre rendrait l'attribut VIDE."""

    def test_every_queue_bar_of_every_app_page_carries_its_three_urls(self):
        import re

        from django.urls import resolve, reverse

        from wama.common.tests.tests_endpoints import EveryEndpointAnswersTest
        # Chaque bouton se lit à partir du DÉBUT de sa barre : le ⬇ peut être un menu
        # (`_download_button`) avec ses propres `</div>`, qui couperait un motif « jusqu'au </div> ».
        opening = '<div class="d-flex gap-2 flex-wrap wama-queue-actions">'
        buttons = (('data-queue-start-url', 'start_all', 'btn btn-success btn-sm'),
                   ('data-queue-clear-url', 'clear_all', 'btn btn-outline-danger btn-sm'))
        seen, wrong = {}, []
        for app in REAL_APPS:
            self.client.force_login(EveryEndpointAnswersTest._account_for(self, app))
            response = self.client.get(reverse(f'{app}:index'))
            self.assertEqual(200, response.status_code, app)
            page = response.content.decode('utf-8', errors='replace')
            starts = [m.end() for m in re.finditer(re.escape(opening), page)]
            seen[app] = len(starts)
            for at in starts:
                for attr, route, css in buttons:
                    tag = re.compile(r'<button id="[^"]*" class="' + css + r'"([^>]*)>').search(page, at)
                    m = tag and re.search(attr + r'="([^"]+)"', tag.group(1))
                    name = resolve(m.group(1)).url_name if m else None
                    if not (name and route in name):
                        wrong.append(f'{app} : {attr} = {m.group(1) if m else "absent"}')
                # ⬇ : la brique (`data-queue-download`), avant le 🗑, et son lien (direct ou premier
                # format du menu) mène à la route `download_all` de la file.
                clear_at = page.find('btn btn-outline-danger btn-sm', at)
                marker = page.find('data-queue-download', at, clear_at)
                href = re.compile(r'href="([^"?]+)').search(page, marker) if marker >= 0 else None
                name = resolve(href.group(1)).url_name if href and href.start() < clear_at else None
                if not (name and 'download_all' in name):
                    wrong.append(f'{app} : ⬇ = {"brique absente" if marker < 0 else href and href.group(1)}')
        self.assertEqual({a: n for a, n in seen.items() if n}, seen, 'une page sans barre de file')
        self.assertEqual([], wrong)
