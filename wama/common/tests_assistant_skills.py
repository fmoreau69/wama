"""
Skills de RÔLE de l'assistant — tests (ROADMAP §19.7).

Ce qu'ils protègent, et qui n'est évident qu'une fois cassé :
  • le domaine choisi atteint RÉELLEMENT le prompt système (une injection silencieusement
    perdue ne se voit pas : l'assistant répond, juste sans sa posture) ;
  • le contexte de laboratoire n'est cherché QUE pour les domaines qui le déclarent — sinon
    chaque « où en est ma transcription ? » paie une recherche vectorielle ;
  • et il n'est JAMAIS injecté à vide, car un contexte hors-sujet dégrade plus qu'il n'aide.

Lancer : `python manage.py test wama.common.tests_assistant_skills` (venv WSL).
Aucun LLM, aucune charge GPU : l'appel au modèle est remplacé par un double.
"""

from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase

from wama.common.services import assistant_engine
from wama.common.utils import assistant_skills as sk


class RegistreDomainesTests(TestCase):

    def test_domaines_declares_ont_tous_leur_fichier(self):
        """Un domaine sans fichier de skill est un domaine muet — la table mentirait."""
        from wama.common.utils.prompt_skills import load_skill
        for d in sk.DOMAINES:
            with self.subTest(domaine=d.key):
                self.assertTrue(load_skill(d.skill), f"skill absent : {d.skill}.md")

    def test_domaine_inconnu_retombe_sur_le_defaut(self):
        self.assertEqual(sk.resolve_domain('inexistant').key, sk.DEFAULT_DOMAIN)
        self.assertEqual(sk.resolve_domain(None).key, sk.DEFAULT_DOMAIN)
        self.assertEqual(sk.resolve_domain('  SCIENCE  ').key, 'science')   # tolérant

    def test_options_ui_derivees_du_registre(self):
        options = sk.domains_for_ui()
        self.assertEqual([o['value'] for o in options], [d.key for d in sk.DOMAINES])
        self.assertTrue(all(o['label'] and o['help'] for o in options))


class ContexteLaboratoireTests(TestCase):

    def setUp(self):
        self.user = User.objects.create(username='chercheur')

    def test_domaine_sans_rag_ne_cherche_rien(self):
        """La garde qui évite de payer une recherche vectorielle sur une question de statut."""
        with patch('wama.common.memory.store.recall') as recall:
            texte = sk.laboratory_context(self.user, 'où en est ma transcription ?', 'general')
        self.assertEqual(texte, '')
        recall.assert_not_called()

    def test_domaine_avec_rag_cherche_et_injecte_avec_la_reference(self):
        class Faux:
            content = "Le laboratoire étudie le comportement des conducteurs."
            source_id = 'lescot/presentation.md'
        hit = type('H', (), {'obj': Faux()})()

        with patch('wama.common.memory.store.recall', return_value=[hit]) as recall:
            texte = sk.laboratory_context(self.user, 'propose-moi un logo', 'design')

        recall.assert_called_once()
        self.assertIn('comportement des conducteurs', texte)
        # La provenance accompagne l'extrait : sans elle, l'utilisateur ne peut pas vérifier.
        self.assertIn('lescot/presentation.md', texte)

    def test_aucun_extrait_pertinent_donne_un_prompt_INCHANGE(self):
        """Data-gated : on n'injecte jamais de bruit faute de mieux."""
        with patch('wama.common.memory.store.recall', return_value=[]):
            self.assertEqual(sk.laboratory_context(self.user, 'xyz', 'science'), '')

    def test_panne_du_rappel_ne_casse_rien(self):
        """Le RAG est un bonus de contexte, jamais une dépendance de la conversation."""
        with patch('wama.common.memory.store.recall', side_effect=RuntimeError('pgvector down')):
            self.assertEqual(sk.laboratory_context(self.user, 'question', 'science'), '')


