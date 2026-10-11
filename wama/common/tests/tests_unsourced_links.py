"""
Un lien que l'assistant n'a obtenu d'AUCUN outil ne sort pas de la boucle (2026-09-23).

LE DÉFAUT MESURÉ, DEUX FOIS. Sur Discord, le modèle local a annoncé une anonymisation
« terminée avec succès » en donnant `https://example.com/output/IMG-…_anonymized.jpg` — une
adresse qu'il a fabriquée. La règle « NEVER INVENT A LINK » a été ajoutée au prompt ; le tour
suivant, APRÈS mise en service, il a recommencé, dans un tour SANS AUCUN appel d'outil.
La cause est mécanique : ses fabrications sont dans l'historique du fil, qui lui est resservi
à chaque tour. *Une règle de prompt ne défait pas un exemple qu'on remet sous ses yeux.*

CE QUE CETTE GARDE TIENT :
  1. un lien absent des résultats d'outils DU TOUR est retiré, et remplacé par une mention
     visible — jamais effacé en silence ;
  2. le libellé du lien Markdown est conservé : on retire une adresse, pas une phrase ;
  3. un lien VENU d'un outil passe intact — y compris l'`output_url` niché sous `jobs[]`,
     qui est la forme réelle des `get_*_status` ;
  4. l'URL que l'UTILISATEUR a lui-même écrite passe : elle a une source.
"""
from django.test import TestCase

from wama.common.services.assistant_engine import _strip_unsourced_urls


class UnsourcedLinksTest(TestCase):

    def test_a_fabricated_link_is_removed_and_said(self):
        text = ("L'anonymisation est terminée.\n"
                "* **Fichier** : [📥 Télécharger](https://example.com/output/photo.jpg)")
        cleaned = _strip_unsourced_urls(text, tool_steps=[])
        self.assertNotIn('example.com', cleaned)
        self.assertIn('lien non vérifié', cleaned)
        self.assertIn('📥 Télécharger', cleaned)      # le libellé reste
        self.assertIn("L'anonymisation est terminée.", cleaned)

    def test_a_link_that_comes_from_a_tool_result_passes_intact(self):
        steps = [{'tool': 'get_anonymizer_status', 'result': {'jobs': [
            {'id': 647, 'status': 'done',
             'output_url': '/media/users/1/anonymizer/output/photo_blurred.jpg'}]}}]
        text = 'Voici le résultat : [📥 Télécharger](/media/users/1/anonymizer/output/photo_blurred.jpg)'
        self.assertEqual(text, _strip_unsourced_urls(text, steps))

    def test_a_bare_fabricated_url_is_removed_too(self):
        cleaned = _strip_unsourced_urls('Récupérez-le sur https://example.com/x.jpg puis dites-moi.',
                                        tool_steps=[])
        self.assertNotIn('example.com', cleaned)
        self.assertIn('puis dites-moi', cleaned)

    def test_the_url_the_user_wrote_himself_has_a_source(self):
        text = 'Vous parlez de https://huggingface.co/modele ?'
        self.assertEqual(text, _strip_unsourced_urls(
            text, tool_steps=[], message='regarde https://huggingface.co/modele'))

    def test_a_text_without_any_link_is_untouched(self):
        text = 'La tâche a démarré — je vous préviens dès la fin.'
        self.assertEqual(text, _strip_unsourced_urls(text, tool_steps=[]))

    def test_the_control_runs_inside_the_engine_not_only_here(self):
        """Contre-épreuve de câblage : la fonction pourrait exister sans être appelée."""
        from unittest.mock import patch

        from django.contrib.auth.models import User

        from wama.common.services import assistant_engine

        user = User.objects.create(username='linkless')
        with patch.object(assistant_engine, '_llm_call',
                          return_value=('Voilà : https://example.com/faux.jpg', {})):
            result = assistant_engine.run_assistant_turn(user, 'où est mon fichier ?',
                                                         provider='ollama', model='m')
        self.assertNotIn('example.com', result['response'])


