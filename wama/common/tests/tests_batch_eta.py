"""L'ETA agrégée de la card MÈRE d'un lot — une source commune, mesurée, et ce que la page
`/apps/` en dit (2026-10-16, Fabien : « il y a 3 apps qui ne sont pas à 100 % »).

Ce qui a été trouvé : la grille mesurait les dix apps à 100 %, la page `/apps/` en montrait trois
en dessous — et derrière, un vrai trou que personne ne voyait. Huit apps recalculaient chacune
l'`eta_ids` de leur card de lot ; l'imager et l'avatarizer l'avaient oublié (lot sans ETA, l'un
déclaré conforme), le synthesizer le passait en LISTE (`"[12, 13]"`, que `wama-eta.js` ne découpe
pas). `build_batches_list` le pose désormais, la card le lit dans `batch_info`, `eta_batch` est
mesuré, et la page ne laisse plus un booléen déclaré en juillet contredire la mesure.
"""
import re
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth.models import User
from django.template.loader import render_to_string
from django.test import SimpleTestCase, TestCase

from wama.common import app_registry
from wama.common.services import conformity_checker as checker

REAL_APPS = sorted(a for a, s in app_registry.APP_CATALOG.items() if not s.get('sandbox'))


class BatchRowCarriesItsEtaTest(TestCase):

    def test_every_batch_row_carries_the_csv_of_its_elements(self):
        from wama.common.utils.batch_common import build_batches_list
        from wama.composer.models import ComposerBatch, ComposerBatchItem, ComposerGeneration
        user = User.objects.create_user('batch_eta_owner', password='x')
        batch = ComposerBatch.objects.create(user=user)
        gens = [ComposerGeneration.objects.create(user=user, prompt=f'p{i}', model='musicgen-small')
                for i in range(2)]
        for row, gen in enumerate(gens):
            ComposerBatchItem.objects.create(batch=batch, row_index=row, generation=gen)
        row = build_batches_list(user, batch_model=ComposerBatch, work_attr='generation')[0]
        self.assertEqual(f'{gens[0].pk},{gens[1].pk}', row['eta_ids'])


class MotherCardShowsTheEtaTest(SimpleTestCase):
    BASE = {'obj': None, 'items': [], 'success_count': 0, 'running_count': 0,
            'failure_count': 0, 'has_success': False}

    def test_the_mother_card_reads_the_eta_from_its_row_without_any_parameter(self):
        html = render_to_string('common/_batch_card.html', {'batch_info': {**self.BASE, 'eta_ids': '7,9'}})
        self.assertIn('data-eta-ids="7,9"', html)

    def test_an_explicit_parameter_still_wins_and_no_ids_means_no_eta(self):
        html = render_to_string('common/_batch_card.html',
                                {'batch_info': {**self.BASE, 'eta_ids': '7,9'}, 'eta_ids': '3'})
        self.assertIn('data-eta-ids="3"', html)
        self.assertNotIn('data-eta-ids', render_to_string('common/_batch_card.html',
                                                          {'batch_info': self.BASE}))


class EtaBatchCriterionTest(SimpleTestCase):
    """`eta_batch` est MESURÉ : le booléen déclaré mentait pour deux apps."""

    def _fake_app(self, tmp, views_py):
        (tmp / 'templates' / 'fake').mkdir(parents=True)
        (tmp / 'templates' / 'fake' / 'index.html').write_text(
            "{% include 'common/_queue_entry.html' with card_template='x' %}", encoding='utf-8')
        (tmp / 'views.py').write_text(views_py, encoding='utf-8')
        files = checker._AppFiles('fake')
        files.root = tmp
        return files

    def test_a_list_is_red_a_brick_row_is_green(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            state, proof = checker._eta_batch(self._fake_app(
                Path(d) / 'a', "rows = build_batches_list(u, extra=lambda b, i, w: {'eta_ids': [x.id for x in w]})\n"))
            self.assertIs(state, False)
            self.assertIn('LISTE', proof)
        with tempfile.TemporaryDirectory() as d:
            state, _ = checker._eta_batch(self._fake_app(
                Path(d) / 'b', "# 'eta_ids': [ ... ] raconté dans un commentaire\nrows = build_batches_list(u)\n"))
            self.assertIs(state, True, 'un commentaire ne rougit pas une app')

    def test_the_ten_apps_measure_green(self):
        states = {app: checker._eta_batch(checker._AppFiles(app))[0] for app in REAL_APPS}
        self.assertEqual({app: True for app in REAL_APPS}, states)

    def test_no_app_recomputes_the_eta_the_brick_already_gives(self):
        """Anti-duplication : une app qui passe par `build_batches_list` ne pose plus `eta_ids`
        elle-même. Le converter construit ses lignes à la main (clé étrangère directe) : il le
        pose, en CSV — c'est le contrat de la ligne, pas une copie."""
        copies = []
        for app in REAL_APPS:
            files = checker._AppFiles(app)
            if files.find_code(checker.VIEWS, r'build_batches_list\('):
                again = files.find_code(checker.VIEWS, r"""['"]eta_ids['"]\s*:""")
                if again:
                    copies.append(again)
        self.assertEqual([], copies)


class AppsPageSaysWhatTheGridMeasuresTest(SimpleTestCase):
    """La page `/apps/` : le non applicable MESURÉ et les clés COUVERTES par des critères
    mesurés ne laissent plus un booléen déclaré abaisser le score."""

    def _summary(self, conv, criteria, declared):
        catalog = {'appx': {'conventions': declared}}
        data = {'apps': {'appx': {'conv': conv}}, 'criteria': criteria, 'generated_at': 'now'}
        with patch.object(app_registry, 'APP_CATALOG', catalog), \
                patch.dict(app_registry._CONFORMITY_REPORT, {'data': data, 'mtime': 1.0}), \
                patch('pathlib.Path.stat', return_value=type('S', (), {'st_mtime': 1.0})()):
            return app_registry.get_conformity_summary()['appx']

    def test_a_criterion_measured_not_applicable_overrides_the_declared_false(self):
        s = self._summary({'a': True}, {'a': {}, 'recursive_import': {}},
                          {'recursive_import': False})
        self.assertEqual((100, []), (s['pct'], s['issues']))

    def test_a_declared_key_covered_by_measured_criteria_is_not_counted_twice(self):
        s = self._summary({'init_from_schema': True}, {'init_from_schema': {'mechanism': 'inspector'}},
                          {'inspector': False})
        self.assertEqual((100, []), (s['pct'], s['issues']))

    def test_a_declared_key_nothing_measures_still_counts(self):
        """Contre-épreuve : le correctif ne vide pas le déclaré — une clé que rien ne mesure
        garde son verdict."""
        s = self._summary({'a': True}, {'a': {}}, {'modes': False})
        self.assertEqual(['modes'], s['issues'])


class NoEtaCopyInTheGeneratorTest(SimpleTestCase):
    def test_the_generated_link_form_relies_on_the_brick(self):
        src = (Path(checker.__file__).resolve().parents[1] / 'manifests' / 'codegen' / 'views_gen.py'
               ).read_text(encoding='utf-8')
        link = src[src.index('index_link = '):src.index('index_direct = ')]
        self.assertIsNone(re.search(r"'eta_ids'", link))
