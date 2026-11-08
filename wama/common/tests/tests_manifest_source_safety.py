"""Un manifeste `app` ne fait entrer dans le code généré que des noms, des chemins et des expressions
admises (`codegen/source_safety.py`) — et le validateur du kind le refuse à toutes les routes.

Constat du 2026-11-07 (instance sœur, vérifié au code le 2026-11-08) : les gabarits composent du
Python par chaînes depuis le manifeste, et un manifeste d'app peut être PROPOSÉ par un rôle LLM.
"""
import json
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

from wama.common.manifests.builtin.app import validate_app_body
from wama.common.manifests.codegen import source_safety


def _corpus():
    """Les manifestes `app` du dépôt : corpus des apps réelles et brouillons d'apps nées de zéro."""
    root = Path(settings.BASE_DIR) / 'manifests'
    for path in sorted((root / 'apps').glob('*.json')) + sorted((root / 'app_drafts').glob('*.json')):
        yield path, json.loads(path.read_text(encoding='utf-8'))


def _field(expr='1', imports=(), name='size', cls='django.db.models.IntegerField', kwargs=None):
    return {'name': name, 'class': cls, 'args': [],
            'kwargs': kwargs if kwargs is not None else {'default': {'expr': expr,
                                                                     'imports': list(imports)}}}


def _data_body(**field):
    return {'data': {'models': [{'name': 'Item', 'bases': ['wama.common.models.ScopedVisibility'],
                                 'manager': 'wama.common.models.ScopedManager',
                                 'fields': [_field(**field)]}]}}


class SourceSafetyRulesTest(SimpleTestCase):
    def test_the_expressions_of_the_corpus_shape_are_admitted(self):
        for expr in ("wama.common.utils.media_paths.UploadToUserPath('describer', 'input')",
                     'django.core.validators.MinValueValidator(0)', 'settings.AUTH_USER_MODEL',
                     'django.db.models.deletion.CASCADE', 'dict', "[('a', 'A'), ('b', 'B')]",
                     '-1.5', "{'k': (1, 2)}", 'None'):
            with self.subTest(expr=expr):
                self.assertEqual('', source_safety.expression_error(expr))

    def test_an_expression_that_would_run_code_is_refused(self):
        for expr in ("__import__('os').system('id')", "os.system('id')", 'lambda: 1',
                     '[x for x in django.a]', 'django.db.__class__', "wama.common.x.purge()",
                     "1) ; import os ; (2", "(y := 1)", "django.core.management.call_command('flush')"):
            with self.subTest(expr=expr):
                self.assertNotEqual('', source_safety.expression_error(expr))

    def test_names_paths_and_imports(self):
        self.assertTrue(source_safety.is_name('input_file'))
        for bad in ('class', 'a b', "x'); import os; ('", '', None, 3):
            self.assertFalse(source_safety.is_name(bad), bad)
        self.assertTrue(source_safety.is_path('django.db.models.CharField'))
        for bad in ('os.path.join', 'django', 'django.db.models.Char Field'):
            self.assertFalse(source_safety.is_path(bad), bad)
        self.assertTrue(source_safety.is_import('from wama.common.models import ScopedManager'))
        for bad in ('import os', 'import django.db; import os', 'from subprocess import run'):
            self.assertFalse(source_safety.is_import(bad), bad)


class AppValidatorRejectsCodeTest(SimpleTestCase):
    """Le validateur du kind — celui qu'appellent l'ingest, « Valider » et la création d'une app
    depuis un fichier — porte le contrôle : un seul endroit pour toutes les routes."""

    def test_the_data_facet_rejects_code_in_an_expression_an_import_or_a_path(self):
        cases = {
            'expression': _data_body(expr="__import__('os').system('id')"),
            'import': _data_body(imports=['import os']),
            'classe': _data_body(cls='os.system'),
            'nom de champ': _data_body(name='x = 1\nimport os\ny'),
            'argument nommé': _data_body(kwargs={'default=1)\nimport os\n#': {'expr': '1'}}),
        }
        for label, body in cases.items():
            with self.subTest(case=label):
                self.assertTrue(validate_app_body(body), f'{label} : rien refusé')

    def test_a_safe_data_facet_passes(self):
        self.assertEqual([], validate_app_body(_data_body()))

    def test_every_value_path_rejects_a_value_that_breaks_out(self):
        """Chaque chemin déclaré, nourri d'une valeur qui sortirait de sa place dans le code :
        refusé, et nommé dans l'erreur. Une règle mal écrite (un chemin qui ne descend pas) ne
        refuserait rien — c'est ce que le test verrait."""
        for _rule, paths in source_safety.DECLARED_VALUES:
            for path in paths:
                with self.subTest(path=path):
                    body = _body_with(path, "x'); import os  #\n")
                    errors = validate_app_body(body)
                    self.assertTrue(any(e.startswith(path + ' :') for e in errors), errors)

    def test_a_declared_value_that_is_a_name_passes(self):
        body = _body_with('processing.model_spec.item.input_field', 'input_file')
        self.assertFalse([e for e in validate_app_body(body) if 'input_field' in e])


