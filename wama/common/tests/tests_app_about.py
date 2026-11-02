"""« À PROPOS » et « AIDE » of every app — DECLARED once, DERIVED for the rest (2026-11-02, Fabien's
request : « Les "À propos" et "Aide" de toutes les applications sont à revérifier […] le corps
pourrait aussi se mettre à jour en fonction des déclarations des modèles utilisés »).

Measured before : the ten apps and the two Lab apps rewrote both tabs in HTML (≈ 2000 lines) and
recopied their models in it — retired models were still presented (imager).

What is held :
  1. no app template rewrites these tabs (`about_content`, `help_content`, `about_models`) ;
  2. every app of the catalogue and every Lab app DECLARES its summary and features
     (`common/app_about.ABOUT`), and every line it cites (`# verified:`) names a file that exists ;
  3. no declaration and no catalogue description names a model of the catalogue — the engines
     are DERIVED (`app_about.engines`, the reading of « Modèles et publications ») ;
  4. the fragments : the About tab shows the declared summary, the derived facts and the ORIGIN
     — a sandbox app names ALL its developers (Fabien's decision, same day) — ; a closed app is
     not readable ; the Help tab shows the app's own help after the common gestures ;
  5. the developers of a sandbox app : whoever regenerates it joins them, and the access rule
     reads them all.
"""
import json
import re
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from wama.common import app_about

ROOT = Path(settings.BASE_DIR)
LAB_APPS = ('cam_analyzer', 'face_analyzer')
OVERRIDDEN = re.compile(r'{%-?\s*block\s+(about_content|help_content|about_models)\b')


def _real_apps():
    from wama.common.app_registry import APP_CATALOG
    return sorted(a for a, spec in APP_CATALOG.items() if not (spec or {}).get('sandbox'))


class NoAppRewritesTheTabsTest(SimpleTestCase):

    def test_no_versioned_app_template_overrides_about_or_help(self):
        from wama.common.sandbox import LABEL_RE
        offenders = []
        for base in ('wama', 'wama_lab'):
            for path in (ROOT / base).rglob('templates/**/*.html'):
                rel = path.relative_to(ROOT).as_posix()
                if LABEL_RE.match(path.relative_to(ROOT / base).parts[0]) or '/common/templates/' in rel:
                    continue                 # a twin is generated ; the common template defines them
                if OVERRIDDEN.search(path.read_text(encoding='utf-8', errors='replace')):
                    offenders.append(rel)
        self.assertEqual([], offenders, 'un onglet se DÉCLARE dans common/app_about.py')


class EveryAppStatesItsAboutTest(SimpleTestCase):

    def test_every_app_and_lab_app_has_a_summary_and_features(self):
        for app in _real_apps() + list(LAB_APPS):
            with self.subTest(app=app):
                mine = app_about.ABOUT.get(app) or {}
                self.assertTrue(mine.get('summary'))
                self.assertGreaterEqual(len(mine.get('features') or ()), 3)
                for item in list(mine.get('features') or ()) + list(mine.get('help') or ()):
                    self.assertEqual({'title', 'text'}, set(item))

    def test_every_cited_line_names_a_file_that_exists(self):
        source = (ROOT / 'wama' / 'common' / 'app_about.py').read_text(encoding='utf-8')
        cited = re.findall(r'verified: ([\w/.\-]+\.(?:py|html|js|md))', source)
        self.assertGreater(len(cited), 100)
        self.assertEqual([], sorted({c for c in cited if not (ROOT / c).is_file()}))

    def test_the_long_description_is_the_declared_summary(self):
        from wama.common.app_registry import APP_CATALOG
        for app in _real_apps():
            with self.subTest(app=app):
                self.assertEqual(app_about.ABOUT[app]['summary'], APP_CATALOG[app]['description_long'])


#: Names of catalogue models that are also ordinary words of the declarations' language : a feature
#: « coupe et fusion au clavier » is not the model `fusion`.
COMMON_WORDS = {'fusion'}


def _catalogue_model_names() -> set:
    """The names of the catalogue's models, from their VERSIONED manifests — short forms of 5
    characters or more (`app_about.short_name`), lower case."""
    names = set()
    for path in (ROOT / 'manifests' / 'models').glob('*.json'):
        data = json.loads(path.read_text(encoding='utf-8'))
        for value in (data.get('name'), (data.get('key') or '').split(':')[-1]):
            short = app_about.short_name(value or '').strip().lower()
            if len(short) >= 5 and not short.isdigit() and short not in COMMON_WORDS:
                names.add(short)
    return names


