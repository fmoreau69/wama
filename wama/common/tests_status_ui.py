"""Contrat d'UI des STATUTS de file sur les cards (état AWAITING_RESOURCES, 2026-09-02).

Tests MESURÉS sur les sources (gabarits, CSS, JS) : l'état orange « En attente de
ressources » doit être connu de chaque surface qui rend un statut — la classe de card,
le libellé (centralisé via get_status_display, plus aucune chaîne en dur), les partials
communs, les maps JS et leurs copies staticfiles (le dossier réellement SERVI).
"""

from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

BASE = Path(settings.BASE_DIR)

#: Les 11 gabarits de card de file (un par app générique ; l'enhancer en a deux).
GABARITS_DE_CARD = [
    'wama/anonymizer/templates/anonymizer/_media_card.html',
    'wama/avatarizer/templates/avatarizer/_avatar_card.html',
    'wama/composer/templates/composer/_generation_card.html',
    'wama/converter/templates/converter/_job_card.html',
    'wama/describer/templates/describer/_description_card.html',
    'wama/enhancer/templates/enhancer/_audio_card.html',
    'wama/enhancer/templates/enhancer/_enhancement_card.html',
    'wama/imager/templates/imager/_generation_card.html',
    'wama/reader/templates/reader/_item_card.html',
    'wama/synthesizer/templates/synthesizer/_synthesis_card.html',
    'wama/transcriber/templates/transcriber/_transcript_card.html',
]


def _lire(chemin: str) -> str:
    return (BASE / chemin).read_text(encoding='utf-8')


class CardsStatutAwaitingTest(SimpleTestCase):

    def test_chaque_gabarit_de_card_pose_la_classe_awaiting(self):
        for chemin in GABARITS_DE_CARD:
            self.assertIn("AWAITING_RESOURCES' %}awaiting", _lire(chemin),
                          f"{chemin} : la racine de card ne pose pas la classe `awaiting` "
                          f"pour AWAITING_RESOURCES — la card resterait sans couleur d'état")

    def test_plus_aucune_chaine_de_libelles_de_statut_en_dur_dans_les_cards(self):
        """Le libellé vient de `get_status_display` (choices communs) : une chaîne
        {% if %}En attente{% elif %}… recopiée par gabarit est la duplication que la
        centralisation des statuts (2026-09-01) a rendue caduque — et elle affichait
        la valeur BRUTE pour tout état qu'elle ne connaissait pas."""
        for chemin in GABARITS_DE_CARD:
            src = _lire(chemin)
            self.assertNotIn("status == 'PENDING' %}En attente", src,
                             f"{chemin} : chaîne de libellés en dur réintroduite")

    def test_les_partials_communs_connaissent_l_etat(self):
        etat = _lire('wama/common/templates/common/_card_state.html')
        self.assertIn("AWAITING_RESOURCES", etat)
        self.assertIn("En attente de ressources", etat)
        progres = _lire('wama/common/templates/common/_card_progress.html')
        self.assertIn("bg-awaiting", progres)
        # Le badge affiche le LIBELLÉ quand on le lui passe — la valeur brute
        # AWAITING_RESOURCES serait illisible sur une card.
        self.assertIn("label|default:status", progres)

    def test_les_maps_js_et_les_styles_connaissent_l_etat(self):
        js = _lire('wama/common/static/common/js/wama-app-base.js')
        self.assertIn("AWAITING_RESOURCES: 'bg-awaiting'", js)
        self.assertIn("AWAITING_RESOURCES: 'En attente de ressources'", js)
        moderne = _lire('wama/common/static/common/css/app_modern.css')
        for classe in ('.wama-card.awaiting', '.bg-awaiting', '.text-awaiting'):
            self.assertIn(classe, moderne)
        self.assertIn('[data-s="AWAITING_RESOURCES"]',
                      _lire('wama/common/static/common/css/wama-inspector.css'))

    def test_staticfiles_sert_les_memes_fichiers(self):
        """`staticfiles/` est le dossier SERVI : un correctif non resynchronisé est
        invisible au navigateur (règle CLAUDE.md « resynchroniser dans le même geste »)."""
        paires = [
            ('wama/common/static/common/js/wama-app-base.js',
             'staticfiles/common/js/wama-app-base.js'),
            ('wama/common/static/common/css/app_modern.css',
             'staticfiles/common/css/app_modern.css'),
            ('wama/common/static/common/css/wama-inspector.css',
             'staticfiles/common/css/wama-inspector.css'),
        ]
        for source, servi in paires:
            self.assertEqual(_lire(source), _lire(servi),
                             f"{servi} diverge de sa source — resynchroniser staticfiles/")
