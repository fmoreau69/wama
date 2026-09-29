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
DEFAUTS = {
    'medias': 'id="preview-placeholder"',
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
        ('gestion des utilisateurs', 'accounts:user-management'),
        ("matrice d'accès", 'accounts:app-access-matrix'),
        ('connexion', 'accounts:login'),
        # Namespaces IMBRIQUÉS : les apps du Lab sont incluses sous `wama_lab`
        # (wama/urls.py:48 → wama_lab/urls.py). `face_analyzer:index` ne résout pas.
        ('face_analyzer', 'wama_lab:face_analyzer:index'),
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

    def test_accueil_garde_son_volet_pour_le_seul_avatar(self):
        from django.urls import reverse

        html = self.client.get(reverse('home')).content.decode('utf-8', 'replace')
        self.assertIn(ASIDE, html, "l'accueil garde son volet : l'avatar y vit (right_panel_top)")
        self.assertNotIn(SANS_VOLET, html)
        for cle, marqueur in MARQUEURS.items():
            self.assertNotIn(marqueur, html,
                             f"accueil : cadre '{cle}' sous l'avatar — c'est ce que la "
                             "déclaration `tete=True` doit retirer (WAMA_VOLETS §5)")

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
