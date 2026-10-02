"""La PURGE automatique suit la même règle que la suppression d'une card — `MEDIA_STORAGE_TIERING §8.6`.

POURQUOI (2026-09-22). `services/retention.py` efface chaque nuit les médias expirés de six
modèles, et n'avait AUCUN test : un geste qui détruit des fichiers sans intervention humaine, sans
contrat. Or c'est exactement là qu'une règle manquante coûte le plus — personne ne regarde.

Ce que le contrat exige, pour CHAQUE modèle déclaré (`RETENTION_MODELS`), sans en nommer un :
  - un élément expiré dont les fichiers vivent CHEZ l'app : l'élément et ses fichiers partent ;
  - un élément expiré qui ne fait que RÉFÉRENCER des fichiers de l'utilisateur : les fichiers restent ;
  - un élément expiré dont les fichiers sont PARTAGÉS par une copie récente : ils restent, la copie
    les utilise encore ;
  - les listes de chemins (`path_lists`) suivent la règle de propriété, comme les champs.

⚠ Ce contrat a été retourné le matin du 2026-10-01 (« la purge LIBÈRE ») puis RÉTABLI le jour même
sur la précision de Fabien : *« si l'utilisateur applique une période de rétention qui n'est pas
nulle, c'est qu'il souhaite la suppression des fichiers au bout de la durée qu'il indique »*. La
décision D34 (prévenir, l'utilisateur supprime) ne vise que le RETRAIT d'une card par l'utilisateur.
"""
import shutil
import tempfile
from datetime import timedelta
from pathlib import Path

from django.contrib.auth import get_user_model
from django.db import models
from django.test import TestCase, override_settings
from django.utils import timezone


class RetentionFollowsTheDeletionRuleTest(TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        setting = override_settings(MEDIA_ROOT=self.tmp)
        setting.enable()
        self.addCleanup(setting.disable)
        self.addCleanup(shutil.rmtree, self.tmp, True)
        from wama.accounts.models import UserProfile
        self.user = get_user_model().objects.create_user('retention_contrat', password='x')
        profile, _created = UserProfile.objects.get_or_create(user=self.user)
        profile.media_retention_days = 1
        profile.save()

    def _file(self, rel):
        path = Path(self.tmp) / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'x')
        return path

    def _witness(self, model, folder, expired=True):
        """Un élément dont chaque champ fichier désigne un vrai fichier sous `folder`."""
        from wama.common.services.retention import RETENTION_MODELS
        from wama.common.tests.tests_queue_delete_contract import _instance
        item = _instance(model, self.user)
        files = []
        for f in model._meta.concrete_fields:
            if isinstance(f, models.FileField):
                rel = f'{folder}/retention_{item.pk}_{f.name}.bin'
                files.append(self._file(rel))
                setattr(item, f.name, rel)
        item.save()
        if expired:
            # Le champ de date DÉCLARÉ (`anonymizer.Media` : `uploaded_at`, 2026-10-02).
            date_field = next((e.get('date', 'created_at') for e in RETENTION_MODELS
                               if e['model'] == model._meta.label), 'created_at')
            model.objects.filter(pk=item.pk).update(
                **{date_field: timezone.now() - timedelta(days=30)})
        return item, files

    def _models(self):
        from django.apps import apps
        from wama.common.services.retention import RETENTION_MODELS
        declared = [(apps.get_model(e['model']), e.get('path_lists', [])) for e in RETENTION_MODELS]
        self.assertGreaterEqual(len(declared), 5, 'la rétention ne déclare presque rien : garde affaiblie')
        return declared

    def test_every_queue_app_is_under_retention(self):
        # D9 (2026-10-02) : cinq des dix apps de file étaient hors rétention — la durée choisie au
        # profil ne valait rien pour elles, sans que rien ne le dise. Toute app de file en relève.
        from wama.common.services.retention import RETENTION_MODELS
        from wama.common.tests.tests_queue_delete_contract import _surfaces
        from wama.common.utils.preview_registry import PreviewRegistry
        declared = {e['model'] for e in RETENTION_MODELS}
        missing = []
        for surface, _delete, _card in _surfaces():
            model = PreviewRegistry.get_model(surface)
            if model is not None and not model._meta.app_label.endswith('_01') \
                    and model._meta.label not in declared:
                missing.append(model._meta.label)
        self.assertEqual([], missing, 'apps de file hors rétention')

    def _home(self, model):
        from wama.common.utils.media_paths import app_media_dir
        return app_media_dir(model._meta.app_label, self.user.id, 'output')

    def test_expired_items_lose_their_own_files_and_keep_the_ones_they_reference(self):
        from wama.common.services.retention import purge_expired_media
        cases = []
        for model, _lists in self._models():
            owned, owned_files = self._witness(model, self._home(model))
            referenced, ref_files = self._witness(model, f'users/{self.user.id}/temp')
            cases.append((model, owned, owned_files, referenced, ref_files))
        purge_expired_media()
        for model, owned, owned_files, referenced, ref_files in cases:
            with self.subTest(model=model._meta.label):
                self.assertFalse(model.objects.filter(pk__in=[owned.pk, referenced.pk]).exists(),
                                 'un élément expiré a survécu à la purge')
                self.assertEqual([], [p.name for p in owned_files if p.exists()],
                                 'la purge a laissé les fichiers de l’app sur le disque — la '
                                 'rétention choisie par l’utilisateur VAUT suppression')
                self.assertEqual([], [p.name for p in ref_files if not p.exists()],
                                 'la purge a DÉTRUIT des fichiers que l’élément ne faisait que '
                                 'référencer')

    def test_a_file_shared_by_a_recent_copy_survives_the_purge(self):
        from wama.common.services.retention import purge_expired_media
        from wama.common.utils.queue_duplication import duplicate_instance
        cases = []
        for model, _lists in self._models():
            original, files = self._witness(model, self._home(model))
            copy = duplicate_instance(original)          # récente : elle, n'expire pas
            cases.append((model, original, copy, files))
        purge_expired_media()
        for model, original, copy, files in cases:
            with self.subTest(model=model._meta.label):
                self.assertFalse(model.objects.filter(pk=original.pk).exists())
                self.assertTrue(model.objects.filter(pk=copy.pk).exists())
                self.assertEqual([], [p.name for p in files if not p.exists()],
                                 'la purge a détruit un fichier que la COPIE récente utilise encore')

    def test_path_lists_follow_the_ownership_rule(self):
        from wama.common.services.retention import purge_expired_media
        cases = []
        for model, lists in self._models():
            for field in lists:
                item, _files = self._witness(model, self._home(model))
                own = self._file(f'{self._home(model)}/liste_{item.pk}.png')
                ref = self._file(f'users/{self.user.id}/temp/liste_{item.pk}.png')
                model.objects.filter(pk=item.pk).update(**{field: [
                    str(own.relative_to(self.tmp)).replace('\\', '/'),
                    str(ref.relative_to(self.tmp)).replace('\\', '/')]})
                cases.append((model, field, own, ref))
        self.assertTrue(cases, 'aucune liste de chemins déclarée : le contrat ne mesure rien')
        purge_expired_media()
        for model, field, own, ref in cases:
            with self.subTest(model=model._meta.label, field=field):
                self.assertFalse(own.exists(), 'un chemin de la liste, chez l’app, est resté')
                self.assertTrue(ref.exists(), 'un chemin de la liste, HORS de l’app, a été détruit')


