"""Fusion d'ESTIMATIONS — combiner N sorties qui estiment la même grandeur (2026-09-09).

Domaine transverse : ce qu'une fonction estime est déclaré sur son port de sortie (facette
`estimates` / `uncertainty` / `derived_from` de `PortSpec`) ; ce module est le premier
CONSOMMATEUR de cette facette. Voir `CAM_ANALYZER_CHAINE_TRAITEMENT.md §INVENTAIRE E`.
"""
from . import estimates  # noqa: F401
