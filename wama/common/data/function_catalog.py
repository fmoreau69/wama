"""
Registre des FONCTIONS de traitement WAMA Data (analogue de `APP_CATALOG` côté apps).

Une fonction est entièrement décrite par son `FunctionSpec` : la card, ses ports et sa
modale de paramètres s'AUTO-GÉNÈRENT depuis ce descripteur (métadonnée-driven). Le
chaînage n'est valide que si les ports sont compatibles en type ET en champs requis.
Voir `WAMA_DATA_FUNCTION_CARDS.md`.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional

from .data_types import is_compatible


class FunctionCategory:
    """Ce que la fonction FAIT (pilote le regroupement UI + le type de sortie)."""
    TRANSFORM = 'transform'      # même type en sortie (nettoyage, lissage, reprojection)
    ENRICHER = 'enricher'        # ajoute des champs/colonnes à l'entrée
    DETECTOR = 'detector'        # produit des events
    INDICATOR = 'indicator'      # produit un scalaire / agrégat
    RESAMPLER = 'resampler'      # change l'échantillonnage
    JOIN = 'join'                # combine plusieurs entrées
    AGGREGATE = 'aggregate'      # agrège par groupe


@dataclass
class ParamSpec:
    """Un paramètre → un champ de la modale de réglages (auto-générée)."""
    key: str
    type: str = 'float'          # 'float' | 'int' | 'bool' | 'enum' | 'str'
    default: object = None
    min: Optional[float] = None
    max: Optional[float] = None
    choices: Optional[list] = None
    unit: str = ''
    description: str = ''


@dataclass
class PortSpec:
    """Un créneau d'entrée ou de sortie typé."""
    key: str
    data_type: str
    required_fields: list = field(default_factory=list)   # champs PRÉCIS exigés (entrée)
    produced_fields: list = field(default_factory=list)   # champs ajoutés/produits (sortie)
    cardinality: str = 'one'                              # 'one' | 'many'
    optional: bool = False
    description: str = ''


class Binding:
    """Comment la fonction se branche dans une chaîne."""
    PURE = 'pure'    # signature pure (données_typées, params) → données_typées : chaînable direct
    APP = 'app'      # couplée à une app (lit/écrit la session/BDD) : cataloguée, non encore pure
                     # → à porter vers PURE quand on la rend chaînable (adaptateur de ports)


@dataclass
class FunctionSpec:
    """Descripteur complet d'une fonction de traitement."""
    key: str
    name: str
    description: str
    category: str
    fn: Callable = None          # None si app-bound déclarée par référence (voir `impl`)
    binding: str = Binding.PURE
    impl: str = ''               # chemin d'implémentation (app-bound), ex. "cam_analyzer.tasks:compute_distance_task"
    app: str = ''                # app propriétaire si binding=app, ex. "cam_analyzer"
    tags: list = field(default_factory=list)
    inputs: list = field(default_factory=list)     # [PortSpec]
    outputs: list = field(default_factory=list)    # [PortSpec]
    params: list = field(default_factory=list)     # [ParamSpec]
    cost: dict = field(default_factory=dict)       # {vram_gb, cpu_bound, approx_s…}
    projects: list = field(default_factory=list)   # traçabilité : projets utilisant la fonction (ex. ["ENA"])
    visibility: str = 'public'                     # 'public' | 'private' | 'shared' (confidentialité — à venir)
    owner: str = ''                                # propriétaire si private/shared (à venir)

    def to_dict(self):
        """Représentation métadonnée-driven (card + ports + modale)."""
        def _port(p):
            return {'key': p.key, 'data_type': p.data_type,
                    'required_fields': p.required_fields, 'produced_fields': p.produced_fields,
                    'cardinality': p.cardinality, 'optional': p.optional,
                    'description': p.description}

        def _param(p):
            return {'key': p.key, 'type': p.type, 'default': p.default, 'min': p.min,
                    'max': p.max, 'choices': p.choices, 'unit': p.unit,
                    'description': p.description}

        return {
            'key': self.key, 'name': self.name, 'description': self.description,
            'category': self.category, 'binding': self.binding, 'app': self.app,
            'impl': self.impl, 'tags': self.tags, 'projects': self.projects,
            'visibility': self.visibility, 'owner': self.owner,
            'inputs': [_port(p) for p in self.inputs],
            'outputs': [_port(p) for p in self.outputs],
            'params': [_param(p) for p in self.params],
            'cost': self.cost,
        }

    def defaults(self):
        return {p.key: p.default for p in self.params}


FUNCTION_CATALOG: dict = {}


def register(spec: FunctionSpec) -> FunctionSpec:
    """Enregistre une fonction dans le catalogue (idempotent par clé)."""
    if spec.key in FUNCTION_CATALOG and FUNCTION_CATALOG[spec.key] is not spec:
        raise ValueError(f"FunctionSpec dupliqué : {spec.key}")
    FUNCTION_CATALOG[spec.key] = spec
    return spec


def get(key) -> Optional[FunctionSpec]:
    return FUNCTION_CATALOG.get(key)


def by_category(category):
    return [s for s in FUNCTION_CATALOG.values() if s.category == category]


def by_tag(tag):
    return [s for s in FUNCTION_CATALOG.values() if tag in s.tags]


def catalog_dict():
    """Tout le catalogue en dicts (pour l'UI / tool_api)."""
    return {k: s.to_dict() for k, s in FUNCTION_CATALOG.items()}


def can_connect(out_port: PortSpec, in_port: PortSpec, available_fields=None):
    """Validation d'une connexion sortie→entrée (chaînage) : compatibilité de TYPE
    (sous-typage) ET satisfaction des champs requis depuis les champs disponibles à
    ce point de la chaîne (`produced` + champs déjà présents). Retourne (ok, raison)."""
    if not is_compatible(out_port.data_type, in_port.data_type):
        return False, (f"type incompatible : {out_port.data_type} → attend {in_port.data_type}")
    avail = set(available_fields) if available_fields is not None else set()
    avail |= set(out_port.produced_fields)
    missing = [f for f in in_port.required_fields if f not in avail]
    if missing and available_fields is not None:
        return False, f"champs manquants : {missing}"
    return True, ''


def load_all():
    """Force l'import des fonctions du catalogue (idempotent) — utile hors cycle Django ready()."""
    try:
        from wama.common.data import functions  # noqa: F401
    except Exception:
        pass
    try:
        from wama_lab.cam_analyzer import function_specs  # noqa: F401
    except Exception:
        pass
    return FUNCTION_CATALOG
