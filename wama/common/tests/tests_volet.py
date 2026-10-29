"""Tests du VOLET DROIT DÉCLARATIF (`common/utils/volet.py`, `base.html`, `WAMA_VOLETS.md`).

Ce qui est vérifié est ce qui a été EXIGÉ du chantier, dans cet ordre :

1. **Défaut inchangé ⇒ zéro régression.** Une page qui ne déclare rien garde ses trois
   sections. C'est la contrainte n°1 : les 10 apps ne doivent rien écrire. Deux angles, parce
   qu'ils peuvent casser séparément — le dict par défaut (context processor) et le rendu réel
   des pages d'app.
2. **Une déclaration RETIRE**, et un retrait total enlève l'`<aside>` ET pose la classe qui
   rend sa largeur au corps. Sans le second, on aurait déplacé le décor au lieu de l'ôter.
3. **`tete` garde le volet ouvert** pour une page qui n'a que le bloc libre (accueil/avatar).

⚠ Le piège que ces tests gardent : un dict PARTIEL. `{% if volet.medias %}` sur une clé absente
vaut faux en Django — une déclaration partielle masquerait donc les sections non citées, soit
l'inverse exact du défaut voulu. `volet()` rend toujours un dict complet ; `test_dict_complet`
est là pour qu'on ne « simplifie » pas ça un jour.
"""
from django.contrib.auth.models import AnonymousUser
from django.template.loader import render_to_string
from django.test import RequestFactory, TestCase

from wama.common.context_processors import volet_defaut
from wama.common.utils.volet import SECTIONS, VOLET_AUCUN, VOLET_DEFAUT, volet

MARQUEURS = {
    'medias': 'id="media-section"',
    'parametres': 'id="settings-section"',
    'actions': 'id="actions-section"',
}
#: Contenu que `base.html` rend quand la page NE SURCHARGE PAS le bloc de la section.
#: Une section rendue qui porte encore ce contenu EST le « cadre vide » que le chantier du
#: 2026-08-22 a supprimé — c'est ce couple (section rendue + contenu par défaut) qui se
#: mesure, jamais la présence de la section seule : une page peut légitimement rouvrir une
#: section POUR LA REMPLIR (cf. `PagesDeclarantesTest`).
#: ⚠ Médias (« Aperçu » depuis le 2026-10-28) se reconnaît à son INVITE par défaut, plus à son
#: conteneur d'aperçu (2026-10-18) : ce conteneur est aussi l'hôte de l'inspecteur, qui y montre la
#: card cliquée (journal, calendrier) — masqué tant que rien n'est sélectionné.
#: Une page qui l'héberge dit SA propre invite (`right_panel_media_hint`) ; l'invite de `base.html`
#: (« Sélectionnez un fichier ») n'a de sens que là où un fichier se sélectionne.
DEFAUTS = {
    'medias': "Sélectionnez un fichier<br>pour l'aperçu",
    'parametres': 'Aucun paramètre disponible',
    'actions': '<!-- Actions will be added by apps -->',
}
ASIDE = 'id="wama-right-panel"'
SANS_VOLET = 'class="wama-sans-volet"'


def _rendu(volet_declare=None):
    """Rend `base.html` comme le ferait une vue — processors compris."""
    requete = RequestFactory().get('/')
    requete.user = AnonymousUser()
    contexte = {} if volet_declare is None else {'volet': volet_declare}
    return render_to_string('base.html', contexte, request=requete)


class ContratTest(TestCase):
    """La déclaration elle-même, avant tout rendu."""

    def test_dict_complet(self):
        # Toute déclaration porte TOUTES les clés, même celles qu'on n'a pas citées.
        d = volet(medias=False)
        for cle in SECTIONS:
            self.assertIn(cle, d, f"clé '{cle}' absente : un dict partiel masquerait "
                                  "les sections non citées (défaut Django : absent == faux)")
        self.assertFalse(d['medias'])
        self.assertTrue(d['parametres'], "un retrait doit être CIBLÉ, pas contagieux")
        self.assertTrue(d['actions'])

    def test_actif_est_derive(self):
        self.assertTrue(volet()['actif'])
        self.assertTrue(volet(tete=True, medias=False, parametres=False, actions=False)['actif'],
                        "le bloc de tête seul doit garder le volet ouvert (accueil/avatar)")
        self.assertFalse(VOLET_AUCUN['actif'])

    def test_defaut_du_processor_est_le_defaut_historique(self):
        self.assertEqual(volet_defaut(None)['volet'], VOLET_DEFAUT)
        self.assertTrue(all(VOLET_DEFAUT[c] for c in ('medias', 'parametres', 'actions')))
        self.assertFalse(VOLET_DEFAUT['tete'], "le bloc de tête n'a jamais été un défaut")


class DefautTest(TestCase):
    """Contrainte n°1 : sans déclaration, RIEN ne change."""

    def test_aucune_declaration_rend_les_trois_sections(self):
        html = _rendu()
        self.assertIn(ASIDE, html)
        for cle, marqueur in MARQUEURS.items():
            self.assertIn(marqueur, html, f"section '{cle}' perdue alors qu'aucune page ne "
                                          "l'a retirée — le défaut a changé")
        self.assertNotIn(SANS_VOLET, html)

    def test_hote_de_l_inspecteur_present_avec_les_medias(self):
        # #info-section n'a pas de déclaration propre : il suit Médias (cf. base.html).
        html = _rendu()
        self.assertIn('id="info-section"', html)
        self.assertIn('id="inspectorInfo"', html)


class DeclarationTest(TestCase):
    """Une déclaration retire — et un retrait total rend sa largeur au corps."""

    def test_retrait_cible(self):
        html = _rendu(volet(medias=False))
        self.assertNotIn(MARQUEURS['medias'], html)
        self.assertIn(MARQUEURS['parametres'], html)
        self.assertIn(MARQUEURS['actions'], html)
        self.assertIn(ASIDE, html, "il reste des sections : le volet doit rester rendu")

    def test_retrait_total(self):
        html = _rendu(VOLET_AUCUN)
        for marqueur in MARQUEURS.values():
            self.assertNotIn(marqueur, html)
        self.assertNotIn(ASIDE, html, "aucune section : l'aside lui-même doit disparaître")
        self.assertIn(SANS_VOLET, html,
                      "sans cette classe, le CSS laisse 360 px de bande morte à droite "
                      "(body > .container-fluid porte margin-right: !important)")

    def test_tete_seule(self):
        html = _rendu(volet(tete=True, medias=False, parametres=False, actions=False))
        self.assertIn(ASIDE, html)
        self.assertNotIn(SANS_VOLET, html)
        for marqueur in MARQUEURS.values():
            self.assertNotIn(marqueur, html)


