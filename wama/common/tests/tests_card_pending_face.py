"""La CARD suit la face Pendant (2026-10-20, demande de Fabien) — côté gabarit.

Le suiveur et son rendu sont gardés en V8 (`tests_cap_from_js`, `test_a_running_card_shows_its_
pending_face_then_stops` et voisins). Ici : CHAQUE card du parc désigne l'hôte de la face (l'adresse
de son élément, par la route commune) — et aucune app n'écrit plus elle-même dans sa card ce qui se
construit. SI la face existe, c'est le serveur qui le dit (`sides.during_capable`, lu de la capacité
déclarée `during_preview`) : le gabarit ne recopie pas la déclaration.

⚠ Pas de bibliothèque de tags NEUVE ici, délibérément : la prod met les gabarits en cache par
worker, mais un worker qui lit une card pour la première fois la lit sur le disque — il ne
connaîtrait pas une bibliothèque importée après son démarrage (500 jusqu'au rechargement).
"""
import re
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

ROOT = Path(settings.BASE_DIR)
SURFACE = re.compile(r"\{% url 'common:unified_preview' '(\w+)' elem\.id")


#: Une jumelle générée (`<app>_01`, bac à sable) a la card du générateur, qui pose un hôte
#: `data-card-preview` dans TOUS les états (Entrée, puis Sortie) : le suiveur s'en sert pendant le
#: traitement, elle n'a pas d'hôte d'attente à poser.
TWIN = re.compile(r'_\d\d$')


def _app_dirs():
    return [d for d in sorted((ROOT / 'wama').iterdir()) if d.is_dir() and not TWIN.search(d.name)]


def _card_templates():
    """Les gabarits de card du parc : ceux qui rendent un aperçu commun de leur élément."""
    for path in (p for d in _app_dirs() for p in sorted(d.glob('templates/*/_*card*.html'))):
        found = SURFACE.findall(path.read_text(encoding='utf-8'))
        if found:
            yield path, found[0]


class EveryCardFollowsThePendingFaceTest(SimpleTestCase):

    def test_the_fleet_is_measured(self):
        surfaces = sorted(s for _p, s in _card_templates())
        self.assertEqual(['anonymizer', 'audio_enhancer', 'avatarizer', 'composer', 'converter',
                          'describer', 'enhancer', 'imager', 'reader', 'synthesizer',
                          'transcriber'], surfaces)

    def test_every_card_lays_out_its_pending_host(self):
        for path, surface in _card_templates():
            with self.subTest(card=path.name, surface=surface):
                self.assertIn("{%% url 'common:unified_preview' '%s' elem.id as pv_during %%}"
                              'data-card-during="{{ pv_during }}"' % surface,
                              path.read_text(encoding='utf-8'))

    def test_no_app_writes_the_text_being_built_into_its_card(self):
        """The describer's own path (its progress `partial_text` written into `.result-preview`,
        cut at 150 characters) and the transcriber's Speak-panel copy are gone : the text being
        built reaches a card through the Pending face only."""
        read = re.compile(r'\.partial_text')          # `data.partial_text`, une LECTURE
        for js in (p for d in _app_dirs() for p in sorted(d.glob('static/*/js/*.js'))):
            with self.subTest(js=js.relative_to(ROOT).as_posix()):
                self.assertIsNone(read.search(js.read_text(encoding='utf-8')))
        for app in ('describer', 'transcriber'):
            with self.subTest(progress=app):
                self.assertNotIn("'partial_text'", (ROOT / 'wama' / app / 'views.py').read_text(
                    encoding='utf-8'))

    def test_the_card_follower_watches_the_status_every_app_writes(self):
        js = (ROOT / 'wama/common/static/common/js/media-preview.js').read_text(encoding='utf-8')
        self.assertIn("attributeFilter: ['data-status']", js)
        self.assertIn("const PREVIEW_HOST = '[data-card-preview], [data-card-during]';", js)
        self.assertEqual(js, (ROOT / 'staticfiles/common/js/media-preview.js').read_text(
            encoding='utf-8'), 'staticfiles out of sync')
