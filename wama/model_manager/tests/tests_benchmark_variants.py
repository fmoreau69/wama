"""
Bancs des modèles DISTANTS : variante, qualificatifs et alias (2026-11-06, demande de Fabien :
« complète au mieux les notes des modèles distants »).

Mesuré ce jour par la synchro à blanc : toute la série Claude 5 restait sans banc (ses efforts
« (Max, Default Fallback) », « (High) » lus comme des mots étrangers, « Max » comme un palier
commercial) ; « GLM 5.3 Prime » d'OpenRouter, une fois les parenthèses lues, prenait la note du
GLM 5.3 de base (la règle ne regardait que les mots du tiers).
"""
from django.test import SimpleTestCase

from ..services import benchmark_sync as bs


def _compat(local_name, third_party_name, identity=('family', (5, 5), None)):
    return bs._compatible(identity, identity, True, local_name, third_party_name)


class VariantQualifiersTest(SimpleTestCase):

    def test_a_variant_in_parentheses_is_not_another_model(self):
        self.assertTrue(_compat('Claude Opus 5.5', 'Claude Opus 5.5 (Max, Default Fallback)'))
        self.assertTrue(_compat('Claude Haiku 5.5', 'Claude Haiku 5.5 (High)'))
        # Contre-épreuve : HORS parenthèses, « Max » reste un autre modèle.
        self.assertFalse(_compat('qwen3-embedding:latest', 'Qwen3 Max'))

    def test_a_word_of_our_name_missing_from_the_bench_is_another_model(self):
        self.assertFalse(_compat('Z.ai: GLM 5.3 Prime', 'GLM 5.3 (Reasoning)'))
        self.assertFalse(_compat('Z.ai: GLM 5.3 FlashX', 'GLM 5.3 (Reasoning)'))
        self.assertTrue(_compat('Z.ai: GLM 5.3', 'GLM 5.3 (Reasoning)'))
        self.assertTrue(_compat('Z.ai: GLM 5.3 (batch)', 'GLM 5.3 (Reasoning)'))

    def test_the_publisher_of_an_aggregator_name_is_not_a_qualifier(self):
        # « Amazon: » côté nous, « Amazon » dans le nom du banc : le même éditeur, pas un mot.
        self.assertTrue(_compat('Amazon: Nova 2 Lite', 'Amazon Nova 2 Lite'))
        self.assertTrue(_compat('mistral-medium-3.5:latest', 'Mistral Medium 3.5'))


class VariantChoiceStaysConservativeTest(SimpleTestCase):
    """Une fois les variantes d'effort APPARIÉES, le choix reste celui du 2026-10-31 : la variante
    SERVIE quand elle est déclarée (`SERVED_VARIANT`), sinon la valeur la PIRE — une règle de la
    « variante de référence » du banc a été essayée ce jour et retirée : elle supposait l'effort
    servi, ce que cette décision refuse (`tests.TroisiemeBancEtSensTest`)."""

    CANDIDATES = [
        {'slug': 'claude-opus-5-5-low', 'name': 'Claude Opus 5.5 (Low, Default Fallback)', 'v': 34.8},
        {'slug': 'claude-opus-5-5', 'name': 'Claude Opus 5.5 (Max, Default Fallback)', 'v': 59.1},
    ]

    def test_without_a_declared_effort_the_worst_value_is_kept(self):
        chosen = bs._choose_variant('Claude Opus 5.5', self.CANDIDATES, lambda e: e['v'])
        self.assertEqual(34.8, chosen['v'])

    def test_an_aggregator_routing_suffix_does_not_change_the_choice(self):
        # « GLM 5.3 » et « GLM 5.3 (batch) » d'OpenRouter : le même modèle, la même note. Les
        # entrées d'AA du jour (relevées le 2026-11-06) : la ressemblance de chaîne donnait « Max »
        # au nom suffixé de « (batch) », « Low » à l'autre.
        cands = [{'slug': 'glm-5-3-low', 'name': 'GLM-5.3 (Low)', 'v': 23.1},
                 {'slug': 'glm-5-3', 'name': 'GLM-5.3 (Max)', 'v': 31.7}]
        self.assertEqual(bs._choose_variant('Z.ai: GLM 5.3', cands, lambda e: e['v']),
                         bs._choose_variant('Z.ai: GLM 5.3 (batch)', cands, lambda e: e['v']))

    def test_a_declared_served_variant_picks_its_entry(self):
        # `SERVED_VARIANT` joint son mot au nom local (`_benchmark_for_category`).
        chosen = bs._choose_variant('Claude Opus 5.5 max', self.CANDIDATES, lambda e: e['v'])
        self.assertEqual(59.1, chosen['v'])


