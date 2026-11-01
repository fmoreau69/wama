"""Reconnaissance d'un appel d'outil dans la réponse du modèle (`assistant_engine._parse_tool_call`).

Vécu le 2026-09-30 : `{"tool": "dev_run_role", "args": {"role": "model", "args": {"catalog": …}}}`
revenait à l'utilisateur comme du TEXTE — le motif interdisait les accolades imbriquées, donc aucun
outil dont un argument est un objet (les rôles de la chaîne d'intégration de modèles) ne pouvait
être appelé par l'assistant.

⚠ Identifiants en anglais ; commentaires et docstrings en français.
"""
from django.test import SimpleTestCase, TestCase

from wama.common.services.assistant_engine import _parse_tool_call


class ToolCallParsingTest(SimpleTestCase):

    def test_nested_arguments_are_recognised(self):
        text = ('{"tool": "dev_run_role", "args": {"role": "model", "args": '
                '{"catalog": "huggingface:linagora/linto_stt_fr_fastconformer_pc"}, '
                '"provider": "albert", "model": null}}')
        call = _parse_tool_call(text)
        self.assertEqual('dev_run_role', call['tool'])
        self.assertEqual({'catalog': 'huggingface:linagora/linto_stt_fr_fastconformer_pc'},
                         call['args']['args'])

    def test_a_flat_call_inside_prose_is_still_recognised(self):
        call = _parse_tool_call('Je lance la recherche.\n{"tool": "search_models", "args": '
                                '{"query": "aihpi/FrWhisper", "limit": 1}}\nMerci.')
        self.assertEqual(('search_models', 'aihpi/FrWhisper'), (call['tool'], call['args']['query']))

    def test_braces_inside_a_string_do_not_break_it(self):
        call = _parse_tool_call('{"tool": "add_note", "args": {"text": "un } et un { dans le texte"}}')
        self.assertEqual('un } et un { dans le texte', call['args']['text'])

    def test_reasoning_is_ignored(self):
        call = _parse_tool_call('<think>{"tool": "x", "args": {}}</think>{"tool": "y", "args": {}}')
        self.assertEqual('y', call['tool'])

    def test_arguments_beside_tool_without_args_key_are_recognised(self):
        """Fil Discord #43 (2026-10-12) : cet appel exact a été AFFICHÉ à l'utilisateur."""
        call = _parse_tool_call('{"tool": "get_item_preview", "app": "reader", '
                                '"side": "result", "pk": 1335}')
        self.assertEqual({'tool': 'get_item_preview',
                          'args': {'app': 'reader', 'side': 'result', 'pk': 1335}}, call)

    def test_an_args_key_that_is_not_an_object_is_not_read_as_flat(self):
        """Contre-épreuve : `args` présent mais mal formé reste refusé, il n'est pas « aplati »."""
        self.assertIsNone(_parse_tool_call('{"tool": "x", "args": "a=1"}'))

    def test_no_call_broken_json_or_missing_args_is_none(self):
        self.assertIsNone(_parse_tool_call('Bonjour, rien à faire.'))
        self.assertIsNone(_parse_tool_call('{"tool": "x", "args": {"a": 1}'))
        self.assertIsNone(_parse_tool_call('{"tool": "x"}'))


class BareCallTest(SimpleTestCase):
    """2026-11-01, épreuve du Writer par l'assistant : la réponse ENTIÈRE était
    `{"tool": "get_reader_status"}`, affichée à l'utilisateur. Rien ne l'entoure et le nom est celui
    d'un outil du tour : c'est un appel. Un nom inconnu, ou un appel cité dans une phrase, reste du
    texte — la raison de la garde ci-dessus."""

    KNOWN = {'get_reader_status'}

    def test_a_whole_answer_that_is_a_bare_call_to_an_announced_tool_is_a_call(self):
        from wama.common.services.assistant_engine import _bare_call
        self.assertEqual({'tool': 'get_reader_status', 'args': {}},
                         _bare_call(' {"tool": "get_reader_status"}\n', self.KNOWN))

    def test_an_unknown_name_or_a_call_quoted_in_prose_stays_text(self):
        from wama.common.services.assistant_engine import _bare_call
        self.assertIsNone(_bare_call('{"tool": "x"}', self.KNOWN))
        self.assertIsNone(_bare_call('Le format est {"tool": "get_reader_status"}.', self.KNOWN))
        self.assertIsNone(_bare_call('{"tool": "get_reader_status", "note": 1}', self.KNOWN))


class BareCallInTheLoopTest(TestCase):

    def test_the_loop_runs_it_instead_of_showing_it(self):
        from unittest import mock

        from django.contrib.auth.models import User

        from wama.common.services import assistant_engine
        user = User.objects.create(username='bare_call')
        answers = iter([('{"tool": "get_reader_status"}', {}), ('Rien en cours.', {})])
        with mock.patch.object(assistant_engine, '_llm_call',
                               side_effect=lambda *a, **k: next(answers)), \
                mock.patch('wama.tool_api.execute_tool', return_value={'jobs': []}) as run:
            result = assistant_engine.run_assistant_turn(user, 'statut ?', provider='ollama',
                                                         model='m')
        self.assertEqual('Rien en cours.', result['response'])
        self.assertEqual('get_reader_status', run.call_args.args[0])
