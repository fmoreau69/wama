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

TROIS NIVEAUX (2026-10-19, décision de Fabien — `ROUTE §F3b`) : un MÉCANISME est une pièce,
adressée par le développeur et mesurée par son adoption (les boutons d'action, l'ETA) ; une BRIQUE
est un tout, posé par l'utilisateur ou le Studio, qui lit une donnée déclarée et a ses options —
elle est COMPOSÉE de mécanismes, lus du code (`UIBrick.mechanisms`), jamais redéclarés ; une PAGE
compose des briques (une surface, la page d'une app). Le catalogue ne montre donc que des briques.
Deux façons de monter une brique : sur la grille d'une SURFACE (son script), ou par une PAGE
d'app (`mount`, le gabarit qui la monte — card d'entrée, inspecteur, visionneuse) ; celle-ci lit
ce que l'app DÉCLARE (`declarations`), et les apps qui la montent se lisent de l'adoption mesurée
du mécanisme qui tient ce gabarit (`UIBrick.adoption`).

CE QU'UNE SURFACE DÉCLARE : ses emplacements (brique, position et taille par défaut sur la
grille), les champs de l'élément qu'elle LIT par rôle, le champ qu'elle ÉCRIT et sa validation,
le process que l'écriture périme. Les vues communes (`surface_views`) la servent sans une ligne
d'app : une app déclare, elle n'écrit pas de page.

LE CHAMP ÉCRIT a deux natures, DÉDUITES de son type — jamais déclarées (2026-10-13, 2ᵉ surface :
le fond du Writer) :
  • un champ de DONNÉE (JSON) : la valeur éditée est ce champ, validée par la fonction que la
    surface déclare (`validate`) — la couche de corrections de l'anonymizer ;
  • un champ FICHIER : la valeur éditée est le TEXTE de ce fichier, comme le texte saisi du
    synthesizer devient le fichier de travail de sa card. Validation, disponibilité et écriture
    sont alors communes (`text_value`) : une app n'a rien à écrire. Quand ce fichier est la
    SORTIE d'un process, le réécrire périme son aval par l'empreinte de sortie
    (`process_pipeline.output_fingerprint`) — sans une ligne de plus.

DES CHAMPS ALTERNATIFS (2026-10-15, 3ᵉ surface : la partition du composer) : `edits` peut nommer
plusieurs champs de même nature, sorties de process ALTERNATIFS — la partition écrite par `plan`
ou extraite par `extract_score`, exclusifs par `applies` (`ROUTE §10.6`, « deux amonts
alternatifs »). La page édite le premier qui est rempli (`edited`) ; une app ne déclare pas une
surface par champ.

L'AXE PARTAGÉ (2026-10-15, chantier « transport commun », `ROUTE §F3b`) : une surface qui monte
une brique temporelle a UN axe de temps (`wama-axis.js`, `ctx.axis()`). Le transport le PILOTE ;
les vues s'y ABONNENT — elles ne se parlent jamais (`WAMA_DATA_WORLD §5bis`).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional

#: Mondes où une brique se monte — par défaut TOUS : une brique est universelle (décision 10/10).
WORLDS = ('media', 'data', 'lab', 'studio')
#: Colonnes de la grille de mise en page (gridstack, défaut 12).
GRID_COLUMNS = 12
#: Plafond d'un texte édité sur une surface : un document qu'on relit et corrige, pas un flux.
MAX_TEXT_CHARS = 2_000_000
#: Dossier des VIGNETTES des briques sous `STATIC_ROOT` (2026-10-18, décision de Fabien) : une
#: capture par brique (`<clé>.png`), prise par le nocturne sur une vraie surface ouverte sur un
#: élément témoin, jamais versionnée (`.gitignore`) — la capture suivante la remplace.
THUMBNAILS_DIR = 'ui_bricks'


def thumbnail_path(key: str):
    """Le fichier de la vignette d'une brique (qu'il existe ou non)."""
    from pathlib import Path

    from django.conf import settings
    return Path(settings.STATIC_ROOT) / THUMBNAILS_DIR / f'{key}.png'