class InventedTurnTest(TestCase):
    """Un tour SANS outil qui cite un résultat est un tour INVENTÉ : il est repris par un modèle
    plus fort, sinon remplacé par un aveu (29/09).

    LE DÉFAUT MESURÉ (Discord, 27/09) : le filtre ci-dessus retirait bien le lien, mais le reste
    partait — « la tâche 648 est terminée » + un libellé `📥 Télécharger…` sans adresse, que
    l'utilisateur a pris pour un lien de téléchargement cassé. Aucune tâche n'existait.
    """

    FABRICATED = ("La tâche 648 est terminée.\n"
                  "[📥 Télécharger](/media/users/1/anonymizer/output/photo_blurred_sam3.jpg)")

    def setUp(self):
        from unittest import mock

        from django.contrib.auth import get_user_model

        from wama.common.utils.user_settings import save_user_app_settings
        from wama.model_manager.models import AIModel

        self.user = get_user_model().objects.create_user('invented_turn', password='x')

        def model(key, coding, vram):
            return AIModel.objects.create(
                model_key=key, name=key, model_type='llm', source='ollama', execution='local',
                is_downloaded=True, vram_gb=vram, capabilities={'completion': True},
                benchmark_meta={'family_scores': {'coding': coding}})
        self.small = model('ollama:small:4b', 22.6, 3.4)
        self.big = model('ollama:big:8b', 58.2, 17.0)
        save_user_app_settings(self.user, 'assistant', {'model': 'ollama:small:4b'})
        vram = mock.patch('wama.model_manager.services.model_selector.get_free_vram_gb',
                          return_value=24.0)
        vram.start()
        self.addCleanup(vram.stop)

    def _turn(self, llm):
        from unittest import mock

        from wama.common.services import assistant_engine
        with mock.patch.object(assistant_engine, '_llm_call', side_effect=llm) as call:
            result = assistant_engine.run_assistant_turn(self.user, 'quel est le statut ?')
        return result, [c.args[1] for c in call.call_args_list]

    def test_an_invented_turn_is_replayed_by_a_stronger_model(self):
        def llm(messages, model, *a, **k):
            return (self.FABRICATED if model == 'small:4b' else 'Aucune tâche en cours.'), {}
        result, models = self._turn(llm)
        self.assertEqual(['small:4b', 'big:8b'], models)
        self.assertEqual('Aucune tâche en cours.', result['response'])
        self.assertIn('· repris', result['model'])
        self.assertIn('small:4b', result['invented_by'])

    def test_without_a_stronger_model_the_turn_says_nothing_was_executed(self):
        self.big.delete()
        result, models = self._turn(lambda *a, **k: (self.FABRICATED, {}))
        self.assertEqual(['small:4b'], models)
        self.assertNotIn('648', result['response'])
        self.assertIn("aucune action", result['response'])

    def test_a_replay_that_invents_too_is_not_replayed_again(self):
        result, models = self._turn(lambda *a, **k: (self.FABRICATED, {}))
        self.assertEqual(['small:4b', 'big:8b'], models)
        self.assertIn("aucune action", result['response'])

    def test_a_turn_that_called_a_tool_is_only_filtered(self):
        """Contre-épreuve : avec un outil appelé, le modèle a AGI — le lien sans source est
        retiré, la réponse reste, personne ne rejoue le tour."""
        def llm(messages, *a, **k):
            if len(messages) == 2:
                return '{"tool": "get_anonymizer_status", "args": {}}', {}
            return self.FABRICATED, {}
        result, models = self._turn(llm)
        self.assertEqual(['small:4b', 'small:4b'], models)
        self.assertIn('lien non vérifié', result['response'])
        self.assertNotIn('invented_by', result)

    def test_a_turn_without_tool_and_without_a_cited_result_is_left_alone(self):
        result, models = self._turn(lambda *a, **k: ('Bonjour ! Que puis-je faire ?', {}))
        self.assertEqual(['small:4b'], models)
        self.assertEqual('Bonjour ! Que puis-je faire ?', result['response'])

    def test_a_mark_copied_from_the_history_counts_as_an_invented_turn(self):
        """Fil Discord n° 11, 05/10 : la mention RECOPIÉE d'un tour passé, sans aucune adresse —
        rien à retirer, donc le contrôle restait muet et « ID 649 terminé » partait."""
        copied = ("La tâche 649 est terminée.\n\n"
                  "📥 Télécharger l'image anonymisée (lien non vérifié — retiré)")

        def llm(messages, model, *a, **k):
            return (copied if model == 'small:4b' else 'Aucune tâche en cours.'), {}
        result, models = self._turn(llm)
        self.assertEqual(['small:4b', 'big:8b'], models)
        self.assertEqual('Aucune tâche en cours.', result['response'])


