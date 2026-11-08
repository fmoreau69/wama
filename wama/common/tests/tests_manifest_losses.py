"""The guard of BOTH writing directions of a manifest (2026-11-08, Fabien).

A manifest is edited to apply a change to the registries (`ingest.write_back`) and regenerated
from them after a change (`manifest_export`). When both happen at once, the second writer erased
what the first had set, silently. Lived the same day: Albert stopped announcing the vision of its
models, the catalogue lost the `image` modality of three models that do see, and the export was
about to remove it from the versioned corpus.

One rule for both doors (`manifests/losses.py`): a fact present before and absent after is a LOSS,
and a loss is written only when explicitly accepted.
"""
import io
import json
import tempfile
from pathlib import Path
from unittest import mock

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, TestCase

from wama.common.manifests.losses import lost_facts
from wama.model_manager.models import AIModel

KEY = 'huggingface:Org/Seer'


class LostFactsTest(SimpleTestCase):

    def test_a_removed_key_a_removed_item_and_an_emptied_value_are_losses(self):
        before = {'a': 1, 'caps': {'modalities': ['text', 'image']}, 'license': 'mit'}
        after = {'caps': {'modalities': ['text']}, 'license': ''}
        self.assertEqual(
            [('a', '1'), ('caps.modalities', '"image"'), ('license', '"mit"')],
            [(x['path'], x['lost']) for x in lost_facts(before, after)])

    def test_a_replaced_value_an_addition_and_a_new_order_are_not(self):
        before = {'description': 'Snapshot HF', 'modalities': ['text', 'image'], 'n': 4}
        after = {'description': 'A real description', 'modalities': ['image', 'text', 'audio'],
                 'n': 11, 'new': True}
        self.assertEqual([], lost_facts(before, after))

    def test_the_objects_of_a_list_are_matched_by_what_names_them(self):
        before = {'requires': [{'kind': 'library', 'key': 'a'}, {'kind': 'model', 'key': 'm'}],
                  'params': [{'name': 'x', 'help': 'h'}, {'name': 'y', 'help': 'g'}]}
        after = {'requires': [{'kind': 'model', 'key': 'm'}, {'kind': 'library', 'key': 'b'}],
                 'params': [{'name': 'y', 'help': 'g'}, {'name': 'x', 'help': ''}]}
        self.assertEqual(
            [('requires', 'library'), ('params[name=x].help', '"h"')],
            [(x['path'], 'library' if 'library' in x['lost'] else x['lost'])
             for x in lost_facts(before, after)])

    def test_objects_sharing_a_key_are_not_confused(self):
        """The three bounds of a temperature setting all carry `field: model` (false positives at
        the first guarded export): they are named by ALL their natural keys, in any order."""
        bounds = [{'capability': 'params', 'field': 'model', 'param': 'temperature'},
                  {'capability': 'max_temperature', 'field': 'model'},
                  {'capability': 'min_temperature', 'field': 'model', 'mode': 'min'}]
        self.assertEqual([], lost_facts({'cap_from': bounds},
                                        {'cap_from': list(reversed(bounds))}))
        self.assertEqual(['cap_from[capability=params].param'],
                         [x['path'] for x in lost_facts(
                             {'cap_from': bounds},
                             {'cap_from': [{'capability': 'params', 'field': 'model'}, *bounds[1:]]})])


def _row(**fields):
    defaults = dict(name='Seer', model_type='llm', source='huggingface', is_downloaded=True,
                    capabilities={'task': 'text-generation', 'modalities': ['text', 'image']})
    defaults.update(fields)
    return AIModel.objects.create(model_key=KEY, **defaults)


class ExportRefusesALossTest(TestCase):
    """Registries → manifest: the file on disk may carry a fact the registry lost."""

    def _export(self, out, **options):
        call_command('manifest_export', KEY, kind='model', out=out, verbosity=0,
                     stdout=options.pop('stdout', mock.MagicMock()), **options)
        from wama.common.management.commands.manifest_export import _nom_fichier
        return json.loads((Path(out) / f"{_nom_fichier(KEY)}.json").read_text(encoding='utf-8'))

    def test_a_lost_modality_is_not_written_until_accepted(self):
        row = _row()
        with tempfile.TemporaryDirectory() as out:
            self.assertIn('image', self._export(out)['body']['capabilities']['modalities'])
            row.capabilities = {**row.capabilities, 'modalities': ['text']}
            row.save(update_fields=['capabilities'])
            with self.assertRaises(CommandError):
                self._export(out)
            on_disk = json.loads(next(Path(out).glob('*.json')).read_text(encoding='utf-8'))
            self.assertIn('image', on_disk['body']['capabilities']['modalities'],
                          'the file keeps the fact')
            written = self._export(out, accept_losses=True)
            self.assertEqual(['text'], written['body']['capabilities']['modalities'])

    def test_check_names_the_loss_and_writes_nothing(self):
        row = _row()
        with tempfile.TemporaryDirectory() as out:
            self._export(out)
            row.capabilities = {**row.capabilities, 'modalities': ['text']}
            row.save(update_fields=['capabilities'])
            report = io.StringIO()
            with self.assertRaises(SystemExit):
                call_command('manifest_export', KEY, kind='model', out=out, check=True,
                             verbosity=0, stdout=report)
            self.assertIn('PERTE', report.getvalue())
            self.assertIn('capabilities.modalities : "image"', report.getvalue())

    def test_a_change_without_loss_is_written_as_before(self):
        """Counter-check: a fact ADDED or REPLACED is not a loss — the export writes it."""
        row = _row()
        with tempfile.TemporaryDirectory() as out:
            self._export(out)
            row.capabilities = {**row.capabilities, 'modalities': ['text', 'image', 'audio']}
            row.save(update_fields=['capabilities'])
            self.assertIn('audio', self._export(out)['body']['capabilities']['modalities'])


class ApplyRefusesALossTest(TestCase):
    """Manifest → registries: a manifest written before a change would revert it."""

    def _manifest(self, license_id):
        from wama.common.manifests.ingest import extract
        manifest = extract('model', KEY)
        manifest['body'].setdefault('identity', {})['license'] = license_id
        return manifest

    def test_a_late_manifest_does_not_erase_a_fact_until_accepted(self):
        from wama.common.manifests.ingest import write_back
        _row(license='mit')
        result = write_back(self._manifest(''), apply=True)
        self.assertEqual(['body.identity.license'], [x['path'] for x in result['losses']])
        self.assertEqual('mit', AIModel.objects.get(model_key=KEY).license,
                         'nothing written: the savepoint was rolled back')
        write_back(self._manifest(''), apply=True, accept_losses=True)
        self.assertEqual('', AIModel.objects.get(model_key=KEY).license)

    def test_a_manifest_that_loses_nothing_applies(self):
        """Counter-check: a replaced value is applied, with no refusal."""
        from wama.common.manifests.ingest import write_back
        _row(license='mit')
        result = write_back(self._manifest('apache-2.0'), apply=True)
        self.assertNotIn('losses', result)
        self.assertEqual('apache-2.0', AIModel.objects.get(model_key=KEY).license)