class PagesDeclarantesTest(TestCase):
    """Les pages transversales déclarent — et leur déclaration PREND EFFET sur la page rendue.

    Sans ce test, le mécanisme pourrait être juste et les 17 déclarations inertes (oubli d'un
    `context[...]`, vue qui reconstruit son contexte, gabarit qui n'étend pas `base.html`).
    On mesure donc la PAGE, pas la vue.

    ⚠⚠ CE QUE CE TEST MESURE A CHANGÉ LE 2026-09-09, ET POURQUOI. Il exigeait « aucune de ces
    pages ne rend AUCUN cadre » — l'état exact du 2026-08-22, où les 17 pages déclaraient
    `VOLET_AUCUN`. Le 2026-09-09, sur demande de Fabien, **cinq pages de liste ont RÉCUPÉRÉ un
    volet** pour héberger l'inspecteur de détail (`licenses`, `registres`, `skills`, `backends`,
    `rag` — `tests_inspecteur_registre.py`) : elles déclarent `volet(medias=False,
    actions=False)` et REMPLISSENT la section Paramètres (titre « Détail de l'élément »,
    `_inspector_registre.html`). Le test est donc devenu rouge en décrivant une intention
    volontairement abandonnée — et il l'était contre `registres` la première de sa liste, ce qui
    MASQUAIT les deux autres pages concernées (`licences`, `rag`).

    *Un test qui fige un ÉTAT se périme dès que l'état bouge pour de bonnes raisons ; deux tests
    du même dépôt se contredisaient alors, sans que l'un ni l'autre ait tort.* Il mesure
    désormais l'INVARIANT que le chantier visait vraiment — son titre le disait déjà :
    « 17 pages cessent d'hériter de 54 cadres VIDES ». Une section rendue est licite ; une
    section rendue avec le contenu par défaut de `base.html` ne l'est pas. L'invariant survit
    à ce qu'une page ouvre ou ferme une section, et il couvre les pages qu'aucune liste ne cite.
    """

    @classmethod
    def setUpTestData(cls):
        from django.contrib.auth import get_user_model
        # Superutilisateur : plusieurs de ces pages sont réservées à l'administration
        # (matrice d'accès, gestion des utilisateurs). Créé dans la base de TEST, jamais
        # dans la vraie — `TestCase` la détruit à la fin.
        cls.compte = get_user_model().objects.create_superuser(
            username='volet_test', email='volet@test.local', password='x')

    def setUp(self):
        self.client.force_login(self.compte)

    #: (libellé, nom d'URL) — les URLs sont RÉSOLUES, jamais écrites en dur.
    PAGES = [
        ('registres', 'common:registries'),
        ('licences', 'common:licenses_catalog'),
        ('mon RAG', 'common:rag'),
        ('médiathèque', 'media_library:index'),
        ('catalogue de fonctions', 'model_manager:functions_catalog'),
        ('catalogue de librairies', 'model_manager:libraries_catalog'),
        ('profil', 'accounts:profile'),
        # 2026-10-28 : déclarait « aucun volet » depuis le 20/10 dans une méthode que la suivante
        # remplaçait — trois cadres vides, que cette liste ne mesurait pas.
        ('modifier mon compte', 'accounts:user-edit'),
        ('gestion des utilisateurs', 'accounts:user-management'),
        ("matrice d'accès", 'accounts:app-access-matrix'),
        ('connexion', 'accounts:login'),
        # Namespaces IMBRIQUÉS : les apps du Lab sont incluses sous `wama_lab`
        # (wama/urls.py:48 → wama_lab/urls.py). `face_analyzer:index` ne résout pas.
        ('face_analyzer', 'wama_lab:face_analyzer:index'),
        # 2026-10-18 : la card de l'élément cliqué au volet, sans cadre « Aucun paramètre ».
        ('journal', 'common:journal'),
        ('calendrier', 'common:calendar'),
        # 2026-10-20 : le Studio déclare ce qu'il remplit (l'inspecteur du nœud, ses actions).
        ('studio', 'studio:index'),
    ]

    def _pages_rendues(self):
        """(libellé, html) de chaque page atteignable — et l'inventaire de ce qui a échappé.

        Rendu UNE fois pour les deux tests qui suivent : chacun mesure une propriété
        différente du MÊME rendu, et les faire diverger sur deux parcours serait le meilleur
        moyen qu'ils finissent par ne plus parler des mêmes pages.
        """
        from django.urls import NoReverseMatch, reverse

        rendues, introuvables, detournees = [], [], []
        for libelle, nom_url in self.PAGES:
            try:
                chemin = reverse(nom_url)
            except NoReverseMatch:
                introuvables.append(f"{libelle} ({nom_url})")
                continue
            reponse = self.client.get(chemin)
            if reponse.status_code != 200:
                detournees.append(f"{libelle} (HTTP {reponse.status_code})")
                continue
            rendues.append((libelle, reponse.content.decode('utf-8', 'replace')))
        self.assertFalse(introuvables, f"URL(s) irrésolvable(s) : {introuvables}")
        # 10 et non 11 : la page de CONNEXION redirige (302) parce que ce test est authentifié —
        # il le faut pour les pages d'administration. Elle est mesurée en VISITEUR plus bas,
        # donc la couverture est complète malgré ce seuil.
        self.assertGreaterEqual(
            len(rendues), 10,
            f"trop peu de pages mesurées ({[l for l, _ in rendues]}) — "
            f"détournées : {detournees}")
        return rendues

    def test_les_pages_declarantes_ne_rendent_aucun_cadre_VIDE(self):
        """L'invariant du chantier : une section rendue est REMPLIE, sinon elle ne l'est pas.

        C'est ce que « 54 cadres vides » désignait. Une page peut rouvrir une section (les 5
        pages de l'inspecteur de registre l'ont fait le 09/09) — à condition de la remplir.
        """
        fautes = []
        for libelle, html in self._pages_rendues():
            for cle, marqueur in MARQUEURS.items():
                if marqueur in html and DEFAUTS[cle] in html:
                    fautes.append(f"{libelle} : section '{cle}' rendue avec le contenu par "
                                  f"défaut de base.html — cadre VIDE hérité")
        self.assertEqual([], fautes, "\n".join(fautes))

    def test_une_page_sans_section_perd_son_aside_et_rend_sa_largeur(self):
        """La cohérence structurelle, pour les pages qui ne gardent AUCUNE section.

        Les deux vont ensemble : sans `wama-sans-volet`, retirer l'aside laisserait 360 px de
        bande morte (le CSS réserve la place sur `body > .container-fluid`, en `!important`).
        """
        vides = []
        for libelle, html in self._pages_rendues():
            if any(m in html for m in MARQUEURS.values()):
                self.assertNotIn(SANS_VOLET, html,
                                 f"{libelle} : classe « sans volet » posée alors qu'une section "
                                 "est rendue — le panneau serait masqué avec son contenu")
                continue
            vides.append(libelle)
            self.assertNotIn(ASIDE, html, f"{libelle} : l'aside subsiste alors qu'il est vide")
            self.assertIn(SANS_VOLET, html,
                          f"{libelle} : classe absente → 360 px de bande morte à droite")
        self.assertGreaterEqual(len(vides), 5,
                                f"trop peu de pages au volet entièrement vide ({vides}) — "
                                "le retrait du 2026-08-22 a-t-il été défait ?")

    def test_la_page_de_connexion_en_visiteur(self):
        """Mesurée déconnectée : c'est le seul état où elle s'affiche."""
        from django.urls import reverse

        self.client.logout()
        reponse = self.client.get(reverse('accounts:login'))
        self.assertEqual(reponse.status_code, 200)
        html = reponse.content.decode('utf-8', 'replace')
        for cle, marqueur in MARQUEURS.items():
            self.assertNotIn(marqueur, html, f"connexion : cadre '{cle}' toujours rendu")
        self.assertIn(SANS_VOLET, html)

    def test_home_keeps_its_panel_for_the_avatar_and_the_assistant_settings(self):
        from django.urls import reverse

        html = self.client.get(reverse('home')).content.decode('utf-8', 'replace')
        self.assertIn(ASIDE, html, "l'accueil garde son volet : l'avatar y vit (right_panel_top)")
        self.assertNotIn(SANS_VOLET, html)
        # 2026-10-18 (décision de Fabien) : la section « Paramètres » porte les RÉGLAGES de
        # l'assistant, comme le volet d'une app — ils encombraient la carte du chat. Les autres
        # cadres restent retirés.
        self.assertIn(MARQUEURS['parametres'], html)
        self.assertIn('id="ai-settings"', html)
        for cle in ('medias', 'actions'):
            self.assertNotIn(MARQUEURS[cle], html,
                             f"accueil : cadre '{cle}' sous l'avatar — c'est ce que la "
                             "déclaration `tete=True` doit retirer (WAMA_VOLETS §5)")

    def test_the_preview_section_shows_only_what_is_selected(self):
        """2026-10-28, Fabien : « la section Médias n'a plus de sens, c'est la preview qui a pris
        sa place […] une section qui ne charge rien ». It is the PREVIEW (its title says so), and
        no page keeps it shown while nothing is selected: the journal and the calendar did
        (`keepMediaSection: true`), a 258 px frame holding an invitation. Only a page that lodges
        PERMANENT content there declares it — the model manager's system resources, shown while
        nothing is selected (`'no-selection'`)."""
        import re
        from pathlib import Path

        from django.conf import settings
        base = Path(settings.BASE_DIR)
        kept = []
        for root in ('wama', 'wama_lab'):
            for path in (base / root).rglob('*'):
                if path.suffix not in ('.js', '.html') or 'staticfiles' in path.parts:
                    continue
                text = path.read_text(encoding='utf-8', errors='replace')
                if re.search(r'keepMediaSection\s*:\s*true', text):
                    kept.append(str(path.relative_to(base)))
        self.assertEqual([], kept, 'the preview stays shown with nothing selected — an inert frame')
        page = (base / 'wama' / 'templates' / 'base.html').read_text(encoding='utf-8')
        self.assertIn('<i class="fas fa-eye me-1"></i> Aperçu{% endblock %}', page)
        self.assertNotIn('> Médias{% endblock %}', page)

    def test_cam_analyzer_garde_son_panneau_de_travail(self):
        from django.urls import NoReverseMatch, reverse
        try:
            chemin = reverse('wama_lab:cam_analyzer:index')     # namespace imbriqué
        except NoReverseMatch:
            self.skipTest('cam_analyzer non installé')
        reponse = self.client.get(chemin)
        if reponse.status_code != 200:
            self.skipTest(f'cam_analyzer inaccessible (HTTP {reponse.status_code})')
        html = reponse.content.decode('utf-8', 'replace')
        # ⚠ Un masquage automatique DÉTRUIRAIT la mini-carte Leaflet (WAMA_VOLETS §5).
        self.assertIn(ASIDE, html)
        for cle, marqueur in MARQUEURS.items():
            self.assertIn(marqueur, html,
                          f"cam_analyzer : section '{cle}' perdue — son volet est un PANNEAU "
                          "DE TRAVAIL permanent, pas un inspecteur")