class ToolLimitTest(TestCase):
    """Ce qui sort de la boucle quand la limite d'outils est atteinte (2026-10-05).

    LE DÉFAUT MESURÉ (Discord, card #1036) : inspection → ajout refusé par le schéma → ajout →
    lancement → statut, cinq outils pour une limite de cinq ; la boucle rendait alors le texte
    du dernier appel — `{"tool": "get_anonymizer_status", "args": {}}` affiché comme réponse.
    """

    CALL = '{"tool": "get_anonymizer_status", "args": {}}'

    def _turn(self, llm):
        from unittest import mock

        from django.contrib.auth.models import User

        from wama.common.services import assistant_engine
        user = User.objects.create(username='tool_limit')
        # L'outil RÉUSSIT : ces tests éprouvent la boucle, pas un refus (un refus ajoute le
        # rappel de `_refusals_notice`, éprouvé par `RefusalsNoticeTest`).
        with mock.patch.object(assistant_engine, '_llm_call', side_effect=llm) as call, \
                mock.patch('wama.tool_api.execute_tool', return_value={'items': []}):
            result = assistant_engine.run_assistant_turn(user, 'floute la plaque',
                                                         provider='ollama', model='m')
        return result, call.call_count

    def test_the_model_gets_a_last_turn_to_answer(self):
        from wama.common.services import assistant_engine

        def llm(messages, *a, **k):
            if messages[-1]['content'] == assistant_engine._TOOL_LIMIT_PROMPT:
                return 'Le floutage est lancé, je vous préviens à la fin.', {}
            return self.CALL, {}
        result, calls = self._turn(llm)
        self.assertEqual(assistant_engine.MAX_TOOL_ITERATIONS + 1, calls)
        self.assertEqual('Le floutage est lancé, je vous préviens à la fin.', result['response'])
        self.assertEqual(assistant_engine.MAX_TOOL_ITERATIONS, len(result['tool_steps']))

    def test_a_raw_tool_call_never_leaves_the_loop(self):
        result, _ = self._turn(lambda *a, **k: (self.CALL, {}))
        self.assertNotIn('{"tool"', result['response'])
        self.assertIn('get_anonymizer_status', result['response'])   # la trace, dite
        self.assertIn('limite', result['response'])


