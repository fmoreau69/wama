"""La VIGNETTE d'un fichier est une brique commune : `WamaMediaPreview.tileHtml` (2026-10-28).

Trois surfaces l'écrivaient à leur main — la grille d'une sortie multiple (`media-preview.js`), la
fenêtre de sélection (`media-picker.js`) et la médiathèque (`media-library.js`) —, et la médiathèque
la décidait par la NATURE de l'onglet, pas par le fichier (reste ④ du chantier aperçu,
`ROUTE §F3b`). La brique décide par le TYPE (`mime_type`) : image, 1ʳᵉ image d'une vidéo, sinon une
icône ; chaque surface n'y met que son cadre.

V8 embarqué (`py_mini_racer`) : les fonctions pures extraites et exécutées seules, le module entier
parsé (il touche au DOM au chargement).

⚠ Identifiants en anglais, noms de tests compris ; commentaires et docstrings en français.
"""
import json
import re
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

ROOT = Path(settings.BASE_DIR)
PREVIEW = 'common/static/common/js/media-preview.js'
PICKER = 'common/static/common/js/media-picker.js'
LIBRARY = 'media_library/static/media_library/js/media-library.js'


def _source(rel):
    return (ROOT / 'wama' / rel).read_text(encoding='utf-8')


def _extract(src, name):
    match = re.search(r'\n    function ' + name + r'\(.*?\n    }\n', src, re.S)
    return match.group(0) if match else None


class TileTest(SimpleTestCase):

    def setUp(self):
        try:
            from py_mini_racer import MiniRacer
        except ImportError:
            self.skipTest('py_mini_racer absent de ce venv : pas de V8 pour exécuter la brique')
        src = _source(PREVIEW)
        self.ctx = MiniRacer()
        self.ctx.eval('(function(){' + src + '\n})')            # parse du module ENTIER
        parts = [_extract(src, f) for f in ('escapeHtml', 'tileIcon', 'tileHtml')]
        self.assertTrue(all(parts), 'une fonction de la vignette a disparu ou changé de forme')
        self.ctx.eval(''.join(parts))

    def _tile(self, data, opts=None):
        return self.ctx.eval('tileHtml(%s, %s)' % (json.dumps(data), json.dumps(opts or {})))

    def test_an_image_shows_itself_in_the_frame_of_its_surface(self):
        html = self._tile({'url': '/media/x/a.png', 'mime_type': 'image/png'},
                          {'className': 'asset-preview-img', 'alt': 'portrait'})
        self.assertTrue(html.startswith('<img src="/media/x/a.png"'), html)
        self.assertIn('class="asset-preview-img"', html)
        self.assertIn('alt="portrait"', html)
        self.assertIn('loading="lazy"', html)

    def test_a_video_shows_its_first_frame_without_loading_the_whole_file(self):
        html = self._tile({'url': '/media/x/clip.webm', 'mime_type': 'video/webm'})
        self.assertIn('src="/media/x/clip.webm#t=0.1"', html)
        self.assertIn('preload="metadata"', html)
        self.assertIn('muted', html)

    def test_what_does_not_show_itself_gets_the_icon_of_its_family(self):
        cases = [('audio/mpeg', 'fa-music'), ('application/pdf', 'fa-file-pdf'),
                 ('text/plain', 'fa-file-lines'), ('model/gltf-binary', 'fa-cube'),
                 ('application/zip', 'fa-file'), ('', 'fa-file')]
        for mime, icon in cases:
            html = self._tile({'url': '/media/x/f', 'mime_type': mime})
            self.assertTrue(html.startswith('<i class="fas ' + icon), (mime, html))

    def test_the_type_decides_not_the_nature(self):
        """Le défaut de la médiathèque : un asset de nature « avatar » qui est un objet 3D."""
        html = self._tile({'url': '/media/x/avatar.glb', 'mime_type': 'model/gltf-binary'},
                          {'className': 'asset-preview-img', 'icon': 'fa-user-astronaut'})
        self.assertNotIn('<img', html)
        self.assertIn('fa-user-astronaut', html)

    def test_a_file_without_address_is_never_drawn_as_media(self):
        self.assertNotIn('<img', self._tile({'url': '', 'mime_type': 'image/png'}))

    def test_the_icon_can_be_boxed_and_the_surface_keeps_its_classes(self):
        html = self._tile({'url': '/media/x/a.mp3', 'mime_type': 'audio/mpeg'},
                          {'iconClass': 'fa-2x text-secondary',
                           'iconBox': {'className': 'd-flex', 'style': 'height:80px'}})
        self.assertEqual('<div class="d-flex" style="height:80px"><i class="fas fa-music fa-2x '
                         'text-secondary"></i></div>', html)

    def test_addresses_and_labels_are_escaped(self):
        html = self._tile({'url': '/media/x/a"b.png', 'mime_type': 'image/png'}, {'alt': '<x>'})
        self.assertIn('src="/media/x/a&quot;b.png"', html)
        self.assertIn('alt="&lt;x&gt;"', html)


class EverySurfaceDrawsItsThumbnailThroughTheBrickTest(SimpleTestCase):
    """Les trois surfaces appellent la brique, et aucune ne réécrit la règle à côté."""

    def test_the_three_surfaces_call_the_brick(self):
        self.assertIn('tileHtml(f, {', _source(PREVIEW))                  # grille d'une sortie multiple
        self.assertIn('WamaMediaPreview.tileHtml(data, {', _source(PICKER))
        self.assertIn('WamaMediaPreview.tileHtml(tile, tileOpts)', _source(LIBRARY))

    def test_the_first_frame_rule_lives_in_the_brick_only(self):
        for rel in (PICKER, LIBRARY):
            src = _source(rel)
            self.assertNotIn('#t=0.1', src, rel)
            self.assertNotIn('<video ', src, rel)
        self.assertEqual(1, _source(PREVIEW).count("'#t=0.1"), 'une seule écriture de la 1ʳᵉ image')

    def test_the_library_no_longer_decides_the_thumbnail_by_the_nature(self):
        src = _source(LIBRARY)
        self.assertNotIn('<img class="asset-preview-img"', src)
        self.assertNotIn("['image', 'avatar'].includes(currentType)", src)

    def test_the_picker_no_longer_guesses_a_type_from_the_nature(self):
        src = _source(PICKER)
        self.assertNotIn("'image/*'", src)
        self.assertNotIn("'video/*'", src)
        self.assertNotIn('function _iconOf', src)

    def test_the_served_copies_match_the_sources(self):
        for rel in (PREVIEW, PICKER, LIBRARY):
            served = ROOT / 'staticfiles' / rel.replace('/static/', '/', 1).split('/', 1)[1]
            if not served.exists():
                self.skipTest('pas de copie servie dans cet arbre')
            self.assertEqual((ROOT / 'wama' / rel).read_bytes(), served.read_bytes(), rel)
