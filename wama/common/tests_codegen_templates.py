"""Tests du GABARIT DE TEMPLATE généré (`codegen/templates_gen.py`) — marche S2bis.

Ce qui est vérifié ici est ce qui a rendu la jumelle `converter_01` VISUELLEMENT complète et
FONCTIONNELLEMENT inerte : des boutons rendus dont rien n'écoutait le clic, et un select de
format qui s'annonçait « non déclaré ». Les deux défauts ont la même forme — une facette
disponible que le gabarit ne relie à rien — et aucun contrôle mécanique ne les voyait :
`manifest_roundtrip` mesure la PROJETABILITÉ, la grille l'ADOPTION, et un écran mort passe les
deux (`WAMA_VERIFICATION §1`).

⚠ Ne pas remplacer ces assertions par des `assertIn('start_url', src)`. Une sous-chaîne dit que
le gabarit a ÉCRIT quelque chose, pas qu'il a écrit quelque chose de JUSTE : la première version
du câblage passait des variables de template au partial sans les définir, ce qui rend
exactement la même barre inerte — avec la sous-chaîne présente.
"""
import re

from django.template.loader import render_to_string
from django.test import SimpleTestCase
from django.urls import NoReverseMatch, reverse

from wama.common.manifests.codegen.templates_gen import render_index

SOURCE = 'converter'

#: Clés `options_source` qu'AUCUN des deux registres communs ne résout aujourd'hui — donc pour
#: lesquelles le resolver généré affiche son avertissement nommé, à dessein. Cette liste doit
#: DÉCROÎTRE : y ajouter une clé est une décision, pas un réflexe (résorber = déclarer la source
#: au registre commun de `wama-params.js`, jamais écrire un resolver dans une app).
SOURCES_NON_RESOLUES = {'backends', 'avatar_gallery'}

_JS = 'wama/common/static/common/js/'


def _manifeste(app):
    from wama.common.manifests.ingest import extract
    return extract('app', app)


def _lire(chemin):
    import wama
    from pathlib import Path
    racine = Path(wama.__file__).parent.parent
    return (racine / chemin).read_text(encoding='utf-8')


def _include_toolbar(src):
    """La balise `{% include 'common/_queue_toolbar.html' … %}` du template généré."""
    for m in re.finditer(r'\{%\s*include\s+\'common/_queue_toolbar\.html\'(.*?)%\}', src, re.S):
        return m.group(1)
    return None


def _variables_url(src):
    """Les variables posées par `{% url '<app>:<route>' as <var> %}` → nom de route."""
    return {m.group(2): m.group(1)
            for m in re.finditer(r"\{%\s*url\s+'[\w_]+:([\w_]+)'\s+as\s+([\w_]+)\s*%\}", src)}


