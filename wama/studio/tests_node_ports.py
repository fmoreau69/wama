"""Les PORTS d'un nœud du Studio arrivent à l'app — ou le disent (2026-09-30).

Constat de Fabien : « le studio utilise les apps en tant que card ; si l'app déclare ses capacités,
le studio en hérite, c'est tout ». Mesuré le même jour : le nœud affichait tous les ports de l'app,
mais le runner n'en transmettait qu'un — un lien sur la voix de référence, la mélodie, l'image…
était IGNORÉ sans un mot. Convention désormais : un port arrive dans l'argument du MÊME NOM de
l'outil `add_to_<app>` (`generic_runner.port_arguments`).

La liste de ce qui reste à porter (`generic_runner.UNWIRED_PORTS_BUDGET`, qui ne peut que
DESCENDRE) se mesure sur le catalogue RÉEL — les ports dérivent des modèles, que la base de test n'a
pas : c'est le geste nocturne `studio.node_ports_wired`. Ici : le MÉCANISME, et le pilote.
"""
from unittest.mock import patch

from django.test import TestCase

from wama.studio.services import generic_runner


class NodePortsReachTheAppTest(TestCase):

    def test_the_budget_report_catches_growth_and_forgotten_lines(self):
        budget = generic_runner.UNWIRED_PORTS_BUDGET
        exact = lambda app: list(budget.get(app, []))
        self.assertTrue(generic_runner.unwired_ports_report(exact)[0])
        grown = lambda app: exact(app) + (['new_port'] if app == 'synthesizer' else [])
        ok, detail = generic_runner.unwired_ports_report(grown)
        self.assertFalse(ok)
        self.assertIn('new_port', detail)
        solved = lambda app: [] if app == 'composer' else exact(app)
        ok, detail = generic_runner.unwired_ports_report(solved)
        self.assertFalse(ok)
        self.assertIn('retirer du budget', detail)

    def test_the_budget_only_names_real_port_tokens(self):
        from wama.common.utils.app_modes import INPUT_TYPES
        for app, ports in generic_runner.UNWIRED_PORTS_BUDGET.items():
            self.assertIn(app, generic_runner.GENERIC_APPS)
            for port in ports:
                self.assertIn(port, INPUT_TYPES, f'{app}.{port} : jeton de port inconnu')

    def test_the_synthesizer_node_is_fully_wired(self):
        self.assertEqual([], generic_runner.unwired_ports('synthesizer'))
        self.assertEqual({'prompt'}, generic_runner.primary_ports('synthesizer'),
                         'le fichier de travail est « l’un OU l’autre » avec le prompt, pas l’entrée principale')

    def test_every_link_reaches_the_synthesizer_tool_by_port_name(self):
        runner = generic_runner.build_generic_runner('synthesizer')
        with patch('wama.tool_api.execute_tool', return_value={'item_id': 7}) as call:
            runner['create'](None, {'work_file': 'users/1/doc.pdf',
                                    'reference_voice': 'users/1/voice.wav'}, {})
        args = call.call_args[0][1]
        self.assertEqual('users/1/doc.pdf', args['work_file'])
        self.assertEqual('users/1/voice.wav', args['reference_voice'])
        self.assertNotIn('text', args, 'aucun prompt fourni : le fichier de travail suffit')

    def test_a_prompt_still_goes_to_the_text_argument(self):
        runner = generic_runner.build_generic_runner('synthesizer')
        with patch('wama.tool_api.execute_tool', return_value={'item_id': 7}) as call:
            runner['create'](None, {'prompt': 'Bonjour'}, {})
        self.assertEqual('Bonjour', call.call_args[0][1]['text'])

    def test_a_link_on_an_unwired_port_is_an_error_not_a_silence(self):
        runner = generic_runner.build_generic_runner('composer')
        with patch('wama.tool_api.execute_tool', return_value={'item_id': 7}):
            with self.assertRaisesMessage(ValueError, 'ne le lit pas encore'):
                runner['create'](None, {'prompt': 'jazz', 'reference_melody': 'users/1/m.wav'}, {})

    def test_no_input_at_all_is_still_refused(self):
        runner = generic_runner.build_generic_runner('synthesizer')
        with self.assertRaisesMessage(ValueError, 'aucun prompt'):
            runner['create'](None, {}, {})