def thumbnail(key: str) -> Optional[dict]:
    """La vignette d'une brique — `{'url', 'taken_at'}`, ou None tant qu'aucune capture n'existe
    (la page le dit, elle n'invente rien). L'URL porte `?v=<mtime>` comme `static_v` : une capture
    refaite change d'adresse, le navigateur ne garde pas l'ancienne. `static_v` lui-même ne la
    trouverait pas — il cherche dans les dossiers statiques SOURCES, la capture n'est que servie."""
    from datetime import datetime, timezone

    from django.templatetags.static import static
    try:
        mtime = thumbnail_path(key).stat().st_mtime
    except OSError:
        return None
    return {'url': f"{static(f'{THUMBNAILS_DIR}/{key}.png')}?v={int(mtime)}",
            'taken_at': datetime.fromtimestamp(mtime, tz=timezone.utc)}


def validate_text(value) -> str:
    """Le texte d'un champ fichier édité, assaini : une chaîne, fins de ligne `\\n`, plafonnée."""
    if not isinstance(value, str):
        raise ValueError("texte : une chaîne est attendue")
    if len(value) > MAX_TEXT_CHARS:
        raise ValueError(f"texte : plus de {MAX_TEXT_CHARS} caractères")
    return value.replace('\r\n', '\n').replace('\r', '\n')


def source_file(path: str) -> Optional[str]:
    """Le fichier SOURCE d'un chemin nommé comme une page le nomme — un gabarit comme
    `{% include %}`, un statique comme `{% static %}` —, None s'il est introuvable."""
    if path.endswith('.html'):
        from django.template import TemplateDoesNotExist
        from django.template.loader import get_template
        try:
            return get_template(path).origin.name
        except TemplateDoesNotExist:
            return None
    from django.contrib.staticfiles import finders
    return finders.find(path)


