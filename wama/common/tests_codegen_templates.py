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

    def test_le_resolver_genere_interroge_les_DEUX_registres_avant_de_se_plaindre(self):
        manifest = _manifeste(SOURCE)
        src, raison = render_index(manifest) if manifest else (None, 'manifeste absent')
        if isinstance(src, dict):
            src = src.get('index.html')
        if not src:
            self.skipTest(f'index non généré : {raison}')
        self.assertIn('WamaParams.resolvePageOptions(p, v)', src,
                      'le resolver généré ignore le registre des données de page')

    def test_toute_cle_declaree_par_une_app_resout_quelque_part_ou_est_ASSUMEE(self):
        # Garde de COUVERTURE : une nouvelle clé apparue dans un schéma d'app doit être
        # rattachée à un registre commun, ou inscrite ici comme trou assumé. Sans ce test, une
        # clé non résolue ne se voit qu'à l'écran, sur un select vide.
        from django.apps import apps as django_apps
        connues = set(SOURCES_NON_RESOLUES) | {'voices'}     # 'voices' = endpoint commun
        params = _lire(_JS + 'wama-params.js')
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
            self.assertIn(f'{cle}: function', params,
                          f"options_source « {cle} » ne résout par aucun registre commun — "
                          f'la déclarer dans PAGE_OPTION_SOURCES, ou l\'assumer explicitement')


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
        for ligne in src.splitlines():
            if '_new_item_card.html' in ligne:
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
