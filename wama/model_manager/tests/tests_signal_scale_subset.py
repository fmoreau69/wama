"""
L'ÉCHELLE DES SIGNAUX se juge sur le sous-ensemble qu'elle couvre (2026-09-26, Fabien).

LE DÉFAUT MESURÉ. Le tirage de DÉVELOPPEMENT rendait `qwen3.6:35b` (coding 41,9 — 23 Go) là
où `qwen3.8:latest` (coding 58,2 — 17 Go) est meilleur ET plus léger. Cause : le lot contenait
`albert:gpt-oss-120b`, SANS score coding. La règle « le sous-indice si TOUT le lot le porte »
tombait donc d'un étage, puis d'un autre, jusqu'au dernier repli — la VRAM. À ce moment-là
« le meilleur » veut dire « le plus gros », ce que la docstring du sélecteur dément
elle-même (un MoE a la qualité d'un 36B au coût d'un 3B).

⭐ *Un lot ne se juge pas au modèle qu'on n'a pas mesuré.*

ET LA DISTINCTION LOCAL / DISTANT. Un modèle distant a `vram_gb = 0` : le repli VRAM en
faisait le PIRE du lot, alors que sa VRAM est nulle par NATURE. Elle se lit désormais sur le
champ DÉCLARÉ `AIModel.execution`, jamais devinée d'un `vram_gb` — la même absence voulant
dire « inconnu » pour un local et « hors sujet » pour un distant.

⚠ Ce que ces gardes NE disent pas : que le sélecteur choisisse entre local et distant.
**C'est l'utilisateur qui le définit** (`cloud_policy`, appliqué à l'ADMISSION par
`allowed_cloud_keys`) ; un distant qui atteint le classement a déjà été autorisé, et il ne
prend rien sur cette carte. Son coût PROPRE (`cost_tier`) reste délibérément non lu ici : son
domicile est l'admission, pas le score — mêler des euros et des gigaoctets dans un min-max
inventerait l'équivalence que l'échelle des signaux interdit.
"""
from django.test import TestCase

from wama.model_manager.models import AIModel, EXECUTION_CLOUD, EXECUTION_LOCAL
from wama.model_manager.services.model_selector import (
    _best_by_vram, _quality_scalars, is_cloud)


def _row(key, *, vram=None, coding=None, quality_index=None, cloud=False,
           benchmark_index=None, scale=None, rank=None, scales=None):
    meta = {}
    if coding is not None:
        meta['family_scores'] = {'coding': coding}
    if scale is not None:
        meta['scale'] = scale
    if rank is not None:
        meta['percentile_rank'] = rank
    if scales is not None:
        meta['scales'] = [{'scale': s, 'value': v, 'direction': d} for s, v, d in scales]
    return AIModel(model_key=key, name=key, vram_gb=vram, quality_index=quality_index,
                   benchmark_index=benchmark_index, benchmark_meta=meta or None,
                   execution=EXECUTION_CLOUD if cloud else EXECUTION_LOCAL)


