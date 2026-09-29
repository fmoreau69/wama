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
