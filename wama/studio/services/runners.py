"""
Studio — résolution des runners d'exécution.

Historique : ce fichier était le « shim V1 » (10 adapters manuels écrits avant le
recadrage « contrat uniforme » du 2026-07-12, cf. STUDIO_VISION principe directeur +
mémoire feedback_studio_uniform_contract). Il a été VIDÉ app par app au fil de la
normalisation des triades tool_api (item_id, clés canoniques du detail, pointeurs
params.py) — 10/10 le 2026-07-13. Il ne reste que la façade de résolution : TOUTE la
logique vit dans generic_runner.py, piloté par le manifeste GENERIC_APPS.

Ajouter une app exécutable = remplir son contrat (triade normalisée + detail canonique
+ params.py) puis quelques lignes de manifeste dans generic_runner.GENERIC_APPS.
"""
from __future__ import annotations

_GENERIC_CACHE = {}


def runner_for(app_id: str):
    from .generic_runner import GENERIC_APPS, build_generic_runner
    if app_id in GENERIC_APPS:
        if app_id not in _GENERIC_CACHE:
            _GENERIC_CACHE[app_id] = build_generic_runner(app_id)
        return _GENERIC_CACHE[app_id]
    return None
