"""Contrat d'UI des STATUTS de file sur les cards — `AWAITING_RESOURCES` (02/09) et `STALE` (17/09).

Tests MESURÉS sur les sources (gabarits, CSS, JS) : un état doit être connu de CHAQUE surface qui
rend un statut — la classe de card, le libellé (centralisé via get_status_display, plus aucune
chaîne en dur), les partials communs, les maps JS et leurs copies staticfiles (le dossier
réellement SERVI).

⭐ **Ce que ce fichier a appris, et qui vaut pour tout état futur** : ajouter un état ne coûte pas
« une ligne ou deux » mais **huit surfaces**. La marche P2 l'a mesuré le 17/09 en voulant ajouter
`STALE` — la route ne parlait que de « deux écritures » (le bouton de cycle et son jumeau), et le
chemin réel a été celui qu'`AWAITING_RESOURCES` avait déjà payé six semaines plus tôt, ligne pour
ligne. C'est pourquoi les deux familles de gardes ci-dessous sont SYMÉTRIQUES : la seconde se lit
comme la liste de contrôle de la prochaine.
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

    def test_l_etat_awaiting_est_filtrable_dans_la_file(self):
        """Quick win du 02/09 : « En attente de ressources » appelle un GESTE (baisser le
        curseur de qualité, ou attendre) — noyé dans « Brouillon », il était introuvable.
        Les trois maillons doivent le connaître : le compteur commun, le filtre, l'option."""
        self.assertIn("statuses.count('AWAITING_RESOURCES')",
                      _lire('wama/common/utils/batch_common.py'))
        self.assertIn("'awaiting'", _lire('wama/common/utils/queue_view.py'))
        # ⚠ On assure sur la barre RENDUE, plus sur le TEXTE de `_queue_toolbar.html`.
        # Le 2026-09-08 l'union des barres a déplacé le markup du filtre par statut dans
        # `common/toolbar/_statut.html` (registre `common/toolbar.py`) : ce test est tombé
        # alors que l'option était toujours offerte, au même endroit à l'écran.
        # Un test qui lit un FICHIER mesure l'emplacement du code ; ce qu'on veut tenir, c'est
        # que la file OFFRE l'option — et le rendu le dit quel que soit le partial qui la porte.
        from django.template.loader import render_to_string
        rendu = render_to_string('common/_queue_toolbar.html',
                                 {'q_sort': 'recent', 'q_filter': 'all'})
        self.assertIn('value="awaiting"', rendu)
        self.assertIn('En attente de ressources', rendu)

    def test_staticfiles_sert_les_memes_fichiers(self):
        """`staticfiles/` est le dossier SERVI : un correctif non resynchronisé est
        invisible au navigateur (règle AGENTS.md « resynchroniser dans le même geste »)."""
        paires = [
            ('wama/common/static/common/js/wama-app-base.js',
             'staticfiles/common/js/wama-app-base.js'),
            ('wama/common/static/common/js/wama-cycle-button.js',
             'staticfiles/common/js/wama-cycle-button.js'),
            ('wama/common/static/common/css/app_modern.css',
             'staticfiles/common/css/app_modern.css'),
            ('wama/common/static/common/css/wama-inspector.css',
             'staticfiles/common/css/wama-inspector.css'),
        ]
        for source, servi in paires:
            self.assertEqual(_lire(source), _lire(servi),
                             f"{servi} diverge de sa source — resynchroniser staticfiles/")


class CardsStatutStaleTest(SimpleTestCase):
    """Contrat d'UI de l'état `STALE` — marche P2, décision de Fabien du 2026-09-17.

    ⚠ Ces gardes existent parce que l'ajout d'un état ne coûte PAS deux écritures mais HUIT
    surfaces : la mesure du 17/09 a montré que le précédent (`AWAITING_RESOURCES`, 02/09) les
    avait toutes payées. Une seule oubliée et l'état est invisible là précisément où il appelle
    un geste — c'est le défaut que ce fichier garde depuis sa création.

    `STALE` = le process a RÉUSSI, mais une de ses conditions a changé (`ROUTE §10.6 4.3`). Ce
    n'est ni un terminé (dire « à jour » serait faux) ni un échec (le résultat reste lisible et
    téléchargeable) — d'où une couleur propre, #9b59b6.
    """

    def test_chaque_gabarit_de_card_pose_la_classe_stale(self):
        for chemin in GABARITS_DE_CARD:
            self.assertIn("'STALE' %}stale", _lire(chemin),
                          f"{chemin} : la racine de card ne pose pas la classe `stale` — "
                          f"une card périmée resterait sans couleur d'état")

    def test_les_partials_communs_connaissent_l_etat_perime(self):
        etat = _lire('wama/common/templates/common/_card_state.html')
        self.assertIn('text-stale', etat)
        self.assertIn('Périmé', etat)
        self.assertIn('bg-stale', _lire('wama/common/templates/common/_card_progress.html'))

    def test_les_maps_js_et_les_styles_connaissent_l_etat_perime(self):
        js = _lire('wama/common/static/common/js/wama-app-base.js')
        self.assertIn("STALE: 'bg-stale'", js)
        self.assertIn("STALE: 'Périmé'", js)
        moderne = _lire('wama/common/static/common/css/app_modern.css')
        for classe in ('.wama-card.stale', '.bg-stale', '.text-stale'):
            self.assertIn(classe, moderne)
        self.assertIn('[data-s="STALE"]',
                      _lire('wama/common/static/common/css/wama-inspector.css'))

    def test_le_bouton_de_cycle_propose_RECALCULER_et_pas_DEMARRER(self):
        """Le défaut exact que cette garde ferme : `STALE` tombait dans le repli ▶ « Démarrer »,
        qui dit que rien n'a jamais tourné.

        ⚠ La CONTRE-ÉPREUVE est la moitié qui compte — sans elle, un libellé changé pour TOUS
        les états passerait ce test en cassant le sens : un terminé doit toujours dire
        « Relancer ». Les deux écritures (gabarit serveur + `stateFor` du JS) sont vérifiées,
        parce qu'elles rendent le même bouton à deux moments (chargement / poll).
        """
        from django.template.loader import render_to_string
        perime = render_to_string('common/_cycle_button.html', {'id': 7, 'status': 'STALE'})
        self.assertIn('data-cycle-action="restart"', perime)
        self.assertIn('Recalculer ce qui est périmé', perime)
        termine = render_to_string('common/_cycle_button.html', {'id': 7, 'status': 'SUCCESS'})
        self.assertIn('data-cycle-action="restart"', termine)
        self.assertIn('Relancer', termine)
        self.assertNotIn('Recalculer', termine, 'le libellé du périmé a débordé sur les terminés')
        js = _lire('wama/common/static/common/js/wama-cycle-button.js')
        self.assertIn("s === 'STALE'", js, "le JUMEAU JS ne connaît pas STALE")
        self.assertIn('Recalculer ce qui est périmé', js)

    def test_l_etat_perime_est_filtrable_dans_la_file(self):
        """Même raison qu'au 02/09 pour l'attente de ressources : un état qui appelle un GESTE
        et qu'aucun filtre ne sait montrer est introuvable dès que la file s'allonge."""
        self.assertIn("statuses.count('STALE')",
                      _lire('wama/common/utils/batch_common.py'))
        self.assertIn("'stale'", _lire('wama/common/utils/queue_view.py'))
        from django.template.loader import render_to_string
        rendu = render_to_string('common/_queue_toolbar.html',
                                 {'q_sort': 'recent', 'q_filter': 'all'})
        self.assertIn('value="stale"', rendu)
        self.assertIn('Périmé', rendu)