class AccountPagesHaveNoDefaultTest(TestCase):
    """Une page du COMPTE n'a pas de volet par défaut (Fabien, 2026-10-20 : « on met les champs
    en fonction du contenu de la page, pas de champ par défaut ») : elle déclare ce qu'elle
    remplit, et sans déclaration elle n'a aucune section (`context_processors.volet_defaut`).

    Mesuré sur TOUTES les pages que le registre déclare (`app_registry.account_pages`), pas sur
    une liste : le jour même, quatre d'entre elles (Partages, Notifications, Formats médias,
    Apps) rendaient encore les trois cadres vides, et aucune liste ne les citait."""

    @classmethod
    def setUpTestData(cls):
        from django.contrib.auth import get_user_model
        cls.account = get_user_model().objects.create_superuser(
            username='volet_account_pages', email='volet-pages@test.local', password='x')

    def setUp(self):
        self.client.force_login(self.account)

    def test_no_account_page_renders_an_empty_default_section(self):
        from django.urls import NoReverseMatch, reverse

        from wama.common.app_registry import account_pages
        measured, faults = [], []
        for page in account_pages():
            try:
                path = reverse(page['url_name'])
            except NoReverseMatch:
                continue
            response = self.client.get(path)
            if response.status_code != 200 or 'text/html' not in response.get('Content-Type', ''):
                continue
            html = response.content.decode('utf-8', 'replace')
            measured.append(page['key'])
            faults += [f"{page['key']} : section '{key}' rendue avec le contenu par défaut"
                       for key, marker in MARQUEURS.items()
                       if marker in html and DEFAUTS[key] in html]
        self.assertGreaterEqual(len(measured), 10, f"trop peu de pages mesurées : {measured}")
        self.assertIn('shares', measured)
        self.assertEqual([], faults, "\n".join(faults))

    def test_a_section_the_page_fills_is_rendered(self):
        """L'autre moitié de l'invariant : une section qu'un gabarit de la page REMPLIT
        (`{% block right_panel_… %}` non vide) doit être rendue. Le jour où les pages du compte ont
        perdu leur défaut, le model manager — page du compte « Modèles » — a perdu TOUT son volet
        (ressources, propositions à valider, actions) : il ne déclarait rien, et le premier garde,
        qui ne cherchait que des cadres VIDES, n'avait rien à voir sur une page sans cadre."""
        import re

        from django.urls import NoReverseMatch, reverse

        from wama.common.app_registry import account_pages
        block = re.compile(r'{%\s*block\s+(?:app_)?right_panel_(media|settings|actions)\s*%}'
                           r'(.*?){%\s*endblock', re.S)
        comment = re.compile(r'{%\s*comment\s*%}.*?{%\s*endcomment\s*%}|{#.*?#}', re.S)
        section = {'media': 'medias', 'settings': 'parametres', 'actions': 'actions'}
        checked, faults = [], []
        for page in account_pages():
            try:
                path = reverse(page['url_name'])
            except NoReverseMatch:
                continue
            response = self.client.get(path)
            if response.status_code != 200 or 'text/html' not in response.get('Content-Type', ''):
                continue
            html = response.content.decode('utf-8', 'replace')
            for template in response.templates:
                source = getattr(template, 'source', '') or ''
                if (template.name or '').startswith('common/_') or template.name == 'base.html':
                    continue
                for name, body in block.findall(source):
                    if not comment.sub('', body).strip():
                        continue
                    checked.append(f"{page['key']}:{name}")
                    if MARQUEURS[section[name]] not in html:
                        faults.append(f"{page['key']} : remplit « {name} » "
                                      f"({template.name}) sans que la section soit rendue")
        self.assertIn('models:settings', checked, "le model manager n'est plus mesuré")
        self.assertEqual([], sorted(set(faults)), "\n".join(sorted(set(faults))))

    def test_an_undeclared_account_page_gets_no_section_and_an_app_page_keeps_its_three(self):
        from django.urls import reverse
        notifications = self.client.get(reverse('common:notifications'))
        self.assertEqual(VOLET_AUCUN, notifications.context['volet'])
        self.assertEqual(VOLET_DEFAUT, volet_defaut(None)['volet'])


