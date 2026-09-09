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

from wama.common.catalog.data_types import CANONICAL_FIELDS, is_compatible


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


#: RÔLE d'un port d'ENTRÉE (marche C du plan `WAMA_DATA_WORLD §9`, 2026-09-09). Vocabulaire
#: EMPRUNTÉ à `app_modes.INPUT_TYPES[*]['port']` — le même que `studio_node_ports` rend pour les
#: apps — jamais un 3ᵉ enum : c'est ce qui permet à `function_node_ports()` de rendre la MÊME
#: forme, donc à la card v4 et au Studio de couvrir Data sans une ligne par consommateur.
#: `travail` = la donnée transformée ; `reference` = ce qui SERT à la transformer (référentiel
#: routier, trace ego…) sans être transformé.
PORT_GROUPS = ('travail', 'reference')

#: FACETTE ESTIMATEUR d'un port de SORTIE (⑤b, forme validée par Fabien le 2026-09-09 —
#: `CAM_ANALYZER_CHAINE_TRAITEMENT §INVENTAIRE E`). Un levier de correction devient un MODÈLE DE
#: MESURE : « j'estime G (`estimates`), je vaux ±σ (`uncertainty`), à partir de telle donnée
#: native (`derived_from`) ». Trois champs OPTIONNELS sur le port existant — pas de 9ᵉ registre.
#: Le critère fusion / confrontation n'est pas la qualité, c'est l'INDÉPENDANCE : deux sorties
#: dont `derived_from` se recouvrent se CONFRONTENT (leviers 1 et 40 viennent de la même bbox),
#: jamais ne se fusionnent — `fusion.fuse_estimates` refuse. Vocabulaires FERMÉS ci-dessous.
#: Grandeurs estimées → unité de σ (celle du levier §INVENTAIRE C qui la corrige).
ESTIMATED_QUANTITIES = {
    'distance': 'm',        # distance longitudinale objet ↔ caméra/navette
    'lateral': 'm',         # écart latéral
    'position': 'm',        # position monde (est/nord) — σ radial
    'speed': 'km/h',
    'heading': 'deg',       # cap (0 = nord, horaire) — grandeur CIRCULAIRE
    'yaw': 'deg',           # rotation autour de la verticale entre deux instants — CIRCULAIRE
    'ground_plane': 'deg',  # angle du plan de sol (pitch) ; la hauteur voyage dans les champs
    'offset': 'm',          # décalage absolu (recalage ortho)
    'ttc': 's',
    'pet': 's',
}
#: Grandeurs dont la fusion est une moyenne VECTORIELLE (mod 360°), jamais arithmétique.
CIRCULAR_QUANTITIES = {'heading', 'yaw'}
#: Données NATIVES dont une estimation dérive — ce qui décide de l'indépendance de deux sources.
NATIVE_SOURCES = {'gps', 'bbox', 'image', 'segmentation', 'depth_map', 'imu', 'orthophoto',
                  'road_map'}