def _body_with(path: str, value):
    """Un corps minimal qui porte `value` au chemin déclaré `path` (syntaxe de `DECLARED_VALUES`)."""
    steps = source_safety._STEP.findall(path)
    root = {}
    node = root
    for index, (name, each, keys, values) in enumerate(steps):
        last = index == len(steps) - 1
        following = steps[index + 1] if not last else None
        if name:
            if last:
                node[name] = value
            else:
                node[name] = [] if following[1] else {}
                node = node[name]
        elif each:
            if last:
                node.append(value)
            else:
                child = {} if following[0] or following[2] or following[3] else []
                node.append(child)
                node = child
        elif keys:
            node[value] = {}
        elif values:
            if last:
                node['k'] = value
            else:
                node['k'] = [] if following[1] else {}
                node = node['k']
    return root


class PipelineProcessNamesTest(SimpleTestCase):
    """Les process DÉCLARÉS d'un pipeline d'app deviennent du code : refusés au validateur du
    kind, et à la lecture qui en tire les process (`pipeline_decl.process_specs`), qui lit les
    brouillons sans passer par l'ingest."""

    def _pipeline(self, nid='transcribe', output='result_file', source='input'):
        return {'key': 'probe', 'manifest_kind': 'pipeline', 'body': {
            # La source porte l'id du lien : seule la règle de nommage peut refuser la dépendance
            # (un lien vers un nœud inconnu serait refusé pour une autre raison).
            'nodes': [{'id': source, 'kind': 'source'},
                      {'id': nid, 'kind': 'function', 'function': 'probe.transcribe',
                       'process': {'label': 'Transcription', 'outputs': [output]}}],
            'links': [{'from': source, 'to': nid}]}}

    def test_a_process_id_or_output_that_is_not_a_name_is_refused_at_both_doors(self):
        from wama.common.manifests.builtin.pipeline import validate_pipeline_body
        from wama.common.manifests.codegen.pipeline_decl import process_specs
        for label, manifest in {'id': self._pipeline(nid="x():\n import os\ndef y"),
                                'sortie': self._pipeline(output='a = 1; import os; b'),
                                'dépendance': self._pipeline(source='in"""\nimport os')}.items():
            with self.subTest(case=label):
                self.assertTrue(validate_pipeline_body(manifest['body']))
                with self.assertRaises(ValueError):
                    process_specs(manifest)

    def test_a_safe_pipeline_passes(self):
        from wama.common.manifests.codegen.pipeline_decl import process_specs
        self.assertEqual(['transcribe'], [s['key'] for s in process_specs(self._pipeline())])


class CorpusPassesTheSafetyRulesTest(SimpleTestCase):
    """La règle ne refuse rien de ce que les apps réelles et les brouillons déclarent : elle est
    tirée de leur mesure, et le corpus la tient."""

    def test_every_app_manifest_of_the_repository_passes(self):
        seen = 0
        for path, manifest in _corpus():
            seen += 1
            with self.subTest(manifest=path.name):
                self.assertEqual([], source_safety.source_safety_errors(manifest.get('body') or {}))
        self.assertGreater(seen, 10, 'corpus introuvable : la garde ne mesurerait rien')

    def test_every_pipeline_of_the_repository_passes(self):
        root = Path(settings.BASE_DIR) / 'manifests'
        paths = sorted((root / 'pipelines').glob('*.json')) + sorted(
            (root / 'app_drafts' / 'pipelines').glob('*.json'))
        self.assertGreater(len(paths), 10)
        for path in paths:
            with self.subTest(pipeline=path.name):
                body = json.loads(path.read_text(encoding='utf-8')).get('body') or {}
                self.assertEqual([], source_safety.pipeline_source_safety_errors(body))
