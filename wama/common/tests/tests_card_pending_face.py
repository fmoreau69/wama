"""L'APERÇU d'une card — côté gabarit : UN hôte commun, posé par toutes les cards.

2026-10-20 (Fabien) : la card suit la face Pendant. 2026-11-18 (Fabien) : « la preview est censée
afficher entrée / during (selon le modèle) / sortie / etc. selon les sous-process que porte la card.
À partir du moment où on a une entrée, on devrait avoir accès à la preview. » Les cards réelles ne
posaient un hôte de SORTIE qu'une fois le résultat produit (et un hôte d'attente à part,
`data-card-during`) : une card en attente ne montrait rien de son entrée. Désormais chaque card —
réelle ou générée — inclut L'HÔTE COMMUN (`common/_card_preview.html`), monté par l'afficheur de
faces (`WamaMediaPreview.mountCardFaces`, gardé en V8 dans `tests_cap_from_js`) ; aucune card ne
l'écrit à la main. SI la face Pendant existe, c'est le serveur qui le dit (`sides.during_capable`,
lu de la capacité déclarée `during_preview`) : le gabarit ne recopie pas la déclaration.

⚠ Pas de bibliothèque de tags NEUVE ici, délibérément : la prod met les gabarits en cache par
worker, mais un worker qui lit une card pour la première fois la lit sur le disque — il ne
connaîtrait pas une bibliothèque importée après son démarrage (500 jusqu'au rechargement). Un
gabarit inclus neuf, lui, se lit sur le disque comme la card.
"""
import re
from pathlib import Path

from django.conf import settings
from django.template import Context, Template
from django.test import SimpleTestCase

ROOT = Path(settings.BASE_DIR)
HOST = 'common/_card_preview.html'
#: L'inclusion de l'hôte commun, et la surface qu'elle nomme : écrite (`'imager'`), ou lue à la
#: déclaration par la balise commune (`{% domain_surface 'enhancer' 'audio' as audio_surface %}`).
INCLUDE = re.compile(r"\{% include '" + re.escape(HOST) + r"' with surface=(?:'(\w+)'|(\w+)) id=elem\.id")
DECLARED = re.compile(r"\{% domain_surface '(\w+)' '(\w+)' as (\w+) %\}")
#: Ce que seul l'hôte commun écrit : une card qui l'écrit à la main est un second chemin.
BY_HAND = re.compile(r'data-card-preview=|data-card-during=')

#: Une jumelle générée (`<app>_01`, bac à sable, hors du dépôt) a la card du générateur, gardée
#: ci-dessous sur ce qu'il émet.
TWIN = re.compile(r'_\d\d$')


def _app_dirs():
    return [d for d in sorted((ROOT / 'wama').iterdir()) if d.is_dir() and not TWIN.search(d.name)]


def _card_templates():
    """Les gabarits de card du parc : ceux qui montrent l'aperçu commun de leur élément."""
    from wama.common.utils.app_modes import domain_surface
    for path in (p for d in _app_dirs() for p in sorted(d.glob('templates/*/_*card*.html'))):
        if path.as_posix().endswith('templates/' + HOST):
            continue                                  # l'hôte lui-même
        text = path.read_text(encoding='utf-8')
        found = INCLUDE.findall(text)
        if found or BY_HAND.search(text):
            written, named = found[0] if found else ('', '')
            declared = {var: domain_surface(app, dom) for app, dom, var in DECLARED.findall(text)}
            yield path, text, written or declared.get(named, named)


class EveryCardShowsItsFacesTest(SimpleTestCase):

    def test_the_fleet_is_measured(self):
        surfaces = sorted(s for _p, _t, s in _card_templates())
        self.assertEqual(['anonymizer', 'audio_enhancer', 'avatarizer', 'composer', 'converter',
                          'describer', 'enhancer', 'imager', 'reader', 'synthesizer',
                          'transcriber'], surfaces)

    def test_every_card_includes_the_common_host_once_and_writes_none(self):
        for path, text, surface in _card_templates():
            with self.subTest(card=path.name, surface=surface):
                self.assertEqual(1, len(INCLUDE.findall(text)), 'the common host, once')
                self.assertIsNone(BY_HAND.search(text), 'no preview host written by hand')
                self.assertNotIn('{% if', text[text.index(HOST) - 200:text.index(HOST)].split(
                    '{% endcomment %}')[-1], 'the host does not wait for an output')

    def test_the_generator_lays_out_the_same_host(self):
        from wama.common.manifests.codegen import templates_gen
        source = Path(templates_gen.__file__).read_text(encoding='utf-8')
        self.assertIn("{{% include '" + HOST + "' with surface='{surface}' id=elem.id", source)
        self.assertIsNone(BY_HAND.search(source), 'the generated card writes no host by hand')

    def test_the_host_carries_the_item_address_and_the_card_density(self):
        html = Template("{% include '" + HOST + "' with surface='reader' id=7 mode='excerpt' "
                        "max_chars=400 classes='reader-preview' action='expand' title='t' %}"
                        ).render(Context({}))
        self.assertIn('data-card-preview="/common/preview/reader/7/"', html)
        self.assertIn('data-preview-url="/common/preview/reader/7/"', html)
        for attr in ('class="wcv3-preview wama-card-preview reader-preview"',
                     'id="preview-row-7"', 'data-player-id="7"', 'data-preview-mode="excerpt"',
                     'data-preview-max-chars="400"', 'data-action="expand"', 'title="t"'):
            self.assertIn(attr, html)
        bare = Template("{% include '" + HOST + "' with surface='composer' id=3 %}").render(Context({}))
        self.assertNotIn('data-preview-mode', bare)
        self.assertNotIn('data-action', bare)

    def test_no_app_writes_the_text_being_built_into_its_card(self):
        """The describer's own path (its progress `partial_text` written into `.result-preview`,
        cut at 150 characters) and the transcriber's Speak-panel copy are gone : the text being
        built reaches a card through the Pending face only."""
        read = re.compile(r'\.partial_text')          # `data.partial_text`, une LECTURE
        for js in (p for d in _app_dirs() for p in sorted(d.glob('static/*/js/*.js'))):
            with self.subTest(js=js.relative_to(ROOT).as_posix()):
                self.assertIsNone(read.search(js.read_text(encoding='utf-8')))
        for app in ('describer', 'transcriber'):
            with self.subTest(progress=app):
                self.assertNotIn("'partial_text'", (ROOT / 'wama' / app / 'views.py').read_text(
                    encoding='utf-8'))

    def test_the_card_viewer_watches_the_status_every_app_writes(self):
        js = (ROOT / 'wama/common/static/common/js/media-preview.js').read_text(encoding='utf-8')
        self.assertIn("attributeFilter: ['data-status']", js)
        self.assertIn("const PREVIEW_HOST = '[data-card-preview]';", js)
        self.assertIn('const viewer = faceViewer(host, base, {', js)
        self.assertEqual(js, (ROOT / 'staticfiles/common/js/media-preview.js').read_text(
            encoding='utf-8'), 'staticfiles out of sync')
