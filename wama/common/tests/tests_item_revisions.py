"""Revisions of an element — the brick of marche 8a (`WAMA_COLLABORATION.md §7.1`).

What the common task skeleton promises (a success = a revision tied to the `produit` fact) is
held by the generic contract `tests_task_skeleton_contract`, on every adopter. Here: what the
service itself promises, on a real element model (the converter's, whose settings are columns).
"""
import shutil
import tempfile
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from wama.common.services import revisions


class _Base(TestCase):

    def setUp(self):
        from wama.converter.models import ConversionJob
        self.user = get_user_model().objects.create_user('revision_owner', password='x')
        self.item = ConversionJob.objects.create(user=self.user, input_filename='in.png',
                                                 quality=85, flip_h=True)


class NumberingTest(_Base):

    def test_each_record_takes_the_next_number_of_its_own_element(self):
        from wama.converter.models import ConversionJob
        other = ConversionJob.objects.create(user=self.user, input_filename='b.png')
        first = revisions.record_revision('converter', self.item)
        second = revisions.record_revision('converter', self.item)
        elsewhere = revisions.record_revision('converter', other)
        self.assertEqual((1, 2, 1), (first.number, second.number, elsewhere.number))
        self.assertEqual([2, 1], [r.number for r in revisions.revisions_of('converter', self.item)])
        self.assertEqual(2, revisions.current_revision('converter', self.item).number)

    def test_the_owner_is_the_default_author(self):
        self.assertEqual(self.user, revisions.record_revision('converter', self.item).user)

    def test_an_unknown_number_is_refused_by_name(self):
        with self.assertRaises(LookupError):
            revisions.get_revision('converter', self.item, 7)

    def test_a_failure_to_record_never_raises(self):
        """Best-effort: a lost trace must not fail the task that succeeded."""
        with mock.patch.object(revisions, 'settings_snapshot', side_effect=RuntimeError('panne')):
            self.assertIsNone(revisions.record_revision('converter', self.item))


class SettingsSnapshotTest(_Base):

    def test_item_settings_come_from_the_schema_and_keep_unset_as_none(self):
        snapshot = revisions.settings_snapshot('converter', self.item)
        self.assertEqual(85, snapshot.get('quality'))
        self.assertIs(True, snapshot.get('flip_h'))
        self.assertIn('fps', snapshot)
        self.assertIsNone(snapshot['fps'], 'an unset setting must stay "unset", not a default')

    def test_the_snapshot_is_frozen_in_the_revision(self):
        revision = revisions.record_revision('converter', self.item)
        self.item.quality = 40
        self.item.save(update_fields=['quality'])
        revision.refresh_from_db()
        self.assertEqual(85, revision.settings['quality'])

    def test_an_app_without_schema_gives_an_empty_snapshot(self):
        self.assertEqual({}, revisions.settings_snapshot('no_such_app', self.item))


class OutputsTest(_Base):

    def setUp(self):
        super().setUp()
        self.media = tempfile.mkdtemp(prefix='wama_revisions_')
        self.addCleanup(shutil.rmtree, self.media, ignore_errors=True)
        self.override = override_settings(MEDIA_ROOT=self.media)
        self.override.enable()
        self.addCleanup(self.override.disable)

    def _write_output(self, content: bytes):
        from pathlib import Path
        path = Path(self.media) / 'users' / 'out.txt'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        self.item.output_file.name = 'users/out.txt'
        self.item.save(update_fields=['output_file'])

    def test_files_are_referenced_with_their_fingerprint(self):
        self._write_output(b'first result')
        refs = revisions.file_references(self.item)
        self.assertEqual(['output_file'], [r['field'] for r in refs],
                         'an empty FileField (input_file) must not be referenced')
        self.assertEqual('users/out.txt', refs[0]['path'])
        self.assertEqual(64, len(refs[0]['sha256']))

    def test_a_file_overwritten_since_the_revision_is_named(self):
        """Until outputs are immutable, the fingerprint keeps the history honest."""
        self._write_output(b'first result')
        revision = revisions.record_revision('converter', self.item)
        self.assertEqual([], revisions.outputs_changed_since(revision))
        self._write_output(b'second result, same path')
        self.assertEqual(['output_file'], revisions.outputs_changed_since(revision))


class PublicationTest(_Base):

    def test_publishing_makes_a_version_and_unpublishing_keeps_the_history(self):
        revisions.record_revision('converter', self.item)
        revisions.record_revision('converter', self.item)
        self.assertIsNone(revisions.published_revision('converter', self.item))

        published = revisions.publish('converter', self.item, 1, user=self.user, note='séminaire')
        self.assertTrue(published.is_published)
        self.assertEqual('séminaire', published.publish_note)
        # The published version stays v1 while v2 is the current revision.
        self.assertEqual(1, revisions.published_revision('converter', self.item).number)
        self.assertEqual(2, revisions.current_revision('converter', self.item).number)

        revisions.unpublish('converter', self.item, 1)
        self.assertIsNone(revisions.published_revision('converter', self.item))
        self.assertEqual(2, revisions.revisions_of('converter', self.item).count())