class SubsetScaleTest(TestCase):

    def test_one_unscored_model_no_longer_drags_the_whole_batch_down(self):
        """LE cas mesuré, reconstitué à l'identique."""
        batch = [_row('albert:gemma-4-31b-it', coding=43.4, vram=0, cloud=True),
               _row('albert:gpt-oss-120b', vram=0, cloud=True),          # AUCUN score
               _row('ollama:qwen3.6:35b', coding=41.9, vram=23.0, quality_index=33.67),
               _row('ollama:qwen3.8:latest', coding=58.2, vram=17.0, quality_index=54.71)]

        values, proxy_vram = _quality_scalars(batch, 'coding')
        self.assertFalse(proxy_vram, "le lot ne doit plus retomber sur la taille")
        self.assertEqual(3, len(values), "les 3 modèles notés, et eux seuls")

        best = _best_by_vram(batch, budget_gb=None, family='coding', quality_intent=100)
        self.assertEqual('ollama:qwen3.8:latest', best.model_key)

    def test_the_unmeasured_model_never_wins_by_default(self):
        batch = [_row('mesure', coding=12.0, vram=4.0), _row('inconnu', vram=40.0)]
        best = _best_by_vram(batch, budget_gb=None, family='coding', quality_intent=100)
        self.assertEqual('mesure', best.model_key)

    def test_but_it_is_chosen_when_it_is_the_only_candidate(self):
        batch = [_row('inconnu', vram=40.0)]
        self.assertEqual('inconnu', _best_by_vram(batch, budget_gb=None, family='coding',
                                                  quality_intent=100).model_key)

    def test_the_benchmark_tier_still_needs_a_single_scale(self):
        """Contre-épreuve : le sous-ensemble mesuré doit AUSSI partager une seule échelle —
        un Elo et un Intelligence Index ne se classent pas ensemble."""
        batch = [_row('a', benchmark_index=1100, scale='arena_elo', vram=5.0),
               _row('b', benchmark_index=52, scale='intelligence_index', vram=9.0),
               _row('c', vram=3.0)]
        values, proxy_vram = _quality_scalars(batch, None)
        self.assertTrue(proxy_vram, "deux échelles → on redescend, comme avant")

    def test_two_scales_fall_back_to_the_percentile_rank_not_to_the_size(self):
        """Le rang centile est la lecture INTER-échelles : elle existait depuis le 01/09 et
        la sélection ne la lisait pas. Un lot local (Intelligence Index) + distant (Elo) se
        classe désormais par rang, au lieu de tomber sur la taille."""
        batch = [_row('local', benchmark_index=26.2, scale='aa_intelligence_index',
                        rank=80.0, vram=17.0),
                 _row('distant', benchmark_index=1458.0, scale='arena_elo_text',
                        rank=95.0, cloud=True, vram=0)]
        values, proxy_vram = _quality_scalars(batch, None)
        self.assertFalse(proxy_vram, "deux échelles ne doivent plus mener à la VRAM")
        self.assertEqual([80.0, 95.0], [values[id(m)] for m in batch])
        best = _best_by_vram(batch, budget_gb=None, family=None, quality_intent=100)
        self.assertEqual('distant', best.model_key)

    def test_a_single_scale_still_uses_the_exact_value_not_the_rank(self):
        """Le rang vient APRÈS : à échelle unique, le score exact dit plus que le rang —
        et le rang est ordinal, dépendant de la population de son banc."""
        batch = [_row('a', benchmark_index=26.2, scale='aa_intelligence_index', rank=10.0,
                        vram=5.0),
                 _row('b', benchmark_index=18.2, scale='aa_intelligence_index', rank=99.0,
                        vram=5.0)]
        values, _ = _quality_scalars(batch, None)
        self.assertEqual([26.2, 18.2], [values[id(m)] for m in batch])

    def test_the_family_tier_beats_the_benchmark_tier_when_it_covers_someone(self):
        batch = [_row('a', coding=70.0, benchmark_index=10, scale='ii', vram=5.0),
               _row('b', benchmark_index=90, scale='ii', vram=5.0)]
        values, _ = _quality_scalars(batch, 'coding')
        self.assertEqual([70.0], list(values.values()))

    def test_sub_scores_of_two_index_versions_are_not_compared(self):
        """2026-10-30 : AA est passé à l'Intelligence Index v5 — un sous-indice v4 et un sous-indice
        v5 sont deux échelles. L'étage s'abstient, le tri descend (ici au rang centile)."""
        batch = [_row('v4', coding=58.2, benchmark_index=26.2, scale='aa_intelligence_index',
                      rank=80.0, vram=5.0),
                 _row('v5', coding=31.0, benchmark_index=15.7, scale='aa_intelligence_index_v5',
                      rank=40.0, vram=5.0)]
        values, _ = _quality_scalars(batch, 'coding')
        self.assertEqual([80.0, 40.0], [values[id(m)] for m in batch])


