"""Imager — le LOT a un DOMAINE (2026-09-08, décision Fabien : lots vidéo, dont depuis le studio).

`handle_file2img` écrivait `txt2img` et `domain='image'` en dur : un fichier de prompts déposé
sur la card VIDÉO ne pouvait exister. Le domaine est désormais DÉCLARÉ par l'appelant ; ces
tests tiennent les deux faces : vidéo → `txt2vid` dans un lot vidéo avec ses réglages, et
l'ABSENCE de déclaration → image, comme avant (aucun appelant existant ne change de sens).
"""
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from wama.imager.models import GenerationBatch, ImageGeneration

User = get_user_model()


class LotParDomaineTest(TestCase):

    def setUp(self):
        from wama.accounts.permissions import GROUP_PREFIX
        self.user = User.objects.create_user('imager_lot', password='x')
        group, _ = Group.objects.get_or_create(name=f'{GROUP_PREFIX}communication')
        self.user.groups.add(group)
        self.client.force_login(self.user)

    def _lot(self, **post):
        temoin = SimpleUploadedFile('wama_temoin_lot.txt', b'un phare dans la brume\nune foret\n',
                                    content_type='text/plain')
        rep = self.client.post(reverse('imager:import_batch'), {'batch_file': temoin, **post})
        self.assertEqual(200, rep.status_code, rep.content[:200])
        return GenerationBatch.objects.get(id=rep.json()['batch_id'])

    def test_un_lot_declare_video_cree_des_txt2vid_dans_un_lot_video(self):
        lot = self._lot(domain='video', video_duration='4', video_fps='24', video_resolution='720p')
        self.assertEqual('video', lot.domain)
        gens = list(ImageGeneration.objects.filter(user=self.user).order_by('id'))
        self.assertEqual(2, len(gens))
        self.assertTrue(all(g.generation_mode == 'txt2vid' and g.is_video_generation for g in gens))
        self.assertEqual((4.0, 24, '720p'),
                         (gens[0].video_duration, gens[0].video_fps, gens[0].video_resolution))

    def test_sans_domaine_declare_le_lot_reste_image_comme_avant(self):
        lot = self._lot()
        self.assertEqual('image', lot.domain)
        self.assertTrue(all(g.generation_mode == 'txt2img'
                            for g in ImageGeneration.objects.filter(user=self.user)))
