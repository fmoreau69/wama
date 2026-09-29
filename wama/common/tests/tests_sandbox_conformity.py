"""Une jumelle bac à sable est NOTÉE, avec son écart à la source, et reste HORS du total
(2026-09-29 — `WAMA_VERIFICATION §1bis` : « maintenant pour la mesure, jamais pour la photo
globale »).

La grille savait noter une jumelle par app depuis le 26/09 ; la commande complète et la page
`/apps/` affichaient pourtant encore « jamais notée ». Le registre des jumelles est gitignoré :
le catalogue est SIMULÉ ici (une jumelle clonée d'une app réelle).
"""
import json
from unittest.mock import patch

from django.test import SimpleTestCase

from wama.common import app_registry


class SandboxConformityTest(SimpleTestCase):

    def _catalog(self):
        catalog = dict(app_registry.APP_CATALOG)
        catalog['reader_77'] = dict(catalog['reader'], sandbox=True, generated_from='reader')
        return catalog

    def test_the_twin_is_measured_apart_with_its_gap_to_the_source(self):
        report = {'apps': {'reader': {'pct': 98}}}
        with patch.object(app_registry, 'APP_CATALOG', self._catalog()), \
                patch('wama.common.services.conformity_checker.run_checks',
                      return_value={'apps': {'reader_77': {'pct': 80, 'score': 1, 'partial': 0,
                                                           'total': 1, 'conv': {}}}}):
            twins = app_registry.sandbox_conformity(report)
        self.assertEqual({'generated_from': 'reader', 'source_pct': 98, 'gap': -18},
                         {k: twins['reader_77'][k] for k in ('generated_from', 'source_pct', 'gap')})

    def test_the_summary_marks_the_twin_and_the_real_apps_stay_unmarked(self):
        data = {'apps': {'reader': {'conv': {'a': True, 'b': True}}},
                'sandbox_apps': {'reader_77': {'conv': {'a': True, 'b': False}}},
                'generated_at': 'now'}
        with patch.object(app_registry, 'APP_CATALOG', self._catalog()), \
                patch.dict(app_registry._CONFORMITY_REPORT, {'data': data, 'mtime': 1.0}), \
                patch('pathlib.Path.stat', return_value=type('S', (), {'st_mtime': 1.0})()):
            summary = app_registry.get_conformity_summary()
        twin, source = summary['reader_77'], summary['reader']
        self.assertTrue(twin['sandbox'] and twin['measured'])
        self.assertEqual(twin['pct'] - source['pct'], twin['gap'])
        self.assertNotIn('sandbox', source, 'une app réelle ne doit pas être marquée')

    def test_the_global_photo_never_contains_a_twin(self):
        """Contre-épreuve : la clé `apps` (lue par le total, les faits générés, les
        manifestes) ne reçoit que les apps réelles, même quand une jumelle existe."""
        with patch.object(app_registry, 'APP_CATALOG', self._catalog()), \
                patch('wama.common.services.conformity_checker.run_checks',
                      side_effect=lambda ids: {'criteria': {}, 'apps': {a: {'pct': 90} for a in ids}}), \
                patch('pathlib.Path.write_text') as written:
            report = app_registry.measure_and_write_conformity()
        self.assertNotIn('reader_77', report['apps'])
        self.assertIn('reader_77', report['sandbox_apps'])
        self.assertNotIn('reader_77', json.loads(written.call_args[0][0])['apps'])