#: Formes de `uncertainty` (évaluées par `fusion.estimates.sigma_of`) :
#:   nombre                                → σ constante (unité de la grandeur) ;
#:   {'field': col}                        → σ par ligne, lue dans la colonne `col` ;
#:   {'model': 'relative', 'ratio': r}     → σ = r·|valeur| (pinhole : ±20 %) ;
#:   {'model': 'held', 'field': f, 'sigma': s} → σ = s, ligne INVALIDE quand le drapeau `f` est vrai
#:                                           (cap tenu à l'arrêt : pas une mesure) ;
#:   {'model': 'declared', 'note': …}      → non chiffrée : la sortie se CONFRONTE, ne se fusionne pas.
UNCERTAINTY_MODELS = ('relative', 'held', 'declared')


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
    # ── rôle (entrée) — marche C ; '' = `travail` (le défaut historique, jamais réécrit) ──
    group: str = ''
    # ── facette estimateur (sortie) — ⑤b ; absente = la sortie n'estime rien ──
    estimates: str = ''                 # ∈ ESTIMATED_QUANTITIES
    uncertainty: object = None          # nombre | {'field'} | {'model', …} — cf. UNCERTAINTY_MODELS
    derived_from: list = field(default_factory=list)      # ⊆ NATIVE_SOURCES
    estimate_field: str = ''            # colonne qui porte la valeur estimée ('' = `value`)

    def port_dict(self, side: str) -> dict:
        """Forme sérialisée d'un port. `group` ne s'écrit que pour une ENTRÉE (une sortie n'a
        pas de rôle) ; la facette estimateur ne s'écrit que si elle est DÉCLARÉE — un port sans
        estimation garde exactement la forme d'avant, le corpus ne bouge pas pour rien."""
        d = {'key': self.key, 'data_type': self.data_type,
             'required_fields': self.required_fields, 'produced_fields': self.produced_fields,
             'cardinality': self.cardinality, 'optional': self.optional,
             'description': self.description}
        if side == 'input':
            d['group'] = self.group or PORT_GROUPS[0]
        if self.estimates:
            d['estimates'] = self.estimates
            d['uncertainty'] = self.uncertainty
            d['derived_from'] = list(self.derived_from)
            if self.estimate_field:
                d['estimate_field'] = self.estimate_field
        return d


def validate_port_facet(port: dict, side: str) -> list:
    """Erreurs de la facette d'un port SÉRIALISÉ (dict) — partagé par le kind manifeste
    `function` (validation à l'export/ingest) et par les tests du catalogue. `side` ∈
    {'input', 'output'} : un rôle n'a de sens qu'en entrée, une estimation qu'en sortie."""
    errs = []
    k = port.get('key', '?')
    grp = port.get('group')
    if grp is not None and grp not in PORT_GROUPS:
        errs.append(f"port '{k}' : group '{grp}' invalide ({'|'.join(PORT_GROUPS)})")
    if side == 'output' and grp:
        errs.append(f"port '{k}' : une SORTIE ne porte pas de rôle (group)")
    q = port.get('estimates')
    if not q:
        for champ in ('uncertainty', 'derived_from'):
            if port.get(champ):
                errs.append(f"port '{k}' : `{champ}` sans `estimates` — la facette est incomplète")
        return errs
    if side == 'input':
        errs.append(f"port '{k}' : une ENTRÉE n'estime rien (`estimates` est une facette de sortie)")
    if q not in ESTIMATED_QUANTITIES:
        errs.append(f"port '{k}' : estimates '{q}' hors vocabulaire "
                    f"({', '.join(sorted(ESTIMATED_QUANTITIES))})")
    src = port.get('derived_from')
    if not src or not isinstance(src, (list, tuple)):
        errs.append(f"port '{k}' : `derived_from` requis avec `estimates` (l'indépendance en dépend)")
    else:
        for s in src:
            if s not in NATIVE_SOURCES:
                errs.append(f"port '{k}' : derived_from '{s}' hors vocabulaire "
                            f"({', '.join(sorted(NATIVE_SOURCES))})")
    u = port.get('uncertainty')
    if u is None:
        errs.append(f"port '{k}' : `uncertainty` requis avec `estimates` "
                    f"(au pire {{'model': 'declared'}})")
    elif isinstance(u, bool) or not isinstance(u, (int, float, dict)):
        errs.append(f"port '{k}' : uncertainty doit être un nombre ou un dict")
    elif isinstance(u, dict):
        if 'field' in u and 'model' not in u:
            if not u['field']:
                errs.append(f"port '{k}' : uncertainty.field vide")
        elif u.get('model') not in UNCERTAINTY_MODELS:
            errs.append(f"port '{k}' : uncertainty.model '{u.get('model')}' inconnu "
                        f"({'|'.join(UNCERTAINTY_MODELS)})")
        elif u['model'] == 'relative' and not isinstance(u.get('ratio'), (int, float)):
            errs.append(f"port '{k}' : uncertainty relative sans `ratio`")
        elif u['model'] == 'held' and (not u.get('field') or not isinstance(u.get('sigma'), (int, float))):
            errs.append(f"port '{k}' : uncertainty held exige `field` (drapeau) et `sigma`")
    elif u <= 0:
        errs.append(f"port '{k}' : σ constante doit être > 0")
    return errs


