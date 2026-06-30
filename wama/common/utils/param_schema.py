"""
Schéma de paramètres WAMA — source unique pour rendre les réglages d'une app dans
TOUTES les surfaces (modale item/batch, volet inspecteur card/batch/file) depuis une
seule description, au lieu de markup dupliqué par template (cause des divergences).

Principe (cf. ROADMAP §2) : la **structure** des champs est DÉRIVÉE du modèle Django
(type, choices, default, help_text, verbose_name) — pas de hardcode — et une surcouche
UI minimale (`overrides`) ajoute ce que le modèle ne connaît pas : contextes d'affichage,
source d'options dynamiques (ex. endpoint backends), visibilité conditionnelle, basique/avancé.

Le rendu (JS/Django) consommera `Param.to_dict()` ; ce module reste pur (aucun rendu ici).
"""

from dataclasses import dataclass, field, asdict
from typing import Any, List, Optional, Tuple

# Contextes de rendu d'un paramètre :
#   item   = modale « Paramètres » d'un élément
#   batch  = modale « Paramètres » d'un batch
#   panel  = volet droit (inspecteur card/batch/file)
ALL_CONTEXTS = ("item", "batch", "panel")


@dataclass
class Param:
    """Description d'UN paramètre, indépendante de la surface de rendu."""
    name: str
    type: str                                   # toggle|select|radio|text|textarea|number|range
    label: str = ""
    icon: str = ""                              # classe FontAwesome optionnelle (ex. "fa-microchip")
    dom_id: Any = ""                            # pont de migration : ID DOM legacy (sinon wp-{ctx}-{name}).
                                                # str = toutes surfaces ; dict {ctx: id} = scopé par contexte
                                                # (ex. {"panel": "backendSelect", "item": "settingsBackend"}).
    radio_name: Any = ""                        # nom du groupe radio (str ou dict par contexte, comme dom_id)
    inline: bool = False                        # radios sur une seule ligne (form-check-inline)
    help: str = ""
    help_html: str = ""                         # aide en HTML brut (ex. lien « En savoir plus ») — prime sur help
    default: Any = None
    choices: Optional[List[Tuple[str, str]]] = None   # [(value, label)]
    min: Optional[float] = None
    max: Optional[float] = None
    step: Optional[float] = None
    contexts: Tuple[str, ...] = ALL_CONTEXTS
    options_source: Optional[str] = None        # clé d'options dynamiques (ex. "backends")
    show_if: Optional[str] = None               # nom d'un toggle qui conditionne l'affichage
    advanced: bool = False                      # repliable sous « Avancé »

    def to_dict(self) -> dict:
        return asdict(self)


# ── Dérivation depuis un modèle Django ───────────────────────────────────────
def _django_field_to_param(f) -> Param:
    """Mappe un champ de modèle Django vers un Param (structure uniquement)."""
    internal = f.get_internal_type()
    choices = list(f.choices) if getattr(f, 'choices', None) else None

    if choices:
        ptype = "select"
    elif internal == "BooleanField":
        ptype = "toggle"
    elif internal in ("IntegerField", "FloatField", "PositiveIntegerField", "DecimalField"):
        ptype = "number"
    elif internal == "TextField":
        ptype = "textarea"
    else:
        ptype = "text"

    # default : NOT_PROVIDED → None
    default = f.default
    try:
        from django.db.models.fields import NOT_PROVIDED
        if default is NOT_PROVIDED:
            default = None
    except Exception:
        pass
    if callable(default):
        default = None

    label = str(getattr(f, 'verbose_name', '') or f.name).strip()
    return Param(
        name=f.name,
        type=ptype,
        label=label[:1].upper() + label[1:] if label else f.name,
        help=str(getattr(f, 'help_text', '') or ''),
        default=default,
        choices=choices,
    )


def derive_from_model(model_class, include: List[str], overrides: dict = None) -> List[Param]:
    """
    Construit la liste de `Param` d'une app à partir des champs d'un modèle Django.

    Args:
        model_class : le modèle (ex. Transcript).
        include     : noms de champs à exposer, DANS L'ORDRE d'affichage.
        overrides   : { champ : {attr: valeur, …} } — surcouche UI (type, label, help,
                      contexts, options_source, show_if, advanced, min/max/step…).

    Returns:
        [Param] prêtes pour le rendu (cf. to_dict()).
    """
    overrides = overrides or {}
    meta = model_class._meta
    params: List[Param] = []
    for name in include:
        ov = dict(overrides.get(name, {}))
        try:
            p = _django_field_to_param(meta.get_field(name))
        except Exception:
            # Champ hors modèle (paramètre transitoire UI) : tout vient de l'override.
            p = Param(name=name, type=ov.pop('type', 'text'))
        for k, v in ov.items():
            setattr(p, k, v)
        params.append(p)
    return params


def schema_to_dicts(params: List[Param]) -> List[dict]:
    """Sérialise un schéma pour le front (JSON) / un template."""
    return [p.to_dict() for p in params]