class CommonScaleTest(TestCase):
    """2026-10-30, décision de Fabien : deux porteurs différents, mais une échelle que tout le lot
    porte AUSSI (l'Arena derrière un porteur AA) — la valeur sur cette échelle passe avant le rang
    centile. Le cas mesuré : qwen3.8 (AA v5, 11ᵉ centile sur 73) contre gemma-4-31b (Arena, 79,5ᵉ),
    alors que l'Arena les note tous deux, 1438 et 1443."""

    def _pair(self, qwen_elo=1438.4, gemma_scales=True):
        qwen = _row('ilaas:qwen-3.8-27b', benchmark_index=20.1, scale='aa_intelligence_index_v5',
                    rank=95.0, cloud=True, vram=0,
                    scales=[('aa_intelligence_index_v5', 20.1, 'higher'),
                            ('arena_elo_text', qwen_elo, 'higher')])
        gemma = _row('albert:gemma-4-31b-it', benchmark_index=1443.0, scale='arena_elo_text',
                     rank=79.5, cloud=True, vram=0,
                     scales=[('arena_elo_text', 1443.0, 'higher')] if gemma_scales else None)
        return qwen, gemma

    def test_a_scale_the_whole_lot_carries_ranks_before_the_percentile(self):
        qwen, gemma = self._pair(qwen_elo=1450.0)
        values, proxy_vram = _quality_scalars([qwen, gemma], None)
        self.assertFalse(proxy_vram)
        self.assertEqual([1450.0, 1443.0], [values[id(m)] for m in (qwen, gemma)])
        best = _best_by_vram([qwen, gemma], budget_gb=None, family=None, quality_intent=100)
        self.assertEqual('ilaas:qwen-3.8-27b', best.model_key, 'le rang (95 > 79,5) aurait dit pareil')
        qwen, gemma = self._pair(qwen_elo=1438.4)
        best = _best_by_vram([qwen, gemma], budget_gb=None, family=None, quality_intent=100)
        self.assertEqual('albert:gemma-4-31b-it', best.model_key,
                         "l'Elo commun tranche, pas le rang de deux populations")

    def test_without_a_shared_scale_the_percentile_still_decides(self):
        qwen, gemma = self._pair(gemma_scales=False)
        values, _ = _quality_scalars([qwen, gemma], None)
        self.assertEqual([95.0, 79.5], [values[id(m)] for m in (qwen, gemma)])

    def test_two_directions_are_not_one_scale(self):
        a = _row('a', benchmark_index=4.0, scale='x', rank=60.0, scales=[('wer', 4.0, 'lower')])
        b = _row('b', benchmark_index=70.0, scale='y', rank=40.0, scales=[('wer', 6.0, 'higher')])
        values, _ = _quality_scalars([a, b], None)
        self.assertEqual([60.0, 40.0], [values[id(m)] for m in (a, b)])

    def test_an_error_rate_shared_by_the_lot_reads_lower_is_better(self):
        a = _row('a', benchmark_index=1.0, scale='x', rank=10.0, scales=[('wer', 4.0, 'lower')])
        b = _row('b', benchmark_index=2.0, scale='y', rank=90.0, scales=[('wer', 6.0, 'lower')])
        best = _best_by_vram([a, b], budget_gb=None, family=None, quality_intent=100)
        self.assertEqual('a', best.model_key)

    def test_the_installed_reference_reads_the_same_stage(self):
        """`AIModel.best_installed` (le référentiel de la prospection) se dit « même règle d'étage
        que la sélection » : il lit le même domicile."""
        from wama.model_manager.models import AIModel
        # Créé en second et nommé après l'autre : sans l'étage, le repli le rangerait derrière.
        for key, scale, value, elo in (('x:a-arena', 'arena_elo_text', 1443.0, 1443.0),
                                       ('x:z-aa', 'aa_intelligence_index_v5', 20.1, 1450.0)):
            scales = [{'scale': 'arena_elo_text', 'value': elo, 'direction': 'higher'}]
            if scale != 'arena_elo_text':
                scales.insert(0, {'scale': scale, 'value': value, 'direction': 'higher'})
            AIModel.objects.create(model_key=key, name=key, model_type='llm', is_downloaded=True,
                                   benchmark_index=value,
                                   benchmark_meta={'scale': scale, 'scales': scales})
        self.assertEqual(['x:z-aa', 'x:a-arena'],
                         [m.model_key for m in AIModel.best_installed('llm', limit=2)])


