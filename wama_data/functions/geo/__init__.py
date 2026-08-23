"""Fonctions géospatiales — référentiels publics et géométrie du terrain.

`ign_vector` : données VECTORIELLES IGN (BD TOPO) — emprises et hauteurs de bâtiments,
réseau routier — et masquage satellite qui en découle.

Règle du domaine : ce qu'un référentiel public publie en VECTEUR ne se détecte pas
visuellement (posée 2026-07-28 sur cam_analyzer, généralisable). La détection reste
réservée à ce qu'aucune base ne contient (marquages au sol, objets mobiles).

`spatial` : prédicats spatiaux réduits à des COLONNES DÉRIVÉES — la distance à un point devient
une colonne, et la chaîne conditionnelle existante fait le reste. Pas de « mode spatial » : voir
l'en-tête du module et `WAMA_DATA_WORLD.md §9septies`.
"""
from . import ign_vector  # noqa: F401
from . import spatial     # noqa: F401
