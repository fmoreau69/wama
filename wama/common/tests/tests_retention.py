"""La PURGE automatique suit la même règle que la suppression d'une card — `MEDIA_STORAGE_TIERING §8.6`.

POURQUOI (2026-09-22). `services/retention.py` efface chaque nuit les médias expirés de six
modèles, et n'avait AUCUN test : un geste qui détruit des fichiers sans intervention humaine, sans
contrat. Or c'est exactement là qu'une règle manquante coûte le plus — personne ne regarde.

Ce que le contrat exige, pour CHAQUE modèle déclaré (`RETENTION_MODELS`), sans en nommer un :
  - un élément expiré dont les fichiers vivent CHEZ l'app : l'élément part, ses fichiers sont
    LIBÉRÉS (restent sur le disque, signalés à l'utilisateur) ;
  - un élément expiré qui ne fait que RÉFÉRENCER des fichiers de l'utilisateur : les fichiers
    restent, sans être signalés ;
  - un élément expiré dont les fichiers sont PARTAGÉS par une copie récente : ils restent, la copie
    les utilise encore, et rien n'est annoncé orphelin ;
  - les listes de chemins (`path_lists`) suivent la règle de propriété, comme les champs.

⚠ RÉÉCRIT LE 2026-10-01 (décision de Fabien du 30/09, `MEDIA_STORAGE_TIERING` D34) : la purge ne
SUPPRIME plus aucun fichier — « la suppression est un geste explicite de l'utilisateur, mais il
est prévenu ». Elle libère ; la règle de propriété décide QUI est prévenu de quoi.
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
            model.objects.filter(pk=item.pk).update(created_at=timezone.now() - timedelta(days=30))
        return item, files

    def _models(self):
        from django.apps import apps
        from wama.common.services.retention import RETENTION_MODELS
        declared = [(apps.get_model(e['model']), e.get('path_lists', [])) for e in RETENTION_MODELS]
        self.assertGreaterEqual(len(declared), 5, 'la rétention ne déclare presque rien : garde affaiblie')
        return declared

    def _home(self, model):
        from wama.common.utils.media_paths import app_media_dir
        return app_media_dir(model._meta.app_label, self.user.id, 'output')

    def _released(self, files):
        """Les témoins signalés comme libérés (une ligne `ReleasedFile` pour leur chemin)."""
        from wama.common.models import ReleasedFile
        rels = {p.relative_to(self.tmp).as_posix(): p.name for p in files}
        noted = ReleasedFile.objects.filter(path__in=list(rels)).values_list('path', flat=True)
        return sorted(rels[r] for r in noted)

    def test_expired_items_release_their_own_files_and_keep_the_ones_they_reference(self):
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
                self.assertEqual([], [p.name for p in owned_files if not p.exists()],
                                 'la purge a SUPPRIMÉ des fichiers : elle doit les libérer')
                self.assertEqual(sorted(p.name for p in owned_files), self._released(owned_files),
                                 'les fichiers de l’app ne sont pas signalés comme libérés')
                self.assertEqual([], [p.name for p in ref_files if not p.exists()],
                                 'la purge a DÉTRUIT des fichiers que l’élément ne faisait que '
                                 'référencer')
                self.assertEqual([], self._released(ref_files),
                                 'un fichier seulement RÉFÉRENCÉ est signalé — il a son propre maître')

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
                self.assertEqual([], self._released(files),
                                 'un fichier que la COPIE récente utilise encore est annoncé orphelin')

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
                self.assertTrue(own.exists(), 'un chemin de la liste, chez l’app, a été SUPPRIMÉ')
                self.assertEqual([own.name], self._released([own]),
                                 'un chemin de la liste, chez l’app, n’est pas signalé comme libéré')
                self.assertTrue(ref.exists(), 'un chemin de la liste, HORS de l’app, a été détruit')
                self.assertEqual([], self._released([ref]),
                                 'un chemin de la liste, HORS de l’app, est signalé comme libéré')
