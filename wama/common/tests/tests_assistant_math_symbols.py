"""
Un symbole écrit en notation mathématique LaTeX ne sort pas de la boucle de l'assistant comme du
code (2026-10-30, demande de Fabien : « dans Discord, les flèches s'affichent en texte »).

LE DÉFAUT MESURÉ : sur Discord, gemma-4-31b (par Albert et par ILaaS) écrivait « Prompt
$\\rightarrow$ Scénario » (tours 612 → 632, fil de fabien.moreau). Aucune surface ne rend le
LaTeX — ni le chat web (`toHtml`), ni Discord, ni Matrix, ni la voix —, le lecteur voyait le code.

CE QUE CETTE GARDE TIENT :
  1. un passage fait de symboles connus devient ses caractères, dans la réponse FINALE du moteur
     (celle que reçoivent toutes les surfaces et que le fil enregistre) ;
  2. une vraie formule (accolades, indice, exposant, commande inconnue) reste écrite telle quelle ;
  3. un montant (`5 $`) n'est pas une formule : il ne bouge pas ;
  4. le code (bloc ou passage entre accents graves) n'est jamais modifié.
"""
from django.test import SimpleTestCase, TestCase

from wama.common.services.assistant_engine import _math_symbols_to_text


class MathSymbolsTest(SimpleTestCase):

    def test_the_arrows_of_the_measured_turn_become_arrows(self):
        self.assertEqual('Chanson → Paroles → Scénario',
                         _math_symbols_to_text('Chanson $\\rightarrow$ Paroles $\\rightarrow$ Scénario'))

    def test_symbols_between_words_keep_the_words(self):
        self.assertEqual('si x → y alors 2 × 3 ≥ 5',
                         _math_symbols_to_text('si $x \\to y$ alors $2 \\times 3 \\geq 5$'))

    def test_the_parenthesis_form_is_read_too(self):
        self.assertEqual('A ⇒ B', _math_symbols_to_text('A \\(\\Rightarrow\\) B'))

    def test_a_real_formula_is_left_alone(self):
        for formula in ('$E = mc^2$', '$\\frac{a}{b}$', '$x_i \\to y$', '$\\unknowncommand$',
                        '$$\\rightarrow$$'):
            with self.subTest(formula=formula):
                self.assertEqual(f'voir {formula}', _math_symbols_to_text(f'voir {formula}'))

    def test_amounts_are_not_formulas(self):
        text = 'Le devis passe de 5 $ à 10 $ par mois.'
        self.assertEqual(text, _math_symbols_to_text(text))

    def test_code_is_never_touched(self):
        text = 'En LaTeX : `$\\rightarrow$`\n```\n$a \\to b$\n```\net ici $\\to$'
        self.assertEqual('En LaTeX : `$\\rightarrow$`\n```\n$a \\to b$\n```\net ici →',
                         _math_symbols_to_text(text))


class EngineAnswerTest(TestCase):
    """La conversion court dans la BOUCLE, pas seulement dans la fonction : la réponse rendue à
    toutes les surfaces (web, Discord, Matrix, API) la porte."""

    def test_the_final_answer_of_a_turn_has_no_latex_arrow(self):
        from unittest import mock

        from django.contrib.auth.models import User

        from wama.common.services import assistant_engine
        user = User.objects.create(username='math_symbols')
        with mock.patch.object(assistant_engine, '_llm_call',
                               return_value=('Prompt $\\rightarrow$ Scénario', {})):
            result = assistant_engine.run_assistant_turn(user, 'résume le flux',
                                                         provider='ollama', model='m')
        self.assertEqual('Prompt → Scénario', result['response'])
