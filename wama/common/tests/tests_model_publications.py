"""Publications of the models in the « About » tab (2026-10-10).

What had been started was hand-written « Publication » links in one app template; the models listed
in the About tabs were hand-written too, and age. Here everything comes from the catalogue: the
models are those of the app's catalogue selects, the publications those the author attaches to the
model card (`arxiv:<id>` tags), carried by the model manifest (`identity.publications`).
"""
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase

from wama.common.services import model_publications as mp
from wama.model_manager.models import AIModel
from wama.model_manager.services.provenance import arxiv_ids, set_identity


class ArxivTagsTest(TestCase):

    def test_the_card_tags_name_the_papers_in_order_without_duplicates(self):
        tags = ['transformers', 'arxiv:2601.14251', 'ocr', 'arxiv:2412.13663', 'arxiv:2601.14251']
        self.assertEqual(['2601.14251', '2412.13663'], arxiv_ids(tags))

    def test_a_tag_that_is_not_an_arxiv_identifier_is_ignored(self):
        self.assertEqual([], arxiv_ids(['arxiv:', 'arxiv:not-an-id', 'doi:10.1/x', 'license:mit']))


class PublicationsThroughTheManifestTest(TestCase):

    def setUp(self):
        self.row = AIModel.objects.create(
            model_key='huggingface:lightonai/LightOnOCR-3-1B', name='LightOnOCR-3-1B',
            model_type='ocr', source='huggingface', platform_ref='huggingface:lightonai/LightOnOCR-3-1B',
            extra_info={'weights': {'total_gb': 2.0}})

    def test_set_identity_projects_the_publications_and_keeps_the_rest_of_extra_info(self):
        res = set_identity(self.row.model_key, {'publications': ['2601.14251']}, export=False)
        self.assertIn('publications', res['posed'])
        self.row.refresh_from_db()
        self.assertEqual(['2601.14251'], self.row.extra_info['publications'])
        self.assertEqual({'total_gb': 2.0}, self.row.extra_info['weights'])

    def test_the_manifest_carries_them_once_under_identity(self):
        from wama.common.manifests.ingest import extract
        set_identity(self.row.model_key, {'publications': ['2601.14251']}, export=False)
        body = extract('model', self.row.model_key)['body']
        self.assertEqual(['2601.14251'], body['identity']['publications'])
        self.assertNotIn('publications', body['extra_info'])

    def test_an_empty_list_erases_nothing(self):
        # Counter-check: a card that says nothing does not remove what was known.
        set_identity(self.row.model_key, {'publications': ['2601.14251']}, export=False)
        set_identity(self.row.model_key, {'publications': [], 'license': 'apache-2.0'},
                     export=False)
        self.row.refresh_from_db()
        self.assertEqual(['2601.14251'], self.row.extra_info['publications'])

    def test_a_malformed_list_is_refused_by_the_manifest(self):
        from wama.common.manifests.builtin.model import validate_model_body
        self.assertTrue(validate_model_body({'identity': {'publications': 'x'}}))
        self.assertTrue(validate_model_body({'identity': {'publications': ['', 3]}}))
        self.assertEqual([], validate_model_body({'identity': {'publications': ['2601.14251']}}))


class AppModelsTest(TestCase):
    FIELD = {'name': 'model', 'label': 'Moteur', 'options_source': 'catalog',
             'options_query': {'source': 'reader', 'task': 'ocr'}}

    def setUp(self):
        AIModel.objects.create(model_key='reader:lighton', name='LightOnOCR', model_type='ocr',
                               source='reader', platform_ref='huggingface:lightonai/LightOnOCR-3-1B',
                               extra_info={'publications': ['2601.14251']})
        AIModel.objects.create(model_key='reader:doctr', name='docTR', model_type='ocr',
                               source='reader')

    def _groups(self, fields):
        choices = [('lighton', 'LightOnOCR'), ('doctr', 'docTR')]
        with patch('wama.common.utils.param_schema.schema_for_app', return_value=fields), \
                patch('wama.model_manager.services.get_registry_models',
                      return_value=(choices, [])):
            return mp.app_models('reader')

    def test_the_models_are_those_of_the_catalogue_select_with_their_papers(self):
        group, = self._groups([self.FIELD])
        self.assertEqual('Moteur', group['label'])
        lighton, doctr = group['models']
        self.assertEqual('https://arxiv.org/abs/2601.14251', lighton['publications'][0]['url'])
        self.assertEqual('https://huggingface.co/lightonai/LightOnOCR-3-1B', lighton['platform_url'])
        self.assertEqual([], doctr['publications'])

    def test_a_model_offered_by_two_selects_is_listed_once(self):
        groups = self._groups([self.FIELD, dict(self.FIELD, name='second', label='Second')])
        self.assertEqual(1, len(groups))

    def test_without_a_catalogue_select_the_app_lists_its_own_models(self):
        # Since 2026-10-10 (Lab apps): no catalogue select → the rows whose source is the app,
        # read from the app manifest's `models` facet (sorted by catalogue key).
        group, = self._groups([{'name': 'lang', 'options_source': 'static'}])
        self.assertEqual(('Modèles', ['docTR', 'LightOnOCR']),
                         (group['label'], [m['name'] for m in group['models']]))


