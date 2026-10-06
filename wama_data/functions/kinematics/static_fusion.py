"""« Pose longue » des objets IMMOBILES : réunir les fragments de suivi d'un même objet garé.

Pourquoi (Fabien, 2026-10-06) : *« les garés peuvent se gérer complètement par moyennage de l'ensemble de
leurs positions et cap — comme un temps de pose long en photographie pour les garés, un temps normal pour
les autres ; avec un filtrage hors voies »*. Un suivi image par image COUPE un objet immobile en fragments
(sorties de champ, relais entre caméras, détections manquées) ; chaque fragment, trop bref, n'est pas
reconnu garé, ou devient un garé de plus au même endroit. Un objet immobile, lui, ne bouge pas : tous ses
fragments ont la même position, quel que soit le moment ou la caméra. On les réunit avant de juger, et la
position et le cap de l'objet se prennent sur TOUTES ses observations.

Règles (fonction pure, l'appelant choisit les candidats — hors voies, ne roulant pas) :
  · deux fragments se réunissent si leurs positions sont à moins de `link_m` et leurs familles égales ;
  · jamais deux fragments qu'une même caméra a vus EN MÊME TEMPS comme deux boîtes distinctes (`conflicts`) ;
  · chaque fragment est jugé contre la position du GROUPE (moyenne pondérée par les observations), pas
    contre un seul membre : sinon une file de garés à 5 m s'enchaînerait de proche en proche ;
  · les fragments les plus observés fondent les groupes (ordre décroissant), la racine est le plus observé.
"""
from __future__ import annotations

import math

from wama.common.catalog.data_types import DataType, TypedFrame
from wama.common.catalog.function_catalog import (FunctionSpec, PortSpec, ParamSpec,
                                                  FunctionCategory, register)

#: Deux fragments d'un même garé : leurs positions médianes sont à moins de cette distance (m). Deux garés
#: voisins sont à ≈ 2,3 m centre à centre de profil, ≈ 5 m en file.
LINK_M = 1.5


def long_exposure_groups(fragments, conflicts=(), *, link_m=LINK_M):
    """`fragments` : itérable de (id, e, n, n_obs, famille) — position (m) d'un fragment immobile, nombre de
    ses observations, famille (`four_wheel`, `two_wheel`…). `conflicts` : paires {a, b} jamais réunies.
    Rend {id: racine} pour chaque fragment ABSORBÉ (la racine n'y figure pas)."""
    conflict = {frozenset(p) for p in conflicts}
    groups = []          # [racine, famille, Σe·w, Σn·w, Σw, membres]
    out = {}
    for fid, e, n, n_obs, fam in sorted(fragments, key=lambda f: (-f[3], str(f[0]))):
        w = max(float(n_obs), 1.0)
        best, best_d = None, None
        for g in groups:
            if g[1] != fam:
                continue
            d = math.hypot(g[2] / g[4] - e, g[3] / g[4] - n)
            if d > link_m or (best_d is not None and d >= best_d):
                continue
            if any(frozenset((fid, m)) in conflict for m in g[5]):
                continue
            best, best_d = g, d
        if best is None:
            groups.append([fid, fam, e * w, n * w, w, [fid]])
            continue
        best[2] += e * w
        best[3] += n * w
        best[4] += w
        best[5].append(fid)
        out[fid] = best[0]
    return out


def long_exposure_frame(fragments: TypedFrame, *, link_m=LINK_M) -> TypedFrame:
    """Wrapper FunctionSpec : une ligne par fragment (`id`, `e`, `n`, `n_obs`, `family`) → (id, racine)."""
    import pandas as pd
    df = fragments.df
    res = long_exposure_groups(zip(df['id'], df['e'], df['n'], df['n_obs'], df['family']), link_m=link_m)
    return TypedFrame(pd.DataFrame([{'id': k, 'root': v} for k, v in res.items()], columns=['id', 'root']),
                      DataType.TABLE)


SPEC = register(FunctionSpec(
    key='long_exposure_groups',
    name='Pose longue des immobiles',
    description="Réunit les fragments de suivi d'un même objet IMMOBILE (garé) : leurs positions coïncident "
                "à moins de 1,5 m, leur famille est la même, et aucune caméra ne les a vus ensemble comme deux "
                "objets. Chaque fragment est jugé contre le groupe entier — une file de garés ne s'enchaîne "
                "pas. La position et le cap d'un garé se prennent ensuite sur TOUTES ses observations.",
    category=FunctionCategory.TRANSFORM,
    tags=['tracking', 'parked', 'static', 'fusion'],
    inputs=[
        PortSpec('fragments', DataType.TABLE, required_fields=['id', 'e', 'n', 'n_obs', 'family'],
                 description="Une ligne par fragment immobile candidat : position médiane (m), nombre "
                             "d'observations, famille."),
    ],
    outputs=[
        PortSpec('groups', DataType.TABLE, produced_fields=['id', 'root'],
                 description="Fragments absorbés et leur racine (le plus observé du groupe)."),
    ],
    params=[
        ParamSpec('link_m', 'float', LINK_M, 0.2, 5.0, unit='m',
                  description="Distance maximale entre un fragment et la position de son groupe."),
    ],
    cost={'cpu_bound': True},
    fn=long_exposure_frame,
))
