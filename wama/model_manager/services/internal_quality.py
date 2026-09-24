"""
Étage 3 de l'échelle des signaux — la MESURE INTERNE d'un modèle (`WAMA_QUALITE.md §4.1`, ⑧).

Les trois étages vivent côte à côte, un module chacun : `model_quality` (a priori structurel),
`benchmark_sync` (bancs TIERS), et celui-ci (ce que WAMA a MESURÉ elle-même, sur les données du
labo, contre une référence humaine — `common.models.ResultEvaluation`).

RABATTUE À LA LECTURE, JAMAIS ÉCRITE AU CATALOGUE (2026-09-23) — même motif que la résidence
des modèles dans `api_models_db`. Deux raisons, toutes deux mesurées au code :
  • « en lecture d'abord » (décision Q3) : la sélection lit `benchmark_index` et
    `benchmark_meta['family_scores']` (`model_selector._quality_scalars`) ; une note qui n'y est
    pas écrite ne peut PAS entrer dans un tri, par construction ;
  • `sync_benchmarks` REMPLACE `benchmark_meta` entier pour chaque modèle apparié
    (`benchmark_sync.synchronize`) : une clé `internal` y serait effacée à chaque passe (Q8).
Le jour où la note entrera dans la sélection, c'est une PROJECTION de ce calcul qu'on écrira —
et cette fonction restera sa seule définition.

LES RÈGLES D'UNE ÉCHELLE (celles de `benchmark_sync`, reprises telles quelles) :
  • une échelle NOMMÉE : `internal_<métrique>_<protocole>` — jamais une valeur nue ;
  • son SENS voyage avec elle (`direction`) : un WER se trie à l'envers d'un score ;
  • le taux est celui du CORPUS mesuré (Σ erreurs / Σ longueurs de référence), pas une moyenne
    de taux — 3 mots ne pèsent pas autant que 3 000 ;
  • une POPULATION : deux modèles ne se comparent que mesurés sur les MÊMES références ; le rang
    ne se lit qu'à l'intérieur de ce groupe, et seulement s'il compte plusieurs modèles ;
  • l'ACCUMULATION se dit (éléments, références, mots) : une note sur trois phrases est une
    anecdote, et c'est au lecteur de le voir, pas à un seuil inventé ici de le cacher.
Les résultats EXTERNES (`external:…`, port `work_result`) sont mesurables mais n'ont pas de note :
ce ne sont pas des modèles du parc.
"""
from __future__ import annotations

from typing import Dict, Iterable, List, Optional

SCALE_PREFIX = 'internal'


def scale_name(metric: str, protocol: str) -> str:
    return f'{SCALE_PREFIX}_{metric}_{protocol}'


def internal_scores(model_keys: Optional[Iterable[str]] = None) -> Dict[str, List[dict]]:
    """Les échelles internes de chaque modèle mesuré : `{model_key: [échelle, …]}`.

    Une échelle : `{scale, metric, protocol, direction, value, items, references,
    reference_words, measured_until, population, rank}` — `rank` (1 = le meilleur) et
    `population` ne valent que parmi les modèles mesurés sur EXACTEMENT les mêmes références ;
    `rank` est None quand le modèle y est seul. Un modèle jamais mesuré est absent du dict.
    """
    from wama.common.models import ResultEvaluation
    from wama.common.services.result_evaluation import EXTERNAL_PREFIX

    rows = (ResultEvaluation.objects.exclude(model_key='')
            .exclude(model_key__startswith=EXTERNAL_PREFIX)
            .exclude(value__isnull=True))
    if model_keys is not None:
        rows = rows.filter(model_key__in=list(model_keys))

    groups: Dict[tuple, dict] = {}
    for r in rows.only('model_key', 'metric', 'protocol', 'direction', 'object_type',
                       'object_id', 'app', 'reference_sha256', 'detail', 'measured_at'):
        key = (r.model_key, r.metric, r.protocol, r.direction)
        g = groups.setdefault(key, {'errors': 0, 'reference_words': 0, 'items': set(),
                                    'references': set(), 'measured_until': None})
        detail = r.detail or {}
        g['errors'] += int(detail.get('errors') or 0)
        g['reference_words'] += int(detail.get('reference_length') or 0)
        g['items'].add((r.app, r.object_type, r.object_id))
        g['references'].add(r.reference_sha256)
        if g['measured_until'] is None or r.measured_at > g['measured_until']:
            g['measured_until'] = r.measured_at

    scales: Dict[str, List[dict]] = {}
    peers: Dict[tuple, list] = {}          # (échelle, jeu de références) → [(valeur, échelle)]
    for (model_key, metric, protocol, direction), g in groups.items():
        if not g['reference_words']:
            continue
        entry = {'scale': scale_name(metric, protocol), 'metric': metric, 'protocol': protocol,
                 'direction': direction,
                 'value': round(g['errors'] / g['reference_words'], 4),
                 'items': len(g['items']), 'references': len(g['references']),
                 'reference_words': g['reference_words'],
                 'measured_until': g['measured_until'].isoformat(),
                 'population': 1, 'rank': None}
        scales.setdefault(model_key, []).append(entry)
        peers.setdefault((entry['scale'], frozenset(g['references'])), []).append(entry)

    for group in peers.values():
        if len(group) < 2:
            continue
        lower_is_better = group[0]['direction'] == 'lower'
        ordered = sorted(group, key=lambda e: e['value'], reverse=not lower_is_better)
        for position, entry in enumerate(ordered, start=1):
            entry['population'] = len(group)
            entry['rank'] = position

    for entries in scales.values():
        entries.sort(key=lambda e: e['scale'])
    return scales
