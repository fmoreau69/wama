"""Onglets de résultat TEXTE — le partial commun et sa déclaration (R18, 2026-09-07).

Ces tests tiennent le CONTRAT que l'extraction ne devait pas casser : les ancres HTML
(`#tab-<clé>`, `#<cible>`, `#wc-<clé>`) sont ce que le JS des apps consomme déjà. Une
factorisation qui les déplace n'est pas une factorisation, c'est une régression silencieuse —
le JS ne lève pas, il ne trouve simplement plus rien.

⚠ 2026-10-13 : AUCUNE app réelle ne déclare plus d'onglets — le describer (R125) puis le
transcriber (R126) ont rendu leurs facettes à la visionneuse commune. Seules deux jumelles de
bac à sable (`describer_01`, `transcriber_01`, gabarits COPIÉS le 07/10) rendent encore le
partial. Le contrat se tient donc sur une déclaration de DÉMONSTRATION, qui reprend celle que
portait le transcriber, tant que le mécanisme existe — son retrait est une décision à part.
"""
import re

from django.contrib.auth import get_user_model
from django.template import Context, Template
from django.test import SimpleTestCase

from wama.common.utils.detail_registry import DetailRegistry, result_tabs_for

DEMO = 'demo_result_tabs'

#: Les facettes que déclarait le transcriber jusqu'au 2026-10-13 (R126).
DEMO_TABS = [
    {'cle': 'transcription', 'label': 'Transcription', 'icone': 'fa-file-alt',
     'cible': 'resultText', 'forme': 'pre', 'badge': True},
    {'cle': 'diarisation', 'label': 'Diarisation', 'icone': 'fa-users',
     'cible': 'diarisationContent', 'forme': 'nu', 'attente': 'Chargement...'},
    {'cle': 'resume', 'label': 'Résumé', 'icone': 'fa-file-lines',
     'cible': 'resumeContent', 'forme': 'html', 'badge': True, 'cache': True},
    {'cle': 'coherence', 'label': 'Cohérence', 'icone': 'fa-spell-check',
     'cible': 'coherenceContent', 'forme': 'nu', 'badge': True, 'cache': True},
    {'cle': 'evaluation', 'label': 'Évaluation', 'icone': 'fa-scale-balanced',
     'cible': 'evaluationContent', 'forme': 'nu', 'cache': True},
]


def setUpModule():
    DetailRegistry.register(DEMO, get_user_model(), lambda item: {}, spec={'result_tabs': DEMO_TABS})


def tearDownModule():
    DetailRegistry._registry.pop(DEMO, None)


#: Les ancres relevées sur les DEUX gabarits AVANT extraction (git HEAD du 07/09) — celles du
#: transcriber, portées par la déclaration de démonstration.
ANCRES_ATTENDUES = {
    DEMO: {'resultTabs', 'tab-transcription', 'tab-transcription-btn',
                    'wc-transcription', 'tab-diarisation', 'tab-diarisation-btn',
                    'tab-resume', 'tab-resume-btn', 'wc-resume', 'tab-coherence',
                    'tab-coherence-btn', 'wc-coherence', 'resultText', 'diarisationContent',
                    'resumeContent', 'coherenceContent',
                    # 2026-09-23 — onglet « Évaluation » (mesure contre la référence) : trois
                    # ancres AJOUTÉES au contrat, lues par `openResultModal` du transcriber.
                    'tab-evaluation', 'tab-evaluation-btn', 'evaluationContent'},
}
_ID = re.compile(r'id="([^"]+)"')


def _rendu(app):
    return Template("{% load wama_catalog %}{% result_tabs '" + app + "' %}").render(Context({}))