class SharedPopulationRankTest(TestCase):
    """2026-11-06, demande de Fabien : l'étage du rang centile lisait le seul rang du PORTEUR. Le cas
    mesuré sur le tirage de l'assistant : Gemma 4 31B portée par AA v5 (93 modèles, surtout
    frontière : 2,2ᵉ centile), DeepSeek V4 Flash portée par l'Arena (72,2ᵉ sur 302) — l'Arena notant
    les deux, Gemma devant. Chaque modèle se lit désormais dans la population la plus partagée."""

    @staticmethod
    def _rated(key, *ranks, vram=0, cloud=True):
        """`ranks` : (échelle, valeur, rang) dans l'ordre de priorité des sources."""
        m = _row(key, benchmark_index=ranks[0][1], scale=ranks[0][0], rank=ranks[0][2],
                 cloud=cloud, vram=vram)
        m.benchmark_meta['scales'] = [{'scale': s, 'value': v, 'direction': 'higher',
                                       'percentile_rank': r} for s, v, r in ranks]
        return m

    def _measured_lot(self):
        gemma = self._rated('albert:gemma-4-31b-it', ('aa_intelligence_index_v5', 4.4, 2.2),
                            ('arena_elo_text', 1443.0, 79.1))
        deepseek = self._rated('albert:deepseek-v4-flash-0731', ('arena_elo_text', 1431.8, 72.2))
        qwen = self._rated('ilaas:qwen-3.8-27b', ('aa_intelligence_index_v5', 20.1, 22.6),
                           ('arena_elo_text', 1438.4, 75.5))
        mistral = self._rated('ilaas:mistral-small-4-119b', ('aa_intelligence_index_v5', 4.3, 1.1))
        # Mesuré : l'Arena note huit modèles du lot, AA v5 cinq.
        small = self._rated('albert:mistral-small-3-2-24b-instruct-2506',
                            ('arena_elo_text', 1338.0, 40.1))
        return gemma, deepseek, qwen, mistral, small

    def test_the_measured_draw_reads_the_population_the_lot_shares(self):
        lot = self._measured_lot()
        values, proxy_vram = _quality_scalars(lot, None)
        self.assertFalse(proxy_vram)
        self.assertEqual([79.1, 72.2, 75.5, 1.1, 40.1], [values[id(m)] for m in lot])
        best = _best_by_vram(lot, budget_gb=None, family=None, quality_intent=100)
        self.assertEqual('albert:gemma-4-31b-it', best.model_key,
                         "l'Arena classe Gemma devant DeepSeek : le rang de deux populations ne "
                         "doit plus l'inverser")

    def test_a_model_the_shared_scale_does_not_rate_keeps_its_own_rank(self):
        lot = self._measured_lot()
        values, _ = _quality_scalars(lot, None)
        self.assertEqual(1.1, values[id(lot[3])])

    def test_the_most_shared_population_wins_not_the_carrier(self):
        """Le porteur (AA, prioritaire) ne décide plus seul : l'Arena note plus de modèles du lot."""
        from wama.model_manager.services.benchmark_sync import shared_percentile_values
        gemma, deepseek, qwen, mistral, small = lot = self._measured_lot()
        self.assertEqual(79.1, shared_percentile_values(lot)[id(gemma)])
        # Avec Mistral seul, c'est AA v5 qui note le plus de modèles du lot.
        self.assertEqual(2.2, shared_percentile_values([gemma, mistral])[id(gemma)])
        # Seule, Gemma est notée autant par l'une que par l'autre : l'ordre de ses échelles (la
        # priorité des sources) tranche.
        self.assertEqual(2.2, shared_percentile_values([gemma])[id(gemma)])

    def test_a_row_synced_before_the_per_scale_rank_reads_its_carrier_rank(self):
        legacy = _row('legacy', benchmark_index=26.2, scale='aa_intelligence_index', rank=80.0,
                      scales=[('aa_intelligence_index', 26.2, 'higher')])
        other = self._rated('other', ('arena_elo_text', 1400.0, 60.0))
        values, _ = _quality_scalars([legacy, other], None)
        self.assertEqual([80.0, 60.0], [values[id(m)] for m in (legacy, other)])

    def test_the_sync_writes_a_rank_per_independent_scale(self):
        """La synchro écrit le rang de CHAQUE échelle, dans la population de sa source — et aucun
        rang pour une valeur auto-déclarée (règle du rang du porteur, 2026-10-10)."""
        from wama.model_manager.services import benchmark_sync as bs
        ident = ('qwen', (3, 8), 27.0)
        other = ('other', (1,), 27.0)
        sources = {
            'aa': {'llm': [{'name': 'Qwen3.8 27B', 'slug': 'qwen3-8-27b', 'value': 20.1,
                            'scale': 'aa_intelligence_index_v5', 'identity': ident,
                            'family_scores': {}},
                           {'name': 'Other 1', 'slug': 'other-1', 'value': 30.0,
                            'scale': 'aa_intelligence_index_v5', 'identity': other,
                            'family_scores': {}}]},
            'arena': {'llm': [{'name': 'Qwen3.8-27B', 'elo': 1438.4, 'votes': 9, 'identity': ident},
                              {'name': 'Other 1', 'elo': 1300.0, 'votes': 9, 'identity': other},
                              {'name': 'Other 2', 'elo': 1200.0, 'votes': 9, 'identity': other}]}}
        row = AIModel(model_key='ilaas:qwen-3.8-27b', name='qwen-3.8-27b')
        benchmark, _ = bs._benchmark_for_category(row, 'llm', None, sources)
        self.assertEqual([('aa_intelligence_index_v5', 0.0, 2), ('arena_elo_text', 66.7, 3)],
                         [(s['scale'], s['percentile_rank'], s['population'])
                          for s in benchmark['scales']])
        self.assertEqual(0.0, benchmark['percentile_rank'], 'le rang du porteur est inchangé')

        sources['aa']['llm'][0]['provenance'] = bs.PROVENANCE_SELF_DECLARED
        benchmark, _ = bs._benchmark_for_category(row, 'llm', None, sources)
        self.assertNotIn('percentile_rank', benchmark['scales'][0])
        self.assertEqual(66.7, benchmark['scales'][1]['percentile_rank'])


