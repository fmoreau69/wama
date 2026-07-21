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
    option_groups: Optional[List[Tuple[str, List[Tuple[str, str]]]]] = None
                                                # select GROUPÉ (optgroup) : [(libellé_groupe, [(value, label)])]
                                                # ex. voix : [("Voix par défaut", [...]), ("Mes voix", [...])]
    min: Optional[float] = None
    max: Optional[float] = None
    step: Optional[float] = None
    unit: str = ""                              # suffixe d'affichage de la valeur d'un range (ex. "s")
    min_label: str = ""                         # libellés FORMATÉS des bornes du range (ex. "10s"/"10min")
    max_label: str = ""                         #   — priment sur min/max bruts à l'affichage (P2-bis)
    contexts: Tuple[str, ...] = ALL_CONTEXTS
    options_source: Optional[str] = None        # clé d'options dynamiques (ex. "backends")
    show_if: Any = None                         # visibilité conditionnelle. string = nom d'un champ
                                                # (visible si « truthy » : toggle coché / valeur non vide).
                                                # dict = condition par VALEUR : {"field": "media_type",
                                                # "in": ["video","image"]} ou {"field": "use_sam3",
                                                # "equals": True}. Réévalué au change de n'importe quel champ.
    advanced: bool = False                      # repliable sous « Avancé »
    help_source: Optional[str] = None           # select de MODÈLE : source catalogue (model_manager)
                                                 # → WamaParams affiche desc courte/longue + VRAM sous le select
    help_fallback: Optional[dict] = None         # {valeur_option: texte} pour backends HORS catalogue
                                                 # (ex. moteurs ASR/OCR maison) — repli si help_source absent/vide
    chip: bool = False                          # CARD_DESIGN §10.3 : le champ produit un CHIP méta sur la
                                                # card (état concis) — valeur courte (label d'option si
                                                # select), icône du schéma. Rendu : common/utils/card_chips.py.

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


def _pget(p, key, default=None):
    """Accès uniforme à un champ de schéma, que `p` soit un Param ou un dict (schema_to_dicts)."""
    return p.get(key, default) if isinstance(p, dict) else getattr(p, key, default)


def coerce_params(schema, data, caps=None):
    """Borne UNIQUE des paramètres numériques = le SCHÉMA (`params.py`). Source de vérité serveur.

    Remplace les clamps hardcodés `max(min_, min(max_, x))` disséminés dans les vues/tâches
    (≈28 sites, cf. PROJECT_STATUS §21bis) : la borne n'est plus copiée, elle est LUE du schéma
    déjà affiché côté client → plus de dérive possible entre le slider et la validation serveur.

    schema : itérable de `Param` (ou de dicts issus de `schema_to_dicts`).
    data   : mapping nom→valeur brute (ex. `request.POST`, ou un simple dict).
    caps   : optionnel {nom: max_dynamique} — plafonne DAVANTAGE la borne haute d'un range/number
             selon une capacité runtime (ex. `duration` ← `max_duration` du modèle choisi). Un cap
             ne peut que RESSERRER la borne du schéma, jamais l'élargir.

    Retourne {nom: valeur_coercée} pour chaque paramètre numérique (`range`/`number`) du schéma :
    valeur absente/illisible → `default` du schéma ; sinon clampée à [min, min(max, cap)].
    Les paramètres non numériques (select/toggle/text…) sont ignorés — le caller les valide à part.
    """
    caps = caps or {}
    out = {}
    for p in schema:
        if _pget(p, 'type') not in ('range', 'number'):
            continue
        name = _pget(p, 'name')
        lo = _pget(p, 'min')
        hi = _pget(p, 'max')
        cap = caps.get(name)
        if cap is not None:
            hi = cap if hi is None else min(hi, cap)
        raw = data.get(name) if hasattr(data, 'get') else None
        try:
            val = float(raw)
        except (TypeError, ValueError):
            dflt = _pget(p, 'default')
            val = float(dflt) if dflt is not None else (float(lo) if lo is not None else 0.0)
        if lo is not None:
            val = max(float(lo), val)
        if hi is not None:
            val = min(float(hi), val)
        out[name] = val
    return out
