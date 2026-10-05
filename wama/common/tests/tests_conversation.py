"""
Store de conversation — tests (ROADMAP §19.5).

Versionnés pour la même raison que `wama/gateway/tests.py` : ce qu'ils vérifient tient au
CLOISONNEMENT (chacun ne voit et n'efface que ses fils) et à une propriété non évidente —
l'historique servi doit être CHRONOLOGIQUE même tronqué, faute de quoi le modèle répond de
travers sans que rien ne le signale.

Lancer : `python manage.py test wama.common.tests.tests_conversation` (venv WSL).
Aucun LLM, aucune charge GPU : le moteur est remplacé par un double.
"""

from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase

from wama.common.models import Conversation
from wama.common.services import assistant_engine, conversation_store as store


def _double_moteur(compteur=None):
    """Double du moteur : renvoie une réponse traçable, sans appeler de LLM."""
    etat = {'n': 0}

    def _repondre(user, message, **kw):
        etat['n'] += 1
        if compteur is not None:
            compteur.append(kw.get('history'))
        return {'success': True, 'response': f"reponse {etat['n']}", 'model': 'faux:1b',
                'tool_steps': [{'tool': 'list_user_files', 'args': {}}]}

    return _repondre


class StoreConversationTests(TestCase):

    def setUp(self):
        self.alice = User.objects.create(username='alice')
        self.bob = User.objects.create(username='bob')

    def test_echange_persiste_avec_sa_trace(self):
        with patch.object(assistant_engine, 'run_assistant_turn', side_effect=_double_moteur()):
            resultat = assistant_engine.conversation_turn(
                self.alice, 'bonjour', surface='web', thread_key='onglet-1')

        fil = Conversation.objects.get(pk=resultat['conversation_id'])
        self.assertEqual(fil.turns.count(), 2)          # la question ET la réponse
        self.assertEqual(fil.title, 'bonjour')          # titre dérivé du 1er message
        reponse = fil.turns.get(role='assistant')
        # La trace des outils rend la conversation VÉRIFIABLE après coup : sans elle, on ne
        # sait pas ce que l'assistant a réellement lancé.
        self.assertEqual(reponse.model, 'faux:1b')
        self.assertTrue(reponse.tool_steps)

    def test_historique_reservi_en_ordre_chronologique(self):
        """Un historique servi à l'envers produit des réponses incohérentes, en silence."""
        vus = []
        with patch.object(assistant_engine, 'run_assistant_turn',
                          side_effect=_double_moteur(vus)):
            assistant_engine.conversation_turn(self.alice, 'un', thread_key='t')
            assistant_engine.conversation_turn(self.alice, 'deux', thread_key='t')

        self.assertEqual(vus[0], [])                     # 1er tour : rien derrière
        self.assertEqual([h['content'] for h in vus[1]], ['un', 'reponse 1'])

    def test_trois_fils_distincts_pour_le_meme_utilisateur(self):
        """Le cœur du multi-conversations : la surface ET le fil séparent."""
        with patch.object(assistant_engine, 'run_assistant_turn', side_effect=_double_moteur()):
            assistant_engine.conversation_turn(self.alice, 'a', surface='web', thread_key='onglet-1')
            assistant_engine.conversation_turn(self.alice, 'b', surface='web', thread_key='onglet-2')
            assistant_engine.conversation_turn(self.alice, 'c', surface='discord', thread_key='salon-42')

        self.assertEqual(Conversation.objects.filter(user=self.alice).count(), 3)
        fil_discord = Conversation.objects.get(user=self.alice, surface='discord')
        self.assertEqual(len(store.history(fil_discord)), 2)   # son propre historique

    def test_cloisonnement_entre_comptes(self):
        with patch.object(assistant_engine, 'run_assistant_turn', side_effect=_double_moteur()):
            assistant_engine.conversation_turn(self.alice, 'a', thread_key='t')
            assistant_engine.conversation_turn(self.bob, 'b', thread_key='t')

        self.assertEqual(len(store.conversations_of(self.alice)), 1)
        self.assertEqual(len(store.conversations_of(self.bob)), 1)

    def test_effacer_seulement_les_siens(self):
        with patch.object(assistant_engine, 'run_assistant_turn', side_effect=_double_moteur()):
            resultat = assistant_engine.conversation_turn(self.alice, 'a', thread_key='t')
        fil_id = resultat['conversation_id']

        self.assertFalse(store.clear(self.bob, fil_id))
        self.assertTrue(Conversation.objects.filter(pk=fil_id).exists())
        self.assertTrue(store.clear(self.alice, fil_id))

    def test_un_seul_fil_par_cle(self):
        """Deux messages du même salon ne doivent pas scinder l'historique en silence."""
        with patch.object(assistant_engine, 'run_assistant_turn', side_effect=_double_moteur()):
            assistant_engine.conversation_turn(self.alice, 'a', surface='discord', thread_key='s1')
            assistant_engine.conversation_turn(self.alice, 'b', surface='discord', thread_key='s1')

        self.assertEqual(
            Conversation.objects.filter(user=self.alice, surface='discord', thread_key='s1').count(), 1)

    def test_le_moteur_reste_sans_etat(self):
        """`run_assistant_turn` ne doit RIEN écrire : c'est ce qui le garde testable sans base."""
        with patch.object(assistant_engine, '_llm_call',
                          return_value=('reponse directe', {'input_tokens': 0, 'output_tokens': 0})):
            resultat = assistant_engine.run_assistant_turn(
                self.alice, 'x', history=[{'role': 'user', 'content': 'y'}])

        self.assertNotIn('conversation_id', resultat)
        self.assertEqual(Conversation.objects.count(), 0)

    def test_reponse_rendue_meme_si_le_store_tombe(self):
        """Best-effort sur le STOCKAGE, jamais sur la RÉPONSE.

        Un assistant muet parce que sa trace est cassée serait bien pire que la perte de la
        trace : on répond, sans historique.
        """
        with patch.object(store, 'thread', side_effect=RuntimeError('base indisponible')), \
             patch.object(assistant_engine, 'run_assistant_turn', side_effect=_double_moteur()):
            resultat = assistant_engine.conversation_turn(self.alice, 'bonjour')

        self.assertEqual(resultat['response'], 'reponse 1')
        self.assertNotIn('conversation_id', resultat)


