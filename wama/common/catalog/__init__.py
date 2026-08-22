"""
Le CONTRAT inter-mondes : la taxonomie de types et le registre de fonctions.

POURQUOI CE PAQUET EST DANS `common/` ET NON DANS `wama_data/` (décision Fabien, 2026-08-22)

    La doctrine des MONDES (`docs/VISION_STATUS.md §Architecture en MONDES`, actée le 2026-07-20)
    dit que **la glu entre les mondes est le système de capacités/ports typés**. Ce paquet EST
    cette glu — il n'appartient donc à aucun monde en particulier.

    Ce n'est pas une lecture de la doctrine, c'est un fait mesuré : `wama_lab/cam_analyzer/
    function_specs.py` déclare des fonctions du monde **Lab** dans ce registre, et les manifestes
    `function` / `dataset` du substrat en dépendent aussi. Loger le registre dans `wama_data`
    forcerait le Lab et les manifestes à dépendre du monde **Data** pour un mécanisme qui ne lui
    appartient pas — l'inverse exact de ce que la séparation cherche à obtenir.

    Le corollaire pratique se vérifie : au déport de WAMA Data hors de `common/`, ce choix a laissé
    `function_specs.py` **inchangé** et réduit la réécriture dans cam_analyzer à 8 imports.

  - `data_types`      : types de donnée (geo_track, timeseries, events, segments…), relation
                        « est-un », champs canoniques, `TypedFrame`.
  - `function_catalog` : `FunctionSpec` / `PortSpec` / `ParamSpec`, registre, validation de
                        connexion entre deux ports.

Les IMPLÉMENTATIONS vivent dans les mondes : `wama_data/functions/` (Data),
`wama_lab/cam_analyzer/function_specs.py` (Lab).
"""
