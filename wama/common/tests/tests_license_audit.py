"""A COMPOUND licence expression (2026-11-05) — `license_audit.license_terms` and `qualifier`.

Whisper's weights are published by OpenAI (apache-2.0) and converted to CTranslate2 by Systran
(mit): the model WAMA installs carries both, `apache-2.0 AND mit` (Fabien's decision). Libraries
already carried such expressions (`MIT AND MPL-2.0`), and the audit qualified them by their FIRST
token — `MIT AND MPL-2.0` passed for permissive while MPL-2.0 is a weak copyleft.
"""
from django.test import SimpleTestCase

from wama.common.services import license_audit as audit


class LicenseTermsTest(SimpleTestCase):

    def test_an_expression_is_split_into_normalised_terms(self):
        self.assertEqual(('AND', ['apache-2.0', 'mit']), audit.license_terms('apache-2.0 AND mit'))
        self.assertEqual(('OR', ['mit', 'apache-2.0']), audit.license_terms('MIT OR Apache-2.0'))
        self.assertEqual(('AND', ['unlicense', 'mit', 'isc']),
                         audit.license_terms('Unlicense AND MIT AND ISC'))

    def test_a_single_licence_and_nothing(self):
        self.assertEqual(('', ['mit']), audit.license_terms('MIT License'))
        self.assertEqual(('', []), audit.license_terms(''))
        self.assertEqual(('', []), audit.license_terms(None))

    def test_a_lower_case_and_belongs_to_a_licence_name(self):
        """SPDX writes its operators in capitals; free text says « and » inside a name."""
        operator, _terms = audit.license_terms('Research and Commercial License')
        self.assertEqual('', operator)

    def test_a_mixed_or_bracketed_expression_is_not_guessed(self):
        self.assertEqual('', audit.license_terms('MIT AND BSD OR ISC')[0])
        self.assertEqual('', audit.license_terms('MIT OR (Apache-2.0 AND BSD)')[0])


class CompoundQualificationTest(SimpleTestCase):

    def test_and_obliges_to_every_term_so_the_most_constraining_one(self):
        q = audit.qualifier('MIT AND MPL-2.0')
        self.assertEqual((audit.COPYLEFT_FAIBLE, 'mit AND mpl-2.0'), (q['rang'], q['id']))

    def test_or_lets_one_choose_so_the_least_constraining_one(self):
        q = audit.qualifier('AGPL-3.0 OR MIT')
        self.assertEqual((audit.PERMISSIVE, 'agpl-3.0 OR mit'), (q['rang'], q['id']))

    def test_whispers_licence_is_permissive_and_owes_attribution(self):
        q = audit.qualifier('apache-2.0 AND mit')
        self.assertEqual((audit.PERMISSIVE, True), (q['rang'], q['attribution']))

    def test_every_text_written_in_the_registries_is_qualified(self):
        """2026-11-13 (registre des licences revu rétroactivement) : 15 textes des registres
        tombaient en « à qualifier » alors que la licence est connue. Chacun reçoit son
        identifiant et sa famille ; « Dual License » et la branche commerciale d'Artifex, qui ne
        disent rien de lisible, restent à qualifier ; « UNKNOWN » est une licence inconnue."""
        expected = {
            'Apache License 2.0': ('apache-2.0', audit.PERMISSIVE),
            'Creative Commons Attribution-NonCommercial 4.0 International':
                ('cc-by-nc-4.0', audit.NON_COMMERCIAL),
            'CC BY 4.0': ('cc-by-4.0', audit.PERMISSIVE),
            'FAIR Noncommercial Research License':
                ('fair-noncommercial-research', audit.NON_COMMERCIAL),
            'GNU General Public License v3 or later (GPLv3+)': ('gpl-3.0', audit.COPYLEFT_FORT),
            'LGPL': ('lgpl', audit.COPYLEFT_FAIBLE),
            'LGPL-2.1-or-later': ('lgpl-2.1', audit.COPYLEFT_FAIBLE),
            'LGPL-3.0-only': ('lgpl-3.0', audit.COPYLEFT_FAIBLE),
            'MIT-CMU': ('mit-cmu', audit.PERMISSIVE),
            'Python style': ('psf-2.0', audit.PERMISSIVE),
            'S-Lab License 1.0': ('s-lab-1.0', audit.NON_COMMERCIAL),
            'SAM License': ('sam-license', audit.PERMISSIVE),
            'The Unlicense (Unlicense)': ('unlicense', audit.PERMISSIVE),
            'UNKNOWN': ('', audit.INCONNUE),
        }
        for text, (ident, rank) in expected.items():
            q = audit.qualifier(text)
            self.assertEqual((ident, rank), (q['id'], q['rang']), text)
        polyform = audit.qualifier('Polyform Noncommercial OR Artifex Commercial License')
        self.assertEqual(audit.NON_COMMERCIAL, polyform['rang'], 'OR : la branche la plus libre')
        self.assertEqual(audit.A_QUALIFIER, audit.qualifier('Dual License')['rang'])

    def test_counter_proof_a_single_licence_is_qualified_as_before(self):
        self.assertEqual(audit.qualifier('mpl-2.0')['rang'], audit.COPYLEFT_FAIBLE)
        self.assertEqual('apache-2.0', audit.qualifier('Apache 2.0 License')['id'])
        self.assertEqual(audit.INCONNUE, audit.qualifier('')['rang'])