class InjectionDansLeMoteurTests(TestCase):
    """Le domaine doit atteindre le prompt système — sinon l'injection est perdue en silence."""

    def setUp(self):
        self.user = User.objects.create(username='chercheur')

    def _prompt_systeme(self, **kw):
        capture = {}

        def _faux_llm(messages, llm_model, provider):
            capture['system'] = messages[0]['content']
            return 'ok', {'input_tokens': 0, 'output_tokens': 0}

        with patch.object(assistant_engine, '_llm_call', side_effect=_faux_llm):
            assistant_engine.run_assistant_turn(self.user, 'bonjour', **kw)
        return capture['system']

    def test_role_scientifique_present_dans_le_prompt(self):
        systeme = self._prompt_systeme(domain='science')
        self.assertIn('MEASURED', systeme)          # la posture du skill science
        self.assertIn('scientific assistant', systeme.lower())

    def test_role_dev_present_et_distinct(self):
        systeme = self._prompt_systeme(domain='dev')
        self.assertIn('wama/common/', systeme)      # la règle de centralisation
        self.assertNotIn('MEASURED', systeme)       # pas la posture scientifique

    def test_domaine_absent_donne_le_role_general(self):
        systeme = self._prompt_systeme()
        self.assertIn('research laboratory', systeme.lower())

    def test_le_contexte_labo_atteint_le_prompt(self):
        class Faux:
            content = "Acronyme du laboratoire : LESCOT."
            source_id = 'lescot/fiche.md'
        hit = type('H', (), {'obj': Faux()})()

        with patch('wama.common.memory.store.recall', return_value=[hit]):
            systeme = self._prompt_systeme(domain='design')

        self.assertIn('LESCOT', systeme)
        self.assertIn('Laboratory context', systeme)

    def test_la_consigne_de_langue_survit_a_l_injection(self):
        """Le rôle s'AJOUTE à la langue, il ne la remplace pas."""
        systeme = self._prompt_systeme(domain='science')
        self.assertIn('in French', systeme)
        self.assertNotIn('{LANGUE}', systeme)


class ChargementParLAssistantTests(TestCase):
    """
    L'assistant choisit LUI-MÊME sa compétence — arbitrage Fabien (2026-08-21).

    Le choix n'appartient ni à la surface (une vue web, un adaptateur de canal), ni à une
    heuristique sur le nom d'un salon : un canal porte le nom d'un projet de recherche, pas
    d'une discipline. Il appartient au modèle, dans la boucle à outils qui existe déjà.
    """

    def setUp(self):
        self.user = User.objects.create(username='chercheur')

    def test_outil_present_et_decrit(self):
        """Un outil non DÉCRIT est un outil que l'assistant ne saura jamais appeler."""
        from wama.tool_api import TOOL_REGISTRY, tool_descriptions
        self.assertIn('charger_competence', TOOL_REGISTRY)
        self.assertIn('domaine', str(tool_descriptions()['charger_competence']))

    def test_rend_la_consigne_du_bon_domaine(self):
        from wama.tool_api import execute_tool
        science = execute_tool('charger_competence', {'domaine': 'science'}, self.user)
        design = execute_tool('charger_competence', {'domaine': 'design'}, self.user)

        self.assertEqual(science['domaine'], 'science')
        self.assertIn('MEASURED', science['consigne'])
        self.assertIn('logo', design['consigne'].lower())      # posture distincte

    def test_domaine_inconnu_retombe_sur_le_defaut(self):
        from wama.tool_api import execute_tool
        r = execute_tool('charger_competence', {'domaine': 'nimportequoi'}, self.user)
        self.assertEqual(r['domaine'], sk.DEFAULT_DOMAIN)

    def test_les_competences_sont_annoncees_au_prompt_systeme(self):
        """Sans annonce, l'assistant ignore que ces compétences existent."""
        capture = {}

        def _faux_llm(messages, llm_model, provider):
            capture['system'] = messages[0]['content']
            return 'ok', {'input_tokens': 0, 'output_tokens': 0}

        with patch.object(assistant_engine, '_llm_call', side_effect=_faux_llm):
            assistant_engine.run_assistant_turn(self.user, 'bonjour')

        self.assertIn('charger_competence', capture['system'])
        self.assertIn('`science`', capture['system'])

    def test_le_domaine_actif_n_est_pas_re_annonce(self):
        capture = {}

        def _faux_llm(messages, llm_model, provider):
            capture['system'] = messages[0]['content']
            return 'ok', {'input_tokens': 0, 'output_tokens': 0}

        with patch.object(assistant_engine, '_llm_call', side_effect=_faux_llm):
            assistant_engine.run_assistant_turn(self.user, 'bonjour', domain='science')

        self.assertNotIn('- `science`', capture['system'])

    def test_annoncer_coute_bien_moins_que_tout_charger(self):
        """La raison d'être de l'annonce : la fenêtre des modèles locaux est étroite."""
        annonce = len(sk.competences_announcement())
        entiers = sum(len(sk.role_instructions(d.key)) for d in sk.DOMAINES)
        self.assertLess(annonce, 600)
        self.assertLess(annonce * 5, entiers)     # au moins 5× moins cher