class TempFolderRetentionTest(TestCase):
    """Le DOSSIER TEMPORAIRE a sa propre durée (2026-10-02, D9 — décision de Fabien : deux réglages,
    la médiathèque sans durée, défaut illimité). Un fichier qu'une card désigne n'est JAMAIS purgé."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        setting = override_settings(MEDIA_ROOT=self.tmp, WAMA_MAX_RETENTION_DAYS=0)
        setting.enable()
        self.addCleanup(setting.disable)
        self.addCleanup(shutil.rmtree, self.tmp, True)
        from wama.accounts.models import UserProfile
        self.user = get_user_model().objects.create_user('temp_retention', password='x')
        self.profile, _created = UserProfile.objects.get_or_create(user=self.user)

    def _file(self, rel, age_days):
        import os
        path = Path(self.tmp) / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'x')
        stamp = (timezone.now() - timedelta(days=age_days)).timestamp()
        os.utime(path, (stamp, stamp))
        return path

    def test_the_default_is_unlimited(self):
        from wama.accounts.models import UserProfile
        self.assertEqual(0, UserProfile._meta.get_field('temp_retention_days').default)
        old = self._file(f'users/{self.user.id}/temp/vieux.png', 400)
        from wama.common.services.retention import purge_expired_temp
        purge_expired_temp()
        self.assertTrue(old.exists(), 'durée illimitée : rien ne doit partir')

    def test_old_unused_temp_files_go_and_designated_or_recent_ones_stay(self):
        from wama.common.services.retention import purge_expired_temp, upcoming_temp_expirations
        from wama.common.tests.tests_queue_delete_contract import _instance
        from wama.describer.models import Description
        self.profile.temp_retention_days = 10
        self.profile.save()
        old = self._file(f'users/{self.user.id}/temp/sous/vieux.png', 30)
        designated = self._file(f'users/{self.user.id}/temp/designe.png', 30)
        recent = self._file(f'users/{self.user.id}/temp/recent.png', 2)
        soon = self._file(f'users/{self.user.id}/temp/bientot.png', 9)
        elsewhere = self._file(f'users/{self.user.id}/describer/input/hors_temp.png', 30)
        card = _instance(Description, self.user)
        card.input_file = f'users/{self.user.id}/temp/designe.png'
        card.save()
        self.assertEqual({self.user.id: 1}, upcoming_temp_expirations(3), 'pré-avis : le fichier de J-1')
        self.assertEqual(1, purge_expired_temp()['deleted'])
        self.assertFalse(old.exists(), 'un vieux fichier inutilisé du temp est resté')
        self.assertTrue(designated.exists(), 'un fichier qu’une card DÉSIGNE a été supprimé')
        self.assertTrue(recent.exists() and soon.exists(), 'un fichier récent a été supprimé')
        self.assertTrue(elsewhere.exists(), 'la purge du temp a touché HORS du temp')

    def test_saving_one_duration_keeps_the_other(self):
        import json
        self.profile.temp_retention_days = 15
        self.profile.save()
        self.client.force_login(self.user)
        from django.urls import reverse
        answer = self.client.post(reverse('accounts:profile-retention'),
                                  json.dumps({'media_retention_days': 7}),
                                  content_type='application/json').json()
        self.assertEqual((7, 15), (answer['media_retention_days'], answer['temp_retention_days']))