class BarreDeFileGenereeTest(SimpleTestCase):
    """Les 3 actions globales de la file : rendues ET reliées à une route qui existe."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        manifest = _manifeste(SOURCE)
        cls.src, cls.raison = render_index(manifest) if manifest else (None, 'manifeste absent')
        if isinstance(cls.src, dict):
            cls.src = cls.src.get('index.html')

    def setUp(self):
        if not self.src:
            self.skipTest(f'index non généré pour {SOURCE} : {self.raison}')

    def test_les_trois_actions_de_file_recoivent_une_url_et_pas_seulement_un_id(self):
        # Un `id` seul est ce qui a produit trois boutons inertes : le partial le rend, l'app
        # est censée l'écouter, et un gabarit n'écrit pas de handler.
        inc = _include_toolbar(self.src)
        self.assertIsNotNone(inc, "le gabarit n'inclut plus la barre d'outils commune")
        for arg in ('start_url=', 'clear_url=', 'download_url='):
            self.assertIn(arg, inc, f'{arg} absent de la barre → bouton inerte (ou ⬇ désactivé)')

    def test_chaque_url_passee_est_DEFINIE_avant_l_include(self):
        # Le défaut que la sous-chaîne ne voit pas : passer `start_url=q_start_url` sans avoir
        # posé `{% url … as q_start_url %}` rend la variable VIDE → le partial n'émet pas
        # l'attribut → bouton inerte, exactement comme avant, sans rien de visible au diff.
        inc = _include_toolbar(self.src)
        posees = _variables_url(self.src)
        passees = re.findall(r'\b(start_url|clear_url|download_url)=([\w_]+)', inc)
        # ⚠ Sans cette ligne, le test passe À VIDE quand AUCUNE url n'est passée — c'est-à-dire
        # exactement dans l'état défectueux. Mesuré : rejoué sur HEAD (avant correctif) il était
        # le seul des trois à rester vert. Un test qui ne boucle sur rien atteste le néant.
        self.assertEqual(3, len(passees), 'les 3 urls de file doivent être passées au partial')
        for arg, var in passees:
            self.assertIn(var, posees,
                          f'{arg} pointe « {var} », jamais défini par un {{% url … as %}}')

    def test_les_routes_citees_existent_reellement(self):
        # Un nom de route supposé produit un POST 404 muet (leçon `stop` vs `cancel`).
        for var, route in _variables_url(self.src).items():
            try:
                reverse(f'{SOURCE}:{route}')
            except NoReverseMatch:
                self.fail(f'route {SOURCE}:{route} citée par le gabarit mais introuvable')

    def test_la_brique_commune_ecoute_les_deux_attributs_emis(self):
        # L'autre moitié du contrat : le partial pose `data-queue-*-url`, `queue-actions.js`
        # doit les écouter. Deux fichiers, un seul comportement — c'est là que les câblages
        # meurent (support ≠ adoption).
        js = _lire(_JS + 'queue-actions.js')
        for attr in ('data-queue-start-url', 'data-queue-clear-url'):
            self.assertIn(f"queueAction('{attr}'", js,
                          f'{attr} émis par le partial mais pas écouté par la brique')


class PartialActionsDeFileTest(SimpleTestCase):
    """Le partial commun — les 10 apps en place ne doivent RIEN changer."""

    def _rendu(self, **ctx):
        base = {'start_id': 'aStart', 'clear_id': 'aClear',
                'download_id': 'aDl', 'show_download': True}
        base.update(ctx)
        return render_to_string('common/_queue_actions.html', base)

    def test_sans_url_le_markup_est_INCHANGE(self):
        # Rétro-compatibilité : une app qui garde son handler par id ne doit pas voir la brique
        # commune poster une seconde fois. Pas d'URL → pas d'attribut → la brique ignore.
        html = self._rendu()
        self.assertNotIn('data-queue-start-url', html)
        self.assertNotIn('data-queue-clear-url', html)

    def test_avec_url_les_boutons_portent_leur_route(self):
        html = self._rendu(start_url='/converter_01/start-all/',
                           clear_url='/converter_01/clear-all/')
        self.assertIn('data-queue-start-url="/converter_01/start-all/"', html)
        self.assertIn('data-queue-clear-url="/converter_01/clear-all/"', html)

    def test_les_urls_TRAVERSENT_la_barre_d_outils_jusqu_aux_boutons(self):
        # Le chemin RÉEL : la page inclut `_queue_toolbar.html`, qui ré-inclut les actions. Un
        # `{% include … with … only %}` posé un jour dans la barre couperait le passage sans
        # qu'aucun des tests ci-dessus ne bouge — les boutons redeviendraient inertes.
        html = render_to_string('common/_queue_toolbar.html', {
            'q_sort': 'recent', 'q_filter': 'all', 'start_id': 'aStart', 'clear_id': 'aClear',
            'download_id': 'aDl', 'show_download': True,
            'start_url': '/converter_01/start-all/', 'clear_url': '/converter_01/clear-all/',
            'download_url': '/converter_01/download-all/'})
        self.assertIn('data-queue-start-url="/converter_01/start-all/"', html)
        self.assertIn('data-queue-clear-url="/converter_01/clear-all/"', html)
        self.assertIn('href="/converter_01/download-all/"', html)

    def test_le_telechargement_reste_desactive_tant_qu_aucune_url_n_est_donnee(self):
        # `show_download=True` sans `download_url` rend un bouton DÉSACTIVÉ — c'est le partial
        # qui le décide, pas un bug d'app : c'est ce qui rendait ⬇ mort sur la jumelle.
        self.assertIn('disabled', self._rendu())
        self.assertIn('href="/converter_01/download-all/"',
                      self._rendu(download_url='/converter_01/download-all/'))


class ParitEDesEtagesDeFileTest(SimpleTestCase):
    """LOT et FILE partagent UN algorithme — l'étage du bas ne peut pas être le plus pauvre.

    Écrit après le balayage exhaustif du 2026-08-29 : la première version de l'étage FILE était
    une COPIE de l'étage LOT amputée de `body` et de `followUp`. Rien ne l'aurait signalé — les
    deux fonctions marchaient — sauf le jour où le synthesizer (qui PORTE ses réglages dans le
    POST) ou le describer (qui insère et polle au lieu de recharger) aurait dû migrer : ils
    n'auraient pas pu, et auraient gardé leur handler. Une brique au contrat plus pauvre que le
    code qu'elle remplace ne résorbe rien, et ça ne se voit qu'à la migration suivante.
    """

    def setUp(self):
        self.js = _lire(_JS + 'queue-actions.js')

    def test_les_deux_etages_passent_par_le_meme_algorithme(self):
        self.assertIn('function groupAction(', self.js,
                      "l'algorithme commun aux deux étages n'existe plus — la copie est revenue")
        for etage in ('function batchAction(', 'function queueAction('):
            i = self.js.index(etage)
            corps = self.js[i:i + 600]
            self.assertIn('groupAction(', corps,
                          f'{etage} ré-implémente le POST au lieu de déléguer')

    def test_le_demarrage_de_FILE_offre_corps_ET_suite_comme_celui_de_LOT(self):
        # Les deux hooks du ▶ de lot, au ▶ de file. Sans eux : 4 apps sur 10 non portables
        # (synthesizer porte des réglages ; describer/transcriber/enhancer pollent).
        i = self.js.index("queueAction('data-queue-start-url'")
        corps = self.js[i:i + 700]
        self.assertIn('body:', corps, 'le ▶ de file ne sait pas porter de réglages')
        self.assertIn('followUp:', corps, 'le ▶ de file impose le rechargement à toutes les apps')

    def test_un_corps_FormData_traverse_le_POST_sans_etre_serialise(self):
        # Le point d'extension ne vaut que si ce qu'une app y met ARRIVE. `JSON.stringify` d'un
        # FormData vaut « {} » : le synthesizer (seul à porter un FICHIER, `voice_reference`)
        # serait parti à vide, sans erreur. Et un corps JSON laisse `request.POST` vide côté
        # Django, or sa vue ne lit que `request.POST`.
        i = self.js.index('function post(')
        corps = self.js[i:i + 700]
        self.assertIn('instanceof FormData', corps,
                      'post() sérialise tout — un corps multipart partirait VIDE et MUET')
        # Et le Content-Type ne doit PAS être posé à la main sur du multipart (la frontière
        # est générée par le navigateur ; l'écrire casse le parsing Django).
        avant = corps[:corps.index('instanceof FormData')]
        self.assertNotIn("'Content-Type': 'application/json'", avant,
                         'Content-Type posé avant le test FormData → multipart cassé')

    def test_les_hooks_de_file_sont_EXPORTES(self):
        # Un hook non exporté est un hook qui n'existe pas : `WamaQueueActions` est la seule
        # surface qu'une app touche.
        for nom in ('onQueueStarted', 'onQueueStartBody'):
            self.assertIn(f'{nom}: {nom}', self.js, f'{nom} déclaré mais absent de WamaQueueActions')


class SourcesDOptionsTest(SimpleTestCase):
    """`options_source` : une clé déclarée au schéma doit résoudre par un registre COMMUN."""

    def test_formats_est_resolu_par_le_registre_commun_et_non_annonce_manquant(self):
        # Le défaut vécu : le resolver généré affichait « ⚠ options « formats » non déclarées »
        # alors que la table était sur toutes les pages. Vérifié ici de bout en bout — la page
        # pose la donnée, le registre la lit, le moteur l'expose.
        self.assertIn('window.WAMA_OUTPUT_FORMATS = {{ converter_output_formats_json|safe }}',
                      _lire('wama/templates/base.html'))
        params = _lire(_JS + 'wama-params.js')
        self.assertIn('WAMA_OUTPUT_FORMATS', params)
        self.assertIn('resolvePageOptions: resolvePageOptions', params)

    def test_le_MOTEUR_resout_seul_et_aucune_app_generee_ne_reecrit_de_resolver(self):
        # Convergence P1 (2026-09-01) : la résolution a QUITTÉ les apps pour le moteur.
        # `render` installe un resolver par défaut adossé au registre commun ; le gabarit
        # d'app n'en émet donc plus AUCUN — en émettre un recréerait, dans chaque app
        # générée, le chemin parallèle que le converter portait TROIS fois.
        params = _lire(_JS + 'wama-params.js')
        self.assertIn('|| function (p) { return resolvePageOptions(p, values); }', params,
                      'le moteur n’installe plus de resolver par défaut : les selects à '
                      'options_source redeviendraient vides sans resolver d’app')
        manifest = _manifeste(SOURCE)
        src, raison = render_index(manifest) if manifest else (None, 'manifeste absent')
        if isinstance(src, dict):
            src = src.get('index.html')
        if not src:
            self.skipTest(f'index non généré : {raison}')
        self.assertNotIn('optionsResolver', src,
                         'le gabarit réécrit un resolver que le moteur porte désormais')

    def test_une_cle_qui_ne_resout_nulle_part_le_DIT_au_lieu_de_rendre_un_select_vide(self):
        # La garde vivait dans le resolver ÉMIS (donc pour la seule app générée) ; portée au
        # moteur le 2026-09-01, elle couvre les 10 apps écrites à la main. Un select vide ne
        # dit pas s'il l'est par absence d'options ou par défaut de câblage — le warn le dit.
        params = _lire(_JS + 'wama-params.js')
        self.assertIn('_avertirSourcesNonResolues', params)
        self.assertIn("aucune source ne la résout", params)
        # …et jamais pour une clé à ENDPOINT async (elle se peuple après le rendu).
        i = params.index('function _avertirSourcesNonResolues')
        self.assertIn('OPTION_SOURCES[p.options_source]', params[i:i + 400])

    def test_toute_cle_declaree_par_une_app_resout_quelque_part_ou_est_ASSUMEE(self):
        # Garde de COUVERTURE : une nouvelle clé apparue dans un schéma d'app doit être
        # rattachée à un registre commun, ou inscrite ici comme trou assumé. Sans ce test, une
        # clé non résolue ne se voit qu'à l'écran, sur un select vide.
        from django.apps import apps as django_apps
        connues = set(SOURCES_NON_RESOLUES)
        params = _lire(_JS + 'wama-params.js')

        # Les DEUX familles de registres communs, lues telles qu'elles s'écrivent :
        #   • ASYNC  `OPTION_SOURCES`      — `voices: '/common/api/voices/'` (une URL) ;
        #   • SYNCHRO `PAGE_OPTION_SOURCES` — `formats: function (values) {…}`.
        # ⚠ Ce test ne connaissait que la seconde, et rattrapait la première par un littéral
        # `{'voices'}` inscrit parmi les clés « connues ». Il donnait donc le bon résultat pour
        # la mauvaise raison : au 2ᵉ endpoint (`catalog`, route F4b) il a accusé une clé
        # parfaitement résolue. *Une exception écrite en dur masque la règle qu'elle imite* —
        # on lit maintenant le registre, et le cas particulier disparaît.
        asynchrones = set(re.findall(r"^\s*(\w+):\s*'[^']+',", params, re.M))
        synchrones = set(re.findall(r'^\s*(\w+):\s*function', params, re.M))
        resolues = asynchrones | synchrones

        vues = set()
        for cfg in django_apps.get_app_configs():
            module = f'{cfg.name}.params'
            try:
                mod = __import__(module, fromlist=['*'])
            except Exception:
                continue
            for obj in vars(mod).values():
                for p in (obj if isinstance(obj, (list, tuple)) else ()):
                    cle = getattr(p, 'options_source', None)
                    if cle:
                        vues.add(cle)
        for cle in sorted(vues - connues):
            self.assertIn(cle, resolues,
                          f"options_source « {cle} » ne résout par aucun registre commun — "
                          f"la déclarer dans OPTION_SOURCES (endpoint) ou PAGE_OPTION_SOURCES "
                          f"(donnée de page), ou l'assumer explicitement")


class EmissionsDuGabaritTest(SimpleTestCase):
    """Les émissions ajoutées au fil du chantier converter_01 (30-31/08) — chacune est née
    d'un échec ou d'un skip MESURÉ du harnais nocturne ; ces tests empêchent leur retour
    sans dépendre de l'existence d'une jumelle locale."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        src, raison = render_index(_manifeste(SOURCE))
        cls.src = src if not isinstance(src, dict) else src.get('index.html')
        cls.card = '' if not isinstance(src, dict) else (src.get('_generic_card.html') or '')
        cls.raison = raison

    def setUp(self):
        if not self.src:
            self.skipTest(f'index non généré : {self.raison}')

    def test_la_card_generee_est_une_card_v3_complete(self):
        # Recadrage Fabien 30/08 : la card squelette (instrument de mesure d'écart) a servi,
        # l'écart est fermé — la card émise porte les 5 sections et les contrats communs.
        for marqueur in ('wcv3-head', 'wcv3-sec--input', 'wcv3-sec--settings',
                         'wcv3-sec--output', 'wcv3-sec--state', 'wcv3-sec--actions',
                         'wcv3-bar', '_cycle_button.html', '_card_chips.html',
                         'duplicate-btn', 'delete-btn', 'settings-btn',
                         'unified_preview', 'data-output-format'):
            self.assertIn(marqueur, self.card, f'card générée sans {marqueur}')

    def test_l_import_de_dossier_est_offert(self):
        # Skip mesuré 30/08 : « folder_input_id non déclaré sur la card d'entrée commune ».
        self.assertIn("folder_input_id=", self.src)
        # Le CÂBLAGE de l'input dossier est porté par la brique depuis le 05/09 : le gabarit
        # le DÉCLARE (`folderInputId`) au lieu d'écrire lui-même l'écouteur WamaFolderImport
        # — un câblage écrit dans le gabarit généré n'existait pour aucune app hors générateur.
        self.assertIn("folderInputId:", self.src, 'affordance sans câblage = input mort')

    def test_le_volet_actions_de_l_inspecteur_est_emis(self):
        # Skip mesuré 30/08 : « pas de volet #inspectorActions sur cette page ».
        self.assertIn("_inspector_actions.html", self.src)

    def test_la_card_mere_recoit_les_actions_communes_quand_les_routes_existent(self):
        # Échec mesuré 30/08 : « la card mère n'émet pas [del, dup, start] ».
        self.assertIn("actions_communes=True", self.src)
        # Discriminant : sans les routes de lot au manifeste, PAS d'opt-in (un data-batch-*-url
        # vers une route absente serait un lien mort silencieux).
        from copy import deepcopy
        manifest = deepcopy(_manifeste(SOURCE))
        proc = (manifest.get('body') or {}).get('processing') or {}
        proc['endpoints'] = [e for e in (proc.get('endpoints') or [])
                             if e not in ('batch_delete', 'batch_duplicate', 'batch_start')]
        proc['extra_routes'] = [e for e in (proc.get('extra_routes') or [])
                                if (e.get('name') or '') not in
                                ('batch_delete', 'batch_duplicate', 'batch_start')]
        src2, _ = render_index(manifest)
        if isinstance(src2, dict):
            src2 = src2.get('index.html') or ''
        self.assertNotIn('actions_communes=True', src2 or '')

    def test_les_data_param_couvrent_tout_le_schema(self):
        # Constat Fabien 31/08 : la modale enregistrait 3 champs sur 20 et le volet était
        # vide — la card doit porter un data-* pour CHAQUE champ du schéma (les valeurs
        # hors-colonnes sont aplaties par _decorer, idiome params_storage dérivé).
        # ⚠ Graphie = LE CONTRAT du parc depuis le 02/09 (`card_gear` : champ à TIRETS →
        # dataset.camelCase). L'ancien `data-param-<champ>` était un vocabulaire PRIVÉ du
        # générateur : son propre ouvreur le relisait, mais le cardSettings dérivé (volet)
        # et sharedGearValues (modale de lot) cherchaient la graphie du contrat et ne
        # trouvaient RIEN — deux moitiés d'une paire qui ne se parlaient plus.
        self.assertIn('data-quality', self.card,
                      'un champ du schéma doit avoir son data-* en graphie du contrat')
        self.assertIn('data-output-format', self.card)
        self.assertNotIn('data-param-', self.card,
                         'le vocabulaire privé data-param-* ne doit pas revenir')