class PagesDAppTest(TestCase):
    """Les apps du CATALOGUE ne déclarent RIEN : leurs pages portent les trois sections.

    C'est la preuve demandée (« les 10 apps doivent rendre à l'identique ») mesurée sur les
    pages RÉELLES et non sur `base.html` seul : une app pourrait déclarer par mégarde, ou un
    gabarit intermédiaire s'intercaler. Les pages qui redirigent (droits) sont comptées et
    signalées plutôt que tues — un test qui saute en silence finit par ne plus rien mesurer.

    ⚠ Le périmètre est `APP_CATALOG`, PAS `discoverable_apps()`. Les deux diffèrent, et la
    différence porte tout le sens du chantier : `media_library`, `model_manager` et `studio`
    exposent aussi un index, mais ce sont des surfaces TRANSVERSALES — la médiathèque figure
    justement parmi les 17 pages au volet vide (WAMA_VOLETS §2) et a vocation à déclarer.
    Les confondre ferait échouer ce test le jour où l'une d'elles déclare, c'est-à-dire au
    moment même où le chantier avance.
    """

    def test_les_apps_du_catalogue_gardent_leurs_sections(self):
        from wama.common.app_registry import APP_CATALOG
        from wama.common.services.ui_smoke import discoverable_apps

        vues, detournees = [], []
        for label, chemin in discoverable_apps():
            if label not in APP_CATALOG:
                continue
            reponse = self.client.get(chemin)
            if reponse.status_code != 200:
                detournees.append(f"{label} (HTTP {reponse.status_code})")
                continue
            html = reponse.content.decode('utf-8', 'replace')
            vues.append(label)
            for cle, marqueur in MARQUEURS.items():
                self.assertIn(marqueur, html,
                              f"{label} : section '{cle}' absente alors que l'app ne déclare "
                              "aucun volet — le défaut ne tient plus")
            self.assertNotIn(SANS_VOLET, html, f"{label} : classe de page sans volet posée à tort")
        self.assertGreaterEqual(len(vues), 10,
                                f"trop peu d'apps réellement mesurées ({vues}) — "
                                f"détournées : {detournees}")


