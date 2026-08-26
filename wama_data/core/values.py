"""
Absence de valeur — la primitive partagée par tout le cœur de WAMA Data.

POURQUOI UN MODULE POUR SIX LIGNES

    `missing()` vivait dans la couche d'adaptation (`functions/temporal/segmentation.py`), parce
    que c'est là que le piège s'était présenté trois fois. Le Calculator en fait le QUATRIÈME
    consommateur — et lui est dans `core/`, qui ne doit pas dépendre de `functions/` (le cœur est
    pur et testable sans pandas ; l'inversion aurait rendu `core` dépendant de sa propre façade).

    Deux issues : recopier la fonction — interdit, c'est la règle première du dépôt — ou la
    remonter là où les deux couches peuvent la lire. C'est le second. `functions/temporal/
    segmentation.py` la RÉEXPORTE, donc ses importateurs existants ne changent pas d'une ligne.

⚠ CE N'EST PAS UN MODULE « UTILS ». Il porte UNE notion : qu'est-ce qu'une valeur absente. Si
    une deuxième notion sans rapport devait y atterrir, c'est qu'elle a son propre domicile
    ailleurs.
"""
from __future__ import annotations

import math


def missing(value) -> bool:
    """Une valeur ABSENTE au sens d'un cadre pandas — `None` **ou** `NaN`.

    ⚠ Le piège est systématique à la frontière avec pandas, et il s'est présenté TROIS fois dans
    la seule couche d'adaptation : une fin de segment inconnue devient `NaN` à l'aller, et une
    colonne qui ne concerne que certaines lignes est remplie de `NaN` sur les autres. Or `NaN`
    n'est ni `None` ni faux : il traverse tous les tests d'absence naïfs et ressort en donnée.
    D'où UNE fonction, utilisée partout où l'on relit un cadre — plutôt qu'une rustine par champ.

    ⚠ `0` et `''` sont des VALEURS. Les confondre avec une absence est l'erreur symétrique, et
    elle est pire : elle fait disparaître des mesures légitimes.
    """
    if value is None:
        return True
    return isinstance(value, float) and math.isnan(value)


def present(values) -> list:
    """Les valeurs réellement mesurées, dans l'ordre. Le complément naturel de `missing`.

    Rendre la liste filtrée plutôt que de tester au cas par cas évite l'oubli d'un `missing()`
    dans une agrégation — c'est exactement ce que le Calculator fait à chaque statistique.
    """
    return [v for v in values if not missing(v)]
