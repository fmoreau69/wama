"""
Le curseur Rapide ↔ Qualité de l'assistant vaut pour les tâches qu'il lance (2026-09-22,
décision de Fabien : « l'utilisateur règle une fois le curseur et demande ses tâches à
l'assistant, qui applique le niveau demandé — en le rendant explicite »).

⚠ CE QUE CES GARDES PROTÈGENT :
  1. un élément créé par un outil `add_to_<app>` reçoit le curseur de l'assistant, et le résultat
     le DIT (`quality_intent`, `quality_level`) ;
  2. frontière voulue : seules les apps dont le champ s'appelle `quality_intent` sont relayées —
     l'anonymizer (`precision_level`) ne l'est pas ;
  3. un résultat en erreur, sans `item_id`, ou l'élément d'un autre compte : rien n'est touché ;
  4. la boucle de l'assistant applique le relais après l'outil, pas la porte `execute_tool`.
"""
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase

from wama.common.services import assistant_engine
from wama.common.utils.user_settings import save_user_app_settings
from wama.composer.models import ComposerGeneration
from wama.tool_api import relay_quality_intent

USAGE = {'input_tokens': 0, 'output_tokens': 0}


class QualityRelayTest(TestCase):

    def setUp(self):
        self.user = get_user_model().objects.create_user('relay_user', password='x')
        save_user_app_settings(self.user, 'assistant', {'quality_intent': 85})

    def _generation(self, user=None):
        return ComposerGeneration.objects.create(user=user or self.user, prompt='p')

    def test_a_created_item_receives_the_assistant_slider_and_the_result_says_so(self):
        gen = self._generation()
        result = relay_quality_intent(self.user, 'add_to_composer', {'item_id': gen.pk})
        gen.refresh_from_db()
        self.assertEqual(85, gen.quality_intent)
        self.assertEqual(85, result['quality_intent'])
        self.assertEqual('Qualité', result['quality_level'])

    def test_an_app_whose_slider_has_another_name_is_not_relayed(self):
        with mock.patch('wama.common.utils.auto_model.intent_field_for', return_value='precision_level'):
            result = relay_quality_intent(self.user, 'add_to_anonymizer', {'item_id': 1, 'media_id': 1})
        self.assertNotIn('quality_level', result)

    def test_errors_missing_ids_and_foreign_items_are_left_alone(self):
        self.assertNotIn('quality_level',
                         relay_quality_intent(self.user, 'add_to_composer', {'error': 'x', 'item_id': 1}))
        self.assertNotIn('quality_level', relay_quality_intent(self.user, 'add_to_composer', {'ok': 1}))
        other = get_user_model().objects.create_user('relay_other', password='x')
        gen = self._generation(user=other)
        relay_quality_intent(self.user, 'add_to_composer', {'item_id': gen.pk})
        gen.refresh_from_db()
        self.assertIsNone(gen.quality_intent)

    def test_the_assistant_loop_relays_after_an_add_tool(self):
        gen = self._generation()

        def llm(messages, *a, **k):
            if len(messages) == 2:
                return ('{"tool": "add_to_composer", "args": {"prompt": "p"}}', USAGE)
            return 'lancé', USAGE
        with mock.patch.object(assistant_engine, '_llm_call', side_effect=llm), \
             mock.patch('wama.tool_api.execute_tool', return_value={'item_id': gen.pk, 'status': 'ok'}):
            result = assistant_engine.run_assistant_turn(self.user, 'compose', provider='wama-dev-ai',
                                                         model='x', history=[])
        step, = result['tool_steps']
        self.assertEqual('Qualité', step['result']['quality_level'])
        gen.refresh_from_db()
        self.assertEqual(85, gen.quality_intent)
        # Explicite pour le modèle : la règle du prompt nomme `quality_level`.
        self.assertIn('quality_level', assistant_engine.WAMA_TOOLS_PROMPT)