class HistoryCarriesToolStepsTests(TestCase):
    """L'historique resservi au modèle MONTRE les outils des tours passés (2026-10-05).

    LE DÉFAUT MESURÉ (fil Discord n° 11) : seul le texte des réponses repartait. Chaque « c'est
    terminé » passé y apparaissait comme une réponse donnée SANS outil — l'exemple que le modèle
    imite. Rejoué vers Albert (`deepseek-v4-flash`), 4 tirages par cas : texte seul, 0/8 tours
    avec un outil ; outils dépliés, 8/8. Le modèle et le message étaient les mêmes.
    """

    STATUS_STEP = {'tool': 'get_anonymizer_status', 'args': {},
                   'result': {'jobs': [{'id': 1031, 'status': 'SUCCESS'}]}}

    def setUp(self):
        self.alice = User.objects.create(username='alice')

    def test_the_store_serves_the_tool_steps_of_an_assistant_turn(self):
        fil = store.thread(self.alice, surface='discord', thread_key='s')
        store.record_exchange(fil, 'statut ?', {'response': 'Terminé.',
                                                'tool_steps': [self.STATUS_STEP]})
        user_turn, assistant_turn = store.history(fil)
        self.assertNotIn('tool_steps', user_turn)
        self.assertEqual([self.STATUS_STEP], assistant_turn['tool_steps'])

    def test_a_past_tool_call_is_unfolded_as_the_loop_played_it(self):
        served = assistant_engine._sanitize_history([
            {'role': 'user', 'content': 'statut ?'},
            {'role': 'assistant', 'content': 'Terminé.', 'tool_steps': [self.STATUS_STEP]},
        ])
        self.assertEqual(['user', 'assistant', 'user', 'assistant'], [m['role'] for m in served])
        self.assertEqual({'tool': 'get_anonymizer_status', 'args': {}},
                         assistant_engine._parse_tool_call(served[1]['content']))
        # La forme du résultat est CELLE de la boucle : une seule fonction l'écrit.
        self.assertEqual(assistant_engine._tool_result_message(
            'get_anonymizer_status', self.STATUS_STEP['result']), served[2])
        self.assertEqual('Terminé.', served[3]['content'])

    def test_a_large_past_result_is_truncated(self):
        step = {'tool': 'get_anonymizer_status', 'args': {}, 'result': {'blob': 'x' * 5000}}
        served = assistant_engine._sanitize_history(
            [{'role': 'assistant', 'content': 'ok', 'tool_steps': [step]}])
        self.assertLess(len(served[1]['content']), 700)
        self.assertTrue(served[1]['content'].endswith('…'))

    def test_the_limit_counts_turns_not_unfolded_messages(self):
        """Borner après dépliage couperait un échange entre l'appel et son résultat."""
        turns = [{'role': 'user', 'content': f'q{i}'} if i % 2 == 0 else
                 {'role': 'assistant', 'content': f'r{i}', 'tool_steps': [self.STATUS_STEP]}
                 for i in range(30)]
        served = assistant_engine._sanitize_history(turns, limit=20)
        self.assertEqual('q10', served[0]['content'])
        self.assertEqual(10 * 1 + 10 * 3, len(served))

    def test_a_past_invented_answer_no_longer_serves_as_an_example(self):
        """« ID 649 » du 05/10 = « 648 » du 27/09 + 1 : le modèle recopiait ses fabrications."""
        invented = "La tâche 648 est terminée.\n📥 Télécharger (lien non vérifié — retiré)"
        served = assistant_engine._sanitize_history([{'role': 'assistant', 'content': invented}])
        self.assertNotIn('648', served[0]['content'])
        self.assertEqual(assistant_engine._HISTORY_INVENTED_PLACEHOLDER, served[0]['content'])

    def test_an_answer_backed_by_a_tool_keeps_its_text(self):
        """Contre-épreuve : la même mention dans un tour OUTILLÉ n'est pas une fabrication."""
        text = "Terminé.\n📥 Télécharger (lien non vérifié — retiré)"
        served = assistant_engine._sanitize_history(
            [{'role': 'assistant', 'content': text, 'tool_steps': [self.STATUS_STEP]}])
        self.assertEqual(text, served[-1]['content'])

    def test_conversation_turn_hands_the_unfolded_steps_to_the_model(self):
        """Câblage de bout en bout : store → `conversation_turn` → messages du LLM."""
        fil = store.thread(self.alice, surface='discord', thread_key='s')
        store.record_exchange(fil, 'statut ?', {'response': 'Terminé.',
                                                'tool_steps': [self.STATUS_STEP]})
        seen = []

        def llm(messages, *a, **k):
            seen.append(messages)
            return 'Bonjour.', {}
        with patch.object(assistant_engine, '_llm_call', side_effect=llm):
            assistant_engine.conversation_turn(self.alice, 'et maintenant ?', surface='discord',
                                               thread_key='s', provider='ollama', model='m')
        contents = [m['content'] for m in seen[0]]
        self.assertIn('{"tool": "get_anonymizer_status", "args": {}}', contents)
