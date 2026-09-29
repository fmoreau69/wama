"""Reconnaissance d'un appel d'outil dans la réponse du modèle (`assistant_engine._parse_tool_call`).

Vécu le 2026-09-30 : `{"tool": "dev_run_role", "args": {"role": "model", "args": {"catalog": …}}}`
revenait à l'utilisateur comme du TEXTE — le motif interdisait les accolades imbriquées, donc aucun
outil dont un argument est un objet (les rôles de la chaîne d'intégration de modèles) ne pouvait
être appelé par l'assistant.

⚠ Identifiants en anglais ; commentaires et docstrings en français.
"""
from django.test import SimpleTestCase

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

    def test_no_call_broken_json_or_missing_args_is_none(self):
        self.assertIsNone(_parse_tool_call('Bonjour, rien à faire.'))
        self.assertIsNone(_parse_tool_call('{"tool": "x", "args": {"a": 1}'))
        self.assertIsNone(_parse_tool_call('{"tool": "x"}'))