class PanelBricksTest(TestCase):
    """Le volet d'une page en BRIQUES (2026-10-28, `WAMA_VOLETS §3-ter` étape ②) : ses sections
    sont des panneaux de la disposition commune, gardée par compte et par page.

    Ce qui est exigé : le rendu par défaut ne change pas (sans disposition gardée, ni la grille ni
    ses fichiers ne sont servis) ; la déclaration des sections vit au serveur, une fois ; la
    disposition est validée par la règle des surfaces (`clean_layout`), jamais par une seconde ;
    une page qui a SA disposition (une surface) ou qui la fera brique par brique (cam_analyzer)
    ne reçoit pas celle-ci. Les gestes eux-mêmes se jouent au navigateur (`common.panel_layout`)."""

    #: La grille SERVIE — sa balise, pas son adresse : le module la porte aussi en attribut, pour la
    #: charger au premier geste.
    GRID_JS = 'vendors/gridstack-13.3.0/gridstack-all.js"></script>'
    PANEL_JS = 'common/js/wama-panel-layout.js'

    @classmethod
    def setUpTestData(cls):
        from django.contrib.auth import get_user_model
        cls.account = get_user_model().objects.create_superuser(
            username='volet_bricks', email='volet-bricks@test.local', password='x')

    def setUp(self):
        from wama.common.utils.user_settings import clear_user_app_settings
        from wama.common.utils.volet import LAYOUT_SETTING
        # Le réglage se lit aussi du CACHE, que l'annulation de la base entre deux tests ne vide pas.
        for page in ('common', 'transcriber'):
            clear_user_app_settings(self.account, page, [LAYOUT_SETTING])
        self.client.force_login(self.account)

    def _open_page(self):
        from django.urls import reverse
        return self.client.get(reverse('common:journal'))

    def _post(self, page, payload):
        import json

        from django.urls import reverse
        return self.client.post(reverse('common:panel_layout', args=[page]), json.dumps(payload),
                                content_type='application/json')

    def test_every_declared_section_is_an_element_the_panel_renders(self):
        from pathlib import Path

        from django.conf import settings

        from wama.common.utils.volet import PANEL_SLOTS
        root = Path(settings.BASE_DIR) / 'wama'
        source = ((root / 'templates' / 'base.html').read_text(encoding='utf-8')
                  + (root / 'common' / 'templates' / 'common' / '_assistant_avatar.html')
                  .read_text(encoding='utf-8'))
        self.assertEqual(['assistant', 'top', 'preview', 'info', 'settings', 'actions'],
                         [s.id for s in PANEL_SLOTS], "l'ordre des sections est celui de base.html")
        for slot in PANEL_SLOTS:
            self.assertIn(f'id="{slot.element}"', source, f'{slot.id} : élément absent du volet')
            self.assertEqual(('panel', 0, 1), (slot.zone, slot.x, slot.w), 'la colonne du volet')
        self.assertEqual([0] + [s.y + s.h for s in PANEL_SLOTS[:-1]], [s.y for s in PANEL_SLOTS],
                         'chacune sous la précédente')

    def test_the_sections_are_declared_once_on_the_server(self):
        from pathlib import Path

        from django.conf import settings

        from wama.common.utils.volet import PANEL_SLOTS
        script = (Path(settings.BASE_DIR) / 'wama' / 'common' / 'static' / self.PANEL_JS).read_text(
            encoding='utf-8')
        copied = [s.element for s in PANEL_SLOTS if s.element in script]
        self.assertEqual([], copied, 'le module lit les sections du serveur, il ne les recopie pas')

    def test_the_default_panel_is_unchanged_until_the_account_arranges_it(self):
        page = self._open_page()
        self.assertContains(page, self.PANEL_JS)
        self.assertContains(page, 'id="wama-panel-layout"')
        self.assertNotContains(page, self.GRID_JS)
        self.assertNotContains(page, 'wama-panel-column')
        config = page.context['panel_layout']()
        self.assertEqual(('common', False), (config['page'], config['arranged']))

    def test_an_arranged_panel_is_kept_for_this_account_and_this_page(self):
        from django.contrib.auth import get_user_model

        from wama.common.utils.volet import layout_of
        response = self._post('common', {'slots': {'settings': {'x': 0, 'y': 0, 'w': 1, 'h': 6,
                                                                'zone': 'panel'}},
                                         'frozen': False, 'docked': {'bottom': [['actions']]}})
        self.assertEqual(200, response.status_code, response.content)
        page = self._open_page()
        self.assertContains(page, self.GRID_JS)          # servie d'emblée : rien ne saute
        config = page.context['panel_layout']()
        self.assertTrue(config['arranged'])
        self.assertEqual({'bottom': [['actions']]}, config['layout']['docked'])
        self.assertEqual({'x': 0, 'y': 0, 'w': 1, 'h': 6, 'zone': 'panel'},
                         config['layout']['slots']['settings'])
        other = get_user_model().objects.create_user(username='volet_other', password='x')
        self.assertFalse(layout_of(other, 'common')['stored'], 'un autre compte garde le sien')
        self.assertFalse(layout_of(self.account, 'transcriber')['stored'], 'une autre page aussi')

    def test_a_frozen_panel_without_gesture_is_the_panel_of_before(self):
        self.assertEqual(200, self._post('common', {'slots': None, 'frozen': True}).status_code)
        page = self._open_page()
        self.assertFalse(page.context['panel_layout']()['arranged'])
        self.assertNotContains(page, self.GRID_JS)

    def test_the_rule_of_the_surfaces_validates_the_panel(self):
        too_wide = self._post('common', {'slots': {'settings': {'x': 0, 'y': 0, 'w': 2, 'h': 3,
                                                                'zone': 'panel'}}})
        self.assertEqual(400, too_wide.status_code, 'la colonne du volet a une colonne')
        unknown_edge = self._post('common', {'docked': {'side': [['actions']]}})
        self.assertEqual(400, unknown_edge.status_code, 'un bord inconnu est refusé')
        dropped = self._post('common', {'slots': {'nowhere': {'x': 0, 'y': 0, 'w': 1, 'h': 3,
                                                              'zone': 'panel'}}})
        self.assertEqual(200, dropped.status_code)
        self.assertIsNone(dropped.json()['layout']['slots'], 'une section non déclarée est oubliée')
        self.assertEqual(404, self._post('9-not-a-page', {}).status_code)
        self.client.logout()
        self.assertEqual(302, self._post('common', {}).status_code)

    def test_a_page_key_names_the_closest_namespace(self):
        from django.urls import NoReverseMatch, resolve, reverse

        from wama.common.utils.volet import page_key
        request = RequestFactory().get('/')
        request.resolver_match = resolve(reverse('common:journal'))
        self.assertEqual('common', page_key(request))
        try:
            request.resolver_match = resolve(reverse('wama_lab:cam_analyzer:index'))
        except NoReverseMatch:
            return
        self.assertEqual('cam_analyzer', page_key(request))

    def test_a_page_with_its_own_layout_does_not_get_this_one(self):
        from django.urls import NoReverseMatch, reverse
        self.assertFalse(volet(arrangeable=False)['arrangeable'])
        self.assertTrue(volet()['arrangeable'] and VOLET_DEFAUT['arrangeable'])
        try:
            path = reverse('wama_lab:cam_analyzer:index')
        except NoReverseMatch:
            self.skipTest('cam_analyzer non installé')
        page = self.client.get(path)
        if page.status_code != 200:
            self.skipTest(f'cam_analyzer inaccessible (HTTP {page.status_code})')
        self.assertFalse(page.context['volet']['arrangeable'])
        self.assertNotContains(page, self.PANEL_JS)

    def test_the_panel_module_and_the_layout_parse_under_v8(self):
        from pathlib import Path

        from django.conf import settings
        from py_mini_racer import MiniRacer
        served = Path(settings.BASE_DIR) / 'staticfiles'
        for path in (self.PANEL_JS, 'common/js/wama-brick-layout.js'):
            MiniRacer().eval('(function(){' + (served / path).read_text(encoding='utf-8') + '})')

    def test_a_withdrawn_panel_stays_in_the_document_and_comes_back_at_its_rank(self):
        from pathlib import Path

        from django.conf import settings
        engine = (Path(settings.BASE_DIR) / 'staticfiles' / 'common' / 'js'
                  / 'wama-brick-layout.js').read_text(encoding='utf-8')
        self.assertIn('setShown: setShown', engine)
        # Garé, jamais détaché : l'inspecteur le retrouve par `getElementById` pour le remontrer.
        self.assertIn('parking.appendChild(el);', engine)
        self.assertIn('at.y = backAt(key, place);', engine)
        # Le volet seul : la grille du centre est facultative, la colonne suffit.
        self.assertIn('var grid = root ? global.GridStack.init(', engine)
        self.assertIn('opts.frameHost ||', engine)

    def test_a_panel_opens_in_another_window_and_keeps_working(self):
        """Un panneau DANS UNE AUTRE FENÊTRE (2026-10-28, `WAMA_DATA_WORLD §8.2 ⑤`) : déplacé, pas
        recréé ; les gestes faits dans la fenêtre rejoués sur la page, sauf une frappe de champ ; la
        page retrouve par son identifiant ce qui est parti ; fermée, la fenêtre le rend à sa place.
        Les gestes eux-mêmes : `common.panel_layout` (fenêtre ouverte, relais, retour au rang)."""
        from pathlib import Path

        from django.conf import settings
        served = Path(settings.BASE_DIR) / 'staticfiles' / 'common'
        engine = (served / 'js' / 'wama-brick-layout.js').read_text(encoding='utf-8')
        sheet = (served / 'css' / 'wama-surface.css').read_text(encoding='utf-8')
        self.assertIn("libelle: 'Dans une autre fenêtre'", engine)
        self.assertIn('doc.body.appendChild(el);', engine, 'déplacé, jamais recréé')
        self.assertIn("if (type.indexOf('key') === 0 && editable(e.target)) return;", engine)
        self.assertIn('document.body.dispatchEvent(new Kind(type, e));', engine)
        self.assertIn('document.getElementById = function (id)', engine)
        self.assertIn("win.addEventListener('pagehide', function () { closeWindow(key); });", engine)
        self.assertIn('if (!dockPlaces[key] && w.place) bringBack(key, w.place);', engine)
        # La fenêtre a l'allure de WAMA : la barre, le panneau qui l'occupe, ses menus de page absents.
        for rule in ('body.wama-panel-window {', '.wama-window-bar {',
                     'body.wama-panel-window .wama-brick-dock'):
            self.assertIn(rule, sheet)


