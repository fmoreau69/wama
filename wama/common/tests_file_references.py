"""D20 — un fichier que des cards désignent : le déplacer les fait suivre, le supprimer se confirme.

Décision de Fabien du 2026-09-22 (`MEDIA_STORAGE_TIERING §8.6` D20) :
  * déplacer ou renommer un fichier depuis le gestionnaire met à jour le lien des cards, sans
    rien demander ;
  * supprimer un fichier qu'une card utilise demande une confirmation qui dit combien de cards il
    touche ; confirmée, les cards restent et sont DÉTACHÉES du fichier disparu.

Et la moitié qui rend la première possible : la PROVENANCE est enregistrée par le répartiteur
« Envoyer vers » pour tous les importeurs (un seul sur onze le faisait).

Tout est GÉNÉRIQUE : les témoins sont fabriqués sur chaque app du parc sans la nommer
(`tests_queue_delete_contract._surfaces` / `_instance`). Une app de plus est couverte sans
toucher à ce fichier.
"""
import json
import shutil
import tempfile
from pathlib import Path

from django.db import models
from django.test import TestCase, override_settings
from django.urls import reverse

from wama.common.tests_queue_delete_contract import (SuppressionDansChaqueAppTest, _instance,
                                                     _surfaces)


class _TempMediaMixin:
    """Un `MEDIA_ROOT` jetable : aucun test ne touche un fichier réel."""

    _account_for = SuppressionDansChaqueAppTest._compte_pour

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        setting = override_settings(MEDIA_ROOT=self.tmp)
        setting.enable()
        self.addCleanup(setting.disable)
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def _write(self, rel):
        path = Path(self.tmp) / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'x')
        return rel

    def _fleet(self):
        """(surface, compte, modèle) pour chaque app de file du parc."""
        from wama.common.utils.preview_registry import PreviewRegistry
        for surface, _delete_route, _card_route in _surfaces():
            account = self._account_for(surface)
            model = PreviewRegistry.get_model(surface)
            self.assertIsNotNone(model, f"aucun modèle d'élément déclaré pour {surface}")
            yield surface, account, model

    def _card_pointing_at(self, model, account, rel):
        """Un élément dont le PREMIER champ fichier désigne `rel` (les autres restent vides)."""
        field = next(f for f in model._meta.concrete_fields if isinstance(f, models.FileField))
        el = _instance(model, account)
        for f in model._meta.concrete_fields:
            if isinstance(f, models.FileField):
                setattr(el, f.name, rel if f is field else '')
        el.save()
        return el, field.name

    @staticmethod
    def _temp(account, name):
        return f'users/{account.id}/temp/{name}'


class FileReferencesBrickTest(_TempMediaMixin, TestCase):
    """La brique seule (`common/utils/file_references.py`), sur chaque app du parc."""

    def test_the_fleet_is_measured(self):
        """Non-vacuité : sans les apps de file, les sous-tests ne garderaient rien."""
        self.assertGreaterEqual(len(list(self._fleet())), 11)

    def test_every_card_designating_a_file_is_found_and_only_those(self):
        from wama.common.utils.file_references import direct_references
        for surface, account, model in self._fleet():
            with self.subTest(surface=surface):
                rel = self._write(self._temp(account, f'src_{surface}.bin'))
                el, field = self._card_pointing_at(model, account, rel)
                other, _ = self._card_pointing_at(model, account,
                                                  self._write(self._temp(account, f'o_{surface}.bin')))
                found = {(r['label'], r['pk'], r['field']) for r in direct_references(rel)}
                self.assertIn((model._meta.label, el.pk, field), found)
                self.assertNotIn((model._meta.label, other.pk, field), found,
                                 'une card qui désigne un AUTRE fichier ne doit pas être comptée')

    def test_moving_a_file_repoints_its_cards_and_leaves_the_others(self):
        from wama.common.utils.file_references import repoint
        for surface, account, model in self._fleet():
            with self.subTest(surface=surface):
                old = self._temp(account, f'a_{surface}.bin')
                new = self._temp(account, f'sub/a_{surface}.bin')
                el, field = self._card_pointing_at(model, account, old)
                bystander_rel = self._temp(account, f'b_{surface}.bin')
                bystander, _ = self._card_pointing_at(model, account, bystander_rel)
                counts = repoint(old, new)
                el.refresh_from_db()
                bystander.refresh_from_db()
                self.assertEqual(new, getattr(el, field).name)
                self.assertEqual(bystander_rel, getattr(bystander, field).name,
                                 'contre-épreuve : une card qui ne désignait pas le fichier bouge')
                self.assertGreaterEqual(counts['direct'], 1)

    def test_moving_a_folder_repoints_every_card_below_it(self):
        from wama.common.utils.file_references import repoint
        for surface, account, model in self._fleet():
            with self.subTest(surface=surface):
                el, field = self._card_pointing_at(
                    model, account, self._temp(account, f'dossier_{surface}/deep/f.bin'))
                repoint(self._temp(account, f'dossier_{surface}'),
                        self._temp(account, f'moved_{surface}'), folder=True)
                el.refresh_from_db()
                self.assertEqual(self._temp(account, f'moved_{surface}/deep/f.bin'),
                                 getattr(el, field).name)

    def test_detaching_empties_the_link_and_keeps_the_card(self):
        from wama.common.utils.file_references import detach, direct_references
        for surface, account, model in self._fleet():
            with self.subTest(surface=surface):
                rel = self._temp(account, f'gone_{surface}.bin')
                el, field = self._card_pointing_at(model, account, rel)
                self.assertGreaterEqual(detach(rel), 1)
                self.assertTrue(model.objects.filter(pk=el.pk).exists(), 'la card doit RESTER')
                el.refresh_from_db()
                self.assertFalse(getattr(el, field).name)
                self.assertEqual([], direct_references(rel))

    def test_the_file_managers_own_index_is_never_counted_as_a_card(self):
        """`UserFile` indexe tout le temp : le compter ferait de chaque fichier un fichier « utilisé »."""
        from wama.common.utils.file_references import usage
        from wama.filemanager.models import UserFile
        from wama.common.services.nightly_tests import get_test_user
        user = get_test_user()
        rel = self._write(self._temp(user, 'indexed_only.bin'))
        uf = UserFile.objects.create(user=user, original_name='indexed_only.bin')
        uf.file.name = rel
        uf.save()
        self.assertEqual(0, usage(rel)['count'])

    def test_a_copy_made_from_a_source_is_information_never_a_blocker(self):
        """La card qui a sa COPIE ne perd rien si la source part : `copies`, pas `count`."""
        from wama.common.utils.file_references import usage
        from wama.common.utils.provenance import record_provenance
        surface, account, model = next(self._fleet())
        src = self._write(self._temp(account, 'source.bin'))
        el, field = self._card_pointing_at(model, account, 'users/x/copie.bin')
        record_provenance(el, field, kind='temp', ref=src, user=account)
        u = usage(src)
        self.assertEqual((0, 1), (u['count'], u['copies']))


