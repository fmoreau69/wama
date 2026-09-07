"""Onglets de résultat TEXTE — le partial commun et sa déclaration (R18, 2026-09-07).

Ces tests tiennent le CONTRAT que l'extraction ne devait pas casser : les ancres HTML
(`#tab-<clé>`, `#<cible>`, `#wc-<clé>`) sont ce que le JS des apps consomme déjà. Une
factorisation qui les déplace n'est pas une factorisation, c'est une régression silencieuse —
le JS ne lève pas, il ne trouve simplement plus rien.
"""
import re

from django.template import Context, Template
from django.test import SimpleTestCase

from wama.common.utils.detail_registry import result_tabs_for

#: Les ancres relevées sur les DEUX gabarits AVANT extraction (git HEAD du 07/09).
ANCRES_ATTENDUES = {
    'describer': {'resultTabs', 'tab-description', 'tab-description-btn', 'wc-description',
                  'tab-resume', 'tab-resume-btn', 'wc-resume', 'tab-coherence',
                  'tab-coherence-btn', 'wc-coherence', 'resultText', 'resumeContent',
                  'coherenceContent'},
    'transcriber': {'resultTabs', 'tab-transcription', 'tab-transcription-btn',
                    'wc-transcription', 'tab-diarisation', 'tab-diarisation-btn',
                    'tab-resume', 'tab-resume-btn', 'wc-resume', 'tab-coherence',
                    'tab-coherence-btn', 'wc-coherence', 'resultText', 'diarisationContent',
                    'resumeContent', 'coherenceContent'},
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

    def test_une_app_SANS_facettes_ne_rend_RIEN(self):
        """La plupart des apps ont UNE seule lecture de leur résultat — ou plusieurs résultats
        dans une preview (imager). Le partial ne doit rien poser pour elles."""
        for app in ('converter', 'imager', 'anonymizer'):
            self.assertEqual(result_tabs_for(app), [])
            self.assertEqual(_rendu(app).strip(), '')

    def test_les_defauts_sont_appliques_PAR_L_ACCESSEUR_pas_par_le_gabarit(self):
        """Une valeur par défaut posée dans un template se recopie au premier partial qui
        l'oublie. Elles vivent donc dans `result_tabs_for`."""
        for o in result_tabs_for('transcriber'):
            self.assertTrue(o['label'] and o['icone'] and o['cible'])
            self.assertIn(o['forme'], ('pre', 'html', 'nu'))
        diar = [o for o in result_tabs_for('transcriber') if o['cle'] == 'diarisation'][0]
        self.assertEqual(diar['attente'], 'Chargement...')
        self.assertFalse(diar['badge'], "la diarisation n'avait pas de compteur de mots")


class DeclarationDansLaSpecDeDetailTest(SimpleTestCase):
    """Les facettes vivent dans la SPEC de détail — pas dans un dict d'interface à côté.

    C'est ce qui les rend extractibles au manifeste (facette `inspector`) et projetables par la
    chaîne de génération. Un second domicile aurait été un chemin parallèle de plus.
    """

    def test_la_declaration_vient_de_la_spec_du_detail_registry(self):
        from wama.common.utils.detail_registry import DetailRegistry
        for app in ('describer', 'transcriber'):
            spec = (DetailRegistry.get(app) or {}).get('spec') or {}
            self.assertTrue(spec.get('result_tabs'),
                            f'{app} : facettes absentes de sa spec de détail')

    def test_un_adapter_CODE_peut_porter_une_spec(self):
        """Le transcriber garde son adapter irréductible ET déclare ses facettes : exiger la
        conversion complète de l'adapter d'abord aurait gelé R18 derrière la marche A3."""
        from wama.common.utils.detail_registry import DetailRegistry
        e = DetailRegistry.get('transcriber')
        self.assertTrue(callable(e['adapter']))
        self.assertTrue(e['spec'].get('result_tabs'))
