"""Les fichiers de RÉVISION gardés — reste 2 de la marche 8a (`WAMA_COLLABORATION §7.2`).

POURQUOI (2026-10-13). Une révision désignait le fichier VIVANT par son chemin et son empreinte :
la relance suivante, ou la correction du fond à la main, réécrivait au même chemin, et la révision
ne pouvait plus que dire « le fichier a changé depuis » (`outputs_changed_since`). Revenir à la
version précédente était impossible (constat de Fabien sur le Writer). Décision du jour : une app
qui le DÉCLARE garde la copie des fichiers de ses 20 dernières révisions + des publiées.

Le contrat, pour CHAQUE modèle installé qui porte la liste (`KeptOutputsMixin`), sans en nommer un :
  - une révision copie ses fichiers de sortie, et la copie ne bouge plus quand le vivant change ;
  - au-delà du nombre gardé, la copie part et la révision le dit (`purged`) — une révision
    PUBLIÉE garde la sienne ;
  - une app qui ne le déclare pas ne copie rien ;
  - la liste est vue par le retrait d'une card (elle est déclarée à la rétention), et une copie
    de la card (⧉) repart sans elle.
Aucun modèle porteur installé (clone sans jumelle Writer) : sauté, en le disant.
"""
import os
import shutil
import tempfile

from django.contrib.auth import get_user_model
from django.db import models
from django.test import SimpleTestCase, TestCase, override_settings


def _keeping_models():
    from django.apps import apps

    from wama.common.services.revisions import KEPT_FIELD
    return [m for m in apps.get_models()
            if any(f.name == KEPT_FIELD for f in m._meta.concrete_fields)]


class KeptPathTest(SimpleTestCase):

    def test_the_copy_lives_beside_the_file_numbered_by_its_revision(self):
        from wama.common.services.revisions import kept_path
        self.assertEqual('users/1/writer/drafts/revisions/7_draft.r3.md',
                         kept_path('users/1/writer/drafts/7_draft.md', 3))
        self.assertEqual('users/1/x/revisions/sans_extension.r1', kept_path('users/1/x/sans_extension', 1))