class CentreBricksTest(TestCase):
    """Le CENTRE d'une page d'app en briques (2026-10-28, `WAMA_VOLETS §3-ter` étape ④) : la card
    d'entrée, la progression, la barre de la file et la file sont des briques de la même
    disposition que le volet, gardée par compte et par page.

    Ce qui est exigé : les briques se déclarent au serveur, un jeu par domaine pour une app à
    onglets ; les pièces COMMUNES les marquent, donc toute page qui rend la file les a, sans rien
    écrire ; une marque ne désigne jamais qu'un emplacement déclaré ; la carte du Studio et une
    barre montrée hors d'une file ne sont pas des briques ; la règle des surfaces valide aussi
    leurs places. Les gestes : `common.centre_layout`."""

    KINDS = ['entry_card', 'global_progress', 'toolbar', 'queue']

    @classmethod
    def setUpTestData(cls):
        from django.contrib.auth import get_user_model
        cls.account = get_user_model().objects.create_superuser(
            username='centre_bricks', email='centre-bricks@test.local', password='x')

    def setUp(self):
        from wama.common.utils.user_settings import clear_user_app_settings
        from wama.common.utils.volet import LAYOUT_SETTING
        clear_user_app_settings(self.account, 'describer', [LAYOUT_SETTING])
        self.client.force_login(self.account)

    @staticmethod
    def _apps():
        """Les apps en place qui ont une page d'index (les jumelles du bac à sable mises à part)."""
        from django.apps import apps
        from django.urls import NoReverseMatch, reverse
        out = []
        for cfg in apps.get_app_configs():
            if not cfg.name.startswith('wama.') or cfg.label.rsplit('_', 1)[-1].isdigit():
                continue
            try:
                out.append((cfg.label, reverse(f'{cfg.label}:index')))
            except NoReverseMatch:
                continue
        return out

    def test_the_centre_bricks_are_declared_once_per_domain(self):
        from wama.common.surfaces import BRICKS, GRID_COLUMNS
        from wama.common.utils.app_modes import APP_MODES, get_domains, has_domain_tabs
        from wama.common.utils.volet import PANEL_SLOTS, centre_slots, declaration
        self.assertEqual(self.KINDS, [s.id for s in centre_slots('describer')])
        for slot in centre_slots('describer'):
            self.assertTrue(BRICKS[slot.kind].is_page, f'{slot.kind} : une brique de page du registre')
            self.assertEqual(BRICKS[slot.kind].name, slot.title, 'son nom vient du registre, une fois')
        self.assertEqual(list(PANEL_SLOTS), list(declaration('describer').slots[:len(PANEL_SLOTS)]),
                         'le volet, puis le centre')
        tabbed = [app for app in APP_MODES if has_domain_tabs(app)]
        self.assertTrue(tabbed, 'au moins une app à onglets de domaine')
        for app in APP_MODES:
            slots = centre_slots(app)
            domains = [d['id'] for d in get_domains(app)] if app in tabbed else ['']
            self.assertEqual([f'{k}-{d}' if d else k for d in domains for k in self.KINDS],
                             [s.id for s in slots], app)
            for slot in slots:
                self.assertEqual(('grid', 0, GRID_COLUMNS), (slot.zone, slot.x, slot.w), slot.id)
                self.assertEqual(slot.kind != 'queue', slot.fit, f'{slot.id} : à la hauteur de son contenu')

    def test_every_app_page_marks_its_centre_bricks_with_declared_slots(self):
        import re

        from wama.common.utils.app_modes import get_domains, has_domain_tabs
        mark = re.compile(r'data-wama-brick="(\w+)"(?:\s+data-wama-brick-domain="([\w-]+)")?')
        seen = 0
        for app, path in self._apps():
            response = self.client.get(path)
            if response.status_code != 200:
                continue
            html = response.content.decode()
            if 'data-wama-queue' not in html:
                continue
            seen += 1
            marks = mark.findall(html)
            kinds = {kind for kind, _ in marks}
            self.assertTrue({'entry_card', 'toolbar', 'queue'} <= kinds, f'{app} : {sorted(kinds)}')
            domains = {d['id'] for d in get_domains(app)} if has_domain_tabs(app) else None
            for kind, domain in marks:
                self.assertIn(kind, self.KINDS, app)
                if domains is not None and domain:
                    self.assertIn(domain, domains, f'{app} : {kind}-{domain} non déclaré')
        self.assertGreaterEqual(seen, 5, "les pages d'apps qui rendent la file commune")

    def test_the_studio_card_and_a_toolbar_outside_a_queue_are_not_bricks(self):
        from pathlib import Path

        from django.conf import settings
        templates = Path(settings.BASE_DIR) / 'wama' / 'common' / 'templates' / 'common'
        card = (templates / '_new_item_card_v4.html').read_text(encoding='utf-8')
        bar = (templates / '_toolbar.html').read_text(encoding='utf-8')
        queue = (templates / '_queue.html').read_text(encoding='utf-8')
        self.assertIn('{% if not compose_only %}data-wama-brick="entry_card"', card)
        self.assertIn('{% if centre_brick %}data-wama-brick="toolbar"', bar)
        self.assertIn('centre_brick=True', queue)
        self.assertIn('data-wama-brick="queue"', queue)

    def test_a_centre_brick_and_a_panel_section_in_the_grid_are_kept(self):
        import json

        from django.urls import reverse

        from wama.common.utils.volet import layout_of
        payload = {'slots': {'queue': {'x': 0, 'y': 0, 'w': 12, 'h': 8, 'zone': 'grid'},
                             'settings': {'x': 8, 'y': 0, 'w': 4, 'h': 4, 'zone': 'grid'},
                             'queue-audio': {'x': 0, 'y': 9, 'w': 12, 'h': 4, 'zone': 'grid'}},
                   'frozen': True}
        response = self.client.post(reverse('common:panel_layout', args=['describer']),
                                    json.dumps(payload), content_type='application/json')
        self.assertEqual(200, response.status_code, response.content)
        kept = layout_of(self.account, 'describer')['slots']
        self.assertEqual({'queue', 'settings'}, set(kept), "un domaine que l'app n'a pas est oublié")
        self.assertEqual('grid', kept['settings']['zone'], 'une section du volet posée au centre')
        wide = self.client.post(reverse('common:panel_layout', args=['describer']),
                                json.dumps({'slots': {'queue': {'x': 2, 'y': 0, 'w': 12, 'h': 8,
                                                                'zone': 'grid'}}}),
                                content_type='application/json')
        self.assertEqual(400, wide.status_code, 'la grille du centre a douze colonnes')

    def test_the_centre_is_mounted_by_the_panel_module_on_the_common_engine(self):
        """Le module du volet monte aussi le centre (une seule disposition par page) ; la barre
        garde sa file une fois séparée d'elle ; un titre part avec le bloc qu'il introduit ; un
        onglet masqué retire ses briques ; une brique `fit` suit son contenu ; la visionneuse
        navigue dans SA file, sortie de son onglet."""
        from pathlib import Path

        from django.conf import settings
        served = Path(settings.BASE_DIR) / 'staticfiles' / 'common'
        module = (served / 'js' / 'wama-panel-layout.js').read_text(encoding='utf-8')
        engine = (served / 'js' / 'wama-brick-layout.js').read_text(encoding='utf-8')
        viewer = (served / 'js' / 'media-preview.js').read_text(encoding='utf-8')
        sheet = (served / 'css' / 'wama-surface.css').read_text(encoding='utf-8')
        self.assertIn("b.el.setAttribute('data-cible-dans', '#' + next.id);", module)
        self.assertIn('if (headings[rec.slot.id]) wrap.appendChild(headings[rec.slot.id]);', module)
        self.assertIn("(!pane || pane.classList.contains('active'))", module)
        self.assertIn('root: grid, panelRoot: column, page: grid || column', module)
        self.assertIn("at.resizeToContentParent = '.wama-brick-body';", engine)
        self.assertIn('node.grid.resizeToContent(rec.el);', engine)
        self.assertIn("card.closest('[data-wama-queue]') || card.closest('.tab-pane')", viewer)
        self.assertIn('.wama-centre-grid.is-frozen > .grid-stack-item > .grid-stack-item-content', sheet)