@dataclass(frozen=True)
class UIBrick:
    key: str
    name: str
    description: str
    #: Le module JS de la brique. Une brique de SURFACE s'y enregistre
    #: (`WamaSurface.registerBrick`) ; une brique de PAGE peut n'en avoir aucun à elle.
    script: str = ''
    consumes: tuple = ()
    emits: tuple = ()
    worlds: tuple = WORLDS
    #: Modules JS communs dont la brique a besoin, chargés AVANT son script (ordre gardé).
    requires: tuple = ()
    #: Brique de PAGE (2026-10-19, décision de Fabien, `ROUTE §F3b`) : le fichier par lequel une
    #: page la monte — le gabarit qu'elle inclut, ou le script que la page de base charge pour
    #: toutes quand la brique n'a pas de gabarit à elle. Vide : une brique de SURFACE, posée sur
    #: la grille d'une surface.
    mount: str = ''
    #: Ce que LIT une brique de page : rien ne circule jusqu'à elle (`consumes` reste vide), elle
    #: lit ce que DÉCLARE l'app qui la monte — `'app.<facette>'` (`builtin.app.APP_FACETS`) ou le
    #: manifeste d'un autre kind de l'app (`'pipeline'`). Décision du 19/10 : pas de type
    #: « élément » dans `catalog.data_types`, qui nomme ce qui circule par les ports.
    declarations: tuple = ()

    @property
    def is_page(self) -> bool:
        return bool(self.mount)

    def scripts(self) -> list:
        return [*self.requires, *([self.script] if self.script else [])]

    def mechanisms(self) -> list:
        """Les mécanismes dont la brique est COMPOSÉE (2026-10-19, « trois niveaux » — une brique
        est un tout, un mécanisme une pièce) : ceux qui tiennent ce qu'elle charge (`requires`) et
        le fichier qui la monte (`mount`), et ceux que son script et ce fichier consomment, par la
        détection même du balayage d'adoption (`mecanismes_scan.consumers`, symbole ou nom de
        fichier) — un global de `base.html` (le lecteur audio commun) compte comme un module
        chargé. Rien ne se redéclare ici : la composition se lit du code, elle ne peut pas
        diverger de lui."""
        import os

        from django.conf import settings

        from wama.common.mecanismes import MECHANISMS
        from wama.common.services.mecanismes_scan import code_only, consumers, owners_of_path
        keys = {key for path in (*self.requires, self.mount) if path
                for key in owners_of_path(path)}
        sources = {}
        for path in dict.fromkeys(p for p in (self.script, self.mount) if p):
            found = source_file(path)
            if found:
                rel = os.path.relpath(found, settings.BASE_DIR).replace(os.sep, '/')
                with open(found, encoding='utf-8', errors='ignore') as handle:
                    sources[rel] = code_only(rel, handle.read())
        if sources:
            keys |= {m.key for m in MECHANISMS if consumers(m, sources)}
        return sorted(keys)

    def adoption(self) -> dict:
        """Les apps qui montent une brique de PAGE : l'adoption MESURÉE du (des) mécanisme(s) qui
        tient son fichier de montage (`app_registry.measured_adoption`, le rapport de `/apps/`) —
        `{'apps': {app: True | 'partial' | False}, 'criteria': [...], 'measured_at'}`. Vide pour
        une brique de surface : ce sont ses surfaces qui la montent."""
        from wama.common.app_registry import combined_state, measured_adoption
        from wama.common.services.mecanismes_scan import owners_of_path
        merged = {'apps': {}, 'criteria': [], 'measured_at': None}
        if not self.mount:
            return merged
        states = {}
        for key in owners_of_path(self.mount):
            measure = measured_adoption(key)
            merged['criteria'] += measure['criteria']
            merged['measured_at'] = merged['measured_at'] or measure['measured_at']
            for app, state in measure['apps'].items():
                states.setdefault(app, []).append(state)
        merged['apps'] = {app: combined_state(found) for app, found in sorted(states.items())}
        return merged

    def to_dict(self) -> dict:
        return {'key': self.key, 'name': self.name, 'description': self.description,
                'script': self.script, 'requires': list(self.requires),
                'consumes': list(self.consumes),
                'emits': list(self.emits), 'worlds': list(self.worlds),
                'mount': self.mount, 'declarations': list(self.declarations)}


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
    #: Un champ FICHIER est édité comme TEXTE et validé par la règle commune (`validate_text`) :
    #: `validate` ne se déclare que pour un champ de donnée. Un TUPLE nomme des champs
    #: ALTERNATIFS de même nature : la page édite le premier rempli (`edited`).
    edits: object
    validate: Optional[Callable] = None
    #: Process que l'écriture périme et que « Appliquer » rejoue (`<app>:start_process`).
    reruns: str = ''
    #: L'élément peut-il s'ouvrir dans cette surface ? `(bool, raison)` — la raison s'affiche.
    #: Jugé AVANT la règle commune (un champ fichier vide nomme le process qui le produit).
    available: Optional[Callable] = None
    #: Rôles lus en JSON (document), les autres étant des fichiers servis par URL.
    documents: tuple = ()
    #: Rôles lus en TEXTE (2026-10-16 : la partition complète du composer, ABC en lecture seule à
    #: côté de celle qu'on édite) — le contenu du fichier, '' s'il n'y en a pas.
    texts: tuple = ()
    #: Valeurs de l'élément passées aux briques : nom de champ, ou fonction de l'élément quand la
    #: valeur se lit assainie (`{'classes': lambda media: sane_classes(media.classes2blur)}`).
    context: dict = field(default_factory=dict)
    #: L'élément TÉMOIN sur lequel le nocturne ouvre la surface pour capturer ses briques
    #: (2026-10-18, décision de Fabien : vignettes du catalogue des briques UI) — `{champ: valeur}`,
    #: une DONNÉE, donc aussi écrite au manifeste d'une app générée. Le sens d'une valeur se
    #: DÉDUIT du type du champ, comme `text_value` : pour un champ FICHIER elle nomme un CONTENU,
    #: dans les vocabulaires existants — une extension que `app_registry.media_extensions` range
    #: sous une nature (`.png`, `.md`, `.html`, `.abc`, `.wav`), ou un type de `catalog.data_types`
    #: (`detections`) ; pour un autre champ, c'est la valeur littérale (`media_type: image`). Le
    #: contenu se fabrique au harnais (`ui_smoke.witness_sample`). Vide : aucun témoin, aucune
    #: capture — la page le dit.
    witness: dict = field(default_factory=dict)

    def witness_problems(self) -> list:
        """Ce qui empêche de fabriquer le témoin déclaré — [] s'il se fabrique."""
        from django.db.models import FileField

        from wama.common.app_registry import media_extensions
        from wama.common.catalog.data_types import known_types
        extensions = {ext for exts in media_extensions().values() for ext in exts}
        problems = []
        try:
            meta = self.model_class()._meta
        except Exception as error:
            return [f"surface {self.id} : modèle {self.model} introuvable ({error})"]
        for name, value in (self.witness or {}).items():
            try:
                model_field = meta.get_field(name)
            except Exception:
                problems.append(f"surface {self.id} : témoin — champ inconnu « {name} »")
                continue
            if not isinstance(model_field, FileField):
                continue
            if not isinstance(value, str) or not (
                    value in known_types()
                    or (value.startswith('.') and value[1:].lower() in extensions)):
                problems.append(f"surface {self.id} : témoin — « {name} » attend une extension "
                                f"connue ou un type de données, pas {value!r}")
        return problems

    def context_of(self, item) -> dict:
        return {name: (source(item) if callable(source) else getattr(item, source, None))
                for name, source in self.context.items()}

    @property
    def id(self) -> str:
        return f'{self.app}.{self.key}'

    def model_class(self):
        from django.apps import apps
        return apps.get_model(self.model)

    @property
    def fields(self) -> tuple:
        """Les champs que la page peut écrire — un seul, ou des ALTERNATIFS de même nature."""
        return tuple(self.edits) if isinstance(self.edits, (tuple, list)) else (self.edits,)

    def edited(self, item) -> str:
        """Le champ que la page écrit POUR CET élément : le premier alternatif rempli, sinon le
        premier déclaré (un champ de donnée vide s'édite ; un fichier vide se refuse à l'ouverture)."""
        for name in self.fields:
            value = getattr(item, name, None)
            if (getattr(value, 'name', '') if self.text_value else value):
                return name
        return self.fields[0]

    @property
    def text_value(self) -> bool:
        """Les champs écrits sont-ils des FICHIERS, édités comme texte ? Lu du modèle, jamais
        déclaré ; des alternatifs de natures différentes ne sont pas une surface."""
        from django.db.models import FileField
        try:
            meta = self.model_class()._meta
            return all(isinstance(meta.get_field(name), FileField) for name in self.fields)
        except Exception:
            return False

    def clean(self, value):
        """La valeur reçue de la page, assainie — lève `ValueError` si elle est refusée."""
        if self.text_value:
            return validate_text(value)
        if self.validate is None:
            raise ValueError(f"surface {self.id} : aucune validation déclarée pour « {self.edits} »")
        return self.validate(value)

    def can_open(self, item) -> tuple:
        if self.available is not None:
            ok, reason = self.available(item)
            if not ok:
                return ok, reason
        if self.text_value and not getattr(getattr(item, self.edited(item), None), 'name', ''):
            return False, f"Rien à éditer : lancer d'abord {self._producer_label(item)}."
        return True, ''

    def _producer_label(self, item) -> str:
        """Le libellé du (des) process qui PRODUIT le fichier édité (sa sortie déclarée), lu du
        pipeline de l'élément — sinon le nom du champ. Des alternatifs se disent « ou »."""
        labels = []
        try:
            from wama.common.services.process_pipeline import pipeline_of
            pipeline = pipeline_of(item)
            for name in self.fields:
                for spec in (pipeline.specs if pipeline is not None else ()):
                    if name in (spec.outputs or ()):
                        labels.append(spec.label or spec.key)
        except Exception:
            pass
        return ' ou '.join(f'« {label} »' for label in (labels or self.fields))

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
    page = [s.brick for s in surface.slots if BRICKS[s.brick].is_page]
    if page:
        raise ValueError(f"surface {surface.id} : {page} se monte(nt) par une page, pas sur une "
                         "surface")
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
    key='text_sections', name='Texte en sections',
    description="Un texte structuré (Markdown) découpé en sections à ses titres, chacune éditable "
                "à la main ; l'annuler/rétablir est celui de WAMA (une rafale de frappe = un cran). "
                "Aucune barre de mise en forme : on corrige le FOND, la forme se demande à part "
                "(ROADMAP §21.5, décision n°2).",
    script='common/js/surfaces/brick-text-sections.js',
    consumes=('document',), emits=('document',)))

