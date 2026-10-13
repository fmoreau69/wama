"""
SURFACES et BRIQUES UI — le registre (2026-10-10, ouverture du chantier SURFACES).

Une SURFACE (`ROUTE §10.6`) est une page ouverte depuis une card, où l'on regarde et où l'on fait
des gestes, sans état d'exécution : un geste qui modifie la donnée devient le changement d'un
champ SURVEILLÉ par un process de la card, qui passe `STALE` et se rejoue. La page de correction
de l'anonymizer en est le premier usage ; YuE2 (partition + paroles) et la retouche vidéo de
l'Imager attendent les mêmes briques.

Décisions de Fabien (2026-10-10) :
  • une page d'édition se COMPOSE de briques UI réutilisables, UNIVERSELLES — les mêmes dans les
    mondes Médias, Data, Lab et Studio (pas de brique « de l'anonymizer ») ;
  • chaque brique se DÉPLACE et se REDIMENSIONNE sur la page (gridstack, vendorisé) ;
  • les briques s'ajouteront dans le Studio sous forme de diagramme : ce registre est la palette
    qu'il lira, et le catalogue des briques (« ce qui existe ») le lira aussi — jamais une
    seconde liste ;
  • l'annuler/rétablir est celui de tout WAMA (`wama-history.js`).

CE QU'UNE BRIQUE DÉCLARE — c'est ce qui la rend composable sans code d'app :
  `consumes` : ce qu'elle lit, dans les vocabulaires EXISTANTS — natures de média
               (`app_registry.MEDIA_CATEGORIES`) ou types de données (`catalog.data_types`).
               Jamais un troisième vocabulaire (`tests_surfaces` le tient) ;
  `emits`    : ce qu'elle produit (une donnée éditée, un geste) ;
  `script`   : le module JS qui la monte (`WamaSurface.registerBrick(clé, …)`).

CE QU'UNE SURFACE DÉCLARE : ses emplacements (brique, position et taille par défaut sur la
grille), les champs de l'élément qu'elle LIT par rôle, le champ qu'elle ÉCRIT et sa validation,
le process que l'écriture périme. Les vues communes (`surface_views`) la servent sans une ligne
d'app : une app déclare, elle n'écrit pas de page.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional

#: Mondes où une brique se monte — par défaut TOUS : une brique est universelle (décision 10/10).
WORLDS = ('media', 'data', 'lab', 'studio')
#: Colonnes de la grille de mise en page (gridstack, défaut 12).
GRID_COLUMNS = 12


@dataclass(frozen=True)
class UIBrick:
    key: str
    name: str
    description: str
    script: str
    consumes: tuple = ()
    emits: tuple = ()
    worlds: tuple = WORLDS
    #: Modules JS communs dont la brique a besoin, chargés AVANT son script (ordre gardé).
    requires: tuple = ()

    def scripts(self) -> list:
        return [*self.requires, self.script]

    def to_dict(self) -> dict:
        return {'key': self.key, 'name': self.name, 'description': self.description,
                'script': self.script, 'requires': list(self.requires),
                'consumes': list(self.consumes),
                'emits': list(self.emits), 'worlds': list(self.worlds)}


@dataclass(frozen=True)
class BrickSlot:
    """Une brique placée sur une surface : position et taille PAR DÉFAUT (l'utilisateur les
    change sur la page), options propres à cet emplacement."""
    id: str
    brick: str
    x: int
    y: int
    w: int
    h: int
    options: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {'id': self.id, 'brick': self.brick, 'x': self.x, 'y': self.y, 'w': self.w,
                'h': self.h, 'options': dict(self.options)}


@dataclass(frozen=True)
class Surface:
    app: str
    key: str
    label: str
    #: Le modèle Django de l'élément (`'anonymizer.Media'`).
    model: str
    slots: tuple
    #: Rôle → champ de l'élément lu par la page (`{'image': 'file'}`). Un champ fichier est
    #: servi par son URL ; un document JSON (`detections_file`) est lu et rendu tel quel.
    reads: dict
    #: Champ ÉCRIT par la page et sa validation (rend la valeur assainie, lève `ValueError`).
    edits: str
    validate: Callable
    #: Process que l'écriture périme et que « Appliquer » rejoue (`<app>:start_process`).
    reruns: str = ''
    #: L'élément peut-il s'ouvrir dans cette surface ? `(bool, raison)` — la raison s'affiche.
    available: Optional[Callable] = None
    #: Rôles lus en JSON (document), les autres étant des fichiers servis par URL.
    documents: tuple = ()
    #: Valeurs de l'élément passées aux briques : nom de champ, ou fonction de l'élément quand la
    #: valeur se lit assainie (`{'classes': lambda media: sane_classes(media.classes2blur)}`).
    context: dict = field(default_factory=dict)

    def context_of(self, item) -> dict:
        return {name: (source(item) if callable(source) else getattr(item, source, None))
                for name, source in self.context.items()}

    @property
    def id(self) -> str:
        return f'{self.app}.{self.key}'

    def model_class(self):
        from django.apps import apps
        return apps.get_model(self.model)

    def can_open(self, item) -> tuple:
        if self.available is None:
            return True, ''
        return self.available(item)

    def bricks(self) -> list:
        return [BRICKS[slot.brick] for slot in self.slots]

    def scripts(self) -> list:
        """Les scripts à charger, dépendances d'abord, sans doublon, dans l'ordre des briques."""
        return list(dict.fromkeys(path for b in self.bricks() for path in b.scripts()))

    def to_dict(self) -> dict:
        return {'id': self.id, 'app': self.app, 'key': self.key, 'label': self.label,
                'slots': [s.to_dict() for s in self.slots], 'edits': self.edits,
                'reruns': self.reruns, 'columns': GRID_COLUMNS,
                'bricks': {b.key: b.to_dict() for b in self.bricks()}}


BRICKS: dict = {}
SURFACES: dict = {}


def register_brick(brick: UIBrick) -> UIBrick:
    BRICKS[brick.key] = brick
    return brick


def register_surface(surface: Surface) -> Surface:
    unknown = [s.brick for s in surface.slots if s.brick not in BRICKS]
    if unknown:
        raise ValueError(f"surface {surface.id} : brique(s) inconnue(s) {unknown}")
    SURFACES[surface.id] = surface
    return surface


def surface(app: str, key: str) -> Optional[Surface]:
    load_all()
    return SURFACES.get(f'{app}.{key}')


def surfaces_of(app: str) -> list:
    load_all()
    return [s for s in SURFACES.values() if s.app == app]


#: Module déclarant d'une app — même règle que le catalogue de fonctions : le registre ne
#: connaît pas ses producteurs, il importe `<app>.surfaces` s'il existe.
DECLARING_MODULE = 'surfaces'


#: Les déclarations sont importées UNE fois par processus, comme celles des pipelines
#: (`process_pipeline._load_declarations`). Mesuré le 2026-10-13 : `surface_button` (une fois par
#: card) relançait le balayage — un `import_module` RATÉ par app sans surfaces, donc une recherche
#: sur tout `sys.path` à travers /mnt/d : 0,15 s l'appel, **4,5 s** pour la page de l'anonymizer.
_loaded = False


def load_all() -> dict:
    """Importe les déclarations de surfaces des apps installées (une fois par processus)."""
    global _loaded
    if _loaded:
        return SURFACES
    import importlib
    import logging
    try:
        from django.apps import apps as django_apps
        names = [c.name for c in django_apps.get_app_configs()]
    except Exception:
        return SURFACES
    _loaded = True
    for name in names:
        if name == 'wama.common':
            continue
        try:
            importlib.import_module(f'{name}.{DECLARING_MODULE}')
        except ModuleNotFoundError as error:
            if error.name != f'{name}.{DECLARING_MODULE}':
                logging.getLogger(__name__).warning('[surfaces] %s : %s', name, error)
        except Exception as error:      # une déclaration cassée se DIT, elle ne tait pas le reste
            logging.getLogger(__name__).warning('[surfaces] %s : %s', name, error)
    return SURFACES


# ── Briques COMMUNES ─────────────────────────────────────────────────────────────────────────
# Déclarées ici parce qu'elles sont communes : aucune ne connaît une app. Leur JS vit sous
# `common/static/common/js/surfaces/`.

register_brick(UIBrick(
    key='image_boxes', name='Image et zones',
    description="Une image et ses zones (boîtes) : zoom à la molette, déplacement, tracé d'une "
                "zone neuve, sélection, suppression, déplacement et redimensionnement d'une "
                "zone. Écrit des CORRECTIONS (ajouts, retraits), jamais le document d'origine.",
    script='common/js/surfaces/brick-image-boxes.js',
    requires=('common/js/wama-detections.js',),
    consumes=('image', 'detections'), emits=('detection_corrections',)))

register_brick(UIBrick(
    key='object_list', name='Liste des objets',
    description="Les objets de la donnée éditée, comptés par classe, détectés ou ajoutés à la "
                "main ; un clic sélectionne l'objet dans les autres briques.",
    script='common/js/surfaces/brick-object-list.js',
    requires=('common/js/wama-detections.js',),
    consumes=('detections',)))

register_brick(UIBrick(
    key='surface_actions', name='Actions de la surface',
    description="Annuler / rétablir (historique commun), enregistrer, appliquer — rejouer le "
                "process que la modification a périmé.",
    script='common/js/surfaces/brick-surface-actions.js'))