class PageControlsTest(TestCase):
    """2026-10-29 (décision de Fabien : « une barre de page ») — ce qui vaut pour TOUTE la page vit
    dans l'en-tête, jamais dans une brique : le cadenas de la disposition (montré quand la page en
    offre une, `offerLayout`) et l'aide de la page (touche « ? »), qui liste les raccourcis des
    briques de CETTE page, lus au registre. Le cadenas du titre du volet et les boutons de la
    brique Actions d'une surface y ont déménagé. Les gestes se jouent au navigateur
    (`common.panel_layout`, `common.surface_layout`)."""

    @classmethod
    def setUpTestData(cls):
        from django.contrib.auth import get_user_model
        cls.account = get_user_model().objects.create_superuser(
            username='page_controls', email='page-controls@test.local', password='x')

    @staticmethod
    def _js(rel):
        from pathlib import Path

        from django.conf import settings
        return (Path(settings.BASE_DIR) / 'wama' / 'common' / 'static' / rel).read_text(encoding='utf-8')

    def test_every_page_brick_with_shortcuts_says_how_it_is_found_on_the_page(self):
        from wama.common.surfaces import BRICKS
        from wama.common.utils.volet import page_controls_config
        groups = {g['brick']: g for g in page_controls_config()['shortcuts']}
        with_keys = {b.key for b in BRICKS.values() if b.is_page and b.shortcuts}
        self.assertEqual(with_keys, set(groups), 'une brique de page à raccourcis, introuvable sur la page')
        self.assertEqual('#actions-section', groups['inspector_panel']['present'])
        self.assertEqual('[data-wama-brick="queue"]', groups['queue']['present'])
        self.assertEqual('always', groups['media_viewer']['present'])
        self.assertEqual(BRICKS['queue'].name, groups['queue']['title'])
        self.assertIn('Ctrl+A', [s['label'] for s in groups['queue']['items']])

    def test_the_header_carries_the_controls_and_the_page_serves_its_bricks(self):
        from django.urls import reverse
        self.client.force_login(self.account)
        page = self.client.get(reverse('common:journal'))
        html = page.content.decode()
        for marker in ('id="wamaLayoutToggle"', 'id="wamaPageHelpToggle"', 'id="wama-page-controls"',
                       'common/css/wama-page-controls.css'):
            self.assertIn(marker, html)
        # Le module est chargé APRÈS le clavier commun (« ? ») et AVANT le volet qui s'y déclare.
        at = html.index('common/js/wama-page-controls.js')
        self.assertLess(html.index('common/js/wama-keys.js'), at)
        self.assertLess(at, html.index('common/js/wama-panel-layout.js'))

    def test_the_panel_and_the_surface_offer_their_layout_to_the_page(self):
        panel = self._js('common/js/wama-panel-layout.js')
        kernel = self._js('common/js/surfaces/wama-surface.js')
        actions = self._js('common/js/surfaces/brick-surface-actions.js')
        controls = self._js('common/js/wama-page-controls.js')
        self.assertIn('global.WamaPageControls.offerLayout({', panel)
        self.assertNotIn('wama-panel-tools', panel, 'plus de cadenas dans le titre du volet')
        self.assertIn('controls.offerLayout({', kernel)
        self.assertIn("WamaPageControls.openHelp('keys')", actions)
        self.assertIn("global.WamaKeys.register({ owner: 'page_controls', scope: 'page'", controls)
        self.assertIn("if (e.key !== '?'", controls)
        # Les gestes de disposition sont lus du SERVEUR (`surfaces.LAYOUT_HELP`), jamais réécrits.
        self.assertIn('config.layout_help', controls)
        self.assertNotIn('Glissez un panneau', controls)

    def test_the_layout_texts_live_on_the_server_once(self):
        """Les gestes et la phrase du cadenas : une source (`surfaces`), servie à la page et lue par
        l'assistant — le JS de la disposition ne les porte plus."""
        from wama.common.surfaces import LAYOUT_CONTROLS, LAYOUT_HELP
        from wama.common.utils.volet import page_controls_config
        config = page_controls_config()
        self.assertEqual((LAYOUT_HELP, LAYOUT_CONTROLS), (config['layout_help'], config['layout_controls']))
        for rel in ('common/js/wama-brick-layout.js', 'common/js/wama-page-controls.js',
                    'common/js/wama-panel-layout.js', 'common/js/surfaces/wama-surface.js'):
            code = self._js(rel)
            self.assertNotIn('Glissez un panneau', code, rel)
            self.assertNotIn('layout.help', code, rel)

    def test_the_first_visit_hint_is_shown_once_per_account(self):
        from django.test import RequestFactory
        from django.urls import reverse

        from wama.common.utils.user_settings import clear_user_app_settings
        from wama.common.utils.volet import HINT_APP, HINT_SETTING, page_controls_config
        clear_user_app_settings(self.account, HINT_APP, [HINT_SETTING])
        request = RequestFactory().get('/')
        request.user = self.account
        self.assertEqual({'seen': False, 'url': reverse('common:page_hint')},
                         page_controls_config(request)['hint'])
        self.client.force_login(self.account)
        self.assertEqual(200, self.client.post(reverse('common:page_hint')).status_code)
        self.assertTrue(page_controls_config(request)['hint']['seen'])
        self.assertNotIn('hint', page_controls_config(), 'sans compte, pas de bulle')
        controls = self._js('common/js/wama-page-controls.js')
        self.assertIn('if (hinted || !hintCfg || hintCfg.seen || !layoutProvider || isOpen()) return;', controls)

    def test_a_button_says_its_key_from_the_registry_not_from_its_brick(self):
        """L'infobulle d'un bouton qu'une touche actionne dit la touche du REGISTRE
        (`Shortcut.targets`) ; les briques ne l'écrivent plus à la main."""
        import re

        from wama.common.surfaces import BRICKS
        targets = {(b.key, t['selector'], t['label']) for b in BRICKS.values() for s in b.shortcuts
                   for t in s.to_dict()['targets']}
        self.assertIn(('media_transport', '[data-transport="play"]', 'Espace'), targets)
        self.assertIn(('image_boxes', '.wama-image-tools [data-tool="add"]', 'N'), targets)
        for _brick, selector, _label in targets:
            # Le sélecteur nomme un attribut ou une classe que le code de la page pose vraiment.
            marks = re.findall(r'data-[\w-]+="([\w-]+)"|\.([\w-]+)', selector)
            self.assertTrue(marks, selector)
        # Toute CHAÎNE du code (une infobulle passe aussi en argument : `button('play', …, titre)`),
        # commentaires exclus (`mecanismes_scan.code_only`).
        from wama.common.services.mecanismes_scan import code_only
        hand_written = re.compile(r"['\"`][^'\"`\n]*(\(Échap\)|\(Espace\)|\(Ctrl\+|Alt\+L|\(←\)|\(→\)"
                                  r"|\(N\)|\(F\)|\(C\)|\(Début\))")
        for rel in ('common/js/surfaces/brick-image-boxes.js', 'common/js/surfaces/brick-surface-actions.js',
                    'common/js/surfaces/brick-segment-list.js', 'common/js/wama-transport.js',
                    'common/js/wama-timeline.js', 'common/js/media-preview.js'):
            found = hand_written.search(code_only(rel, self._js(rel)))
            self.assertIsNone(found, f'{rel} : une touche écrite à la main ({found and found.group(0)})')
        controls = self._js('common/js/wama-page-controls.js')
        self.assertIn("document.addEventListener('pointerover', annotate, true);", controls)

    def test_the_assistant_describes_a_page_and_resets_its_layout(self):
        from wama.common.utils.user_settings import get_user_app_setting, save_user_app_settings
        from wama.common.utils.volet import LAYOUT_SETTING
        from wama.tool_api import TOOL_REGISTRY, get_page_interface, reset_page_layout
        self.assertIs(TOOL_REGISTRY['get_page_interface'], get_page_interface)
        found = get_page_interface(self.account, 'transcriber')
        keys = {b['key']: b for b in found['bricks']}
        self.assertTrue({'queue', 'toolbar', 'inspector_panel', 'media_viewer'} <= set(keys))
        self.assertIn('Ctrl+A', [s['keys'] for s in keys['queue']['shortcuts']])
        self.assertIn('Glissez un panneau', found['gestures'])
        surface = get_page_interface(self.account, 'transcriber.correct')
        self.assertEqual('surface', surface['kind'])
        self.assertIn('media_transport', [b['key'] for b in surface['bricks']])
        self.assertIn('error', get_page_interface(self.account, 'pas une page !'))
        save_user_app_settings(self.account, 'transcriber', {LAYOUT_SETTING: {'frozen': False}})
        self.assertIn('message', reset_page_layout(self.account, 'transcriber'))
        self.assertIsNone(get_user_app_setting(self.account, 'transcriber', LAYOUT_SETTING))
        self.assertIn('error', reset_page_layout(self.account, 'pas une page !'))

    def test_the_served_copies_match_the_sources(self):
        from pathlib import Path

        from django.conf import settings
        root = Path(settings.BASE_DIR)
        for rel in ('js/wama-page-controls.js', 'css/wama-page-controls.css', 'js/wama-panel-layout.js',
                    'js/surfaces/brick-surface-actions.js', 'js/surfaces/wama-surface.js',
                    'js/wama-brick-layout.js'):
            served = root / 'staticfiles' / 'common' / rel
            if not served.exists():
                self.skipTest('pas de copie servie dans cet arbre')
            self.assertEqual((root / 'wama' / 'common' / 'static' / 'common' / rel).read_bytes(),
                             served.read_bytes(), rel)
