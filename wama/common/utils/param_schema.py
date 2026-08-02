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
    chip_label: str = ""                        # Libellé COURT du chip, quand le label du réglage est trop
                                                # long pour une card ("Diarisation" pour « Identifier les
                                                # locuteurs »). Vide = on reprend `label`. Le label complet
                                                # reste dans le title, donc rien n'est perdu.
    section: str = "settings"                   # CARD_DESIGN §11 : SECTION de la card v3 où le chip atterrit
                                                # ("settings" par défaut, "output" pour un champ qui décrit ce
                                                # qui va SORTIR — ex. format de sortie). Déclaré à la source :
                                                # ni la vue ni le template ne trient les chips.

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


# ── Accès au schéma d'une app (accesseur UNIQUE, facette F3) ─────────────────
def schema_for_app(app_id: str) -> List[dict]:
    """
    Schéma de params d'une app, résolu depuis le REGISTRE (`wama/<app>/params.py`).

    Accesseur UNIQUE de la facette F3 — pendant de `app_capabilities()` (F2 capacités) et de
    `studio_node_ports()` (F2 ports). Consommateurs : runner studio, surface outils
    (`tool_api.sanitize_tool_args`). Évite que chaque consommateur recopie la résolution.

    Résolution : pointeur DÉCLARATIF `GENERIC_APPS[app_id]` (`params_module`/`params_attr`),
    sinon convention `wama.<app_id>.params.PARAMS_JSON`. Aucun nom de module en dur.

    Retourne [] si l'app n'en déclare pas — l'appelant ne doit pas s'en trouver bloqué.

    ⚠ Une app à plusieurs domaines (imager image/vidéo, enhancer média/audio) n'expose ici que
    son attribut PRINCIPAL : c'est ce que `params_attr` déclare aujourd'hui, pas une limite de
    cette fonction. Le jour où le pointeur devient multiple, il ne bouge qu'ICI.
    """
    import importlib
    module_name = attr = None
    try:
        from wama.studio.services.generic_runner import GENERIC_APPS
        conf = GENERIC_APPS.get(app_id) or {}
        module_name, attr = conf.get('params_module'), conf.get('params_attr')
    except Exception:
        pass
    if not module_name:
        module_name, attr = f'wama.{app_id}.params', 'PARAMS_JSON'
    try:
        return list(getattr(importlib.import_module(module_name), attr, []) or [])
    except Exception:
        return []


def schema_model_kwargs(app_id: str, params: dict) -> dict:
    """
    Sous-ensemble de `params` qui est À LA FOIS déclaré au schéma de l'app ET un champ
    concret de son modèle — prêt à passer à `Model.objects.create(**…)`.

    Sert à ce qu'un outil `add_to_<app>` accepte TOUT ce que le schéma expose à l'UI, sans
    recopier la liste des champs dans sa signature (elle dériverait au prochain param ajouté).
    Le schéma étant lui-même dérivé du modèle (`derive_from_model`), la correspondance est la
    règle ; les params « transitoires UI » (déclarés par override, sans champ) sont écartés
    ici et restent à la charge de l'outil qui sait quoi en faire.

    Les valeurs sont coercées par le schéma (bornes + booléens) avant d'être rendues.
    """
    schema = schema_for_app(app_id)
    if not schema or not params:
        return {}
    try:
        from wama.common.utils.detail_registry import DetailRegistry
        entry = DetailRegistry.get(app_id)
        model = entry['model'] if entry else None
    except Exception:
        model = None
    if model is None:
        return {}
    concrete = {f.name for f in model._meta.get_fields() if getattr(f, 'concrete', False)}
    declared = {_pget(p, 'name') for p in schema}
    coerced = coerce_schema_values(schema, params)
    return {k: v for k, v in coerced.items() if k in declared and k in concrete}


def schema_extra_params(app_id: str, params: dict) -> dict:
    """
    Symétrique de `schema_model_kwargs` : les params DÉCLARÉS au schéma qui ne sont PAS des
    champs du modèle — les « réglages transitoires » que l'app range dans un champ JSON
    (`ConversionJob.options`, par ex.).

    Évite de re-lister ces clés à la main chez chaque appelant : la liste vit au schéma.
    """
    schema = schema_for_app(app_id)
    if not schema or not params:
        return {}
    model_keys = set(schema_model_kwargs(app_id, params))
    coerced = coerce_schema_values(schema, params)
    return {k: v for k, v in coerced.items() if k not in model_keys}


def schema_arg_names(app_id: str) -> set:
    """Noms de params qu'une app DÉCLARE — surface d'arguments acceptable d'un outil `**params`."""
    return {_pget(p, 'name') for p in schema_for_app(app_id)}


_TRUTHY = ('1', 'true', 'on', 'oui', 'yes')


def coerce_schema_values(schema, data, only_present: bool = True) -> dict:
    """
    Coercition COMPLÈTE d'un mapping selon le schéma : types (booléens) + bornes (numériques).

    COMPLÈTE `coerce_params()` sans la ré-implémenter : les bornes restent calculées par elle
    (la « borne unique » du schéma), on n'ajoute ici que le typage des toggles et le passage
    des autres champs. Remplace le `_coerce()` local du runner studio, qui convertissait les
    types SANS appliquer les bornes — le studio échappait donc au clamp serveur.

    only_present=True (défaut) : ne retourne QUE les clés réellement fournies. C'est ce qu'il
    faut pour un appel d'outil, où une clé absente doit laisser jouer le défaut de la fonction
    Python — à l'inverse d'un POST de formulaire, où `coerce_params` réinjecte le défaut du
    schéma pour tous les numériques.
    """
    get = data.get if hasattr(data, 'get') else (lambda k, d=None: d)
    numeric = coerce_params(schema, data)
    out = {}
    for p in schema:
        name, ptype = _pget(p, 'name'), _pget(p, 'type')
        raw = get(name)
        # `''` = champ de formulaire laissé vide = NON FOURNI. Sans ça, un `resize_w=''` posté
        # par un <input number> vide serait clampé au minimum du schéma (0) au lieu d'être
        # ignoré, et écraserait la valeur par défaut du traitement.
        if only_present and (raw is None or raw == ''):
            continue
        if ptype in ('range', 'number'):
            val = numeric.get(name)
            if val is not None and float(val).is_integer():
                val = int(val)          # 3.0 → 3 : les champs entiers n'aiment pas les floats
            out[name] = val
        elif ptype == 'toggle':
            out[name] = raw if isinstance(raw, bool) else str(raw).strip().lower() in _TRUTHY
        else:
            out[name] = raw
    return out