register_brick(UIBrick(
    key='html_preview', name='Aperçu du document',
    description="Le document rendu (HTML) en lecture seule, dans un cadre isolé — sans script ni "
                "navigation, la règle de l'aperçu de l'inspecteur. On ne l'édite jamais : il se "
                "recharge quand le process qui le produit a été rejoué.",
    script='common/js/surfaces/brick-html-preview.js',
    consumes=('document',)))

register_brick(UIBrick(
    key='revision_history', name='Versions',
    description="Les révisions de l'élément dont le fichier édité a été GARDÉ (`revisions."
                "keep_outputs`, `WAMA_COLLABORATION §7.2`), la plus récente d'abord : qui, quand, "
                "d'où (traitement, correction à la main). « Reprendre » charge le texte d'une "
                "version dans la page — un geste d'édition comme un autre, annulable, que "
                "l'enregistrement fait révision nouvelle : restaurer ne détruit rien (§7.1).",
    script='common/js/surfaces/brick-revision-history.js',
    consumes=('document',), emits=('document',)))

register_brick(UIBrick(
    key='media_transport', name='Transport média',
    description="Le magnéto de la surface : un média attaché à l'AXE partagé (`wama-axis.js`), son "
                "onde (le lecteur commun, pics serveur pour un long fichier), lecture / pause, "
                "début, sauts, vitesse, shuttle J/K/L dont l'arrière silencieux. Il PILOTE l'axe, "
                "jamais une vue (`WAMA_DATA_WORLD §5bis`) ; il dit si le média est périmé par une "
                "modification et le recharge quand le process qui le produit a été rejoué.",
    script='common/js/surfaces/brick-media-transport.js',
    requires=('common/js/wama-axis.js', 'common/js/wama-shuttle.js'),
    consumes=('audio',)))