class LocalAndCloudAreDistinctTest(TestCase):

    def test_cloud_is_read_from_the_declared_field_not_from_vram(self):
        self.assertTrue(is_cloud(_row('x', vram=0, cloud=True)))
        self.assertFalse(is_cloud(_row('y', vram=0)))     # local jamais mesuré ≠ distant

    def test_the_vram_proxy_only_ranks_local_models(self):
        """Un distant n'a pas de taille : il ne peut pas être « le plus petit », ni le pire."""
        batch = [_row('distant', vram=0, cloud=True), _row('local', vram=8.0)]
        values, proxy_vram = _quality_scalars(batch, None)
        self.assertTrue(proxy_vram)
        self.assertEqual(['local'], [m.model_key for m in batch if id(m) in values])

    def test_a_cloud_model_costs_nothing_on_this_card(self):
        """Le sélecteur N'ARBITRE PAS local/distant : c'est `cloud_policy` qui le fait, à
        l'ADMISSION. Un distant admis jusqu'ici ne prend rien sur cette carte — au curseur
        « Rapide », à qualité égale, c'est une mesure, pas une faveur."""
        batch = [_row('distant', vram=0, cloud=True, quality_index=50.0),
                 _row('local', vram=6.0, quality_index=50.0)]
        best = _best_by_vram(batch, budget_gb=None, family=None, quality_intent=15)
        self.assertEqual('distant', best.model_key)

    def test_an_unmeasured_local_is_still_the_worst_cost(self):
        """Contre-épreuve de la garde du 02/09 : « pas mesuré » ne devient pas « gratuit »
        parce qu'on a appris à reconnaître le distant."""
        batch = [_row('jamais_mesure', vram=0), _row('leger', vram=0.5, quality_index=1.0),
                 _row('lourd', vram=20.0, quality_index=1.0)]
        batch[0].quality_index = 1.0
        best = _best_by_vram(batch, budget_gb=None, family=None, quality_intent=15)
        self.assertEqual('leger', best.model_key)

    def test_a_cloud_model_still_wins_on_quality(self):
        batch = [_row('distant', vram=0, cloud=True, quality_index=90.0),
               _row('local', vram=6.0, quality_index=20.0)]
        best = _best_by_vram(batch, budget_gb=None, family=None, quality_intent=100)
        self.assertEqual('distant', best.model_key)


