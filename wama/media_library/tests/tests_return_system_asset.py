"""Rendre un asset SYSTÈME à son auteur (2026-09-29, `MEDIA_STORAGE_TIERING §8.6` D27).

Le versement de la galerie (12/09) avait fait des photos personnelles d'un utilisateur des avatars
système, qu'il ne pouvait plus supprimer. La brique les lui rend : asset PRIVÉ, fichier déplacé
dans sa médiathèque, ligne système retirée — et les travaux de l'avatarizer qui citaient l'avatar
PAR SON NOM suivent (holder déclaré par l'app). Médias jetables (runner de test).
"""
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.test import TestCase

from wama.avatarizer.models import AvatarJob
from wama.media_library.models import SystemAsset, UserAsset
from wama.media_library.services import SystemAssetStillNamed, return_system_asset

User = get_user_model()


class ReturnSystemAssetTest(TestCase):

    def setUp(self):
        self.author = User.objects.create_user('asset_author', password='x')
        self.other = User.objects.create_user('asset_other', password='x')
        self.asset = SystemAsset(name='portrait_witness.png', asset_type='avatar')
        self.asset.file.save('portrait_witness.png', ContentFile(b'\x89PNG witness'), save=True)
        self.old_path = self.asset.file.name
        self.job = AvatarJob.objects.create(user=self.author, mode='standalone',
                                            avatar_source='gallery',
                                            avatar_gallery_name='portrait_witness.png')

    def test_the_plan_writes_nothing(self):
        plan = return_system_asset(self.asset, self.author)
        self.assertEqual(1, plan['references'][0]['mine'])
        self.assertTrue(SystemAsset.objects.filter(pk=self.asset.pk).exists())
        self.assertFalse(UserAsset.objects.filter(user=self.author).exists())
        self.assertTrue((Path(settings.MEDIA_ROOT) / self.old_path).is_file())

    def test_applied_the_author_owns_it_and_the_jobs_follow(self):
        plan = return_system_asset(self.asset, self.author, apply=True)
        owned = UserAsset.objects.get(user=self.author, name='portrait_witness.png')
        self.assertEqual('private', owned.visibility)
        self.assertEqual(plan['to'], owned.file.name)
        self.assertTrue(owned.file.name.startswith(f'users/{self.author.id}/'))
        self.assertTrue((Path(settings.MEDIA_ROOT) / owned.file.name).is_file())
        self.assertFalse((Path(settings.MEDIA_ROOT) / self.old_path).exists())
        self.assertNotIn('moved_from', owned.attributes or {})
        self.assertFalse(SystemAsset.objects.filter(pk=self.asset.pk).exists())
        self.job.refresh_from_db()
        self.assertEqual(('upload', owned.file.name, ''),
                         (self.job.avatar_source, self.job.avatar_upload.name,
                          self.job.avatar_gallery_name))

    def test_refused_while_someone_else_names_it(self):
        """Contre-épreuve : le travail d'un AUTRE utilisateur casserait — rien ne bouge."""
        AvatarJob.objects.create(user=self.other, mode='standalone', avatar_source='gallery',
                                 avatar_gallery_name='portrait_witness.png')
        with self.assertRaises(SystemAssetStillNamed):
            return_system_asset(self.asset, self.author, apply=True)
        self.assertTrue(SystemAsset.objects.filter(pk=self.asset.pk).exists())
        self.assertTrue((Path(settings.MEDIA_ROOT) / self.old_path).is_file())
        self.job.refresh_from_db()
        self.assertEqual('gallery', self.job.avatar_source)