def port_estimate_meta(port: PortSpec) -> Optional[dict]:
    """La facette d'un port de sortie sous la forme que porte un `TypedFrame.meta['estimate']`
    à l'exécution — c'est ce que `fusion.fuse_estimates` lit, et ce que l'exécuteur du Studio
    pose sur chaque sortie de nœud `function`. `None` si le port n'estime rien."""
    if not port.estimates:
        return None
    return {'quantity': port.estimates,
            'unit': ESTIMATED_QUANTITIES.get(port.estimates, ''),
            'field': port.estimate_field or 'value',
            'uncertainty': port.uncertainty,
            'derived_from': list(port.derived_from),
            'circular': port.estimates in CIRCULAR_QUANTITIES}


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
        def _param(p):
            return {'key': p.key, 'type': p.type, 'default': p.default, 'min': p.min,
                    'max': p.max, 'choices': p.choices, 'unit': p.unit,
                    'description': p.description}

        return {
            'key': self.key, 'name': self.name, 'description': self.description,
            'category': self.category, 'binding': self.binding, 'app': self.app,
            'impl': self.impl, 'tags': self.tags, 'projects': self.projects,
            'visibility': self.visibility, 'owner': self.owner,
            'inputs': [p.port_dict('input') for p in self.inputs],
            'outputs': [p.port_dict('output') for p in self.outputs],
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


def function_node_ports(key):
    """Ports d'un NŒUD de fonction — MÊME forme que `app_registry.studio_node_ports(app_id)`
    (marche C, `WAMA_DATA_WORLD §9`) : `{'inputs': [{id, label, group, types, multi}],
    'output': {id, label, types}}`, plus `outputs` (liste) parce qu'une fonction peut produire
    plusieurs sorties là où une app n'en a qu'une — `manifests/builtin/app._ports` lit déjà
    les deux formes. `None` si la clé est inconnue.

    Les `types` d'une SORTIE sont le type déclaré ET ses super-types (`data_types.ancestors`) :
    le Studio apparie par INTERSECTION de listes (JS `inter()`), c'est ainsi que le sous-typage
    `geo_track ⊂ timeseries ⊂ table` reste vrai au canvas sans y réécrire la taxonomie.
    """
    from wama.common.catalog.data_types import ancestors
    spec = FUNCTION_CATALOG.get(key)
    if spec is None:
        return None
    # `label` = la CLÉ du port : c'est le nom du créneau (`WAMA_DATA_FUNCTION_CARDS §2`), il est
    # court, et c'est lui que `to_port` sérialise — un libellé inventé ici divergerait du graphe.
    # La `description` DÉCLARÉE voyage à côté et devient l'infobulle : elle existait dans chaque
    # spec sans être rendue nulle part (mesuré au navigateur le 2026-09-09), alors que c'est la
    # seule phrase qui dise à l'utilisateur ce qu'un port attend.
    inputs = [{'id': p.key, 'label': p.key, 'group': p.group or PORT_GROUPS[0],
               'types': [p.data_type], 'multi': p.cardinality == 'many',
               'optional': bool(p.optional), 'description': p.description}
              for p in spec.inputs]
    outs = [{'id': p.key, 'label': p.key, 'types': sorted(ancestors(p.data_type)),
             'description': p.description}
            for p in spec.outputs]
    if not outs:
        output = None
    elif len(outs) == 1:
        output = outs[0]
    else:
        output = {'id': 'out', 'label': 'Sortie',
                  'types': sorted({t for o in outs for t in o['types']})}
    return {'inputs': inputs, 'output': output, 'outputs': outs}


def can_connect(out_port: PortSpec, in_port: PortSpec, available_fields=None):
    """Validation d'une connexion sortie→entrée (chaînage) : compatibilité de TYPE
    (sous-typage) ET satisfaction des champs requis depuis les champs disponibles à
    ce point de la chaîne (`produced` + CANONIQUES DU TYPE + champs déjà présents).
    Retourne (ok, raison)."""
    if not is_compatible(out_port.data_type, in_port.data_type):
        return False, (f"type incompatible : {out_port.data_type} → attend {in_port.data_type}")
    avail = set(available_fields) if available_fields is not None else set()
    avail |= set(out_port.produced_fields)
    # ⚠ LES CHAMPS CANONIQUES DU TYPE SONT LÀ PAR DÉFINITION (2026-09-09). Un `geo_track`
    # PORTE `time/lat/lon` — c'est ce que le type VEUT DIRE. Une fonction qui en rend un
    # ne « produit » donc pas `time` : elle le transmet, et n'a aucune raison de le déclarer.
    #
    # Mesuré avant d'écrire cette ligne : sur les paires de fonctions pures, 81 refus après
    # accumulation réaliste, dont **exactement 29** dus à ce seul manque — `gps_map_match`
    # (geo_track → geo_track) refusé vers `generate_sections` faute de `time`, alors que les
    # deux ports sont des `geo_track`. Ce n'étaient pas 29 déclarations à corriger, c'était
    # UNE règle absente. *Un compte qui se concentre sur une cause n'est pas une liste de
    # défauts, c'est un défaut unique vu N fois.*
    #
    # Ça n'assouplit rien : une fonction qui déclare rendre un `signal` sans porter
    # `time`/`value` ment sur son TYPE — et c'est `FunctionCatalogConformiteTest` qui tient
    # ce contrat-là, pas le chaînage. Même forme que `_PATTERNS_DE_BORD` côté installation :
    # le jeu déclaré, plus ce que la nature garantit.
    avail |= set(CANONICAL_FIELDS.get(out_port.data_type) or ())
    missing = [f for f in in_port.required_fields if f not in avail]
    if missing and available_fields is not None:
        return False, f"champs manquants : {missing}"
    return True, ''


# ── LA RÈGLE DE GRANULARITÉ (WAMA_DATA_WORLD §9quater.4) ─────────────────────────────────
# « Une colonne calculée reste dans SA table tant que la CLÉ TEMPORELLE ne change pas ;
#   elle en sort dès qu'elle change. »
#
# ⚠ REMONTÉE ICI le 2026-09-09, depuis `wama_data/view.py` où elle est née. Elle porte sur
# `FunctionCategory`, qui vit dans CE module — la glu INTER-MONDES. La laisser dans le monde
# Data obligeait le STUDIO (substrat) à en dépendre pour valider un graphe : exactement le
# défaut que le AGENTS.md nomme, « le registre ne connaît JAMAIS ses producteurs ».
# `wama_data/view.py` la RÉ-EXPORTE : aucun appelant ne change, aucun comportement non plus.

#: Catégories qui LAISSENT la granularité intacte — leur sortie a les mêmes lignes que l'entrée,
#: donc la colonne produite s'adjoint à la table qu'on regarde.
CATEGORIES_ADJOINTES = frozenset({FunctionCategory.TRANSFORM, FunctionCategory.ENRICHER})

#: Tout le reste change la clé temporelle, donc sort dans une table à part. On énumère quand même
#: — un `not in` silencieux rangerait une catégorie NOUVELLE du mauvais côté sans le dire.
CATEGORIES_NOUVELLE_TABLE = frozenset({
    FunctionCategory.DETECTOR, FunctionCategory.INDICATOR, FunctionCategory.RESAMPLER,
    FunctionCategory.AGGREGATE, FunctionCategory.JOIN,
})


def changes_time_key(cle_fonction: str) -> bool:
    """La fonction change-t-elle la clé temporelle — donc faut-il une nouvelle table ?

    Lu dans la `FunctionCategory` DÉCLARÉE, jamais dans une liste de noms de fonctions. C'est ce
    qui fait que la règle de §9quater.4 s'applique à une fonction écrite demain sans qu'on touche
    ici. Une catégorie inconnue lève : mieux vaut refuser que ranger au hasard.
    """
    spec = get(cle_fonction)
    if spec is None:
        raise ValueError(f"fonction '{cle_fonction}' absente du catalogue "
                         f"(connues : {', '.join(sorted(FUNCTION_CATALOG)) or '—'})")
    if spec.category in CATEGORIES_ADJOINTES:
        return False
    if spec.category in CATEGORIES_NOUVELLE_TABLE:
        return True
    raise ValueError(
        f"catégorie '{spec.category}' de '{cle_fonction}' non classée par la règle de "
        "§9quater.4 — décider si elle change la clé temporelle et l'ajouter à l'un des deux "
        "ensembles de `common/catalog/function_catalog.py`, plutôt que de la laisser tomber "
        "d'un côté par défaut")


def champs_apres(sortie: PortSpec, cle_fonction: str, champs_avant=()) -> set:
    """Champs DISPONIBLES en aval d'un nœud fonction — l'accumulation que `can_connect`
    attendait et que personne ne lui donnait (mesuré le 2026-09-09).

    C'est la règle de granularité ci-dessus, appliquée aux CHAMPS au lieu des tables :
      • granularité intacte (`transform`/`enricher`) → les champs d'amont SURVIVENT, la
        fonction ajoute les siens. `calc_rolling` enrichit : il ne « produit » pas `time`,
        il le laisse passer — d'où `produced_fields == []` alors que `time` reste lisible ;
      • clé temporelle changée → on repart des SEULS champs produits : les lignes ne sont
        plus les mêmes, une colonne d'amont n'a plus de sens en face.

    ⚠ POURQUOI ÇA COMPTE : sans cette accumulation, `can_connect` refuse
    `calc_rolling → calc_per_segment` (« champs manquants : ['time'] ») — une connexion que
    la suite de tests déclare VALIDE. Un contrôle des champs alimenté au seul saut précédent
    transforme tout enrichisseur en cul-de-sac.

    ⚠ COUTURE À CONNAÎTRE, non construite ici (`WAMA_APPRENTISSAGE §3` A2) : la provenance
    réel/synthétique devra être PROPAGÉE le long des mêmes liens. Le jour venu, c'est CE
    parcours qu'on étend — pas un second. *Une couture nommée n'est pas une couture bâtie.*
    """
    produits = set(sortie.produced_fields or ())
    return produits if changes_time_key(cle_fonction) else set(champs_avant) | produits


#: Modules qu'une app peut exposer pour déclarer ses fonctions. Convention, pas configuration.
MODULES_DECLARANTS = ('functions', 'function_specs')


def load_all():
    """Force l'import des fonctions du catalogue (idempotent) — utile hors cycle Django ready().

    ⚠ Le registre ne connaît PAS ses producteurs. Il citait auparavant `wama.common.data` et
    `wama_lab.cam_analyzer` **en dur** : le substrat nommait deux mondes, donc ajouter un monde
    exigeait de modifier le registre, et le déport de WAMA Data l'aurait cassé silencieusement.
    Il parcourt maintenant les apps installées et importe leur module déclarant s'il existe —
    la même leçon de registre keyé qu'ailleurs dans WAMA.

    En cycle Django normal, chaque app le fait déjà dans son `ready()` ; cette fonction sert aux
    scripts et aux commandes qui lisent le catalogue hors de ce cycle. Les imports sont idempotents.
    """
    import importlib
    try:
        from django.apps import apps as django_apps
        noms = [c.name for c in django_apps.get_app_configs()]
    except Exception:
        # PAS de repli citant des mondes en dur : ce serait réintroduire exactement le couplage
        # qu'on vient de retirer. Hors Django on rend ce qui a été enregistré par les imports.
        import logging
        logging.getLogger(__name__).debug(
            'registre Django indisponible — catalogue rendu en l’état')
        return FUNCTION_CATALOG
    for nom in noms:
        for module in MODULES_DECLARANTS:
            try:
                importlib.import_module(f'{nom}.{module}')
            except ImportError:
                pass          # l'app ne déclare rien — le cas NORMAL, pas une erreur
            except Exception:
                import logging
                logging.getLogger(__name__).warning(
                    'fonctions de %s.%s non enregistrées', nom, module, exc_info=True)
    return FUNCTION_CATALOG