class LearnedSpeedCostTest(TestCase):
    """La VITESSE apprise est le coût du curseur quand TOUT le lot en a une (2026-10-11, demande
    de Fabien : « intégrer la vitesse dans la sélection », pour toutes les apps). Elle vient de la
    boucle d'ETA commune (`ModelRuntimeStat`, clé de catalogue, ce matériel) ; sinon la VRAM."""

    def _time(self, key, seconds, unit='image'):
        from wama.model_manager.models import ModelRuntimeStat
        from wama.model_manager.services.eta_estimator import hardware_fingerprint
        ModelRuntimeStat.objects.create(model_key=key, hardware_fingerprint=hardware_fingerprint(),
                                        unit=unit, per_unit_ema_seconds=seconds, samples=3)

    def _batch(self):
        # Le plus LÉGER en VRAM est le plus LENT : c'est le cas que la VRAM classait mal.
        return [_row('small_slow', vram=1.0, quality_index=40.0),
                _row('big_fast', vram=8.0, quality_index=40.0)]

    def test_fast_takes_the_fastest_model_once_the_lot_is_timed(self):
        self._time('small_slow', 0.09)
        self._time('big_fast', 0.01)
        self.assertEqual('big_fast', _best_by_vram(self._batch(), None, quality_intent=0).model_key)

    def test_without_timings_the_vram_stays_the_cost(self):
        self.assertEqual('small_slow',
                         _best_by_vram(self._batch(), None, quality_intent=0).model_key)

    def test_a_lot_timed_in_part_keeps_the_vram(self):
        """Règle de lot : on ne compare pas un modèle chronométré à un autre qui ne l'est pas."""
        self._time('big_fast', 0.01)
        self.assertEqual('small_slow',
                         _best_by_vram(self._batch(), None, quality_intent=0).model_key)

    def test_two_units_do_not_compare(self):
        from wama.model_manager.services.eta_estimator import comparable_speeds
        self._time('small_slow', 0.09, unit='image')
        self._time('big_fast', 0.01, unit='token')
        self.assertEqual({}, comparable_speeds(['small_slow', 'big_fast']))
        self.assertEqual('small_slow',
                         _best_by_vram(self._batch(), None, quality_intent=0).model_key)

    def test_the_budget_still_filters_before_speed(self):
        """La VRAM reste le BUDGET : un modèle rapide qui ne tient pas n'est pas candidat."""
        self._time('small_slow', 0.09)
        self._time('big_fast', 0.01)
        self.assertEqual('small_slow',
                         _best_by_vram(self._batch(), 4.0, quality_intent=0).model_key)