class SingleSizeAliasesTest(SimpleTestCase):

    def test_the_two_single_size_mistral_series_are_confirmed_by_name(self):
        entries = [{'name': 'Mistral Small 3.2 (2506)', 'slug': ''},
                   {'name': 'Mistral Small 3.1 (2503)', 'slug': ''},
                   {'name': 'Mistral Small 4 (Reasoning)', 'slug': 'mistral-small-4'}]
        found = {key: [e['name'] for e in bs._match_alias(bs.ALIAS[key], entries)]
                 for key in ('albert:mistral-small-3-2-24b-instruct-2506', 'ilaas:mistral-small-4-119b')}
        self.assertEqual({'albert:mistral-small-3-2-24b-instruct-2506': ['Mistral Small 3.2 (2506)'],
                          'ilaas:mistral-small-4-119b': ['Mistral Small 4 (Reasoning)']}, found)


class SubscriptionServedEntryTest(SimpleTestCase):
    """Mesuré sur l'abonnement le 2026-11-06 : chaque alias de Claude Code sert un modèle (lu dans
    `modelUsage`) à l'effort des réglages que lit le CLI (`high`). Sa ligne prend l'entrée d'AA de
    CET effort — jamais la pire, que le choix conservateur lui donnerait sans déclaration."""

    #: Les entrées d'AA du jour (relevées le 2026-11-06), toutes variantes d'effort.
    OPUS = [{'slug': 'claude-opus-5-5-low', 'name': 'Claude Opus 5.5 (Low, Default Fallback)',
             'value': 34.8},
            {'slug': 'claude-opus-5-5-high', 'name': 'Claude Opus 5.5 (High, Default Fallback)',
             'value': 51.8},
            {'slug': 'claude-opus-5-5', 'name': 'Claude Opus 5.5 (Max, Default Fallback)',
             'value': 59.1}]

    def test_each_subscription_alias_designates_the_entry_of_its_served_effort(self):
        entries = self.OPUS + [
            {'slug': 'claude-sonnet-5-5-high', 'name': 'Claude Sonnet 5.5 (High, Default Fallback)'},
            {'slug': 'claude-sonnet-5-5', 'name': 'Claude Sonnet 5.5 (Max, Default Fallback)'},
            {'slug': 'claude-fable-5-1-high', 'name': 'Claude Fable 5.1 (High, Default Fallback)'},
            {'slug': 'claude-fable-5-1', 'name': 'Claude Fable 5.1 (Max, Default Fallback)'}]
        found = {key: [e['slug'] for e in bs._match_alias(bs.ALIAS[key], entries)]
                 for key in ('claude_code:opus', 'claude_code:default', 'claude_code:sonnet',
                             'claude_code:fable')}
        self.assertEqual({'claude_code:opus': ['claude-opus-5-5-high'],
                          'claude_code:default': ['claude-opus-5-5-high'],
                          'claude_code:sonnet': ['claude-sonnet-5-5-high'],
                          'claude_code:fable': ['claude-fable-5-1-high']}, found)

    def test_the_subscription_line_is_rated_at_its_served_effort(self):
        from ..models import AIModel
        row = AIModel(model_key='claude_code:opus', name='Claude Code — Opus', model_type='llm')
        benchmark, _ = bs._benchmark_for_category(
            row, 'llm', bs.ALIAS['claude_code:opus'],
            {'aa': {'llm': [dict(e, scale='aa_intelligence_index_v5', family_scores={})
                            for e in self.OPUS]}})
        self.assertEqual((51.8, 'alias'), (benchmark['value'], benchmark['matched_by']))
