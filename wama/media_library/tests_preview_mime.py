"""L'aperçu de la médiathèque lit le type du FICHIER, jamais celui du NOM d'asset.

Constat du 2026-09-21 : « smoke-0802-desc-text », `text/plain` bien posé en base, affichait
« Preview not available » — `assetToPreviewData` devinait le MIME depuis le LIBELLÉ (qui n'a pas
d'extension) et jetait celui que le serveur envoie. La correction avait été attestée par un
script de brouillon ; un smoke lancé à la main n'est pas une garde, d'où ce fichier.

Même patron que `common/tests_queue_dnd.py` : V8 embarqué (`py_mini_racer`), les fonctions
extraites et exécutées seules (le module entier touche au DOM au chargement).

⚠ Identifiants en anglais, noms de tests compris ; commentaires et docstrings en français.
"""
import json
import re
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

SOURCE = Path(settings.BASE_DIR) / 'wama/media_library/static/media_library/js/media-library.js'
SERVED = Path(settings.BASE_DIR) / 'staticfiles/media_library/js/media-library.js'
FUNCTIONS = ('fileExtension', 'storedMime', 'assetToPreviewData')


def _extract(src, name):
    match = re.search(r'\n    function ' + name + r'\(.*?\n    }\n', src, re.S)
    return match.group(0) if match else None


class PreviewMimeTest(SimpleTestCase):

    def setUp(self):
        try:
            from py_mini_racer import MiniRacer
        except ImportError:
            self.skipTest('py_mini_racer absent de ce venv : pas de V8 pour exécuter la brique')
        src = SOURCE.read_text(encoding='utf-8')
        self.ctx = MiniRacer()
        self.ctx.eval('(function(){' + src + '\n})')           # parse du module ENTIER
        parts = [_extract(src, f) for f in FUNCTIONS]
        self.assertTrue(all(parts), 'une des fonctions d\'aperçu a disparu ou changé de forme')
        self.ctx.eval("var AUDIO_TYPES = ['voice','audio_music','audio_sfx']; "
                      "var currentType = 'document';\n" + ''.join(parts))

    def _mime(self, asset, asset_type):
        return self.ctx.eval('assetToPreviewData(' + json.dumps(dict(asset, _assetType=asset_type))
                             + ').mime_type')

    def test_a_document_without_extension_in_its_name_is_previewed_from_its_stored_type(self):
        """Le cas SIGNALÉ."""
        asset = {'name': 'smoke-0802-desc-text', 'mime_type': 'text/plain',
                 'file_url': '/media/users/1/media_library/assets/smoke-0802-desc-text.txt'}
        self.assertEqual('text/plain', self._mime(asset, 'document'))

    def test_without_a_stored_type_the_file_extension_decides_not_the_name(self):
        asset = {'name': 'Rapport final', 'mime_type': '', 'file_url': '/media/x/rapport.pdf?v=2'}
        self.assertEqual('application/pdf', self._mime(asset, 'document'))

    def test_a_generic_stored_type_is_not_trusted(self):
        asset = {'name': 'notes', 'mime_type': 'application/octet-stream', 'file_url': '/media/x/notes.md'}
        self.assertEqual('text/plain', self._mime(asset, 'document'))

    def test_counter_proofs_unchanged_families(self):
        """Contre-épreuves : ce qui marchait avant marche pareil."""
        cases = [
            ({'name': 'lettre', 'mime_type': '', 'file_url': '/media/x/lettre.docx'},
             'document', 'application/octet-stream'),
            ({'name': 'Ma musique', 'mime_type': '', 'file_url': '/media/x/piste.mp3'},
             'audio_music', 'audio/mpeg'),
            ({'name': 'v', 'mime_type': 'audio/wav', 'file_url': '/media/s/v.wav'}, 'voice', 'audio/wav'),
            ({'name': 'objet', 'mime_type': '', 'file_url': '/media/x/objet.glb'},
             'object3d', 'model/gltf-binary'),
        ]
        for asset, asset_type, expected in cases:
            self.assertEqual(expected, self._mime(asset, asset_type), asset)


class ServedCopyTest(SimpleTestCase):

    def test_the_served_copy_matches_the_source(self):
        """`staticfiles/` est ce qui est SERVI : une correction non recopiée n'existe pas pour
        l'utilisateur."""
        if not SERVED.exists():
            self.skipTest('pas de copie servie dans cet arbre')
        self.assertEqual(SOURCE.read_bytes(), SERVED.read_bytes())
