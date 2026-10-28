"""L'aperçu de la médiathèque lit le type que le SERVEUR résout, jamais un type deviné.

Deux étapes vécues. Le 2026-09-21 : « smoke-0802-desc-text », `text/plain` bien posé en base,
affichait « Preview not available » — `assetToPreviewData` devinait le MIME depuis le LIBELLÉ (qui
n'a pas d'extension). Le 2026-10-28 : la page devinait encore par la NATURE de l'onglet (toute
image en `image/jpeg`, toute vidéo en `video/mp4`, rien pour une partition) alors que le serveur lui
envoyait déjà `preview_mime` (`media_library/views.py::_preview_mime`), que la fenêtre de sélection
lisait. La page lit désormais ce champ et rien d'autre ; la résolution elle-même (type stocké, sinon
celui du fichier) est gardée côté serveur par `tests_picker_list.PreviewMimeForThePickerTest`.

Même patron que `common/tests/tests_queue_dnd.py` : V8 embarqué (`py_mini_racer`), la fonction
extraite et exécutée seule (le module entier touche au DOM au chargement).

⚠ Identifiants en anglais, noms de tests compris ; commentaires et docstrings en français.
"""
import json
import re
from pathlib import Path

from django.conf import settings
from django.contrib.auth.models import User
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from wama.media_library.models import SystemAsset, UserAsset

SOURCE = Path(settings.BASE_DIR) / 'wama/media_library/static/media_library/js/media-library.js'
SERVED = Path(settings.BASE_DIR) / 'staticfiles/media_library/js/media-library.js'


def _extract(src, name):
    match = re.search(r'\n    function ' + name + r'\(.*?\n    }\n', src, re.S)
    return match.group(0) if match else None


class PreviewMimeTest(SimpleTestCase):

    def setUp(self):
        try:
            from py_mini_racer import MiniRacer
        except ImportError:
            self.skipTest('py_mini_racer absent de ce venv : pas de V8 pour exécuter la brique')
        self.src = SOURCE.read_text(encoding='utf-8')
        self.ctx = MiniRacer()
        self.ctx.eval('(function(){' + self.src + '\n})')           # parse du module ENTIER
        self.part = _extract(self.src, 'assetToPreviewData')
        self.assertTrue(self.part, 'la fonction d\'aperçu a disparu ou changé de forme')
        self.ctx.eval(self.part)

    def _mime(self, asset):
        return self.ctx.eval('assetToPreviewData(' + json.dumps(asset) + ').mime_type')

    def test_the_type_resolved_by_the_server_is_the_one_shown(self):
        """Le cas SIGNALÉ le 21/09 : un nom sans extension, un type stocké qui dit quelque chose."""
        asset = {'name': 'smoke-0802-desc-text', 'mime_type': 'text/plain', 'preview_mime': 'text/plain',
                 'file_url': '/media/users/1/media_library/assets/smoke-0802-desc-text.txt'}
        self.assertEqual('text/plain', self._mime(asset))

    def test_an_image_keeps_its_real_type(self):
        """Mesuré le 28/10 : deux avatars PNG étaient montrés comme `image/jpeg`."""
        asset = {'name': 'portrait', 'preview_mime': 'image/png', 'file_url': '/media/x/portrait.png'}
        self.assertEqual('image/png', self._mime(asset))

    def test_nothing_is_guessed_from_the_nature_or_the_name(self):
        """Sans le champ du serveur, la page ne devine plus : ni par l'onglet, ni par l'extension."""
        self.assertEqual('', self._mime({'name': 'clip.mp4', 'file_url': '/media/x/clip.mp4'}))
        for guess in ("'image/jpeg'", "'video/mp4'", "'audio/wav'", 'storedMime', 'fileExtension'):
            self.assertNotIn(guess, self.part, guess)

    def test_the_rest_of_the_preview_data_is_unchanged(self):
        """Contre-épreuve : adresse, nom, durée et propriétés passent comme avant."""
        asset = {'name': 'v', 'preview_mime': 'audio/wav', 'file_url': '/media/s/v.wav',
                 'duration': '0:03', 'file_size': '12 Ko'}
        data = self.ctx.eval('assetToPreviewData(' + json.dumps(asset) + ')')
        self.assertEqual({'url': '/media/s/v.wav', 'name': 'v', 'mime_type': 'audio/wav',
                          'duration': '0:03', 'properties': '12 Ko'}, dict(data))


class EveryListTheLibraryReadsCarriesTheTypeTest(TestCase):
    """La page ne devine plus : chaque liste qu'elle lit doit donc porter `preview_mime`, assets
    personnels comme assets système (les deux onglets d'une même nature)."""

    def setUp(self):
        self.me = User.objects.create_user('library_mime', password='x')
        self.client.force_login(self.me)

    def test_the_user_list_carries_the_preview_type(self):
        UserAsset.objects.create(user=self.me, name='mine', asset_type='image',
                                 file='users/1/media_library/assets/mine.png', mime_type='')
        data = self.client.get(reverse('media_library:api_list'), {'type': 'image'}).json()
        asset = next(a for a in data['assets'] if a['name'] == 'mine')
        self.assertEqual('image/png', asset['preview_mime'])

    def test_the_system_list_carries_the_preview_type(self):
        SystemAsset.objects.create(name='gallery_mime', asset_type='avatar',
                                   file='media_library/system/avatar/gallery_mime.png', mime_type='')
        data = self.client.get(reverse('media_library:api_system_list'), {'type': 'avatar'}).json()
        asset = next(a for a in data['assets'] if a['name'] == 'gallery_mime')
        self.assertEqual('image/png', asset['preview_mime'])


class ServedCopyTest(SimpleTestCase):

    def test_the_served_copy_matches_the_source(self):
        """`staticfiles/` est ce qui est SERVI : une correction non recopiée n'existe pas pour
        l'utilisateur."""
        if not SERVED.exists():
            self.skipTest('pas de copie servie dans cet arbre')
        self.assertEqual(SOURCE.read_bytes(), SERVED.read_bytes())