class SlotDeReferenceGenereTest(SimpleTestCase):
    """Le slot de référence de la card générée : DÉRIVÉ du port `reference` du manifeste.

    §S2bis.6 (b) : `inputs[]` ne se déclarait que sur un MODE, or 6 apps sur 10 n'ont pas de
    switch — leur typage par slot vivait en littéral dans 2 gabarits d'app, et une app générée
    naissait avec UN slot unique (le sélecteur du slot « image de travail » aurait proposé
    `.docx` dès la 2ᵉ app portée). Depuis le 2026-08-30 un domaine sans switch déclare ses
    `inputs`, `studio_node_ports` en dérive le port, et le gabarit lit LE PORT.
    Baseline mesurée : `show_reference` était absent du gabarit sur HEAD (0 occurrence).
    """

    def _rendu(self, manifest):
        src, raison = render_index(manifest)
        if isinstance(src, dict):
            src = src.get('index.html')
        if not src:
            self.skipTest(f'index non généré : {raison}')
        return src

    def _include_card(self, src):
        # ⚠ Cibler la BALISE D'INCLUSION, pas une mention du nom (2026-09-04) : la brique a
        # une v4 (`_new_item_card_v4.html`, CARD_DESIGN §11.11) et un commentaire de gabarit
        # qui la cite passait AVANT la vraie ligne — le test mesurait alors une phrase de
        # prose. Le préfixe `{% include 'common/_new_item_card` couvre les deux versions et
        # ne peut matcher qu'une inclusion.
        for ligne in src.splitlines():
            if "{% include 'common/_new_item_card" in ligne:
                return ligne
        self.fail('le gabarit ne rend plus la card d\'entrée commune')

    def test_un_port_reference_declare_rend_le_slot_type(self):
        # Manifeste MUTÉ (pas l'état du jour du converter) : c'est ce qui distingue « dérivé »
        # de « écrit en dur avec la bonne valeur » (même recette que le vocabulaire d'entrée).
        from copy import deepcopy
        manifest = deepcopy(_manifeste(SOURCE))
        ports = (manifest.get('body') or {}).get('ports') or {}
        ports.setdefault('inputs', []).append(
            {'id': 'reference_voice', 'label': 'Voix de référence', 'group': 'reference',
             'types': ['audio'], 'multi': False})
        src = self._rendu(manifest)
        inc = self._include_card(src)
        self.assertIn('show_reference=True', inc)
        self.assertIn("reference_accept='audio/*'", inc,
                      'le slot doit être typé par les catégories du PORT')
        self.assertIn("reference_label='Voix de référence'", inc)
        self.assertIn('slot de référence RENDU', src,
                      "le câblage d'attache non généré doit être un TROU NOMMÉ, pas un silence")

    def test_sans_port_reference_aucun_slot_ne_se_rend(self):
        # Le converter n'a qu'une entrée de travail : un slot de référence y serait un mensonge
        # d'écran, symétrique du menu de formats sur une app `early`.
        inc = self._include_card(self._rendu(_manifeste(SOURCE)))
        self.assertNotIn('show_reference', inc)

    def test_la_chaine_complete_declare_derive_emet_sur_le_composer(self):
        """Bout en bout SUR LE VIVANT : domaine sans switch → port → émission.

        C'est le test qui était structurellement rouge avant le chantier (b) : le composer
        offrait `reference_accept='audio/*'` en littéral de gabarit, sa déclaration
        l'excluait (`input_extensions = TEXT` seul), et son manifeste n'avait aucun port
        `reference`. La mélodie a désormais UNE source : `APP_MODES['composer']`,
        `inputs` du domaine `composition`.
        """
        inc = self._include_card(self._rendu(_manifeste('composer')))
        self.assertIn('show_reference=True', inc)
        self.assertIn("reference_accept='audio/*'", inc)
        self.assertIn("reference_label='Mélodie de référence'", inc)

    def test_le_slot_travail_est_retreci_aux_categories_du_port(self):
        """Moitié TRAVAIL de §S2bis.6 (b), débloquée par le retrait de l'homonyme `text`.

        Manifeste MUTÉ (port travail réduit à `image`) : l'accept généré ne doit plus offrir
        `.mp3`, mais doit GARDER les formats de fichier de LOT (le même input les reçoit,
        détection structurelle). Sur le converter réel (5 catégories), l'accept est inchangé.
        """
        from copy import deepcopy
        manifest = deepcopy(_manifeste(SOURCE))
        ports = (manifest.get('body') or {}).get('ports') or {}
        for p in ports.get('inputs') or []:
            if p.get('group') == 'travail':
                p['types'] = ['image']
        src = self._rendu(manifest)
        m = re.search(r"file_accept='([^']*)'", self._include_card(src))
        self.assertIsNotNone(m)
        jetons = m.group(1).split(',')
        self.assertIn('.jpg', jetons)
        self.assertNotIn('.mp3', jetons, 'le slot image ne doit plus offrir de l’audio')
        self.assertIn('.txt', jetons, 'les formats de LOT restent acceptés (détection)')

    def test_sur_le_converter_reel_l_accept_reste_l_union_complete(self):
        # 5 catégories au port travail → rien à rétrécir : les 60 extensions déclarées passent.
        m = re.search(r"file_accept='([^']*)'", self._include_card(self._rendu(_manifeste(SOURCE))))
        jetons = m.group(1).split(',')
        self.assertIn('.zip', jetons)
        self.assertIn('.mp3', jetons)
        self.assertGreater(len(jetons), 50)

    def test_plusieurs_ports_reference_le_surplus_est_NOMME(self):
        # La card commune n'a qu'un slot de référence : le 2ᵉ port ne se rend pas, mais il ne
        # doit JAMAIS disparaître en silence (jamais d'omission silencieuse).
        from copy import deepcopy
        manifest = deepcopy(_manifeste(SOURCE))
        ports = (manifest.get('body') or {}).get('ports') or {}
        ports.setdefault('inputs', []).extend([
            {'id': 'reference_image', 'label': 'Image de référence (style)',
             'group': 'reference', 'types': ['image'], 'multi': False},
            {'id': 'reference_voice', 'label': 'Voix de référence', 'group': 'reference',
             'types': ['audio'], 'multi': False},
        ])
        src = self._rendu(manifest)
        inc = self._include_card(src)
        self.assertIn("reference_accept='image/*'", inc, 'le PREMIER port déclaré se rend')
        self.assertIn('port de référence supplémentaire NON rendu : `reference_voice`', src)