class EveryDomainIsShownTest(TestCase):
    """2026-11-12: an app with several domains shows the models of ALL of them. The main schema
    alone left the imager's video models and the enhancer's audio engines out of « À propos »."""

    def setUp(self):
        AIModel.objects.create(model_key='reader:lighton', name='LightOnOCR', model_type='ocr',
                               source='reader')
        AIModel.objects.create(model_key='reader:doctr', name='docTR', model_type='ocr',
                               source='reader')

    def test_every_catalogue_select_of_every_declared_domain_is_read(self):
        # The contract, on the DECLARATIONS: no app named here, a new domain enters by itself.
        from wama.common.utils import app_modes
        from wama.common.utils.param_schema import _pget, catalog_choice_keys
        missing = []
        with patch('wama.model_manager.services.get_registry_models',
                   return_value=([('m', 'M')], [])):
            for app in app_modes.APP_MODES:
                read = {id(field) for field, _keys in catalog_choice_keys(app)}
                for domain in app_modes.get_domains(app):
                    for field in app_modes.domain_schema(app, domain['id']):
                        if _pget(field, 'options_source') == 'catalog' and id(field) not in read:
                            missing.append(f"{app}/{domain['id']}/{_pget(field, 'name')}")
        self.assertEqual([], missing)

    def _two_domains(self):
        first = {'name': 'model', 'label': 'Moteur', 'options_source': 'catalog',
                 'options_query': {'source': 'reader', 'task': 'first'}}
        second = {'name': 'model', 'label': 'Moteur', 'options_source': 'catalog',
                  'options_query': {'source': 'reader', 'task': 'second'}}
        domains = [{'id': 'a', 'label': 'Image', 'params_schema': 'A'},
                   {'id': 'b', 'label': 'Vidéo', 'params_schema': 'B'}]

        def registry(source, task=None, **_kw):
            return ([('lighton', 'LightOnOCR')] if task == 'first' else [('doctr', 'docTR')]), []

        return (patch('wama.common.utils.app_modes.get_domains', return_value=domains),
                patch('wama.common.utils.param_schema.schema_for_app', return_value=[first]),
                patch('wama.common.utils.param_schema.declared_param_schemas',
                      return_value={'schemas': {'A': [first], 'B': [second]}}),
                patch('wama.model_manager.services.get_registry_models', side_effect=registry))

    def test_each_domain_gets_its_own_group_named_after_it(self):
        a, b, c, d = self._two_domains()
        with a, b, c, d:
            groups = mp.app_models('reader')
        self.assertEqual([('Image — Moteur', ['LightOnOCR']), ('Vidéo — Moteur', ['docTR'])],
                         [(g['label'], [m['name'] for m in g['models']]) for g in groups])

    def test_the_page_of_one_domain_shows_its_models_only(self):
        """2026-11-12: « À propos » of the page of a domain does not mix models that have nothing
        in common — the question that opened the chantier."""
        a, b, c, d = self._two_domains()
        with a, b, c, d:
            groups = mp.app_models('reader', domain='b')
            whole = mp.app_models('reader')
        self.assertEqual([('Moteur', ['docTR'])],
                         [(g['label'], [m['name'] for m in g['models']]) for g in groups])
        self.assertEqual(2, len(whole), 'counter-check: without a domain, the whole app')

    def test_the_whole_app_reading_counts_a_shared_field_once(self):
        # The main schema and domain « a » hold the SAME field: read once, not twice.
        from wama.common.utils.param_schema import catalog_choice_keys
        a, b, c, d = self._two_domains()
        with a, b, c, d:
            whole = catalog_choice_keys('reader')
            only_b = catalog_choice_keys('reader', 'b')
        self.assertEqual([['reader:lighton'], ['reader:doctr']], [keys for _f, keys in whole])
        self.assertEqual([['reader:doctr']], [keys for _f, keys in only_b])