class OngletsDeResultatTest(SimpleTestCase):

    def test_les_ancres_du_contrat_JS_sont_TOUTES_rendues(self):
        """LE test de non-régression : le JS des apps cible ces ids, il ne lève pas s'ils
        manquent — il cesse silencieusement de remplir les onglets."""
        for app, attendues in ANCRES_ATTENDUES.items():
            rendues = set(_ID.findall(_rendu(app)))
            self.assertEqual(sorted(attendues - rendues), [],
                             f"{app} : ancres PERDUES par l'extraction")
            self.assertEqual(sorted(rendues - attendues), [],
                             f'{app} : ancres INVENTÉES — le contrat JS ne les connaît pas')

    def test_le_PREMIER_onglet_declare_est_le_seul_actif(self):
        for app in ANCRES_ATTENDUES:
            html = _rendu(app)
            self.assertEqual(html.count('nav-link active'), 1, f'{app} : un seul onglet actif')
            self.assertEqual(html.count('show active'), 1, f'{app} : un seul panneau actif')
            premier = result_tabs_for(app)[0]['cle']
            aplati = ' '.join(html.split())
            self.assertIn(f'id="tab-{premier}-btn" data-bs-toggle="tab"', aplati)

    def test_les_onglets_A_LA_DEMANDE_sont_masques(self):
        """`résumé` et `cohérence` n'existent qu'après un appel : les afficher d'emblée
        promettrait un contenu qui n'est pas là."""
        for app in ANCRES_ATTENDUES:
            html = _rendu(app)
            for cle in ('resume', 'coherence'):
                bloc = html[html.index(f'id="tab-{cle}-btn"'):][:260]
                self.assertIn('display:none', bloc, f'{app}/{cle} devrait être masqué')

    def test_the_evaluation_tab_waits_for_a_reference(self):
        """No reference, no measure: showing the tab would promise a comparison that isn't there."""
        html = _rendu(DEMO)
        bloc = html[html.index('id="tab-evaluation-btn"'):][:260]
        self.assertIn('display:none', bloc)

    def test_une_app_SANS_facettes_ne_rend_RIEN(self):
        """La plupart des apps ont UNE seule lecture de leur résultat — ou plusieurs résultats
        dans une preview (imager). Le partial ne doit rien poser pour elles."""
        # Parcours du REGISTRE de détail, pas une liste de trois apps (Fabien, 19/09).
        from wama.common.utils.detail_registry import DetailRegistry
        sans = [a for a in DetailRegistry.registered_apps() if not result_tabs_for(a)]
        self.assertGreaterEqual(len(sans), 3, 'parcours vacueux')
        for app in sans:
            self.assertEqual(_rendu(app).strip(), '', f'{app} : le partial pose quelque chose sans facette')

    def test_les_defauts_sont_appliques_PAR_L_ACCESSEUR_pas_par_le_gabarit(self):
        """Une valeur par défaut posée dans un template se recopie au premier partial qui
        l'oublie. Elles vivent donc dans `result_tabs_for`."""
        for o in result_tabs_for(DEMO):
            self.assertTrue(o['label'] and o['icone'] and o['cible'])
            self.assertIn(o['forme'], ('pre', 'html', 'nu'))
        diar = [o for o in result_tabs_for(DEMO) if o['cle'] == 'diarisation'][0]
        self.assertEqual(diar['attente'], 'Chargement...')
        self.assertFalse(diar['badge'], "la diarisation n'avait pas de compteur de mots")


class DeclarationDansLaSpecDeDetailTest(SimpleTestCase):
    """Les facettes vivent dans la SPEC de détail — pas dans un dict d'interface à côté.

    C'est ce qui les rend extractibles au manifeste (facette `inspector`) et projetables par la
    chaîne de génération. Un second domicile aurait été un chemin parallèle de plus.
    """

    def test_la_declaration_vient_de_la_spec_du_detail_registry(self):
        """Pour TOUTE app du registre qui rend des facettes (pas deux apps nommées) : ce que
        l'accesseur rend est ce que sa SPEC déclare, clé pour clé."""
        from wama.common.utils.detail_registry import DetailRegistry
        avec = [a for a in DetailRegistry.registered_apps() if result_tabs_for(a)]
        self.assertGreaterEqual(len(avec), 1, 'parcours vacueux')
        for app in avec:
            spec = (DetailRegistry.get(app) or {}).get('spec') or {}
            self.assertEqual([o['cle'] for o in result_tabs_for(app)],
                             [o['cle'] for o in spec.get('result_tabs') or []],
                             f'{app} : facettes rendues sans venir de sa spec de détail')

    def test_un_adapter_CODE_peut_porter_une_spec(self):
        """Une app à adapter irréductible peut déclarer ses facettes (le transcriber l'a fait
        jusqu'au 2026-10-13) : exiger la conversion complète de l'adapter d'abord aurait gelé R18
        derrière la marche A3."""
        e = DetailRegistry.get(DEMO)
        self.assertTrue(callable(e['adapter']))
        self.assertTrue(e['spec'].get('result_tabs'))
        self.assertEqual([o['cle'] for o in DEMO_TABS], [o['cle'] for o in result_tabs_for(DEMO)])
