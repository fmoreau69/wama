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
        solved = lambda app: [] if app == 'imager' else exact(app)
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

    @staticmethod
    def _model(key, task, optional):
        """Les ports dérivent des MODÈLES (la base de test n'en a pas) : le modèle qui ouvre le port."""
        from wama.model_manager.models import AIModel
        AIModel.objects.create(model_key=key, name=key, model_type='diffusion', source=key.split(':')[0],
                               vram_gb=1.0, is_available=True, is_downloaded=True,
                               capabilities={'task': task, 'inputs_required': ['prompt'],
                                             'inputs_optional': list(optional)})

    def test_a_link_on_an_unwired_port_is_an_error_not_a_silence(self):
        # L'imager garde un port non lu (`work_image`, au budget) ; le composer, qui servait
        # d'exemple, lit son `work_audio` depuis le 2026-10-03.
        self._model('imager:sdxl', 'image-to-image', ['work_image'])
        runner = generic_runner.build_generic_runner('imager')
        with patch('wama.tool_api.execute_tool', return_value={'item_id': 7}):
            with self.assertRaisesMessage(ValueError, 'ne le lit pas encore'):
                runner['create'](None, {'prompt': 'a cat', 'work_image': 'users/1/c.png'}, {})

    def test_an_optional_work_port_beside_a_required_prompt_is_not_the_main_input(self):
        """Le morceau à reprendre (cover) est un port de TRAVAIL qu'AUCUN modèle n'exige : le nœud
        composer garde le prompt pour entrée principale (2026-10-03). Sans cette règle, il exigeait
        un audio, et « Texte → Composer » échouait — mesuré sur le catalogue réel."""
        self._model('composer:musicgen-melody', 'text-to-music', ['work_audio'])
        io = generic_runner._derive_io_from_ports('composer')
        self.assertEqual('prompt', io.get('primary_input'))
        self.assertNotIn('input_kinds', io)

    def test_a_required_work_port_stays_the_main_input(self):
        """Contre-épreuve : un port de travail EXIGÉ (l'audio de l'avatarizer, du transcriber) reste
        l'entrée principale."""
        self._model('transcriber:whisper', 'transcription', [])
        from wama.model_manager.models import AIModel
        AIModel.objects.filter(model_key='transcriber:whisper').update(
            capabilities={'task': 'transcription', 'inputs_required': ['work_audio']})
        self.assertIn('audio', generic_runner._derive_io_from_ports('transcriber').get('input_kinds') or ())

    def test_the_song_to_cover_reaches_the_composer_tool(self):
        self._model('composer:musicgen-melody', 'text-to-music', ['work_audio'])
        runner = generic_runner.build_generic_runner('composer')
        with patch('wama.tool_api.execute_tool', return_value={'item_id': 7}) as call:
            runner['create'](None, {'prompt': 'jazz', 'work_audio': 'users/1/m.wav'}, {})
        self.assertEqual('users/1/m.wav', call.call_args[0][1]['work_audio'])

    def test_no_input_at_all_is_still_refused(self):
        runner = generic_runner.build_generic_runner('synthesizer')
        with self.assertRaisesMessage(ValueError, 'aucun prompt'):
            runner['create'](None, {}, {})
