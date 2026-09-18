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

    def test_chaque_gabarit_de_card_porte_data_status(self):
        """Le CONTRAT est l'ATTRIBUT, plus la classe (bascule du 2026-09-18).

        Les 11 gabarits recopiaient une chaîne `{% if elem.status == … %}` pour poser une classe
        d'état — sur la balise même qui portait déjà `data-status`. Le CSS lit désormais
        l'attribut : la classe n'apportait aucune information, et elle coûtait 11 copies, celle
        du générateur, et 4 sites JS. Ce qui doit être tenu, c'est l'attribut : sans lui la card
        n'a plus AUCUNE couleur d'état.
        """
        for chemin in GABARITS_DE_CARD:
            self.assertIn('data-status="{{ elem.status }}"', _lire(chemin),
                          f"{chemin} : la racine de card ne porte pas `data-status`")

    def test_aucune_chaine_de_classe_d_etat_nulle_part_LE_GENERATEUR_COMPRIS(self):
        """⚠ Cette garde couvre le GÉNÉRATEUR, et c'est tout son intérêt.

        Celle d'avant lisait une liste FIGÉE de 11 chemins : `templates_gen.py` lui échappait et
        continuait d'émettre une chaîne à TROIS états (ni `AWAITING_RESOURCES`, ni `STALE`) plus
        une table de libellés en dur dont le repli affichait la valeur BRUTE à l'écran. Corriger
        onze gabarits pendant que la machine en fabrique de faux n'est pas une correction.
        """
        surveilles = GABARITS_DE_CARD + ['wama/common/manifests/codegen/templates_gen.py']
        for chemin in surveilles:
            src = _lire(chemin)
            self.assertNotIn('%}processing', src,
                             f"{chemin} : chaîne de CLASSE d'état réintroduite — le CSS lit "
                             f"`data-status`, cette classe serait une copie de plus")
            self.assertNotIn("'PENDING' %}En attente", src,
                             f"{chemin} : table de LIBELLÉS en dur réintroduite — le libellé "
                             f"vient de `get_status_display` (les choices du modèle)")

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
        for classe in ('.wama-card[data-status="AWAITING_RESOURCES"]', '.bg-awaiting',
                       '.text-awaiting'):
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


class LaPresentationDUnEtatEstDECLAREEUneFoisTest(SimpleTestCase):
    """La 3ᵉ étape : l'APPARENCE d'un état dérive, elle ne se recopie plus (2026-09-18).

    Le vocabulaire (valeurs, libellés, alias) n'avait jamais été dupliqué — il vit dans
    `common/models.py`. C'est son APPARENCE qui l'était : classe de badge, classe de texte,
    icône, réécrites dans `wama-app-base.js`, les deux partials, le ternaire de
    `wama-inspector.js` et jusque dans des gabarits d'app. **Cinq écritures du même fait.**
    """

    def test_les_libelles_de_la_charge_VIENNENT_du_vocabulaire(self):
        """Le libellé ne se réécrit pas dans la présentation : il en est TIRÉ. Sinon on aurait
        simplement déplacé la copie."""
        from wama.common.models import PROCESS_STATUS_CHOICES
        from wama.common.utils.state_presentation import js_payload
        labels = js_payload()['labels']
        for valeur, libelle in PROCESS_STATUS_CHOICES:
            self.assertEqual(labels.get(valeur), str(libelle), valeur)

    def test_DRAFT_est_declare_a_part_et_ne_disparait_pas(self):
        """⚠ `DRAFT` n'est dans AUCUN des deux vocabulaires, mais les maps JS l'affichaient :
        dériver naïvement l'aurait fait disparaître de l'écran. Il est déclaré comme état
        d'AFFICHAGE — la distinction est le piège que ce test tient."""
        from wama.common.models import PROCESS_STATUS_CHOICES
        from wama.common.utils.state_presentation import js_payload
        charge = js_payload()
        self.assertIn('DRAFT', charge['labels'])
        self.assertEqual(charge['labels']['DRAFT'], 'Brouillon')
        self.assertNotIn('DRAFT', [v for v, _ in PROCESS_STATUS_CHOICES],
                         "DRAFT a rejoint le vocabulaire : le déclarer à part n'a plus lieu d'être")

    def test_la_charge_porte_les_ALIAS_sinon_le_client_ne_sait_pas_lire_le_Lab(self):
        from wama.common.models import JOB_STATUS_ALIASES
        from wama.common.utils.state_presentation import js_payload
        self.assertEqual(js_payload()['aliases'], dict(JOB_STATUS_ALIASES))
        self.assertEqual(js_payload()['aliases'].get('completed'.upper()), 'SUCCESS')

    def test_le_CABLAGE_serveur_vers_client_existe(self):
        """Une charge que personne ne pousse n'atteint aucun écran : les deux maillons se
        tiennent ensemble — le processeur de contexte la calcule, `base.html` la rend."""
        self.assertIn("'wama_states_json'", _lire('wama/accounts/context_processors.py'))
        self.assertIn('window.WAMA_STATES', _lire('wama/templates/base.html'))
        js = _lire('wama/common/static/common/js/wama-app-base.js')
        for accesseur in ('normalizeStatus', 'statusLabel', 'statusBadge'):
            self.assertIn(accesseur + ':', js, f'{accesseur} non exporté par WamaApp')

    def test_l_inspecteur_CONSOMME_les_accesseurs_et_ne_REPREFIXE_pas(self):
        """La 5ᵉ écriture était DANS le commun — et rien ne l'attestait jusqu'au 18/09 au soir.

        `wama-inspector.js` refaisait sa mise en majuscules et son PROPRE ternaire de classe, qui
        ne connaissait que 4 états sur 7. ⚠ Le piège mesuré en le branchant : sa ligne composait
        `'badge bg-' + cls`, alors que l'accesseur rend la classe COMPLÈTE — préfixer donnait
        `bg-bg-success`, une classe inexistante, donc un badge **GRIS sans aucune erreur**. C'est
        le genre de défaut qu'aucun test Python ne voit et qu'aucune console ne signale.
        """
        js = _lire('wama/common/static/common/js/wama-inspector.js')
        for accesseur in ('normalizeStatus', 'statusBadge', 'statusLabel'):
            self.assertIn('A.' + accesseur, js,
                          f"l'inspecteur ne consomme pas `{accesseur}` — il réécrit sa table")
        self.assertNotIn("'badge bg-' +", js,
                         'préfixe `bg-` réintroduit : la classe deviendrait `bg-bg-…`, donc un '
                         'badge GRIS, et rien ne le signalerait')


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

    def test_la_couleur_du_perime_se_lit_sur_data_status(self):
        """Depuis la bascule du 2026-09-18 la couleur ne dépend plus d'une classe recopiée par
        onze gabarits : le CSS lit l'attribut que la card porte déjà."""
        moderne = _lire('wama/common/static/common/css/app_modern.css')
        self.assertIn('.wama-card[data-status="STALE"]', moderne)
        self.assertIn('#9b59b6', moderne)

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
        for classe in ('.wama-card[data-status="STALE"]', '.bg-stale', '.text-stale'):
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