class VoletParametresGenereTest(SimpleTestCase):
    """L'hôte PARAMÈTRES du volet : UN SEUL, rendu au chargement, montré à la sélection.

    Défaut mesuré le 2026-08-31 (constat Fabien, capture) : l'émission de la veille passait
    comme `panelContainer` un second hôte (`ItemParams`) qu'AUCUN rendu ne remplissait — la
    section PARAMÈTRES restait vide à la sélection pendant que la modale, elle, s'affichait.
    La convention MESURÉE sur l'app réelle (converter/index.html) est : un hôte `d-none`
    rendu du même schéma que la modale (context 'panel'), basculé par la sélection."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        src, raison = render_index(_manifeste(SOURCE))
        cls.src = src if not isinstance(src, dict) else src.get('index.html')
        cls.raison = raison

    def setUp(self):
        if not self.src:
            self.skipTest(f'index non généré : {self.raison}')

    def test_un_seul_hote_rendu_et_pointe_par_panelContainer(self):
        self.assertNotIn('ItemParams', self.src,
                         "l'hôte fantôme (jamais rendu) ne doit pas réapparaître")
        # Le rendu au chargement vise l'hôte, et panelContainer pointe sur LE MÊME nœud (ph).
        self.assertIn("var ph = document.getElementById('converterPanelParams')", self.src)
        self.assertIn("WamaParams.render(ph,", self.src)
        self.assertIn("{ context: 'panel', values: PANEL_DEFAULTS", self.src)
        self.assertIn('panelContainer: ph,', self.src)

    def test_l_hote_montre_les_defauts_de_file_hors_selection(self):
        # Constat Fabien 31/08 (« les paramètres par défaut ne s'affichent pas ; au F5 je
        # retombe sur le template générique ») : l'hôte est VISIBLE au chargement avec les
        # DÉFAUTS des prochains dépôts (mêmes valeurs que la cascade serveur), la sélection
        # y applique la card, lot et désélection RÉ-APPLIQUENT les défauts.
        self.assertRegex(self.src, r'class="wama-params" id="converterPanelParams"')
        self.assertNotIn('wama-params d-none', self.src,
                         "l'hôte ne doit plus naître masqué — les défauts de file se voient")
        self.assertIn('Défauts des prochains dépôts', self.src)
        self.assertIn('var PANEL_DEFAULTS = {{ panel_defaults|default:', self.src)
        self.assertIn('WamaParams.apply(ph, PANEL_DEFAULTS)', self.src)
        idx_batch = self.src.index('renderBatchActions')
        self.assertIn('showPanelParams(false);', self.src[idx_batch:idx_batch + 300])
        self.assertIn('onDeselect: function () { showPanelParams(false); }', self.src)

    def test_les_valeurs_courantes_traversent_jusqu_au_moteur(self):
        # Ce qui reste à vérifier après la convergence P1 : le gabarit ne résout plus les
        # options lui-même, mais il doit PASSER ce dont le registre commun a besoin — les
        # valeurs. Volet : les défauts de file ; modale d'item : les valeurs de la card.
        # (Sans elles, `formats` ne saurait pas borner la liste à la nature de l'élément.)
        self.assertIn("{ context: 'panel', values: PANEL_DEFAULTS }", self.src)
        self.assertIn('values: v,', self.src)

    def test_les_cards_running_sont_pollees_par_la_brique_commune(self):
        # Audit 31/08 : la jumelle n'avait AUCUNE boucle — une card RUNNING n'avançait
        # jamais sans recharger la page. Poller commun + remplacement par le partial
        # serveur (card_html, source unique du markup), gaté par les DEUX routes.
        self.assertIn('new WamaApp.Poller({', self.src)
        # `status` et non `progress` : le converter est le seul du parc à ce nom (cadrage
        # A0) — le gating passe par resolve_route + l'alias, jamais par le nom canonique
        # en dur (c'est ce nom en dur qui avait rendu `poll: False` en silence).
        self.assertIn("urlTemplate: \"{% url 'converter:status' 0 %}\"", self.src)
        self.assertIn("{% url 'converter:card_html' 0 %}", self.src)
        self.assertIn("card.replaceWith(tpl.content.firstElementChild)", self.src)

    def test_la_card_non_terminee_montre_la_preview_de_sa_source(self):
        # Demande Fabien 31/08 (« la preview n'apparaît pas dans les cards, uniquement dans
        # le volet droit ») : même hydrateur commun, face input, tant que le résultat
        # n'existe pas ; face output en SUCCESS, comme avant.
        src, _ = render_index(_manifeste(SOURCE))
        card = (src or {}).get('_generic_card.html') or ''
        if not card:
            self.skipTest('card non générée')
        self.assertIn('?side=output', card)
        self.assertIn('?side=input', card,
                      'la card en attente doit hydrater la preview de sa SOURCE')
        self.assertNotIn('<div id="preview-row-{{ item.id }}"></div>', card,
                         'le placeholder MORT (jamais hydraté) ne doit pas revenir')

    def test_la_card_mere_affiche_les_reglages_communs_des_filles(self):
        # Mécanisme DU PARC (« déjà acté et en place, juste à câbler » — Fabien 31/08) :
        # slot meta_template de _batch_card.html, pilote transcriber (modèle/langue/
        # diarisation calculés « valeur si partagée par toutes les filles »). La jumelle ne
        # passait pas le slot. Ici : chips GÉNÉRÉS du schéma sur les valeurs partagées.
        src, _ = render_index(_manifeste(SOURCE))
        idx = (src or {}).get('index.html') or ''
        # Depuis la promotion au COMMUN (31/08) : le générateur n'émet plus de partial
        # d'app — il passe le partial commun, comme n'importe quelle app portée.
        self.assertIn("meta_template='common/_batch_meta_chips.html'", idx,
                      'le slot méta de la card mère doit viser le partial COMMUN')
        self.assertNotIn('_batch_meta.html', str(sorted((src or {}).keys())),
                         'un partial de méta par app généré = duplication du commun')

    def test_la_brique_des_communs_de_mere_applique_la_regle_du_pilote(self):
        # « Valeur si partagée par toutes les filles, sinon rien » (transcriber) — sur TOUT
        # champ chip=True du schéma, divergence OMISE, assiette `values_of` pour les JSON.
        from wama.common.utils.card_chips import common_chips_for_items
        params = [{'name': 'quality', 'type': 'range', 'chip': True, 'label': 'Qualité'},
                  {'name': 'output_format', 'type': 'select', 'chip': True,
                   'section': 'output', 'label': 'Format'}]
        class _I:
            def __init__(self, q, f): self.quality, self.output_format = q, f
        memes = [_I(85, 'webp'), _I(85, 'webp')]
        divergent = [_I(85, 'webp'), _I(60, 'webp')]
        cc = common_chips_for_items(memes, params)
        self.assertEqual([c['label'] for c in cc.get('settings') or []], ['Qualité 85'])
        self.assertEqual([c['label'] for c in cc.get('output') or []], ['webp'])
        cc2 = common_chips_for_items(divergent, params)
        self.assertNotIn('settings', cc2, 'une valeur divergente ne produit AUCUN chip')
        self.assertEqual(common_chips_for_items([], params), {})

    def test_le_gear_de_lot_recoit_son_ouvreur(self):
        # La brique commune tient le clic du ⚙ de card MÈRE et attend un ouvreur déclaré
        # (`onBatchSettings`) ; sans émission le clic n'aboutissait qu'à un console.warn —
        # « la modale du batch ne s'affiche pas » (constat Fabien 31/08). Contexte 'batch' :
        # seuls les params le déclarant se rendent (préréglage qualité, format).
        self.assertIn('WamaQueueActions.onBatchSettings(function (bid)', self.src)
        self.assertIn("context: 'batch',", self.src)
        self.assertIn('urlFor(U.batch_update, bid)', self.src)
        self.assertIn("batch_update:", self.src, 'la route de lot doit entrer dans U')


class CardGearPolymorpheTest(SimpleTestCase):
    """`card_gear.gear_data` accepte objets Param ET dicts (schema_to_dicts / manifeste).

    Défaut mesuré le 2026-08-31 : `_decorer` généré (views_gen) lui passait `PARAMS_JSON`
    (des dicts) ; `getattr` sur dict rendait None → chaque param sauté au filtre de contexte
    → `{}` SANS LEVER. Le ⚙ de la jumelle ne portait que `data-id`, le volet n'avait donc
    aucune valeur à appliquer. La brique sœur `card_chips` consommait déjà les dicts : deux
    contrats pour deux briques jumelles était le défaut de fond."""

    class _Objet:
        pass

    def _instance(self):
        o = self._Objet()
        o.output_format = 'jpg'
        o.quality = 85
        o.flip_h = True
        return o

    def test_les_dicts_du_manifeste_produisent_les_memes_data_que_les_objets_Param(self):
        from wama.common.utils.card_gear import gear_data
        from wama.common.utils.param_schema import Param, schema_to_dicts
        params = [
            Param(name='output_format', type='select', contexts=('item', 'panel')),
            Param(name='quality', type='range', contexts=('item',)),
            Param(name='flip_h', type='toggle', contexts=('item',)),
            Param(name='quality_preset', type='select', contexts=('batch',)),  # PAS 'item'
        ]
        attendu = {'output-format': 'jpg', 'quality': 85, 'flip-h': 'true'}
        self.assertEqual(gear_data(self._instance(), params), attendu)
        self.assertEqual(gear_data(self._instance(), schema_to_dicts(params)), attendu,
                         'les dicts (PARAMS_JSON, chemin des vues GÉNÉRÉES) doivent produire '
                         'les mêmes data-* que les objets — le {} silencieux était le défaut')

    def test_un_param_item_sans_valeur_emet_une_chaine_vide(self):
        # Contrat : TOUS les params 'item' sont émis ('' si absents) — un changement de
        # sélection ne laisse pas les valeurs de la card précédente dans le volet.
        from wama.common.utils.card_gear import gear_data
        params = [{'name': 'fps', 'type': 'number', 'contexts': ['item']}]
        self.assertEqual(gear_data(self._Objet(), params), {'fps': ''})

    def test_chips_lisent_le_conteneur_json_via_values_comme_gear_data(self):
        # Brique JUMELLE de gear_data, même contrat `values` : les réglages d'un converter
        # vivent dans options/cross_app_options, pas en colonnes — sans `values`, chipper un
        # champ hors-colonne rendait silencieusement RIEN (getattr → None → filtré ; mesuré
        # 31/08 sur le converter réel en chippant quality/upscale).
        from wama.common.utils.card_chips import chips_by_section
        params = [
            {'name': 'quality', 'type': 'range', 'chip': True, 'label': 'Qualité'},
            {'name': 'upscale', 'type': 'select', 'chip': True, 'label': 'Upscaling',
             'choices': [['', 'Aucun'], ['x2', '×2']]},
            {'name': 'output_format', 'type': 'select', 'chip': True, 'section': 'output',
             'label': 'Format'},
        ]
        obj = self._Objet()
        obj.output_format = 'webp'          # colonne : getattr suffit
        obj.flip_h = 'false'                # chaîne du JSON — ne doit produire AUCUN chip
        params.append({'name': 'flip_h', 'type': 'toggle', 'chip': True,
                       'label': 'Miroir horizontal', 'chip_label': 'Miroir H'})
        params.append({'name': 'fps', 'type': 'number', 'chip': True,
                       'label': 'Images/s (FPS)', 'chip_label': 'fps'})
        params.append({'name': 'engine', 'type': 'select', 'chip': True, 'label': 'Moteur',
                       'option_groups': [['IA', [['esr', 'Real-ESRGAN']]]]})
        sections = chips_by_section(
            obj, params, values={'quality': 85, 'upscale': 'x2', 'fps': 24, 'engine': 'esr'})
        # Règle issue de l'audit du 31/08 (« résoudre mieux, pas préfixer plus ») :
        # NOMBRE → libellé préfixé (« Qualité 85 ») ou UNITÉ suffixée (chip_label court
        # minuscule = unité, idiome imager : « 24 fps », pas « fps 24 ») ; option résolue —
        # y compris via option_groups, le trou enhancer — → son libellé seul ; select/text
        # NON résolu → valeur NUE (le préfixe donnait « Format de sortie mp4 » en SORTIE) ;
        # 'false' (chaîne) → rien.
        self.assertEqual([c['label'] for c in sections.get('settings') or []],
                         ['Qualité 85', '×2', '24 fps', 'Real-ESRGAN'])
        self.assertEqual([c['label'] for c in sections.get('output') or []], ['webp'])


class DefautsApplicablesTest(SimpleTestCase):
    """`applicable_defaults` : la couche BASSE de la cascade du dépôt (défauts ← user_settings
    ← POST). Un élément frais sans elle n'a AUCUNE valeur — section RÉGLAGES de card vide et
    volet aux champs blancs jusqu'au premier passage par la modale (constat Fabien 31/08)."""

    SCHEMA = [
        {'name': 'media_type', 'type': 'hidden', 'contexts': ['item']},
        {'name': 'quality', 'type': 'range', 'default': 85, 'contexts': ['item', 'panel'],
         'show_if': {'field': 'media_type', 'equals': 'image'}},
        {'name': 'gif_fps', 'type': 'number', 'default': 12, 'contexts': ['item'],
         'show_if': {'field': 'media_type', 'equals': 'video'}},
        {'name': 'rotation', 'type': 'select', 'contexts': ['item'],
         'show_if': {'field': 'media_type', 'in': ['image', 'video']}},   # sans default
        {'name': 'quality_preset', 'type': 'select', 'default': 'web', 'contexts': ['batch']},
    ]

    def test_seuls_les_defauts_de_la_famille_visible_s_appliquent(self):
        from wama.common.utils.param_schema import applicable_defaults
        self.assertEqual(applicable_defaults(self.SCHEMA, {'media_type': 'image'}),
                         {'quality': 85},
                         "gif_fps (famille vidéo) ne doit PAS se poser sur une image — l'app "
                         "réelle ne poste que les champs VISIBLES de sa zone de composition")
        self.assertEqual(applicable_defaults(self.SCHEMA, {'media_type': 'video'}),
                         {'gif_fps': 12})

    def test_un_contexte_batch_ou_un_default_absent_ne_produisent_rien(self):
        from wama.common.utils.param_schema import applicable_defaults
        defauts = applicable_defaults(self.SCHEMA, {'media_type': 'image'})
        self.assertNotIn('quality_preset', defauts, "contexte 'batch' : pas un réglage d'item")
        self.assertNotIn('rotation', defauts, 'visible mais sans default : rien à poser')

    def test_la_cascade_complete_defauts_preset_posees(self):
        # LA cascade (ROADMAP §23.2bis) : défauts du schéma ← preset ← réglages POSÉS.
        from wama.common.utils.param_schema import effective_settings
        # (a) rien de posé, pas de preset → le défaut du schéma s'applique
        self.assertEqual(effective_settings(self.SCHEMA, contexte={'media_type': 'image'}),
                         {'quality': 85})
        # (b) un preset ÉCRASE le défaut — c'est tout l'objet d'un préréglage
        self.assertEqual(
            effective_settings(self.SCHEMA, preset={'quality': 80},
                               contexte={'media_type': 'image'}),
            {'quality': 80})
        # (c) un réglage POSÉ écrase le preset — l'utilisateur a le dernier mot
        self.assertEqual(
            effective_settings(self.SCHEMA, posees={'quality': 95}, preset={'quality': 80},
                               contexte={'media_type': 'image'}),
            {'quality': 95})
        # (d) le show_if tient : le preset d'une AUTRE famille n'entre pas
        eff = effective_settings(self.SCHEMA, preset={'gif_fps': 24},
                                 contexte={'media_type': 'image'})
        self.assertEqual(eff, {'quality': 85, 'gif_fps': 24},
                         'un preset explicite passe (il est fourni par l’app pour CE média)')

    def test_une_valeur_vide_ne_compte_pas_comme_posee_mais_zero_et_False_si(self):
        # ⚠ C'est CE point qui rend un preset possible : « non réglé » doit être
        # distinguable. `''`/None = silence ; `0` et `False` sont des CHOIX (« 0 = inchangé »,
        # un interrupteur décoché) — même convention que la vue d'upload du converter.
        from wama.common.utils.param_schema import effective_settings
        self.assertEqual(
            effective_settings(self.SCHEMA, posees={'quality': ''}, preset={'quality': 80},
                               contexte={'media_type': 'image'})['quality'], 80)
        self.assertEqual(
            effective_settings(self.SCHEMA, posees={'quality': 0}, preset={'quality': 80},
                               contexte={'media_type': 'image'})['quality'], 0)

    def test_le_vocabulaire_show_if_est_celui_du_moteur_js(self):
        # wama-params.js::met — {field, in|equals} + legacy « nom de champ » = truthy.
        from wama.common.utils.param_schema import _show_if_met
        self.assertTrue(_show_if_met({'field': 'x', 'in': ['a', 'b']}, {'x': 'a'}))
        self.assertFalse(_show_if_met({'field': 'x', 'equals': 'a'}, {'x': 'b'}))
        self.assertTrue(_show_if_met('flag', {'flag': 'true'}))
        self.assertFalse(_show_if_met('flag', {'flag': 'false'}))
        self.assertTrue(_show_if_met(None, {}))