class EmptyAnswerTest(TestCase):
    """Une réponse finale VIDE ne sort pas de la boucle comme un succès muet (2026-10-10).

    LE DÉFAUT MESURÉ (fil web n° 37) : « Relance la prospection… donne-moi les trois meilleurs » —
    `prospect_models` a tourné, puis le modèle local (réflexion demandée) a rendu '' ; le tour est
    parti en succès avec une réponse vide. L'utilisateur ne savait même pas que la prospection
    avait été lancée.
    """

    CALL = '{"tool": "get_anonymizer_status", "args": {}}'

    def _turn(self, llm):
        from unittest import mock

        from django.contrib.auth.models import User

        from wama.common.services import assistant_engine
        user = User.objects.create(username='empty_answer')
        with mock.patch.object(assistant_engine, '_llm_call', side_effect=llm) as call, \
                mock.patch('wama.tool_api.execute_tool', return_value={'items': []}):
            result = assistant_engine.run_assistant_turn(user, 'où en est le floutage ?',
                                                         provider='ollama', model='m')
        return result, call.call_args_list

    def test_an_empty_answer_is_asked_again_without_thinking(self):
        answers = iter([(self.CALL, {}), ('', {}), ('Le floutage est terminé.', {})])
        result, calls = self._turn(lambda *a, **k: next(answers))
        self.assertEqual('Le floutage est terminé.', result['response'])
        self.assertEqual(3, len(calls))
        self.assertIs(False, calls[2].kwargs['think'])

    def test_empty_twice_says_what_was_executed(self):
        answers = iter([(self.CALL, {}), ('', {}), ('<think>…</think>', {})])
        result, _ = self._turn(lambda *a, **k: next(answers))
        self.assertTrue(result['success'])
        self.assertIn('aucune réponse', result['response'])
        self.assertIn('get_anonymizer_status', result['response'])

    def test_a_non_empty_answer_is_not_asked_again(self):
        """Contre-épreuve : un seul appel quand le modèle répond."""
        result, calls = self._turn(lambda *a, **k: ('Rien en cours.', {}))
        self.assertEqual('Rien en cours.', result['response'])
        self.assertEqual(1, len(calls))

    def test_a_declared_provider_answering_without_text_is_an_empty_answer_not_a_failure(self):
        """gpt-oss sur Albert (fil web n° 37) : l'appel d'outil NATIF part dans le raisonnement,
        `content` vide — `llm_chat` le dit par son motif nommé, et c'était un 502 qui finissait
        le tour. C'est désormais une réponse vide : un nouvel essai, avec le rappel du format."""
        from unittest import mock

        from django.contrib.auth.models import User

        from wama.common.services import assistant_engine
        from wama.common.utils import llm_utils
        answers = iter([(None, llm_utils.EMPTY_RESPONSE_ERROR), ('Rien en cours.', None)])
        user = User.objects.create(username='empty_cloud')
        with mock.patch.object(llm_utils, 'chat_with_source',
                               side_effect=lambda *a, **k: next(answers)) as call:
            result = assistant_engine.run_assistant_turn(user, 'statut ?', provider='albert',
                                                         model='gpt-oss-120b')
        self.assertEqual('Rien en cours.', result['response'])
        retried = call.call_args_list[1].args[2]
        self.assertEqual(assistant_engine._EMPTY_ANSWER_RETRY_PROMPT, retried[-1]['content'])

    def test_an_empty_past_answer_is_noted_in_the_history(self):
        """Resservi vide, le tour laissait croire que la demande attendait encore sa réponse."""
        from wama.common.services import assistant_engine
        history = [{'role': 'user', 'content': 'relance la prospection'},
                   {'role': 'assistant', 'content': '',
                    'tool_steps': [{'tool': 'prospect_models', 'args': {}, 'result': {'total': 38}}]}]
        clean = assistant_engine._sanitize_history(history)
        self.assertEqual(assistant_engine._HISTORY_EMPTY_PLACEHOLDER, clean[-1]['content'])
        self.assertIn('prospect_models', clean[1]['content'])     # l'outil joué reste visible


class RefusalsNoticeTest(TestCase):
    """Fil web n° 41 (2026-10-11) : deux fois de suite, « a bien été installé » alors que chaque
    `install_model` du tour avait été refusé. La trace dit le refus, pas le modèle."""

    def test_a_tool_that_never_succeeded_is_said_with_its_refusal(self):
        from wama.common.services.assistant_engine import _refusals_notice
        steps = [{'tool': 'install_model', 'result': {'error': 'not_found : clé inconnue'}},
                 {'tool': 'install_model', 'result': {'error': 'modèle Ollama retiré'}},
                 {'tool': 'get_install_options', 'result': {'error': 'aucune proposition'}},
                 {'tool': 'get_install_options', 'result': {'options': []}}]
        notice = _refusals_notice(steps)
        self.assertIn('install_model', notice)
        self.assertIn('modèle Ollama retiré', notice)          # le DERNIER refus
        self.assertNotIn('get_install_options', notice)        # échoué puis réussi : rien à dire

    def test_the_turn_answer_carries_it(self):
        from unittest import mock

        from django.contrib.auth.models import User

        from wama.common.services import assistant_engine
        user = User.objects.create(username='refusals_notice')
        answers = iter([('{"tool": "install_model", "args": {"model_key": "x"}}', {}),
                        ('Le modèle a bien été installé.', {})])
        with mock.patch.object(assistant_engine, '_llm_call', side_effect=lambda *a, **k: next(answers)), \
                mock.patch('wama.tool_api.execute_tool', return_value={'error': 'refusé : clé inconnue'}):
            result = assistant_engine.run_assistant_turn(user, 'installe x', provider='ollama',
                                                         model='m')
        self.assertIn('Refusé par WAMA', result['response'])
        self.assertIn('refusé : clé inconnue', result['response'])

    def test_a_turn_without_refusal_is_unchanged(self):
        """Contre-épreuve : rien n'est ajouté quand tout a réussi."""
        from wama.common.services.assistant_engine import _refusals_notice
        self.assertEqual('', _refusals_notice([{'tool': 'install_model',
                                                'result': {'started': True}}]))