class ServiceTermsTest(SimpleTestCase):
    """2026-11-15 (décision de Fabien) : un modèle SERVI par un service distant n'a pas de licence
    de poids à tenir ici — le service la gère ; l'audit tient les conditions d'usage du SERVICE
    (`ExternalSource.terms_url`), une ligne par service."""

    @staticmethod
    def _model(source, execution='cloud', licence=''):
        from types import SimpleNamespace
        return SimpleNamespace(source=source, execution=execution, license=licence, model_key=f'{source}:m',
                               name='m', author='', platform_url='', get_model_type_display=lambda: 'LLM')

    def _lines(self, models, terms):
        from unittest import mock

        from wama.common import external_sources as xs
        from wama.model_manager.models import AIModel
        sources = {key: mock.Mock(terms_url=url, label=key.title(), hosting='third_party')
                   for key, url in terms.items()}
        manager = mock.Mock()
        manager.filter.return_value.only.return_value = models
        manager.filter.return_value.order_by.return_value = models
        with mock.patch.object(AIModel, 'objects', manager), mock.patch.object(xs, 'by_key', lambda: sources):
            lines = list(audit._lignes_modeles()) + list(audit._service_lines())
            for line in lines:
                line['q'] = audit.qualifier(line['licence'])
            return lines, [audit.qualifier(audit.model_licence(m))['rang'] for m in models]

    def test_served_models_make_one_line_per_service_not_one_each(self):
        models = [self._model('alpha'), self._model('alpha'), self._model('beta')]
        lines, _ = self._lines(models, {'alpha': 'https://alpha.example/terms', 'beta': ''})
        self.assertEqual([('service', 'alpha'), ('service', 'beta')], [(l['registre'], l['cle']) for l in lines])
        alpha, beta = lines
        self.assertEqual((audit.SERVICE_TERMS, audit.A_QUALIFIER, 'https://alpha.example/terms'),
                         (alpha['q']['id'], alpha['q']['rang'], alpha['url']))
        self.assertIn('2 modèles servis', alpha['detail'])
        self.assertEqual(audit.INCONNUE, beta['q']['rang'], 'des conditions non établies sont inconnues')
        self.assertIsNone(beta['url'])

    def test_a_local_model_keeps_its_line_and_a_served_one_never_does(self):
        """Un modèle ouvert servi par un tiers (licence des poids connue) reste sous les
        conditions du service : WAMA n'en détient pas les poids."""
        models = [self._model('alpha', execution='local', licence='mit'),
                  self._model('alpha', licence='apache-2.0')]
        lines, ranks = self._lines(models, {'alpha': 'https://alpha.example/terms'})
        self.assertEqual(['model', 'service'], [l['registre'] for l in lines])
        self.assertEqual([audit.PERMISSIVE, audit.A_QUALIFIER], ranks)

    def test_the_model_scene_reads_the_same_rule(self):
        models = [self._model('alpha'), self._model('beta')]
        _, ranks = self._lines(models, {'alpha': 'https://alpha.example/terms', 'beta': ''})
        self.assertEqual([audit.A_QUALIFIER, audit.INCONNUE], ranks)

    def test_every_service_line_has_its_registry_colour_and_shape(self):
        from pathlib import Path

        from django.conf import settings

        from wama.common.services import license_scene
        css = (Path(settings.BASE_DIR) / 'wama/common/static/common/css/wama-constellation.css').read_text('utf-8')
        for registry in audit.REGISTRES:
            self.assertIn(f'--wc-registry-{registry}:', css, registry)
            self.assertIn(registry, license_scene.SHAPES, registry)

    def test_terms_written_on_a_source_are_an_https_page(self):
        from wama.common import external_sources as xs
        written = {s.key: s.terms_url for s in xs.SOURCES if s.terms_url}
        self.assertTrue(written)
        for key, url in written.items():
            self.assertTrue(url.startswith('https://'), key)
            self.assertEqual('llm', xs.by_key()[key].kind, key)