class ParamsGenereTest(SimpleTestCase):
    """Cible `params` d'app_sandbox substitute : params.py suit le MANIFESTE, pas une copie.

    La jumelle mesurée le 31/08 tournait sur une copie de params.py d'AVANT le 18/08 : sans
    le contexte 'panel', le rendu du volet filtrait tout (0 champ, en silence) alors que le
    manifeste était à jour. Un fichier que les vues générées consomment doit être
    substituable comme elles."""

    def test_le_fichier_genere_compile_et_porte_le_schema_du_manifeste(self):
        from wama.common.manifests.codegen.params_gen import render_params
        manifest = _manifeste(SOURCE)
        if not manifest:
            self.skipTest('manifeste converter absent')
        src, raison = render_params(manifest)
        self.assertIsNotNone(src, raison)
        self.assertIn('[manifest-gen app:converter]', src[:600],
                      'le fichier doit être MARQUÉ (write_back ne régénère que le marqué)')
        ns = {}
        exec(compile(src, '<test>', 'exec'), ns)   # le littéral s'évalue sans le dépôt autour
        schema = ns.get('PARAMS_JSON') or []
        self.assertTrue(schema, 'PARAMS_JSON attendu (primary du manifeste converter)')
        avec_panel = [p['name'] for p in schema if 'panel' in (p.get('contexts') or [])]
        self.assertIn('output_format', avec_panel,
                      "le contexte 'panel' du manifeste doit traverser — son absence était "
                      'le volet vide de converter_01')

    def test_la_cible_params_est_substituable(self):
        from wama.common.management.commands.app_sandbox import _SUBSTITUTABLE
        self.assertIn('params', _SUBSTITUTABLE)
        self.assertEqual(_SUBSTITUTABLE['params'][0], 'params.py')

    def test_write_back_et_substitute_partagent_le_meme_constructeur(self):
        # Zéro duplication : builtin/app.py (_write_params_file) délègue à render_params_source.
        import inspect
        from wama.common.manifests.builtin import app as builtin_app
        src = inspect.getsource(builtin_app._write_params_file)
        self.assertIn('render_params_source', src)
