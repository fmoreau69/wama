"""Lire la DÉCLARATION d'un modèle sans importer l'app qui la porte.

POURQUOI (étape 2 du plan Fabien, 2026-09-06) : six backends importaient le `model_config` de
leur propre app. Tant que le backend vit dans l'app, c'est anodin ; le jour où il rejoint le
substrat transversal, c'est **le commun qui importerait une app** — inversion de couche
interdite. Ce module est le passe-plat : il applique la CONVENTION, il ne connaît aucune app.

    `wama/<app>/utils/model_config.py` expose `<APP>_MODELS`, dict indexé par `model_id`.

C'est la même convention que `model_registry._overlay_declared_engines` : elle est donc
VÉRIFIÉE par l'usage, pas supposée. Une app qui ne la suit pas est simplement introuvable —
on ne devine pas un second emplacement.

⚠ POURQUOI PAS LE CATALOGUE (`AIModel`). C'était mon idée première, et elle était FAUSSE :
lire le catalogue ajouterait une dépendance ORM à chaque backend, alors que c'est précisément
leur absence de Django qui les rend déplaçables (les backends du describer portent
« signature ORM-free » dans leur en-tête). On lirait la bonne donnée en cassant la propriété
qu'on cherche à préserver. *Un backend ne doit pas avoir besoin d'une base pour charger des
poids.*

⚠ CE MODULE NE RÉSOUT PAS LES CHEMINS DE POIDS. Ceux-là viennent de `settings.MODEL_PATHS`,
qui est déjà commun — un backend le lit directement, sans passer par l'app. La distinction
compte : un chemin est une donnée d'INSTALLATION, une déclaration est une donnée de MODÈLE.
"""
from __future__ import annotations

import importlib
import logging
from typing import Optional

logger = logging.getLogger(__name__)


def declaration(source: str, model_id: str) -> Optional[dict]:
    """Déclaration de `model_id` telle que l'app `source` la porte, ou None.

    Args:
        source   : nom d'app (`composer`, `describer`…) — le préfixe de `model_key`.
        model_id : identifiant du modèle dans le dict de l'app (le segment d'après).

    None quand l'app n'existe pas, ne suit pas la convention, ou ne déclare pas ce modèle.
    Les trois se valent pour l'appelant : il n'a pas de déclaration, et c'est tout ce qu'il
    a besoin de savoir pour lever une erreur claire.
    """
    if not source or not model_id:
        return None
    try:
        module = importlib.import_module(f'wama.{source}.utils.model_config')
    except Exception as e:
        logger.debug('[declarations] %s sans model_config : %s', source, e)
        return None
    declarations = getattr(module, f'{source.upper()}_MODELS', None)
    if not isinstance(declarations, dict):
        return None
    valeur = declarations.get(model_id)
    return valeur if isinstance(valeur, dict) else None


# ⚠ Une commodité `declaration_for(model_key)` a vécu ici le 2026-09-06 — elle découpait la clé
# de catalogue puis appelait `declaration()`. AUCUN appelant : les backends connaissent leur app
# et leur `model_id`, ils n'ont pas de `model_key` sous la main. Retirée le 07/09.
# *Une commodité sans appelant n'est pas une API, c'est une seconde façon de faire qui attend
# son premier utilisateur pour diverger.*