class KeptRevisionOutputsTest(TestCase):

    def setUp(self):
        self.models = _keeping_models()
        if not self.models:
            self.skipTest('aucun modèle installé ne porte la liste des fichiers gardés')
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root, True)
        media = override_settings(MEDIA_ROOT=self.root)
        media.enable()
        self.addCleanup(media.disable)
        self.user = get_user_model().objects.create_user('kept_outputs_owner', password='x')
        from wama.common.services import revisions
        saved = dict(revisions._KEEPING)
        self.addCleanup(lambda: (revisions._KEEPING.clear(), revisions._KEEPING.update(saved)))

    def _card(self, model):
        """Une card de `model` dont un champ fichier désigne un vrai fichier CHEZ l'app."""
        from wama.common.tests.tests_queue_delete_contract import _instance
        from wama.common.utils.media_paths import app_media_dir
        item = _instance(model, self.user)
        field = next(f.name for f in model._meta.concrete_fields if isinstance(f, models.FileField))
        rel = f"{app_media_dir(model._meta.app_label, self.user.id, 'output')}/kept_{item.pk}.md"
        self._write(rel, 'version 1')
        setattr(item, field, rel)
        item.save()
        return item, field, rel

    def _write(self, rel, text):
        path = os.path.join(self.root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w', encoding='utf-8') as out:
            out.write(text)

    def _read(self, rel):
        with open(os.path.join(self.root, rel), encoding='utf-8') as source:
            return source.read()

    def test_a_revision_keeps_a_copy_the_next_write_does_not_touch(self):
        from wama.common.services.revisions import keep_outputs, kept_file, record_revision
        for model in self.models:
            app = model._meta.app_label
            keep_outputs(app, keep=20)
            item, field, rel = self._card(model)
            first = record_revision(app, item, output_fields=[field])
            self._write(rel, 'version 2')
            second = record_revision(app, item, output_fields=[field])
            item.refresh_from_db()
            self.assertEqual('version 1', self._read(kept_file(app, item, first.number, field)))
            self.assertEqual('version 2', self._read(kept_file(app, item, second.number, field)))
            self.assertEqual(rel, first.outputs[0]['path'], 'the revision still names the live file')

    def test_beyond_the_kept_count_the_copy_goes_and_the_revision_says_so(self):
        from wama.common.models import ItemRevision
        from wama.common.services.revisions import keep_outputs, kept_file, publish, record_revision
        for model in self.models:
            app = model._meta.app_label
            keep_outputs(app, keep=2)
            item, field, rel = self._card(model)
            r1 = record_revision(app, item, output_fields=[field])
            publish(app, item, r1.number, user=self.user)
            r2 = record_revision(app, item, output_fields=[field])
            r3 = record_revision(app, item, output_fields=[field])
            r4 = record_revision(app, item, output_fields=[field])
            item.refresh_from_db()
            self.assertTrue(kept_file(app, item, r1.number, field), 'a published revision keeps its file')
            self.assertEqual('', kept_file(app, item, r2.number, field))
            self.assertTrue(kept_file(app, item, r3.number, field) and kept_file(app, item, r4.number, field))
            gone = ItemRevision.objects.get(pk=r2.pk)
            self.assertTrue(gone.outputs[0].get('purged'), 'the revision stays and says its file is gone')
            self.assertFalse(os.path.exists(os.path.join(
                self.root, rel.rsplit('/', 1)[0], 'revisions', f'kept_{item.pk}.r{r2.number}.md')))

    def test_an_app_that_does_not_declare_it_copies_nothing(self):
        from wama.common.services.revisions import record_revision
        for model in self.models:
            app = model._meta.app_label
            from wama.common.services import revisions
            revisions._KEEPING.pop(app, None)
            item, field, _rel = self._card(model)
            record_revision(app, item, output_fields=[field])
            item.refresh_from_db()
            self.assertEqual([], list(item.kept_outputs or []))

    def test_the_card_carries_its_kept_files_and_a_copy_of_the_card_does_not(self):
        from wama.common.services.revisions import keep_outputs, record_revision
        from wama.common.utils.file_references import listed_paths
        from wama.common.utils.queue_duplication import duplicate_instance
        for model in self.models:
            app = model._meta.app_label
            keep_outputs(app, keep=20)
            item, field, _rel = self._card(model)
            revision = record_revision(app, item, output_fields=[field])
            item.refresh_from_db()
            kept = [rel for _f, rel in listed_paths(item)]
            self.assertIn(item.kept_outputs[0]['path'], kept,
                          'declared to retention : release, purge and the reference index see it')
            self.assertEqual(revision.number, item.kept_outputs[0]['revision'])
            copy = duplicate_instance(item)
            self.assertEqual([], list(copy.kept_outputs or []))


class KeptVersionsInASurfaceTest(TestCase):
    """The « Versions » brick of a surface (`…/revisions/`, `…/revisions/<n>/`) : each save of the
    edited text file is a revision whose copy is kept, and taking a version back reads THAT copy —
    the live file has moved on since. Held on a probe surface over every installed model carrying
    the list, editing its first file field as text."""

    def setUp(self):
        self.models = _keeping_models()
        if not self.models:
            self.skipTest('aucun modèle installé ne porte la liste des fichiers gardés')
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root, True)
        media = override_settings(MEDIA_ROOT=self.root)
        media.enable()
        self.addCleanup(media.disable)
        self.user = get_user_model().objects.create_user('kept_versions_owner', password='x')
        self.client.force_login(self.user)
        from wama.common.services import revisions
        saved = dict(revisions._KEEPING)
        self.addCleanup(lambda: (revisions._KEEPING.clear(), revisions._KEEPING.update(saved)))

    def _probe(self, model):
        import json

        from wama.common.surfaces import SURFACES, BrickSlot, Surface, register_surface
        from wama.common.tests.tests_queue_delete_contract import _instance
        from wama.common.utils.media_paths import app_media_dir
        app = model._meta.app_label
        field = next(f.name for f in model._meta.concrete_fields if isinstance(f, models.FileField))
        item = _instance(model, self.user)
        rel = f"{app_media_dir(app, self.user.id, 'output')}/versions_{item.pk}.md"
        path = os.path.join(self.root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w', encoding='utf-8') as out:
            out.write('# Fond\nPremier texte.\n')
        setattr(item, field, rel)
        item.save()
        register_surface(Surface(app=app, key='versions_probe', label='Probe', model=model._meta.label,
                                 slots=(BrickSlot('text', 'text_sections', 0, 0, 12, 10),),
                                 reads={}, edits=field))
        self.addCleanup(SURFACES.pop, f'{app}.versions_probe', None)
        base = f'/common/surface/{app}/versions_probe/{item.pk}/'

        def save(text):
            token = self.client.get(base + 'data/').json()['token']
            response = self.client.post(base + 'save/', json.dumps({'value': text, 'base': token}),
                                        content_type='application/json')
            self.assertEqual(200, response.status_code, response.content[:300])
        return app, base, save

    def test_each_save_is_a_version_that_can_be_taken_back(self):
        from wama.common.services.revisions import keep_outputs
        for model in self.models:
            app, base, save = self._probe(model)
            keep_outputs(app, keep=20)
            save('# Fond\nDeuxième texte.\n')
            save('# Fond\nTroisième texte.\n')
            listed = self.client.get(base + 'revisions/').json()
            self.assertTrue(listed['keeps'])
            numbers = [r['number'] for r in listed['revisions']]
            self.assertEqual(sorted(numbers, reverse=True), numbers, 'the most recent first')
            self.assertTrue(all(r['kept'] for r in listed['revisions']))
            oldest = min(numbers)
            back = self.client.get(f'{base}revisions/{oldest}/').json()
            # The state BEFORE the first correction is kept first (`revisions.ensure_kept`,
            # 2026-10-15) : produced before the app kept its outputs, it would be lost otherwise.
            self.assertEqual('# Fond\nPremier texte.\n', back['value'],
                             'the original produced state is kept before it is rewritten in place')
            second = self.client.get(f'{base}revisions/{oldest + 1}/').json()
            self.assertEqual('# Fond\nDeuxième texte.\n', second['value'],
                             'the kept copy, not the live file that moved on')
            self.assertEqual(404, self.client.get(f'{base}revisions/{max(numbers) + 9}/').status_code)

    def test_an_app_that_does_not_keep_lists_no_version(self):
        from wama.common.services import revisions
        for model in self.models:
            app, base, save = self._probe(model)
            revisions._KEEPING.pop(app, None)
            save('# Fond\nAutre texte.\n')
            listed = self.client.get(base + 'revisions/').json()
            self.assertEqual({'revisions': [], 'keeps': False}, listed)