class NoDeclarationNamesAModelTest(SimpleTestCase):

    def test_no_declared_or_catalogue_text_cites_a_model_of_the_catalogue(self):
        from wama.common.app_registry import APP_CATALOG
        names = _catalogue_model_names()
        self.assertGreater(len(names), 50, 'the catalogue corpus is read')
        texts = []
        for app, mine in app_about.ABOUT.items():
            texts.append((app, mine.get('summary') or ''))
            texts += [(app, f"{i['title']} {i['text']}") for i in
                      list(mine.get('features') or ()) + list(mine.get('help') or ())]
        texts += [(app, spec.get('description') or '') for app, spec in APP_CATALOG.items()
                  if not (spec or {}).get('sandbox')]
        found = sorted({(app, n) for app, text in texts for n in names
                        if re.search(r'(?<![\w-])' + re.escape(n) + r'(?![\w-])', text.lower())})
        self.assertEqual([], found, 'un moteur se DÉRIVE du catalogue, il ne s\'écrit pas')

    def test_a_short_name_keeps_what_a_chip_can_show(self):
        self.assertEqual('Qwen Image 2 (20B)', app_about.short_name('Qwen Image 2 (20B) — #1 open source'))
        self.assertEqual('chandra-ocr-2-GGUF',
                         app_about.short_name('hf.co/SandLogicTechnologies/chandra-ocr-2-GGUF:Q6_K'))


def _account(name, tier='utilisateur', role=''):
    from django.contrib.auth.models import Group
    from wama.accounts.models import UserProfile
    from wama.accounts.permissions import GROUP_PREFIX
    user = get_user_model().objects.create_user(name, password='x', first_name=name.title())
    UserProfile.objects.update_or_create(user=user, defaults={'account_tier': tier})
    if role:
        user.groups.add(Group.objects.get_or_create(name=GROUP_PREFIX + role)[0])
    return get_user_model().objects.get(pk=user.pk)


class FragmentsTest(TestCase):

    def setUp(self):
        self.user = _account('about_reader', role='recherche')

    def test_the_about_tab_shows_the_declaration_and_the_derived_facts(self):
        self.client.force_login(self.user)
        groups = [{'label': 'Modèle de transcription',
                   'models': [{'name': 'Moteur Témoin — longue description', 'key': 'x',
                               'description': '', 'platform_url': '', 'publications': []}]}]
        with mock.patch('wama.common.services.model_publications.app_models', return_value=groups):
            page = self.client.get(reverse('common:app_about', args=['transcriber'])).content.decode()
        from django.utils.html import escape
        self.assertIn(escape(app_about.ABOUT['transcriber']['summary']), page)
        self.assertIn(escape(app_about.ABOUT['transcriber']['features'][0]['title']), page)
        # The derived engine, as a CHIP of the body (short name) — the full name also appears in
        # « Modèles et publications » below, which must not make this check pass on its own.
        self.assertIn('data-about-engines', page)
        self.assertIn('<i class="fas fa-microchip"></i>Moteur Témoin</span>', page)
        self.assertIn('Application de WAMA', page)
        self.assertIn('Modèles et publications', page)             # the full list follows

    def test_a_closed_app_is_not_readable(self):
        self.client.force_login(_account('about_plain'))
        with mock.patch('wama.accounts.permissions.accessible', return_value=False):
            self.assertEqual(404, self.client.get(reverse('common:app_about', args=['imager'])).status_code)
            self.assertEqual(404, self.client.get(reverse('common:app_help', args=['imager'])).status_code)

    def test_the_help_tab_shows_the_own_help_then_the_common_gestures(self):
        self.client.force_login(self.user)
        from django.utils.html import escape
        page = self.client.get(reverse('common:app_help', args=['transcriber'])).content.decode()
        self.assertIn(escape(app_about.ABOUT['transcriber']['help'][0]['title']), page)
        self.assertIn('Les gestes communs', page)
        self.assertIn('menu « … » les réaligne', page)            # batches : the transcriber has them

    def test_a_lab_app_and_a_twin_read_their_declaration(self):
        # The world is READ (app_identity) and named by its declared label, never cited here.
        from wama.common.app_registry import app_world, world_label
        self.assertEqual(world_label(app_world('face_analyzer')), app_about.origin('face_analyzer')['world'])
        self.assertNotEqual(app_about.origin('face_analyzer')['world'], app_about.origin('transcriber')['world'])
        self.assertTrue(app_about.about_facts('face_analyzer', groups=[])['links'])
        from wama.common.app_registry import APP_CATALOG
        with mock.patch.dict(APP_CATALOG, {'reader_42': {**APP_CATALOG['reader'], 'sandbox': True,
                                                         'generated_from': 'reader'}}):
            self.assertEqual('reader', app_about.declaration_key('reader_42'))
            self.assertEqual(app_about.ABOUT['reader']['features'],
                             app_about.about_facts('reader_42', groups=[])['features'])


