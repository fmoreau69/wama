"""GARÉS EN DOUBLE : deux garés retenus à moins de 2 m — un même objet compté deux fois, ou deux voisins ?

Pourquoi (Fabien, 2026-10-28, sur la mesure du 2026-10-14) : la mesure « garés en double » comptait toute
paire d'ancres à moins de 2 m. Rejouée sur `4da52df3` le 2026-10-28, ses 336 paires se répartissent en :
  · 146 vues dans la MÊME IMAGE par la même caméra comme deux boîtes — deux vraies voitures côte à côte, que
    le placement rapproche ; jamais un doublon ;
  · 155 PASSAGES DISTINCTS (jamais vus à moins d'une minute l'un de l'autre) — la navette repasse, l'objet a
    pu changer ; jamais affichés ensemble (un garé n'est dessiné qu'aux images où il est détecté) ;
  · 35 SUSPECTS — 5 vus au MÊME INSTANT par deux caméras, 25 IMBRIQUÉS et 5 À LA SUITE au cours d'un même
    passage, sans jamais une image commune : un objet dont le suivi a changé d'identifiant, ou que deux
    caméras n'ont pas recollé.
⚠ La 1ʳᵉ ventilation (2026-10-14 : 101 imbriquées sur 333) jugeait le passage sur le chevauchement des
PÉRIODES ; or la pose longue réunit les passages d'un garé, qui couvre alors des heures — rejouée le
2026-10-28 avec cette règle, 86 des 111 « imbriquées » n'avaient jamais été vues au même passage. La mesure ne compte plus que les suspects, et ⚑ parked_twin_merge
les réunit.

Règles (fonctions pures ; l'appelant donne la position fixe de chaque garé et les instants où il est vu) :
  · une paire vue comme deux boîtes d'une même image n'est jamais réunie, quelle que soit sa distance ;
  · une paire jamais vue au même passage (observations les plus proches à plus d'une minute) non plus ;
  · un groupe se forme de proche en proche SEULEMENT si chaque nouveau membre est un suspect de CHAQUE membre
    déjà présent (moins de `twin_m`, même famille) — une file de garés ne s'enchaîne pas ;
  · les plus observés fondent les groupes, la racine est le plus observé.
"""
from __future__ import annotations

import bisect
import math
from collections import Counter

from wama.common.catalog.data_types import DataType, TypedFrame
from wama.common.catalog.function_catalog import (FunctionSpec, PortSpec, ParamSpec,
                                                  FunctionCategory, register)

#: Deux garés plus proches que ceci sont une paire à juger (deux voitures garées sont à ≈ 2,3 m centre à
#: centre de profil) — le seuil de la mesure historique `parked_twins`.
TWIN_M = 2.0
#: Deux observations à moins de cet écart (s) sont du même instant.
SAME_INSTANT_S = 0.2
#: Au-delà de cet écart (s) entre deux périodes d'observation, ce sont deux passages de la navette.
PASSAGE_GAP_S = 60.0
#: Les natures de paire qui désignent un même objet compté deux fois.
SUSPECT_KINDS = ('same_instant', 'nested', 'consecutive')


def twin_pair_kind(times_a, times_b, seen_as_two=False, *, same_instant_s=SAME_INSTANT_S,
                   passage_gap_s=PASSAGE_GAP_S):
    """Nature d'une paire de garés proches. `times_*` : instants (s) TRIÉS où chacun est vu ; `seen_as_two` :
    une même caméra les a vus dans une même image comme deux boîtes. Rend 'same_image', 'same_instant',
    'nested', 'consecutive' ou 'distinct_passes'.
    ⚠ Le passage se juge sur les deux observations les PLUS PROCHES, jamais sur le chevauchement des
    périodes : la pose longue réunit les passages d'un garé, qui couvre alors des heures (rejeu du
    2026-10-28 : 777 → 4325 s) — deux garés vus à des passages différents auraient des périodes
    « imbriquées » sans avoir jamais été vus au même passage."""
    if seen_as_two:
        return 'same_image'
    best = math.inf
    for t in times_a:
        k = bisect.bisect_left(times_b, t)
        for j in (k - 1, k):
            if 0 <= j < len(times_b):
                best = min(best, abs(t - times_b[j]))
        if best < same_instant_s:
            return 'same_instant'
    if best >= passage_gap_s:
        return 'distinct_passes'
    gap = max(times_b[0] - times_a[-1], times_a[0] - times_b[-1])      # < 0 : périodes qui se chevauchent
    return 'nested' if gap < 0 else 'consecutive'