class TransitiveLicencesTest(SimpleTestCase):
    """2026-11-15 (décision de Fabien) : les dépendances des librairies du registre ne s'y
    inscrivent pas — l'audit les LIT dans l'environnement et n'en liste que les exceptions, avec
    la librairie du registre qui les tire."""

    INSTALLED = {
        'engine': {'name': 'Engine', 'version': '1', 'license': 'MIT', 'requires': ['helper', 'other-lib']},
        'other-lib': {'name': 'Other_Lib', 'version': '2', 'license': 'MIT', 'requires': ['deep']},
        'helper': {'name': 'helper', 'version': '3', 'license': 'MIT', 'requires': ['gpl-part', 'silent']},
        'gpl-part': {'name': 'gpl-part', 'version': '4', 'license': 'GPLv3+', 'requires': []},
        'silent': {'name': 'silent', 'version': '5', 'license': '', 'requires': []},
        'deep': {'name': 'deep', 'version': '6', 'license': 'Some House Terms', 'requires': []},
        'stray': {'name': 'stray', 'version': '7', 'license': 'LGPLv3', 'requires': []},
    }

    def _report(self):
        return audit.transitives(installed=self.INSTALLED, registry_keys=['Engine', 'other_lib'])

    def test_only_what_the_registry_does_not_carry_is_read(self):
        report = self._report()
        self.assertEqual(5, report['total'])
        self.assertEqual({'Permissive': 1, 'Copyleft fort': 1, 'Inconnue': 1, 'À qualifier': 1,
                          'Copyleft faible': 1}, report['families'])

    def test_exceptions_are_listed_most_constraining_first_with_what_pulls_them(self):
        listed = [(e['nom'], e['pulled_by']) for e in self._report()['exceptions']]
        self.assertEqual([('silent', ['Engine']), ('deep', ['Other_Lib']), ('gpl-part', ['Engine'])], listed)

    def test_a_dependency_is_answered_for_by_the_nearest_registry_library(self):
        """`deep` vient par `other-lib`, elle-même au registre : c'est elle qui en répond, pas
        `engine` qui la tire de plus loin."""
        from wama.common.services import library_index
        parents = library_index.pulled_by(self.INSTALLED, ['engine', 'other-lib'])
        self.assertEqual(['Other_Lib'], parents['deep'])
        self.assertNotIn('stray', parents)
        self.assertEqual(1, self._report()['unpulled'])

    def test_spellings_read_in_installed_metadata_are_known_licences(self):
        expected = {'New BSD': 'bsd-3-clause', '3-Clause BSD License': 'bsd-3-clause',
                    'LGPLv3': 'lgpl-3.0', 'GNU Lesser General Public License v3 (LGPLv3)': 'lgpl-3.0',
                    'PSFL': 'psf-2.0', 'Python Software Foundation License': 'psf-2.0',
                    'Apache Software License 2.0': 'apache-2.0', 'FreeBSD': 'bsd-2-clause',
                    'GNU General Public License v2 or later (GPLv2+)': 'gpl-2.0'}
        for text, ident in expected.items():
            self.assertEqual(ident, audit.qualifier(text)['id'], text)
        self.assertEqual(audit.A_QUALIFIER, audit.qualifier('NVIDIA Proprietary Software')['rang'])

    def test_installed_distributions_are_read_by_the_rules_of_the_library_manifest(self):
        """Clé normalisée, licence courte, et les dépendances SANS celles d'un extra."""
        from unittest import mock

        from wama.common.services import library_index

        class _Dist:
            version = '1.2'
            metadata = {'Name': 'Some_Engine', 'License': 'MIT'}
            requires = ['Deep.Lib>=2', 'gui-kit ; extra == "gui"', 'plain']

        with mock.patch.object(library_index, '_INSTALLED', ((), None)), \
                mock.patch('importlib.metadata.distributions', lambda: [_Dist()]), \
                mock.patch.object(library_index, 'licence_courte', create=True), \
                mock.patch('wama.common.manifests.builtin.library.licence_courte', lambda meta: meta['License']):
            found = library_index.installed_distributions()
        self.assertEqual({'some-engine': {'name': 'Some_Engine', 'version': '1.2', 'license': 'MIT',
                                          'requires': ['deep-lib', 'plain']}}, found)
