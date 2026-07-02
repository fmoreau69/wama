"""
Garde-fou anti-dérive des enums `ModelSource`/`ModelType` (REMOVAL_LEDGER F5).

Il existe DEUX familles d'enums pour la même notion, pour une raison technique :
  • `services/model_registry.py` : `Enum` PUR (sans dépendance Django) — utilisé par la découverte
    (`ModelInfo.source/model_type`) et ré-exporté via `services/__init__` (views, sync…).
  • `models.py` : `models.TextChoices` — pilote le CHAMP DB `AIModel.source/model_type` (choices/admin).
    Ses membres doivent rester des littéraux statiques (déterminisme des migrations Django) → on ne
    peut pas les générer dynamiquement depuis l'enum du registre.

Plutôt qu'un merge structurel risqué (imports ré-exportés + migrations), on GARANTIT le contrat qui
compte : **tout ce que la découverte peut émettre doit être un choix VALIDE en base**
(`registre ⊆ DB`). La DB a des sources EN PLUS, légitimes et propres au stockage (le registre de
découverte ne couvre QUE les modèles des apps WAMA) :
  • `huggingface` : défaut du PROSPECTEUR pour un modèle auto-proposé sans app assignée
    (`management/commands/prospect_models.py`) ;
  • `custom` : ajouts manuels.
(Vérifié 2026-07-01 : 0 ligne `huggingface`/`custom` en base actuellement — membres réservés à ces
flux. NB : à ne pas confondre avec le *répertoire* de cache `AI-models/cache/huggingface/` gardé pour
les dépendances des modèles, qui est autre chose.)
C'est exactement le bug F2 (la découverte écrivait `composer`/`reader` absents des choices) que ce
check aurait attrapé au démarrage.

Sévérité = Warning (visible à chaque `manage.py check`/démarrage) sans bloquer WAMA-Lab.
"""
from __future__ import annotations

from django.core.checks import Warning as DjangoWarning, register, Tags


def _values(enum_cls) -> set:
    return {member.value for member in enum_cls}


@register(Tags.models)
def check_model_enums_in_sync(app_configs, **kwargs):
    """registre ⊆ DB pour ModelSource ET ModelType (sinon des modèles découverts seraient hors-enum)."""
    errors = []
    try:
        from wama.model_manager.models import ModelSource as DBSource, ModelType as DBType
        from wama.model_manager.services.model_registry import (
            ModelSource as RegSource, ModelType as RegType,
        )
    except Exception:
        # Import impossible (ex. check très tôt) : ne pas faire échouer le check lui-même.
        return errors

    for label, reg, db, hint in (
        ('ModelSource', RegSource, DBSource, "wama/model_manager/models.py::ModelSource"),
        ('ModelType', RegType, DBType, "wama/model_manager/models.py::ModelType"),
    ):
        missing = _values(reg) - _values(db)
        if missing:
            errors.append(DjangoWarning(
                f"{label} : la découverte peut émettre {sorted(missing)} — absent(s) des choices DB.",
                hint=f"Ajouter ces membres dans {hint} (migration) pour éviter des entrées hors-enum "
                     f"(cf. REMOVAL_LEDGER F5, régression type F2).",
                id='model_manager.W001',
            ))
    return errors
