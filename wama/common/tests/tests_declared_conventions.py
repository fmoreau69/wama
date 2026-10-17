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

from django.test import SimpleTestCase

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
        format de sortie EST son process (« devrait être N/A », relevé le 2026-08-17)."""
        states = {a: checker._output_settings(checker._AppFiles(a))[0] for a in REAL_APPS}
        self.assertEqual({'anonymizer': True, 'avatarizer': None, 'composer': True, 'converter': None,
                          'describer': None, 'enhancer': True, 'imager': True, 'reader': None,
                          'synthesizer': True, 'transcriber': None}, states)


class SettingsProfilesCriterionTest(SimpleTestCase):
    def test_only_the_converter_offers_profiles_today_and_it_is_optional_elsewhere(self):
        """État au 2026-10-16 ; le portage au commun (`ROADMAP §22.5`) fera changer ce test —
        c'est voulu : il dit ce qui EST, la feuille de route dit ce qui vient."""
        states = {a: checker._settings_profiles(checker._AppFiles(a))[0] for a in REAL_APPS}
        self.assertEqual({a: (True if a == 'converter' else None) for a in REAL_APPS}, states)
