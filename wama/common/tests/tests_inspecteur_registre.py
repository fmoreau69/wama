"""INSPECTEUR DE REGISTRE — le détail d'un élément dans le volet, sur les pages de liste.

Demande de Fabien (2026-09-08) : « certaines pages de registres ou listes comme les licences
n'utilisent pas l'inspecteur contextuel pour permettre d'avoir accès au détail des informations
de chaque élément ».

⚠ MON RELEVÉ DE LA VEILLE ÉTAIT FAUX, et la correction est instructive : j'avais annoncé
« journal, apps, backends, external_sources l'ont » en comptant les MENTIONS de
`wama-inspector` dans le gabarit (lien CSS, commentaire). Mesuré le 2026-09-09 sur les
MONTAGES (`WamaInspector.init`) : `backends` n'en avait aucun. Le périmètre réel était de CINQ
pages, pas quatre. *Une mesure par motif oriente, elle ne conclut pas.*

CE QUE CES TESTS TIENNENT — le câblage, en trois maillons qui ne se déduisent pas l'un de
l'autre, et dont chacun a manqué au premier essai :
  1. le VOLET existe (les 4 pages déclaraient `VOLET_AUCUN` : aucun panneau du tout) ;
  2. l'élément porte `data-id` (contrat de SÉLECTION de l'inspecteur — sans lui la surbrillance
     s'applique et le panneau reste vide, mesuré) ;
  3. la FEUILLE de `WamaDetails` est chargée globalement (sinon les lignes clé/valeur se rendent
     COLLÉES : « Registremodel », mesuré au navigateur).
Le comportement, lui, s'atteste au navigateur — un `.js` ne casse que là.
"""
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

RACINE = Path(settings.BASE_DIR)
COMMUN = RACINE / 'wama' / 'common' / 'templates' / 'common'

#: Les pages qui ont gagné l'inspecteur de registre le 2026-09-09, et le sélecteur déclaré.
PAGES = {
    'licenses.html': ('.wama-cat-card', 'tbody tr'),
    'registres.html': ('.wama-cat-card',),
    'skills.html': ('.wama-cat-card',),
    'backends.html': ('.wama-cat-card',),
    'rag.html': ('.rag-doc',),
}


class CablageDeLInspecteurDeRegistreTest(SimpleTestCase):

    def _lire(self, nom):
        return (COMMUN / nom).read_text(encoding='utf-8')

    def test_chaque_page_declare_son_conteneur_et_son_hote(self):
        manques = []
        for nom, selecteurs in PAGES.items():
            src = self._lire(nom)
            if 'data-wama-inspecte' not in src:
                manques.append(f"{nom} : aucun conteneur `data-wama-inspecte`")
            if "_inspector_registre.html" not in src:
                manques.append(f"{nom} : l'hôte du détail n'est pas inclus")
            for sel in selecteurs:
                if f'data-wama-inspecte="{sel}"' not in src:
                    manques.append(f"{nom} : sélecteur {sel!r} non déclaré")
        self.assertEqual([], manques, "\n".join(manques))

    def test_aucune_page_ne_monte_l_inspecteur_DEUX_fois(self):
        """Auto-montage ET `init` manuel sur la même page monteraient deux inspecteurs sur le
        même conteneur : deux sélections concurrentes, dont une seule rendrait."""
        doubles = []
        for nom in sorted(p.name for p in COMMUN.glob('*.html')):
            src = self._lire(nom)
            if 'data-wama-inspecte' in src and 'WamaInspector.init' in src:
                doubles.append(nom)
        self.assertEqual([], doubles, f"pages à double montage : {doubles}")

    def test_les_elements_portent_data_id(self):
        """⚠ Contrat de SÉLECTION : `wama-inspector.js` ne sélectionne que sur `data-id`
        (`if (card && card.dataset.id)`). Sans lui, le clic pose la surbrillance et le panneau
        reste sur son texte d'invite — mesuré au navigateur avant correction."""
        manques = []
        for nom in PAGES:
            src = self._lire(nom)
            if 'data-id=' not in src:
                manques.append(f"{nom} : aucun `data-id` — la sélection ne peut pas aboutir")
        self.assertEqual([], manques, "\n".join(manques))

    def test_la_feuille_de_WamaDetails_est_GLOBALE(self):
        """Une brique globale et une feuille par page finissent par diverger.

        `WamaDetails` est chargé par `base.html` depuis toujours ; sa feuille l'était par TROIS
        pages seulement. Les cinq nouvelles rendaient donc des lignes clé/valeur collées.
        """
        base = (RACINE / 'wama' / 'templates' / 'base.html').read_text(encoding='utf-8')
        self.assertIn('wama-inspector-autofill.css', base,
                      "la feuille de `WamaDetails` n'est plus chargée globalement")

    def test_les_quatre_pages_ont_RECUPERE_un_volet(self):
        """Elles déclaraient `VOLET_AUCUN` (retrait délibéré du 2026-08-22, qui supprimait 51
        cadres vides). On ne rouvre que ce qu'on REMPLIT : `medias=False, actions=False`."""
        vues = (RACINE / 'wama' / 'common' / 'views.py').read_text(encoding='utf-8')
        for vue in ('licenses_catalog_view', 'registres_view', 'skills_catalog_view', 'rag_view'):
            i = vues.find(f'def {vue}(')
            self.assertNotEqual(-1, i, f"vue {vue} introuvable")
            corps = vues[i:vues.find('\ndef ', i + 1)]
            with self.subTest(vue=vue):
                self.assertIn('volet(medias=False, actions=False)', corps,
                              f"{vue} ne déclare pas le volet réduit attendu")
                self.assertNotIn('VOLET_AUCUN', corps,
                                 f"{vue} déclare encore VOLET_AUCUN : pas de volet, donc pas "
                                 f"d'hôte pour le détail")

    def test_le_deriveur_ne_fabrique_pas_de_libelles_depuis_des_classes_CSS(self):
        """Un repli qui nommerait ses lignes d'après `.rag-niveau` afficherait « Rag niveau » :
        l'implémentation fuirait dans l'interface. Le repli rend un RÉSUMÉ, pas une fiche."""
        js = (RACINE / 'wama' / 'common' / 'static' / 'common' / 'js'
              / 'wama-inspector.js').read_text(encoding='utf-8')
        self.assertIn('donnees.resume', js)
        self.assertIn('autoInitRegistres', js)
        # L'hôte est déclaré comme hôte d'ACTIONS : c'est ce qui fait courir `fillActions`.
        self.assertIn("ids: { actions: 'inspectorRegistreDetail' }", js)

    def test_staticfiles_sert_la_meme_brique(self):
        for rel in ('common/js/wama-inspector.js', 'common/css/wama-inspector-autofill.css'):
            source = RACINE / 'wama' / 'common' / 'static' / rel
            servi = RACINE / 'staticfiles' / rel
            with self.subTest(fichier=rel):
                self.assertTrue(servi.exists(), f"{rel} absent de staticfiles/")
                self.assertEqual(source.read_text(encoding='utf-8'),
                                 servi.read_text(encoding='utf-8'),
                                 f"{rel} : staticfiles/ diverge de la source")
