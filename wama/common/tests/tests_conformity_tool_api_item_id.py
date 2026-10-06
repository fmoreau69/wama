"""Criterion `tool_api_item_id`: `add_to_<app>` hands back the uniform `item_id` key.

Since 2026-10-06 (`c928fd69`) the creators return the key THEMSELVES and the normalised aliases
(`add_to_synthesizer`, `add_to_imager`…) only delegate. The criterion read the alias body alone
and turned red on four apps that keep the contract. It follows the delegation now — and still
refuses an alias whose delegate does not return the key.
"""
from types import SimpleNamespace
from unittest import mock

from django.test import SimpleTestCase

from wama.common.services import conformity_checker as cc


def _verdict(app, source):
    with mock.patch.object(cc, '_wama_text', return_value=source):
        return cc._tool_api_item_id(SimpleNamespace(app=app))


DELEGATING = '''
def create_thing(user, prompt=''):
    return {'item_id': 1, 'id': 1}


@functools.wraps(create_thing)
def add_to_thing(user, *args, **kwargs):
    return create_thing(user, *args, **kwargs)
'''


class ToolApiItemIdCriterionTest(SimpleTestCase):

    def test_an_alias_that_delegates_to_a_creator_returning_the_key_is_green(self):
        state, proof = _verdict('thing', DELEGATING)
        self.assertIs(True, state, proof)
        self.assertIn('create_thing', proof)

    def test_a_delegate_without_the_key_stays_red(self):
        state, _proof = _verdict('thing', DELEGATING.replace("'item_id': 1, ", ''))
        self.assertIs(False, state)

    def test_a_body_returning_the_key_itself_is_green(self):
        source = "def add_to_thing(user):\n    return {'item_id': 3}\n"
        self.assertIs(True, _verdict('thing', source)[0])

    def test_the_real_aliases_keep_the_contract(self):
        for app in ('synthesizer', 'composer', 'converter', 'imager'):
            with self.subTest(app=app):
                state, proof = cc._tool_api_item_id(SimpleNamespace(app=app))
                self.assertIs(True, state, proof)