def parked_twin_pairs(objects, seen_as_two=(), *, twin_m=TWIN_M, **kind_kw):
    """`objects` : itérable de (id, e, n, instants triés[, famille]) — position fixe (m) d'un garé.
    `seen_as_two` : paires {a, b} vues comme deux boîtes d'une même image. Rend [(a, b, distance, nature)]
    pour chaque paire à moins de `twin_m`."""
    objs = list(objects)
    two = {frozenset(p) for p in seen_as_two}
    out = []
    for i in range(len(objs)):
        a = objs[i]
        for j in range(i + 1, len(objs)):
            b = objs[j]
            d = math.hypot(a[1] - b[1], a[2] - b[2])
            if d >= twin_m or not a[3] or not b[3]:
                continue
            kind = twin_pair_kind(a[3], b[3], frozenset((a[0], b[0])) in two, **kind_kw)
            out.append((a[0], b[0], d, kind))
    return out


def twin_pair_counts(pairs):
    """Bilan d'une liste de `parked_twin_pairs` : {'pairs', 'suspects', <nature>: nombre…}."""
    by_kind = Counter(p[3] for p in pairs)
    return dict(by_kind, pairs=len(pairs), suspects=sum(by_kind[k] for k in SUSPECT_KINDS))


def parked_twin_groups(objects, seen_as_two=(), *, twin_m=TWIN_M, **kind_kw):
    """`objects` : itérable de (id, e, n, instants triés, famille). Réunit les suspects (cf. module) ; rend
    {id: racine} pour chaque garé ABSORBÉ (la racine n'y figure pas)."""
    objs = {o[0]: o for o in objects}
    suspect = {frozenset((a, b)) for a, b, _d, kind in parked_twin_pairs(objs.values(), seen_as_two,
                                                                       twin_m=twin_m, **kind_kw)
               if kind in SUSPECT_KINDS and objs[a][4] == objs[b][4]}
    groups, out = [], {}             # [racine, [membres]]
    for oid, e, n, _times, _fam in sorted(objs.values(), key=lambda o: (-len(o[3]), str(o[0]))):
        best, best_d = None, None
        for g in groups:
            if not all(frozenset((oid, m)) in suspect for m in g[1]):
                continue
            d = min(math.hypot(objs[m][1] - e, objs[m][2] - n) for m in g[1])
            if best_d is None or d < best_d:
                best, best_d = g, d
        if best is None:
            groups.append([oid, [oid]])
            continue
        best[1].append(oid)
        out[oid] = best[0]
    return out


def _objects_from_observations(df):
    """Une ligne par observation (`id`, `t`, `e`, `n`, `family`) → objets (id, e médian, n médian, instants)."""
    objs = []
    for oid, rows in df.groupby('id', sort=False):
        es, ns = sorted(rows['e']), sorted(rows['n'])
        objs.append((oid, es[len(es) // 2], ns[len(ns) // 2], sorted(rows['t']), rows['family'].mode().iloc[0]))
    return objs


def parked_twin_frame(observations: TypedFrame, *, twin_m=TWIN_M) -> TypedFrame:
    """Wrapper FunctionSpec : une ligne par observation d'un garé → (id absorbé, racine) ; le bilan des
    paires par nature est dans meta."""
    import pandas as pd
    objs = _objects_from_observations(observations.df)
    res = parked_twin_groups(objs, twin_m=twin_m)
    return TypedFrame(pd.DataFrame([{'id': k, 'root': v} for k, v in res.items()], columns=['id', 'root']),
                      DataType.TABLE, meta=twin_pair_counts(parked_twin_pairs(objs, twin_m=twin_m)))


SPEC = register(FunctionSpec(
    key='parked_twin_groups',
    name='Garés en double',
    description="Classe les paires de garés à moins de 2 m — vus ensemble dans une image (deux voitures), "
                "jamais vus au même passage (observations les plus proches à plus d'une minute), ou suspects : "
                "vus au même instant par deux caméras, ou au même passage sans jamais d'image commune — et "
                "réunit les suspects de même famille. Chaque "
                "membre d'un groupe est un suspect de tous les autres : une file de garés ne s'enchaîne pas.",
    category=FunctionCategory.TRANSFORM,
    tags=['tracking', 'parked', 'duplicates', 'fusion'],
    inputs=[
        PortSpec('observations', DataType.TABLE, required_fields=['id', 't', 'e', 'n', 'family'],
                 description="Une ligne par observation d'un garé : identifiant, instant (s), position (m), "
                             "famille."),
    ],
    outputs=[
        PortSpec('groups', DataType.TABLE, produced_fields=['id', 'root'],
                 description="Garés absorbés et leur racine (le plus observé) ; le bilan des paires par "
                             "nature est dans meta."),
    ],
    params=[
        ParamSpec('twin_m', 'float', TWIN_M, 0.5, 5.0, unit='m',
                  description="Distance maximale entre deux positions fixes pour juger une paire."),
    ],
    cost={'cpu_bound': True},
    fn=parked_twin_frame,
))