class TheRealRegistryIsNeverWrittenByATestTest(SimpleTestCase):
    """2026-11-02, vécu : un test qui simulait la LECTURE du registre des bacs à sable, pas son
    ÉCRITURE, a remplacé le vrai `wama/sandbox_apps.json` par ses lignes témoins. Le « vrai »
    registre est ici un fichier JETABLE (`_REAL_REGISTRY_PATH` redirigé) : la garde se prouve
    sans jamais exposer le vrai fichier."""

    def test_the_real_registry_rejects_a_write_a_redirected_one_takes_it(self):
        import tempfile
        from wama.common import sandbox
        with tempfile.TemporaryDirectory() as tmp:
            real, other = Path(tmp) / 'real.json', Path(tmp) / 'other.json'
            real.write_text('[]', encoding='utf-8')
            with mock.patch.object(sandbox, '_REAL_REGISTRY_PATH', real), \
                    mock.patch.object(sandbox, 'REGISTRY_PATH', real):
                with self.assertRaises(PermissionError):
                    sandbox.save_registry([{'label': 'x_01'}])
            self.assertEqual('[]', real.read_text(encoding='utf-8'), 'left untouched')
            with mock.patch.object(sandbox, '_REAL_REGISTRY_PATH', real), \
                    mock.patch.object(sandbox, 'REGISTRY_PATH', other):
                sandbox.save_registry([{'label': 'x_01'}])
            self.assertIn('x_01', other.read_text(encoding='utf-8'))


class SandboxDevelopersTest(TestCase):
    """« Si plusieurs utilisateurs participent à la génération d'une application, l'ensemble des
    utilisateurs doit apparaître » (Fabien, 2026-11-02)."""

    def setUp(self):
        self.registry = [{'label': 'notes_01', 'generated_from': '', 'created_by': 'about_dev_a'}]
        writes = []

        def save(entries):
            self.registry = [dict(e) for e in entries]
            writes.append(entries)
        for patch in (mock.patch('wama.common.sandbox.load_registry',
                                 side_effect=lambda: [dict(e) for e in self.registry]),
                      mock.patch('wama.common.sandbox.save_registry', side_effect=save)):
            patch.start()
            self.addCleanup(patch.stop)
        self.writes = writes
        self.dev_a = _account('about_dev_a', 'developpeur')
        self.dev_b = _account('about_dev_b', 'developpeur')

    def test_whoever_takes_part_joins_the_developers_once(self):
        from wama.common.sandbox import app_contributors, record_contributor
        self.assertTrue(record_contributor('notes_01', 'about_dev_b'))
        self.assertFalse(record_contributor('notes_01', 'about_dev_b'), 'once')
        self.assertFalse(record_contributor('notes_01', ''), 'nobody')
        self.assertEqual(['about_dev_a', 'about_dev_b'], app_contributors('notes_01'))

    def test_the_access_rule_and_the_about_tab_read_all_of_them(self):
        from wama.accounts.app_access import can_grant, sandbox_decision, sandbox_owners
        from wama.common.sandbox import record_contributor
        owners = sandbox_owners()
        self.assertFalse(sandbox_decision(self.dev_b, 'notes_01', owners, set()))
        record_contributor('notes_01', 'about_dev_b')
        owners = sandbox_owners()
        self.assertTrue(sandbox_decision(self.dev_b, 'notes_01', owners, set()))
        self.assertTrue(can_grant(self.dev_b, 'notes_01'))
        from wama.common.app_registry import APP_CATALOG
        with mock.patch.dict(APP_CATALOG, {'notes_01': {'label': 'Notes', 'sandbox': True}}):
            self.assertEqual(['About_Dev_A', 'About_Dev_B'], app_about.origin('notes_01')['developers'])

    def test_regenerating_through_the_assistant_records_the_developer(self):
        from wama.common.services import dev_tools
        from wama.common.sandbox import app_contributors
        admin = _account('about_admin', 'admin')
        with mock.patch.object(dev_tools, 'start_job', return_value={'job_id': 'x'}):
            dev_tools.dev_sandbox(admin, 'substitute', app='notes_01', target='params')
            refused = dev_tools.dev_sandbox(self.dev_b, 'substitute', app='notes_01', target='params')
        self.assertEqual('forbidden', refused.get('error'), 'not one of its developers')
        self.assertEqual(['about_dev_a', 'about_admin'], app_contributors('notes_01'))
