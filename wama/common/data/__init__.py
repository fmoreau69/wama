"""
WAMA Data — fonctions de traitement comme cards génériques déclarées par capacités.

Voir `WAMA_DATA_FUNCTION_CARDS.md` (racine repo) pour le design complet.

- `data_types`      : taxonomie des types de donnée (geo_track, timeseries, events…) + TypedFrame.
- `function_catalog`: FunctionSpec/PortSpec/ParamSpec + registre + validation de connexion.
- `functions/`      : implémentations capability-first (conduite : map-matching, freinage, sections…).

Importer `wama.common.data.functions` enregistre toutes les fonctions dans le catalogue.
"""
