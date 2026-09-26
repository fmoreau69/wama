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
