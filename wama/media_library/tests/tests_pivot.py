"""Le PIVOT d'une nature, appliqué à l'AJOUT (2026-09-30).

`natures.Nature.pivot` était déclaré depuis A′ sans aucun consommateur. Conséquence mesurée : le
bouton « Enregistrer ma voix » du synthesizer produit un `recorded_voice.webm` que le serveur
refusait (« Format non supporté ») depuis février. Désormais une nature déclare `to_pivot` —
ce qu'elle admet À CONDITION de le convertir — et `add_file_to_library` range le fichier dans
son pivot.
"""
import shutil
import subprocess
import tempfile
from pathlib import Path
from unittest import skipUnless

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

from wama.media_library.natures import ASSET_NATURES, natures_as_json


def _ffmpeg():
    try:
        from wama.common.utils.ffmpeg_utils import get_ffmpeg_exe
        return get_ffmpeg_exe()
    except Exception:
        return shutil.which('ffmpeg')


def _webm_bytes(seconds=1):
    """Un vrai fichier webm/opus — ce que produit `MediaRecorder` dans un navigateur."""
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / 'rec.webm'
        subprocess.run([_ffmpeg(), '-nostdin', '-y', '-f', 'lavfi', '-i',
                        f'sine=frequency=220:duration={seconds}', '-c:a', 'libopus', str(out)],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        return out.read_bytes()


class PivotDeclarationTest(TestCase):
    def test_spoken_natures_accept_a_browser_recording_through_their_pivot(self):
        for key in ('voice', 'speech'):
            nature = ASSET_NATURES[key]
            self.assertEqual(nature.pivot, 'wav')
            self.assertIn('webm', nature.to_pivot, key)
            self.assertNotIn('webm', nature.extensions, f'{key} ne STOCKE jamais du webm')

    def test_the_add_gesture_advertises_what_it_converts(self):
        self.assertIn('webm', natures_as_json()['voice']['extensions'])

    def test_a_nature_without_to_pivot_is_unchanged(self):
        self.assertEqual(natures_as_json()['audio_music']['extensions'],
                         list(ASSET_NATURES['audio_music'].extensions))


@skipUnless(_ffmpeg(), 'ffmpeg absent')
class RecordedVoiceIsStoredAsWavTest(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user('pivot_user', password='x')

    def test_add_file_to_library_converts_webm_to_wav(self):
        from wama.media_library.services import add_file_to_library
        asset = add_file_to_library(self.user, 'voice', name='Recorded',
                                    uploaded=SimpleUploadedFile('recorded_voice.webm', _webm_bytes()))
        self.assertTrue(asset.file.name.endswith('.wav'), asset.file.name)
        with open(asset.file.path, 'rb') as fh:
            self.assertEqual(fh.read(4), b'RIFF')
        self.assertAlmostEqual(asset.duration or 0, 1.0, delta=0.3)

    def test_an_unreadable_recording_is_refused_with_a_message(self):
        from wama.media_library.services import LibraryAddRefused, add_file_to_library
        with self.assertRaises(LibraryAddRefused):
            add_file_to_library(self.user, 'voice', name='Broken',
                                uploaded=SimpleUploadedFile('broken.webm', b'not audio'))

    def test_the_synthesizer_record_button_route_accepts_the_recording(self):
        """Le geste RÉEL : la route que poste la modale « Ajouter une voix »."""
        from django.contrib.auth.models import Group
        from wama.accounts.permissions import GROUP_PREFIX
        from wama.media_library.models import UserAsset
        # Le rôle qui ouvre le synthesizer, comme `synthesizer/tests.py` : un test de vue doit
        # FRANCHIR le portier d'app, jamais le contourner.
        group, _ = Group.objects.get_or_create(name=f'{GROUP_PREFIX}communication')
        self.user.groups.add(group)
        client = self.client
        client.force_login(self.user)
        response = client.post('/synthesizer/custom-voices/upload/', {
            'name': 'My recording',
            'audio': SimpleUploadedFile('recorded_voice.webm', _webm_bytes(), content_type='audio/webm'),
        })
        self.assertEqual(response.status_code, 200, response.content)
        asset = UserAsset.objects.get(pk=response.json()['id'])
        self.assertEqual(asset.asset_type, 'voice')
        self.assertTrue(asset.file.name.endswith('.wav'))