class FileManagerGesturesTest(_TempMediaMixin, TestCase):
    """Les quatre gestes du gestionnaire, par leurs VUES, sur chaque app du parc."""

    def _login(self, account):
        self.client.force_login(account)

    def _post(self, name, body):
        r = self.client.post(reverse(f'filemanager:{name}'), data=json.dumps(body),
                             content_type='application/json')
        return r, (json.loads(r.content) if r.content else {})

    def test_deleting_a_used_file_asks_first_then_detaches_its_cards(self):
        for surface, account, model in self._fleet():
            with self.subTest(surface=surface):
                self._login(account)
                rel = self._write(self._temp(account, f'used_{surface}.bin'))
                el, field = self._card_pointing_at(model, account, rel)

                r, data = self._post('api_delete', {'path': rel})
                self.assertEqual(409, r.status_code, data)
                self.assertTrue(data['in_use'])
                self.assertGreaterEqual(data['count'], 1)
                self.assertTrue((Path(self.tmp) / rel).exists(),
                                'sans confirmation, le fichier ne doit PAS partir')
                el.refresh_from_db()
                self.assertEqual(rel, getattr(el, field).name, 'ni la card être touchée')

                r, data = self._post('api_delete', {'path': rel, 'confirm': True})
                self.assertEqual(200, r.status_code, data)
                self.assertTrue(data['deleted'])
                self.assertFalse((Path(self.tmp) / rel).exists())
                el.refresh_from_db()
                self.assertFalse(getattr(el, field).name,
                                 'confirmée : la card reste, détachée du fichier disparu')

    def test_deleting_an_unused_file_needs_no_confirmation(self):
        """Contre-épreuve : la confirmation n'est demandée QUE pour un fichier utilisé."""
        surface, account, model = next(self._fleet())
        self._login(account)
        rel = self._write(self._temp(account, 'free.bin'))
        r, data = self._post('api_delete', {'path': rel})
        self.assertEqual(200, r.status_code, data)
        self.assertEqual(0, data['detached'])

    def test_emptying_a_folder_asks_first_when_a_card_uses_a_file_inside(self):
        surface, account, model = next(self._fleet())
        self._login(account)
        rel = self._write(self._temp(account, 'lot/deep/used.bin'))
        el, field = self._card_pointing_at(model, account, rel)
        folder = self._temp(account, 'lot')

        r, data = self._post('api_delete_all', {'path': folder})
        self.assertEqual(409, r.status_code, data)
        self.assertTrue((Path(self.tmp) / rel).exists())

        r, data = self._post('api_delete_all', {'path': folder, 'confirm': True})
        self.assertEqual(200, r.status_code, data)
        self.assertEqual(1, data['detached'])
        el.refresh_from_db()
        self.assertFalse(getattr(el, field).name)

    def test_moving_or_renaming_a_used_file_makes_its_cards_follow_silently(self):
        for surface, account, model in self._fleet():
            with self.subTest(surface=surface):
                self._login(account)
                rel = self._write(self._temp(account, f'mv_{surface}.bin'))
                (Path(self.tmp) / self._temp(account, f'dest_{surface}')).mkdir(parents=True)
                el, field = self._card_pointing_at(model, account, rel)

                r, data = self._post('api_move', {'source': rel,
                                                  'destination': self._temp(account, f'dest_{surface}')})
                self.assertEqual(200, r.status_code, data)
                el.refresh_from_db()
                self.assertEqual(data['new_path'], getattr(el, field).name)

                r, data = self._post('api_rename', {'path': data['new_path'],
                                                    'new_name': f'renamed_{surface}.bin'})
                self.assertEqual(200, r.status_code, data)
                el.refresh_from_db()
                self.assertEqual(self._temp(account, f'dest_{surface}/renamed_{surface}.bin'),
                                 getattr(el, field).name)
                self.assertTrue((Path(self.tmp) / getattr(el, field).name).exists(),
                                'le lien de la card désigne le fichier là où il est')