class AboutFragmentTest(TestCase):

    def setUp(self):
        self.client.force_login(get_user_model().objects.create_user('about_models', password='x'))

    def test_the_fragment_lists_the_models_and_links_the_papers(self):
        groups = [{'label': 'Moteur', 'models': [{
            'key': 'reader:lighton', 'name': 'LightOnOCR', 'description': '', 'platform_url': '',
            'publications': mp.publication_links(AIModel(extra_info={'publications': ['2601.14251']}))}]}]
        with patch.object(mp, 'app_models', return_value=groups):
            r = self.client.get('/common/about/models/reader/')
        self.assertEqual(200, r.status_code)
        self.assertContains(r, 'LightOnOCR')
        self.assertContains(r, 'https://arxiv.org/abs/2601.14251')

    def test_an_unknown_app_is_not_found(self):
        self.assertEqual(404, self.client.get('/common/about/models/no-such-app/').status_code)

    def test_the_shared_template_cites_the_route_literally(self):
        # The shared template is re-read hot by the production server, the route only on reload:
        # a reverse() of a route the server does not know yet breaks EVERY app page.
        import wama
        tpl = (Path(wama.__file__).parent / 'common' / 'templates' / 'common'
               / 'app_modern_base.html').read_text(encoding='utf-8')
        # Since 7577c1c77 (2026-11-02) the tabs load the whole derived « À propos » / « Aide »
        # (`common:app_about` / `common:app_help`), the models fragment being part of it.
        self.assertIn('data-about-models="/common/about/{% block about_app %}{{ current_app }}'
                      '{% endblock %}/"', tpl)
        self.assertIn('data-about-models="/common/help/{% block help_app %}{{ current_app }}'
                      '{% endblock %}/"', tpl)
        for name in ('common:app_about_models', 'common:app_about', 'common:app_help'):
            self.assertNotIn(name, tpl)


class LabAppAndDoiTest(TestCase):
    """2026-10-10: Face Analyzer (Lab world, no catalogue select, served under /lab/) shows the
    models it declares; an author who cites a journal article is named by its DOI."""

    def setUp(self):
        AIModel.objects.create(model_key='face_analyzer:deepface-age', name='deepface-age',
                               model_type='vision', source='face_analyzer',
                               extra_info={'publications': ['10.35378/gujs.1794891']})

    def test_a_doi_links_to_doi_org(self):
        link, = mp.publication_links(AIModel(extra_info={'publications': ['10.35378/gujs.1794891']}))
        self.assertEqual(('doi', 'DOI 10.35378/gujs.1794891', 'https://doi.org/10.35378/gujs.1794891'),
                         (link['kind'], link['label'], link['url']))
        # Counter-check: an arXiv identifier keeps its arXiv link.
        self.assertEqual('https://arxiv.org/abs/2601.14251', mp.publication_links(
            AIModel(extra_info={'publications': ['2601.14251']}))[0]['url'])

    def test_an_app_without_catalogue_select_lists_its_own_models(self):
        with patch('wama.common.utils.param_schema.schema_for_app', return_value=[]):
            group, = mp.app_models('face_analyzer')
        self.assertEqual(['deepface-age'], [m['name'] for m in group['models']])

    def test_the_fragment_answers_for_a_lab_app_with_its_own_models(self):
        self.client.force_login(get_user_model().objects.create_user('about_lab', password='x'))
        with patch('wama.common.utils.param_schema.schema_for_app', return_value=[]):
            r = self.client.get('/common/about/models/face_analyzer/')
        self.assertEqual(200, r.status_code)
        self.assertContains(r, 'https://doi.org/10.35378/gujs.1794891')
