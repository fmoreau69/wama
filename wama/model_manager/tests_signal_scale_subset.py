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


def _model(key, *, vram=None, coding=None, quality_index=None, cloud=False,
           benchmark_index=None, scale=None, rank=None):
    meta = {}
    if coding is not None:
        meta['family_scores'] = {'coding': coding}
    if scale is not None:
        meta['scale'] = scale
    if rank is not None:
        meta['percentile_rank'] = rank
    return AIModel(model_key=key, name=key, vram_gb=vram, quality_index=quality_index,
                   benchmark_index=benchmark_index, benchmark_meta=meta or None,
                   execution=EXECUTION_CLOUD if cloud else EXECUTION_LOCAL)


class SubsetScaleTest(TestCase):

    def test_one_unscored_model_no_longer_drags_the_whole_batch_down(self):
        """LE cas mesuré, reconstitué à l'identique."""
        batch = [_model('albert:gemma-4-31b-it', coding=43.4, vram=0, cloud=True),
               _model('albert:gpt-oss-120b', vram=0, cloud=True),          # AUCUN score
               _model('ollama:qwen3.6:35b', coding=41.9, vram=23.0, quality_index=33.67),
               _model('ollama:qwen3.8:latest', coding=58.2, vram=17.0, quality_index=54.71)]

        values, proxy_vram = _quality_scalars(batch, 'coding')
        self.assertFalse(proxy_vram, "le lot ne doit plus retomber sur la taille")
        self.assertEqual(3, len(values), "les 3 modèles notés, et eux seuls")

        best = _best_by_vram(batch, budget_gb=None, family='coding', quality_intent=100)
        self.assertEqual('ollama:qwen3.8:latest', best.model_key)

    def test_the_unmeasured_model_never_wins_by_default(self):
        batch = [_model('mesure', coding=12.0, vram=4.0), _model('inconnu', vram=40.0)]
        best = _best_by_vram(batch, budget_gb=None, family='coding', quality_intent=100)
        self.assertEqual('mesure', best.model_key)

    def test_but_it_is_chosen_when_it_is_the_only_candidate(self):
        batch = [_model('inconnu', vram=40.0)]
        self.assertEqual('inconnu', _best_by_vram(batch, budget_gb=None, family='coding',
                                                  quality_intent=100).model_key)

    def test_the_benchmark_tier_still_needs_a_single_scale(self):
        """Contre-épreuve : le sous-ensemble mesuré doit AUSSI partager une seule échelle —
        un Elo et un Intelligence Index ne se classent pas ensemble."""
        batch = [_model('a', benchmark_index=1100, scale='arena_elo', vram=5.0),
               _model('b', benchmark_index=52, scale='intelligence_index', vram=9.0),
               _model('c', vram=3.0)]
        values, proxy_vram = _quality_scalars(batch, None)
        self.assertTrue(proxy_vram, "deux échelles → on redescend, comme avant")

    def test_two_scales_fall_back_to_the_percentile_rank_not_to_the_size(self):
        """Le rang centile est la lecture INTER-échelles : elle existait depuis le 01/09 et
        la sélection ne la lisait pas. Un lot local (Intelligence Index) + distant (Elo) se
        classe désormais par rang, au lieu de tomber sur la taille."""
        batch = [_model('local', benchmark_index=26.2, scale='aa_intelligence_index',
                        rank=80.0, vram=17.0),
                 _model('distant', benchmark_index=1458.0, scale='arena_elo_text',
                        rank=95.0, cloud=True, vram=0)]
        values, proxy_vram = _quality_scalars(batch, None)
        self.assertFalse(proxy_vram, "deux échelles ne doivent plus mener à la VRAM")
        self.assertEqual([80.0, 95.0], [values[id(m)] for m in batch])
        best = _best_by_vram(batch, budget_gb=None, family=None, quality_intent=100)
        self.assertEqual('distant', best.model_key)

    def test_a_single_scale_still_uses_the_exact_value_not_the_rank(self):
        """Le rang vient APRÈS : à échelle unique, le score exact dit plus que le rang —
        et le rang est ordinal, dépendant de la population de son banc."""
        batch = [_model('a', benchmark_index=26.2, scale='aa_intelligence_index', rank=10.0,
                        vram=5.0),
                 _model('b', benchmark_index=18.2, scale='aa_intelligence_index', rank=99.0,
                        vram=5.0)]
        values, _ = _quality_scalars(batch, None)
        self.assertEqual([26.2, 18.2], [values[id(m)] for m in batch])

    def test_the_family_tier_beats_the_benchmark_tier_when_it_covers_someone(self):
        batch = [_model('a', coding=70.0, benchmark_index=10, scale='ii', vram=5.0),
               _model('b', benchmark_index=90, scale='ii', vram=5.0)]
        values, _ = _quality_scalars(batch, 'coding')
        self.assertEqual([70.0], list(values.values()))


class LocalAndCloudAreDistinctTest(TestCase):

    def test_cloud_is_read_from_the_declared_field_not_from_vram(self):
        self.assertTrue(is_cloud(_model('x', vram=0, cloud=True)))
        self.assertFalse(is_cloud(_model('y', vram=0)))     # local jamais mesuré ≠ distant

    def test_the_vram_proxy_only_ranks_local_models(self):
        """Un distant n'a pas de taille : il ne peut pas être « le plus petit », ni le pire."""
        batch = [_model('distant', vram=0, cloud=True), _model('local', vram=8.0)]
        values, proxy_vram = _quality_scalars(batch, None)
        self.assertTrue(proxy_vram)
        self.assertEqual(['local'], [m.model_key for m in batch if id(m) in values])

    def test_a_cloud_model_costs_nothing_on_this_card(self):
        """Le sélecteur N'ARBITRE PAS local/distant : c'est `cloud_policy` qui le fait, à
        l'ADMISSION. Un distant admis jusqu'ici ne prend rien sur cette carte — au curseur
        « Rapide », à qualité égale, c'est une mesure, pas une faveur."""
        batch = [_model('distant', vram=0, cloud=True, quality_index=50.0),
                 _model('local', vram=6.0, quality_index=50.0)]
        best = _best_by_vram(batch, budget_gb=None, family=None, quality_intent=15)
        self.assertEqual('distant', best.model_key)

    def test_an_unmeasured_local_is_still_the_worst_cost(self):
        """Contre-épreuve de la garde du 02/09 : « pas mesuré » ne devient pas « gratuit »
        parce qu'on a appris à reconnaître le distant."""
        batch = [_model('jamais_mesure', vram=0), _model('leger', vram=0.5, quality_index=1.0),
                 _model('lourd', vram=20.0, quality_index=1.0)]
        batch[0].quality_index = 1.0
        best = _best_by_vram(batch, budget_gb=None, family=None, quality_intent=15)
        self.assertEqual('leger', best.model_key)

    def test_a_cloud_model_still_wins_on_quality(self):
        batch = [_model('distant', vram=0, cloud=True, quality_index=90.0),
               _model('local', vram=6.0, quality_index=20.0)]
        best = _best_by_vram(batch, budget_gb=None, family=None, quality_intent=100)
        self.assertEqual('distant', best.model_key)