class SendToRecordsProvenanceTest(_TempMediaMixin, TestCase):
    """« Envoyer vers » : chaque card créée depuis le temp se souvient de sa source.

    Le répartiteur enregistre UNE fois pour tous les importeurs (2026-09-22 : un seul sur onze
    le faisait). Mesuré par la vue, pour chaque app qui reçoit, avec un fichier réel qu'elle
    accepte — sans quoi la provenance de ses cards ne serait jamais vérifiée.
    """

    #: Une source fabriquée par extension : du texte, une image PNG, un son WAV réels. Une app
    #: dont aucune extension n'a de fabrique est SAUTÉE en le disant (`skipped`), jamais en
    #: silence.
    @staticmethod
    def _make(path: Path):
        ext = path.suffix.lower()
        if ext in ('.txt', '.md', '.csv'):
            path.write_text('Bonjour. Ceci est un témoin.', encoding='utf-8')
        elif ext == '.png':
            from PIL import Image
            Image.new('RGB', (8, 8), (200, 10, 10)).save(path)
        elif ext == '.wav':
            import wave
            with wave.open(str(path), 'wb') as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(8000)
                w.writeframes(b'\x00\x00' * 800)
        else:
            return False
        return True

    def test_every_card_created_by_send_to_carries_its_source(self):
        from wama.common.app_registry import APP_CATALOG
        from wama.common.services.nightly_tests import get_test_user
        from wama.common.utils.file_references import direct_references
        from wama.common.utils.provenance import provenance_of
        from wama.filemanager.views import IMPORTERS
        from django.apps import apps as django_apps

        user = get_test_user()
        self.client.force_login(user)
        covered, skipped = [], []
        # Chaque extension fabricable qu'une app accepte : une app a plusieurs VOIES d'import
        # (l'imager : un .txt devient un lot de prompts, une image une card de référence).
        cases = []
        for app in IMPORTERS:
            exts = {e.lower() for e in (APP_CATALOG.get(app) or {}).get('input_extensions', ())}
            mine = [e for e in ('.txt', '.png', '.wav') if e in exts]
            if not mine:
                skipped.append(app)
            cases += [(app, e) for e in mine]
        for app, ext in cases:
            with self.subTest(app=app, ext=ext):
                rel = self._temp(user, f'send_{app}_{ext[1:]}{ext}')
                path = Path(self.tmp) / rel
                path.parent.mkdir(parents=True, exist_ok=True)
                self._make(path)
                r = self.client.post(reverse('filemanager:api_import'),
                                     data=json.dumps({'path': rel, 'app': app}),
                                     content_type='application/json')
                data = json.loads(r.content)
                self.assertTrue(data.get('imported'), data)
                copy = data.get('path')
                refs = direct_references(copy) if copy and copy != rel else []
                for ref in refs:
                    el = django_apps.get_model(ref['label']).objects.get(pk=ref['pk'])
                    prov = provenance_of(el, ref['field'])
                    self.assertIsNotNone(prov, f"{ref['label']} #{ref['pk']} : aucune provenance")
                    self.assertEqual(('temp', rel), (prov.kind, prov.ref))
                if refs:
                    covered.append(app)
        # Non-vacuité : le câblage est prouvé sur le parc, pas sur une app. Mesuré le 2026-09-22 :
        # 8 apps (les deux analyseurs n'acceptent que de la vidéo, qu'on ne fabrique pas ici).
        self.assertGreaterEqual(len(set(covered)), 8,
                                f'couvertes {sorted(set(covered))}, sautées {skipped}')

    def test_the_source_kind_follows_the_path_it_comes_from(self):
        from wama.common.utils.provenance import kind_of
        self.assertEqual('temp', kind_of('users/7/temp/a.png'))
        self.assertEqual('mount', kind_of('mounts/3/photos/a.png'))
        self.assertEqual('app', kind_of('users/7/describer/output/a.txt'))
