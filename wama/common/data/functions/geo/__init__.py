"""Fonctions géospatiales — référentiels publics et géométrie du terrain.

`ign_vector` : données VECTORIELLES IGN (BD TOPO) — emprises et hauteurs de bâtiments,
réseau routier — et masquage satellite qui en découle.

Règle du domaine : ce qu'un référentiel public publie en VECTEUR ne se détecte pas
visuellement (posée 2026-07-28 sur cam_analyzer, généralisable). La détection reste
réservée à ce qu'aucune base ne contient (marquages au sol, objets mobiles).
"""
from . import ign_vector  # noqa: F401
