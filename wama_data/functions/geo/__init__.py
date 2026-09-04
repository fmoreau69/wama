"""Fonctions géospatiales — référentiels publics et géométrie du terrain.

`ign_vector` : données VECTORIELLES IGN (BD TOPO) — emprises et hauteurs de bâtiments,
réseau routier — et masquage satellite qui en découle.

`osm_vector` : données VECTORIELLES OpenStreetMap (Overpass) — nœuds de CONTRÔLE (stop,
cédez-le-passage, feux, passages piétons, giratoires) et réseau carrossable mondial.

Règle du domaine : ce qu'un référentiel public publie en VECTEUR ne se détecte pas
visuellement (posée 2026-07-28 sur cam_analyzer, généralisable). La détection reste
réservée à ce qu'aucune base ne contient (marquages au sol, objets mobiles).

Les deux référentiels ne se doublonnent pas, ils se complètent : l'IGN est autoritatif sur
la GÉOMÉTRIE (décimètre, largeurs, hauteurs), OSM est seul à porter la SÉMANTIQUE de
circulation (priorité, sens unique, vitesse limite, nombre de voies) et à couvrir
l'étranger. ⚠ Leurs conventions d'axes sont OPPOSÉES — chaque module documente la sienne.

`spatial` : prédicats spatiaux réduits à des COLONNES DÉRIVÉES — la distance à un point devient
une colonne, et la chaîne conditionnelle existante fait le reste. Pas de « mode spatial » : voir
l'en-tête du module et `WAMA_DATA_WORLD.md §9septies`.
"""
from . import ign_vector  # noqa: F401
from . import osm_vector  # noqa: F401
from . import spatial     # noqa: F401
