"""Guards of the catalogue TAXONOMY (2026-11-06).

1. Code never names a member the taxonomy no longer declares. `ModelType.SUMMARIZATION` was
   retired on 2026-08-05 ; the describer discovery still branched on it, an `AttributeError`
   waiting for the first model config typed `summarization`. Found while removing BART
   (`REMOVAL_LEDGER R219`) : `manage.py check` does not see an attribute read, only running the
   branch would. Measured that day after the fix : 347 references, none outside.
2. `check_model_taxonomy`, owner of the catalogue VOCABULARY, holds the language rule the `model`
   manifest validator holds (`model_capabilities.languages_outside_vocabulary`) : a row written by
   a discovery never goes through the validator.
"""
import ast
import io
from pathlib import Path

from django.conf import settings
from django.core.management import call_command
from django.test import SimpleTestCase, TestCase

from wama.common.management.commands.check_identifier_language import python_files

from ..models import AIModel, ModelSource, ModelTask, ModelType

ENUMS = {'ModelType': ModelType, 'ModelSource': ModelSource, 'ModelTask': ModelTask}


def undeclared_references(sources):
    """`[(path, line, 'Enum.MEMBER')]` for every `Enum.MEMBER` read that the enum does not have."""
    found = []
    for path, text in sources:
        try:
            tree = ast.parse(text)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if (isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name)
                    and node.value.id in ENUMS and not hasattr(ENUMS[node.value.id], node.attr)):
                found.append((str(path), node.lineno, f'{node.value.id}.{node.attr}'))
    return found


class TaxonomyReferencesTest(SimpleTestCase):

    def test_no_code_names_a_retired_member_of_the_taxonomy(self):
        base = Path(settings.BASE_DIR)
        sources = [(p.relative_to(base), p.read_text(encoding='utf-8', errors='replace'))
                   for p in python_files(base)]
        self.assertGreater(len(sources), 100, "garde d'instrument : le parcours ne voit plus le code")
        self.assertEqual([], undeclared_references(sources))

    def test_the_reader_sees_a_retired_member_and_lets_a_declared_one_pass(self):
        code = "a = ModelType.SUMMARIZATION\nb = ModelType.VLM\nc = ModelTask.choices\n"
        self.assertEqual([('x.py', 1, 'ModelType.SUMMARIZATION')],
                         undeclared_references([('x.py', code)]))


class TaxonomyCommandLanguagesTest(TestCase):

    def _run(self):
        out = io.StringIO()
        try:
            call_command('check_model_taxonomy', stdout=out, stderr=io.StringIO())
        except SystemExit:
            pass
        return out.getvalue()

    def test_a_row_whose_language_is_no_code_is_named_and_a_coded_one_is_not(self):
        for key, languages in (('huggingface:org/bad', ['50+ languages']),
                               ('huggingface:org/good', ['fr', 'zh-cn'])):
            AIModel.objects.create(model_key=key, name=key, model_type='music', source='huggingface',
                                   capabilities={'task': 'text-to-music', 'languages': languages})
        report = self._run()
        self.assertIn("huggingface:org/bad : languages ['50+ languages']", report)
        self.assertNotIn('huggingface:org/good', report)

    def test_a_catalogue_of_coded_languages_passes(self):
        AIModel.objects.create(model_key='huggingface:org/good', name='good', model_type='music',
                               source='huggingface',
                               capabilities={'task': 'text-to-music', 'fallback_languages': ['*']})
        self.assertIn('langues : toutes au vocabulaire', self._run())
