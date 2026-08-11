"""
Gabarits de CODE-GEN depuis le manifeste (marche A de la route §10.3).

Un gabarit couvre le squelette CONVENTIONNEL d'une cible (la convention est MESURÉE — cadrage
A0 de la route, balayage 6 cibles × 10 apps), les trous étant alimentés par le manifeste ; les
écarts légitimes d'une app sont DÉCLARÉS dans la facette concernée, jamais codés dans le
gabarit. Les corps de backends (glu d'usage des librairies) restent hors périmètre (marche B).

Modules :
  - `urls_gen`   : gabarit `urls.py` (palier A1) — ROUTE_TABLE conventionnelle + `extra_routes`
Mêmes contrats que le moteur commun de write-back (builtin/app.py §10.3) : fichiers générés
marqués `[manifest-gen]`, dry-run/idempotent/réversible, garde `compile()`, un fichier écrit
main n'est JAMAIS réécrit (comparaison sémantique seulement).
"""
