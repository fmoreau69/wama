"""
Un résultat d'outil renvoyé au MODÈLE est borné, et la bascule de modèle est jugée DANS la boucle
(`WAMA_HARNESS §9` chantier 1, 2026-10-28).

LE DÉFAUT. La boucle réinjectait chaque résultat ENTIER (`get_item_detail` d'une transcription :
61 642 caractères mesurés le 22/09), renvoyé à chaque itération suivante ; et la fenêtre du modèle
n'était jugée qu'au départ du tour, jamais après ce que la boucle ajoutait.

CE QUE CETTE GARDE TIENT :
  1. un résultat au-delà de `TOOL_RESULT_CHARS` est borné EN LE DISANT (taille d'origine), début
     ET fin gardés — la fin porte `truncated`/`total_chars` de `get_item_result` ;
  2. un résultat sous le budget passe octet pour octet (contre-épreuve) ;
  3. la trace `tool_steps` et l'étape diffusée gardent l'intégral (tranché le 23/09) ;
  4. la fenêtre est jugée après chaque résultat, lue UNE fois par modèle et par tour, et la
     bascule ne va jamais vers une fenêtre plus petite.
"""
import json
from unittest import mock

from django.contrib.auth.models import User
from django.test import TestCase

from wama.common.services import assistant_engine
from wama.common.services.assistant_engine import (
    TOOL_RESULT_CHARS, _bounded_payload, _tool_result_message,
)

CALL = '{"tool": "get_item_detail", "args": {"app": "transcriber", "pk": 1}}'


def _turn(tool_result, *, tool_calls=1, model='m', on_event=None, **patches):
    """Un tour local : `tool_calls` appels d'outil puis une réponse. Rend (résultat, messages vus
    par le modèle à chaque appel, modèle de chaque appel)."""
    seen, models = [], []

    def llm(messages, llm_model, *a, **k):
        seen.append([dict(m) for m in messages])        # la liste continue d'évoluer : copier
        models.append(llm_model)
        return (CALL if len(seen) <= tool_calls else 'Voici le détail.'), {}

    user = User.objects.create(username=f'budget_{User.objects.count()}')
    with mock.patch.object(assistant_engine, '_llm_call', side_effect=llm), \
            mock.patch('wama.tool_api.execute_tool', return_value=tool_result):
        if patches:
            with mock.patch.multiple(assistant_engine, **patches):
                result = assistant_engine.run_assistant_turn(
                    user, 'détail de ma transcription', provider='ollama', model=model,
                    on_event=on_event)
        else:
            result = assistant_engine.run_assistant_turn(
                user, 'détail de ma transcription', provider='ollama', model=model,
                on_event=on_event)
    return result, seen, models


def _tool_message(seen):
    """Le résultat d'outil tel que le modèle l'a lu à l'appel suivant."""
    return seen[1][-1]['content']


class ToolResultBudgetTest(TestCase):

    def test_a_short_result_passes_byte_for_byte(self):
        small = {'id': 1, 'text': 'bonjour ' * 60}
        _, seen, _ = _turn(small)
        expected = f"Résultat du tool get_item_detail : {json.dumps(small, ensure_ascii=False)}"
        self.assertEqual(expected, _tool_message(seen))

    def test_a_large_result_is_bounded_and_says_so(self):
        big = {'id': 1, 'text': 'é' * 200_000}
        _, seen, _ = _turn(big)
        message = _tool_message(seen)
        self.assertLess(len(message), TOOL_RESULT_CHARS + 400)
        self.assertIn('tronqué', message)
        self.assertIn(str(len(json.dumps(big, ensure_ascii=False))), message)   # taille d'origine

    def test_the_end_of_a_bounded_result_is_kept(self):
        # La forme réelle de `get_item_result` : le drapeau de troncature vit en FIN de dict.
        big = {'text': 'x' * 100_000, 'truncated': True, 'total_chars': 123456}
        _, seen, _ = _turn(big)
        message = _tool_message(seen)
        self.assertIn('"truncated": true', message)
        self.assertIn('"total_chars": 123456', message)

    def test_the_threshold_is_exact(self):
        at_budget = 'a' * TOOL_RESULT_CHARS
        self.assertEqual(at_budget, _bounded_payload(at_budget, TOOL_RESULT_CHARS))
        self.assertIn('tronqué', _bounded_payload(at_budget + 'a', TOOL_RESULT_CHARS))

    def test_the_trace_and_the_streamed_step_keep_the_full_result(self):
        big = {'id': 1, 'text': 'x' * 200_000}
        events = []
        result, _, _ = _turn(big, on_event=events.append)
        self.assertEqual(big, result['tool_steps'][0]['result'])
        steps = [e['step'] for e in events if e.get('type') == 'step']
        self.assertEqual(big, steps[0]['result'])

    def test_the_history_keeps_its_plain_cut(self):
        # L'historique resservi n'annonce rien : à 600 caractères l'en-tête en mangerait le tiers.
        message = _tool_result_message('t', {'blob': 'x' * 5000}, limit=600)
        self.assertNotIn('tronqué', message['content'])
        self.assertTrue(message['content'].endswith('…'))


class ContextRoutingInTheLoopTest(TestCase):

    def test_the_window_is_read_once_and_nothing_is_selected_below_it(self):
        window = mock.Mock(return_value=10 ** 9)
        route = mock.Mock(side_effect=lambda model, messages: model)
        _turn({'ok': True}, tool_calls=3, _safe_char_limit=window,
              _route_model_by_context=route)
        self.assertEqual(1, window.call_count)        # une lecture pour le modèle du tour
        self.assertEqual(1, route.call_count)         # celle du départ, aucune dans la boucle

    @staticmethod
    def _routing_after_a_tool(target):
        """La sélection propose `target` dès qu'un résultat d'outil est dans le contexte — le
        départ du tour (prompt système seul) garde le modèle demandé."""
        def route(model, messages):
            grown = any(m['content'].startswith('Résultat du tool') for m in messages)
            return target if grown else model
        return route

    def test_an_overflowing_context_switches_to_a_larger_window(self):
        windows = {'small': 1, 'big': 10 ** 9}          # 'small' déborde dès le premier résultat
        _, _, models = _turn({'text': 'x' * 5_000}, tool_calls=2, model='small',
                             _safe_char_limit=lambda model: windows[model],
                             _route_model_by_context=self._routing_after_a_tool('big'))
        self.assertEqual(['small', 'big', 'big'], models)

    def test_it_never_switches_to_a_smaller_window(self):
        windows = {'small': 1, 'tiny': 0}
        _, _, models = _turn({'text': 'x' * 5_000}, tool_calls=2, model='small',
                             _safe_char_limit=lambda model: windows[model],
                             _route_model_by_context=self._routing_after_a_tool('tiny'))
        self.assertEqual(['small', 'small', 'small'], models)