register_brick(UIBrick(
    key='score_view', name='Partition',
    description="Une partition ABC gravée (abcjs, vendorisé), abonnée à l'axe partagé : les notes "
                "JOUÉES se colorent, voix par voix, et la partition défile avec elles ; un clic sur "
                "une note y amène la lecture. Glisser une note vers le haut ou le bas la transpose "
                "d'un degré par cran — un geste d'édition annulable. Le temps de la PARTITION "
                "guide : chaque temps écrit est calé sur un temps joué de l'audio lu "
                "(`options.media`, grille de `audio_rhythm` servie par `data/?only=rhythm`), "
                "le premier ancré par les hauteurs qui sonnent ; le tempo écrit sinon.",
    script='common/js/surfaces/brick-score-view.js',
    requires=('vendors/abcjs-6.4.4/abcjs-basic-min.js', 'common/js/wama-axis.js',
              'common/js/wama-score.js'),
    consumes=('score',), emits=('score',)))

register_brick(UIBrick(
    key='surface_actions', name='Actions de la surface',
    description="Annuler / rétablir (historique commun), enregistrer, appliquer — rejouer le "
                "process que la modification a périmé.",
    script='common/js/surfaces/brick-surface-actions.js'))


# ── Briques de PAGE (2026-10-19, `ROUTE §F3b`, étape 3) ──────────────────────────────────────
# Une page d'app les monte par un gabarit (ou par la page de base, pour toutes) : elles ne se
# posent pas sur une surface. Elles lisent ce que l'app qui les monte DÉCLARE. La FILE viendra
# quand elle sera une pièce unique (un gabarit commun aux dix apps et au générateur).

register_brick(UIBrick(
    key='entry_card', name="Card d'entrée",
    description="La card « Nouvel élément » en tête de file : un onglet par PORT d'entrée que "
                "l'app déclare (travail, prompt, référence, en direct), et dans sa zone d'aperçu "
                "les modalités du port actif — importer, URL, médiathèque —, qui bascule sur les "
                "fichiers attachés.",
    mount='common/_new_item_card_v4.html',
    declarations=('app.ports', 'app.modes', 'app.capabilities')))

register_brick(UIBrick(
    key='inspector_panel', name='Inspecteur',
    description="Le volet droit d'une page : au clic sur une card, son aperçu, les champs de "
                "détail que l'app déclare, ses réglages rendus du schéma de ses paramètres et les "
                "actions de l'élément ou du lot. Une page d'app le monte par ses actions ; le "
                "volet lui-même est l'ossature de la page de base.",
    script='common/js/wama-inspector.js',
    mount='common/_inspector_actions.html',
    declarations=('app.inspector', 'app.params')))

register_brick(UIBrick(
    key='media_viewer', name='Visionneuse',
    description="L'élément en grand : ses faces — Entrée, une par process du pipeline de la "
                "card, Sortie —, la comparaison et les surcouches de détection ; aussi la galerie "
                "sans élément (les vignettes de ce catalogue). La page de base la charge pour "
                "toutes les pages.",
    mount='common/js/media-preview.js',
    declarations=('app.inspector', 'pipeline')))
