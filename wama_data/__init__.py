"""
WAMA Data — le monde des DONNÉES.

Troisième racine du dépôt, à côté de `wama/` (Médias + substrat transversal) et `wama_lab/`
(applications métier de recherche). Cette structure traduit en arborescence la doctrine des MONDES
actée le 2026-07-20 (`docs/WAMA_VISION_COMPLET.md §Les quatre mondes`) : **un monde n'est pas un
sous-dossier du substrat**. Le sous-système a vécu sous `wama/common/data/` jusqu'au 2026-08-22 ;
il en est sorti dès qu'il a cessé d'être quelques fonctions pour devenir une chaîne de traitement.

CE QUI EST ICI (le monde) / CE QUI N'Y EST PAS (le contrat)
    Le registre de fonctions et la taxonomie de types sont restés dans `wama/common/catalog/` :
    ils sont la **glu entre les mondes**, pas une pièce de celui-ci — le Lab y déclare ses propres
    fonctions. Voir l'entête de ce paquet pour le raisonnement complet.

STRUCTURE
    core/       le moteur, sans Django ni UI : référentiel temporel, segmentation, codage
    sources/    l'importer universel — un registre de lecteurs, aucun format privilégié
    functions/  la bibliothèque déclarée au catalogue commun (io, geometry, kinematics,
                driving, geo, temporal)
    modules.py  registre DÉCLARATIF des modules + MESURE de leur avancement (rendue dans
                `WAMA_DATA_WORLD.md §0` par `doc_facts`) — on ne déclare pas l'état, on le mesure

L'enregistrement au catalogue se fait dans `apps.py:ready()` — chaque monde déclare ses propres
fonctions, le registre n'a pas à connaître ses producteurs.

Documents de référence : `WAMA_DATA_WORLD.md` (le monde, ses modules, les décisions) et
`WAMA_DATA_FUNCTION_CARDS.md` (le catalogue de fonctions comme cards).
"""

default_app_config = 'wama_data.apps.WamaDataConfig'
