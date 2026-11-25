"""
MARQUES — les événements et les segments d'une card, lus sous UN vocabulaire, dans les trois mondes.

Marche 1 de `WAMA_APP_GENERATION_ROUTE.md §10.7` (décisions de Fabien du 2026-11-24 : D6 le modèle
de marques vit dans la glu inter-mondes, D7 les noms communs sont lus sans toucher au stockage, D13
une piste déclare son axe). `data_types.py` écrit depuis août qu'« une transcription EST une
collection de segments » — mais le Transcriber range `start_time` / `end_time`, le cam_analyzer
`t_enter` / `t_exit`, le monde Data `start` / `end`, et rien ne faisait la traduction. Ce module
EST cette traduction : une app DÉCLARE ses pistes, un seul lecteur les rend.

VOCABULAIRE (dictionnaire : `docs/construction/architecture/WAMA_CONCEPTS.md`)
  • une MARQUE est un événement (`time`) ou un segment (`start`, `end` — `None` = segment OUVERT,
    la convention de `wama_data.core.segmentation.OPEN_END`) ; elle porte son `origin` ;
  • une PISTE est un ensemble nommé de marques de même niveau sur un AXE ;
  • une piste peut avoir une piste PARENTE : c'est l'imbrication des marques (tour de parole >
    phrase > mot), sans borne d'étages — chaque marque dit alors `parent`, le rang de sa marque
    parente dans la piste parente.

LA PISTE DÉRIVÉE (`§10.7.14 ⑰`, marche 1ter) : une piste source + la LISTE ordonnée des gestes faits
dessus (scinder, fusionner, masquer, étiqueter…). On persiste la déclaration, pas les valeurs : la
source n'est jamais modifiée, le lecteur REJOUE les gestes (`read_derived`, `apply_edits`) et dit
ceux qui ne s'appliquent plus. `effective_line` rend ce qui reste après les masques.

CE QUE CE MODULE NE FAIT PAS : il n'écrit rien, ne déplace aucun stockage (où se range la liste des
gestes d'une card est l'affaire de son monde), et ne calcule rien sur les marques (« présent
dans », filtre, indicateur par segment restent au Segmenter). Ce qu'il rend a la FORME que ces
fonctions lisent déjà (`start`, `end`, `origin`) — c'est tout l'intérêt.

Sans Django : le lecteur ne connaît que des objets et des dictionnaires.
"""
from __future__ import annotations

from dataclasses import dataclass
from importlib import import_module
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple, Union

from ..utils.detections import CORRECTION_MIN_IOU
from ..utils.intervals import overlap_ratio
from .data_types import DataType

#: Les AXES qu'une piste peut déclarer (D13). Seul `time` (secondes) est servi aujourd'hui ; les
#: autres sont nommés pour qu'une piste d'un autre axe ne soit jamais une migration.
AXES = ('time', 'distance', 'frame', 'text', 'page')

#: Ce que les marques d'une piste doivent à leur marque parente.
INCLUSION = 'inclusion'      # dans ses bornes, trous permis (les mots d'une phrase)
PARTITION = 'partition'      # la couvrent sans trou ni chevauchement (les plans d'une séquence)
CONSTRAINTS = ('', INCLUSION, PARTITION)

#: Tolérance par défaut des contraintes, en unités de l'axe — la valeur de `MIN_SECTION` dans la
#: brique des règles de segments de la page d'édition : en deçà, deux bornes sont la même.
TOLERANCE = 0.05

#: Les ÉCHELLES de couleur d'une piste (`ROUTE §10.7.13 ⑭`) — la piste dit l'attribut coloré
#: (`color_by`) et l'échelle (`scale`) ; l'écran n'en invente aucune. L'ÉTAT (attente, en cours,
#: échec…) n'en est pas une : il est réservé à l'avancement.
CATEGORY = 'category'        # une couleur par valeur (locuteur, type) — aucun repère
SEVERITY = 'severity'        # trois niveaux, du plus bénin au plus grave ; hors d'eux = inconnu
INTENSITY = 'intensity'      # une grandeur continue, de sa borne calme à sa borne critique
SCALES = (CATEGORY, SEVERITY, INTENSITY)
#: Le nombre de repères (`steps`) que chaque échelle demande.
STEPS = {CATEGORY: 0, SEVERITY: 3, INTENSITY: 2}

#: Les GESTES qu'une piste peut permettre (`ROUTE §10.7.12 ⑤`, `§10.7.14`). Une piste qui n'en
#: déclare aucun se regarde seulement.
EXTRACT = 'extract'          # une card dérivée ajustée au segment — ne change pas la piste
GESTURES = ('retime', 'move', 'reorder', 'split', 'merge', 'mask', 'add', 'delete', 'label',
            EXTRACT)
#: Où vont les gestes qui changent la piste : une piste DÉRIVÉE (la source et la liste des gestes,
#: la source intacte — le monde Data) ou la piste elle-même.
DERIVED, IN_PLACE = 'derived', 'in_place'
EDITS = ('', DERIVED, IN_PLACE)

#: Un GESTE fait sur une piste est une DONNÉE (ce qu'on range, ce qu'on rejoue) :
#:   `gesture`  lequel ; `was` les bornes de la marque visée au moment du geste — c'est par sa
#:   PLACE qu'un geste désigne sa cible (la règle des corrections humaines de WAMA,
#:   `utils/detections.apply_corrections`), et c'est l'« avant » de sa trace ; `mark` le rang où
#:   elle était, qui ne départage que deux marques à la même place ;
#:   puis ce que CE geste demande (`EDIT_DETAILS`) : `at` où scinder ; `count` combien de marques
#:   fusionner (2 par défaut) ; `set` les attributs posés ; `start` / `end` / `time` les bornes
#:   neuves ; `to` où déplacer (une position sur l'axe) ou réordonner (un rang) ;
#:   et sa trace (`EDIT_TRACE`) : qui, quand, pourquoi — gardés, jamais interprétés.
#: Pour `add`, `mark` est le rang où la marque s'insère (omis : à sa place sur l'axe).
EDIT_DETAILS = {'split': ('at',), 'merge': ('count',), 'mask': (), 'label': ('set',),
                'delete': (), 'retime': ('start', 'end'), 'move': ('to',), 'reorder': ('to',),
                'add': ('start', 'end', 'time', 'set')}
EDIT_TRACE = ('by', 'on', 'note')
#: Les gestes qui demandent une DURÉE : un événement ne se scinde, ne se fusionne ni ne se retaille.
SEGMENT_GESTURES = ('split', 'merge', 'retime')
#: L'attribut d'une ÉTIQUETTE posée par un geste, quand la piste n'en porte pas d'autre (le nom de
#: la colonne que le codage du monde Data écrit déjà).
LABEL = 'label'
#: L'origine d'une marque AJOUTÉE par un geste.
ADDED = 'added'
#: Les noms que le LECTEUR écrit dans une marque (ses bornes, son origine, sa parente, et ce qu'une
#: piste dérivée y ajoute). Aucun attribut ne se lit sous l'un d'eux — il serait écrasé sans bruit :
#: la déclaration le lit sous un autre nom commun (`('nom commun', 'nom rangé')`).
RESERVED = ('start', 'end', 'time', 'origin', 'parent', 'source', 'touched', 'masked')


class InvalidTracks(ValueError):
    """Une déclaration de pistes incohérente — refusée à l'enregistrement, pas à la lecture."""


class InvalidEdit(ValueError):
    """Un geste qui ne peut pas se faire sur la piste telle qu'elle est — refusé quand on l'AJOUTE
    à la liste (`extend_edits`), pour qu'aucun geste inapplicable n'y entre."""


@dataclass(frozen=True)
class Track:
    """Une piste DÉCLARÉE par une app. Trois façons de dire d'où viennent ses lignes :

      • `source` — un attribut de la card (une liste, un champ JSON, un gestionnaire de lignes
        liées), une fonction `f(card)`, ou son chemin pointé `'paquet.module:fonction'` (lu à la
        première lecture : un `apps.py` ne charge pas ses vues au démarrage) ;
      • `within` — la clé de la liste d'enfants DANS chaque ligne de la piste parente (les `words`
        d'une phrase) : l'imbrication écrite en document ;
      • `runs_of` + `by` — une piste CALCULÉE : les suites de marques consécutives d'une autre piste
        qui partagent la valeur `by` (les tours de parole, des phrases d'un même locuteur). ⚠ Le
        mot « dérivée » est réservé à la piste source + ses gestes (`read_derived`).

    `fields` : nom commun → nom rangé (`{'start': 't_enter', 'end': 't_exit'}`) ; un nom absent se
    lit sous son nom commun. `attributes` : ce que la marque garde en plus, sous son nom commun
    (`'text'`) ou renommé (`('speaker', 'speaker_id')`).

    Le PARENT d'une marque se résout, dans cet ordre : par construction (`within`, `runs_of`), par
    référence (`parent_ref` : le champ de la ligne qui porte le rang de sa marque parente, négatif
    = aucune), sinon par CONTENANCE — la marque parente dont les bornes contiennent son début.

    Ce que l'écran et les gestes ont à savoir se déclare ICI, jamais dans une page (`§10.7.14`) :
      • `main` — la piste PRINCIPALE du porteur, celle de la ligne segmentée de sa zone temporelle
        (une seule ; les autres se déplient) ;
      • `color_by` + `scale` (+ `steps`) — l'attribut qui colore ses marques et l'échelle : pour
        `severity`, ses trois valeurs de la plus bénigne à la plus grave ; pour `intensity`, ses
        deux bornes, de la calme à la critique (dans cet ordre, croissant ou non) ;
      • `gestures` — ce qu'on peut y faire ; `edits` — où vont les gestes qui la changent.
    """
    key: str
    label: str
    source: Union[str, Callable, None] = None
    kind: str = DataType.SEGMENTS
    axis: str = 'time'
    fields: Tuple[Tuple[str, str], ...] = ()
    attributes: Tuple[Any, ...] = ()
    parent: str = ''
    constraint: str = ''
    within: str = ''
    parent_ref: str = ''
    runs_of: str = ''
    by: str = ''
    origin: str = ''
    origin_field: str = ''
    main: bool = False
    color_by: str = ''
    scale: str = ''
    steps: Tuple[Any, ...] = ()
    gestures: Tuple[str, ...] = ()
    edits: str = ''

    def __post_init__(self):
        # Les gestes sont un ENSEMBLE (triés, sans double) ; les repères une suite ORDONNÉE.
        object.__setattr__(self, 'gestures', tuple(sorted({str(g) for g in self.gestures})))
        object.__setattr__(self, 'steps', tuple(self.steps))
        # Forme CANONIQUE : `fields` et `attributes` triés par nom commun, un attribut gardé sous
        # son propre nom écrit seul. L'ordre n'y porte aucun sens, et un manifeste range ses clés
        # triées : sans cela, la piste relue d'un manifeste ne serait plus égale à celle déclarée.
        pairs = sorted((str(common), str(stored)) for common, stored in dict(self.fields).items())
        kept = {}
        for attribute in self.attributes:
            common, stored = attribute if isinstance(attribute, (tuple, list)) else (attribute, attribute)
            kept[str(common)] = str(stored)
        object.__setattr__(self, 'fields', tuple(pairs))
        object.__setattr__(self, 'attributes', tuple(
            common if common == stored else (common, stored) for common, stored in sorted(kept.items())))

    def stored(self, name: str) -> str:
        """Le nom RANGÉ d'un nom commun."""
        return dict(self.fields).get(name, name)

    def carried(self) -> Tuple[str, ...]:
        """Les noms communs de ce que ses marques portent en plus de leurs bornes."""
        names = [a if isinstance(a, str) else a[0] for a in self.attributes]
        return tuple(names + ([self.by] if self.runs_of and self.by else []))


_DEFAULTS = Track(key='', label='')


def track_to_dict(track: Track) -> dict:
    """La déclaration d'une piste en DONNÉE (ce que porte la facette `inspector.tracks` d'un
    manifeste d'app) : ses seuls champs qui ne sont pas à leur défaut ; `fields` et `attributes`
    en dictionnaires `nom commun → nom rangé`. Une source qui est une fonction en mémoire ne
    s'écrit pas : une app la déclare par son chemin pointé."""
    if track.source is not None and not isinstance(track.source, str):
        raise InvalidTracks(f"piste « {track.key} » : une source qui est une fonction ne se "
                            f"range pas dans un manifeste — la nommer par 'module:fonction'")
    data = {'key': track.key, 'label': track.label}
    for name in ('source', 'kind', 'axis', 'parent', 'constraint', 'within', 'parent_ref',
                 'runs_of', 'by', 'origin', 'origin_field', 'main', 'color_by', 'scale', 'edits'):
        value = getattr(track, name)
        if value != getattr(_DEFAULTS, name):
            data[name] = value
    for name in ('steps', 'gestures'):
        if getattr(track, name):
            data[name] = list(getattr(track, name))
    if track.fields:
        data['fields'] = dict(track.fields)
    if track.attributes:
        data['attributes'] = {(a if isinstance(a, str) else a[0]): (a if isinstance(a, str) else a[1])
                              for a in track.attributes}
    return data


def track_from_dict(data: dict) -> Track:
    """L'inverse de `track_to_dict` — la piste que le générateur écrit dans le `apps.py` d'une app
    née de son manifeste. Un attribut gardé sous son propre nom redevient un nom seul."""
    known = {name for name in Track.__dataclass_fields__}
    extra = sorted(set(data) - known)
    if extra:
        raise InvalidTracks(f"piste « {data.get('key')} » : champ(s) inconnu(s) {', '.join(extra)}")
    values = {k: (tuple(v) if k in ('steps', 'gestures') else v)
              for k, v in data.items() if k not in ('fields', 'attributes')}
    values['fields'] = tuple((str(k), str(v)) for k, v in (data.get('fields') or {}).items())
    values['attributes'] = tuple(k if k == v else (k, v)
                                 for k, v in (data.get('attributes') or {}).items())
    return Track(**values)


_REGISTRY: Dict[str, Tuple[Track, ...]] = {}


def _label_of(model_or_card) -> str:
    if isinstance(model_or_card, str):
        return model_or_card.lower()
    meta = getattr(model_or_card, '_meta', None)
    return str(getattr(meta, 'label_lower', '') or '')


def _display_problems(track: Track) -> List[str]:
    """Les défauts de ce qu'une piste déclare pour l'écran et les gestes."""
    problems = []
    if bool(track.color_by) != bool(track.scale):
        problems.append("`color_by` et `scale` se déclarent ensemble")
    if track.scale and track.scale not in SCALES:
        problems.append(f"échelle « {track.scale} » inconnue ({', '.join(SCALES)})")
    if track.color_by and track.color_by not in track.carried():
        problems.append(f"colorée par « {track.color_by} », que ses marques ne portent pas")
    if len(track.steps) != STEPS.get(track.scale, 0):
        problems.append(f"l'échelle « {track.scale or 'aucune'} » demande "
                        f"{STEPS.get(track.scale, 0)} repère(s), {len(track.steps)} déclaré(s)")
    elif track.scale == INTENSITY and (
            any(isinstance(s, bool) or not isinstance(s, (int, float)) for s in track.steps)
            or track.steps[0] == track.steps[1]):
        problems.append("une intensité a deux bornes numériques distinctes")
    elif len(set(track.steps)) != len(track.steps):
        problems.append("un repère déclaré deux fois")
    unknown = [gesture for gesture in track.gestures if gesture not in GESTURES]
    if unknown:
        problems.append(f"geste(s) inconnu(s) {', '.join(unknown)}")
    if track.edits not in EDITS:
        problems.append(f"`edits` « {track.edits} » inconnu ({DERIVED} ou {IN_PLACE})")
    changing = [gesture for gesture in track.gestures if gesture != EXTRACT]
    if bool(changing) != bool(track.edits):
        problems.append("des gestes qui changent la piste demandent `edits`, et `edits` de tels gestes")
    on_segments = [gesture for gesture in track.gestures if gesture in SEGMENT_GESTURES]
    if track.kind == DataType.EVENTS and on_segments:
        problems.append(f"un événement n'a pas de durée : {', '.join(on_segments)} ne s'y font pas")
    return problems


def validate(tracks: Iterable[Track]) -> List[str]:
    """Les défauts d'une déclaration, en clair — liste vide = cohérente."""
    tracks = list(tracks)
    by_key, problems = {}, []
    for track in tracks:
        if track.key in by_key:
            problems.append(f"piste « {track.key} » déclarée deux fois")
        by_key[track.key] = track
    mains = [track.key for track in tracks if track.main]
    if len(mains) > 1:
        problems.append(f"plusieurs pistes principales ({', '.join(mains)}) : une seule par porteur")
    for track in tracks:
        name = f"piste « {track.key} »"
        problems += [f"{name} : {problem}" for problem in _display_problems(track)]
        if track.kind not in (DataType.SEGMENTS, DataType.EVENTS):
            problems.append(f"{name} : type « {track.kind} » (attendu segments ou events)")
        if track.axis not in AXES:
            problems.append(f"{name} : axe « {track.axis} » inconnu ({', '.join(AXES)})")
        clash = sorted(set(track.carried()) & set(RESERVED))
        if clash:
            problems.append(f"{name} : attribut(s) {', '.join(clash)} sous un nom que le lecteur "
                            f"écrit — le lire sous un autre nom commun")
        if track.constraint not in CONSTRAINTS:
            problems.append(f"{name} : contrainte « {track.constraint} » inconnue")
        ways = [bool(track.source), bool(track.within), bool(track.runs_of)]
        if sum(ways) != 1:
            problems.append(f"{name} : UNE origine des lignes, parmi source, within et runs_of")
        if track.parent and track.parent not in by_key:
            problems.append(f"{name} : piste parente « {track.parent} » non déclarée")
        if (track.within or track.parent_ref or track.constraint) and not track.parent:
            problems.append(f"{name} : within, parent_ref et constraint demandent une piste parente")
        if track.runs_of and (track.runs_of not in by_key or not track.by):
            problems.append(f"{name} : runs_of demande une piste déclarée et le champ `by`")
        if track.parent and by_key.get(track.parent) is not None \
                and by_key[track.parent].axis != track.axis:
            problems.append(f"{name} : n'est pas sur l'axe de sa piste parente")
        # Deux chaînes doivent FINIR : celle des parentes, et celle des pistes calculées. Elles se
        # suivent à part — une piste calculée peut être la parente de celle qu'elle regroupe (les
        # tours, suites de phrases d'un même locuteur, sont au-dessus des phrases) : la calculée
        # se lit sur les marques nues de l'autre, ce n'est pas une boucle.
        for link, word in ((lambda t: t.parent, 'lignée'), (lambda t: t.runs_of, 'dérivation')):
            seen, cursor = {track.key}, by_key.get(link(track))
            while cursor is not None:
                if cursor.key in seen:
                    problems.append(f"{name} : sa {word} revient sur « {cursor.key} »")
                    break
                seen.add(cursor.key)
                cursor = by_key.get(link(cursor))
    return problems


def register_tracks(model, tracks: Iterable[Track]) -> None:
    """Déclare les pistes des cards de `model` (une classe de modèle, ou `'app.Modele'`) — dans le
    `ready()` de l'app, comme sa spec de détail. Une déclaration incohérente est REFUSÉE ici."""
    tracks = tuple(tracks)
    problems = validate(tracks)
    label = _label_of(model)
    if not label:
        problems.append("modèle sans étiquette (`_meta.label_lower`)")
    if problems:
        raise InvalidTracks(f"{label or model} : " + ' ; '.join(problems))
    _REGISTRY[label] = tracks


def registered() -> Dict[str, Tuple[Track, ...]]:
    """Toutes les déclarations, par étiquette de modèle — ce que lit la garde générique."""
    return dict(_REGISTRY)


def tracks_of(model_or_card) -> Tuple[Track, ...]:
    """Les pistes déclarées pour ce modèle ou cette card ; () quand l'app n'en déclare pas."""
    return _REGISTRY.get(_label_of(model_or_card), ())


#: La place, dans le contexte d'UNE lecture, des pistes qu'elle lit (par clé, dans l'ordre dit).
_STATED = ('stated',)


def _context(holder, tracks: Optional[Iterable[Track]] = None) -> dict:
    """Le contexte d'UNE lecture : les pistes lues et ce qui a déjà été lu. Les pistes sont celles
    que l'app a déclarées pour ce modèle, ou celles DITES SUR PLACE (`tracks`) quand la source les
    porte elle-même — un fichier de données dit ses flux, aucune app n'a à les déclarer. Dites sur
    place, elles passent le même contrôle qu'à l'enregistrement."""
    if tracks is None:
        tracks = tracks_of(holder)
    else:
        tracks = tuple(tracks)
        problems = validate(tracks)
        if problems:
            raise InvalidTracks(' ; '.join(problems))
    return {_STATED: {track.key: track for track in tracks}}


def _track(card, key: str, cache: dict) -> Track:
    track = cache[_STATED].get(key)
    if track is None:
        raise KeyError(f"{_label_of(card) or type(card).__name__} : aucune piste « {key} » déclarée")
    return track


def _get(row, name: str, default=None):
    if isinstance(row, dict):
        return row.get(name, default)
    return getattr(row, name, default)


def _number(value) -> Optional[float]:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _rows(card, source) -> list:
    """Les lignes d'une source : une fonction (ou son chemin pointé) appelée avec la card, sinon
    un attribut de la card — une liste, ou un gestionnaire de lignes liées (`.all()`)."""
    if isinstance(source, str) and ':' in source:
        module, _, name = source.partition(':')
        source = getattr(import_module(module), name)
    if callable(source):
        value = source(card)
    else:
        value = getattr(card, source, None)
        if callable(getattr(value, 'all', None)):
            value = value.all()
    return [row for row in (value or ()) if row is not None]


def _mark(track: Track, row) -> Optional[dict]:
    """La marque d'une ligne, sous les noms communs — None quand elle n'a pas de temps (un texte
    importé sans horodatage n'est pas une marque : il ne s'invente pas de bornes)."""
    if track.kind == DataType.EVENTS:
        time = _number(_get(row, track.stored('time')))
        if time is None:
            return None
        mark = {'time': time}
    else:
        start = _number(_get(row, track.stored('start')))
        if start is None:
            return None
        mark = {'start': start, 'end': _number(_get(row, track.stored('end')))}
    for attribute in track.attributes:
        name, stored = attribute if isinstance(attribute, (tuple, list)) else (attribute, attribute)
        value = _get(row, stored)
        if value is not None and value != '':
            mark[name] = value
    origin = (_get(row, track.origin_field) if track.origin_field else '') or track.origin
    mark['origin'] = origin or track.key
    return mark


def _starts_at(mark: dict) -> float:
    return mark['time'] if 'time' in mark else mark['start']


def _holder(parents: List[dict], mark: dict) -> Optional[int]:
    """Par CONTENANCE : le rang de la marque parente dont les bornes contiennent le début de
    `mark` — une fin ouverte contient tout instant postérieur (`times_within` côté Data)."""
    at = _starts_at(mark)
    for index, parent in enumerate(parents):
        if 'start' not in parent or at < parent['start']:
            continue
        if parent['end'] is None or at < parent['end'] or (at == parent['end'] == parent['start']):
            return index
    return None


def _runs(track: Track, marks: List[dict]) -> List[dict]:
    """Les suites de marques consécutives qui partagent `by` : du début de la première à la fin de
    la dernière (ouverte si la dernière l'est)."""
    out: List[dict] = []
    for mark in marks:
        if 'start' not in mark:
            continue
        value = mark.get(track.by)
        if out and out[-1].get(track.by) == value:
            out[-1]['end'] = mark['end']
            continue
        run = {'start': mark['start'], 'end': mark['end'], 'origin': track.origin or 'runs'}
        if value is not None:
            run[track.by] = value
        out.append(run)
    return out


def _read(card, track: Track, cache: dict) -> List[dict]:
    if track.key in cache:
        return cache[track.key]
    marks: List[dict] = []
    cache[track.key] = marks            # posé d'abord : une lecture ne se relance pas elle-même
    if track.runs_of:
        base = _track(card, track.runs_of, cache)
        # Ses marques SANS leur parent (qui peut être cette piste même) : lues à part.
        raw = [m for m in (_mark(base, row) for row in _source_rows(card, base, cache)) if m]
        marks.extend(_runs(track, raw))
    else:
        for row, built_parent in _source_rows_with_parent(card, track, cache):
            mark = _mark(track, row)
            if mark is None:
                continue
            if track.parent:
                parents = _read(card, _track(card, track.parent, cache), cache)
                if built_parent is not None:
                    mark['parent'] = built_parent
                elif track.parent_ref:
                    ref = _get(row, track.parent_ref)
                    mark['parent'] = ref if isinstance(ref, int) and 0 <= ref < len(parents) else None
                else:
                    mark['parent'] = _holder(parents, mark)
            marks.append(mark)
    return marks


def _source_rows(card, track: Track, cache: dict) -> list:
    return [row for row, _parent in _source_rows_with_parent(card, track, cache)]


def _source_rows_with_parent(card, track: Track, cache: dict) -> List[tuple]:
    """Les lignes d'une piste et, quand l'imbrication est écrite en document (`within`), le rang
    de la marque parente de chacune — le rang parmi les marques parentes RENDUES (une ligne
    parente sans temps n'est pas une marque, ses enfants n'ont alors pas de parent)."""
    if not track.within:
        # Une source se lit UNE fois par lecture (une piste calculée et sa base la partagent).
        slot = ('rows', track.key)
        if slot not in cache:
            cache[slot] = _rows(card, track.source)
        return [(row, None) for row in cache[slot]]
    parent = _track(card, track.parent, cache)
    out, rank = [], 0
    for parent_row in _source_rows(card, parent, cache):
        timed = _mark(parent, parent_row) is not None
        for row in (_get(parent_row, track.within) or ()):
            if row is not None:
                out.append((row, rank if timed else None))
        rank += timed
    return out


def read_tracks(card, tracks: Optional[Iterable[Track]] = None) -> Dict[str, List[dict]]:
    """Toutes les pistes d'une card : `{clé: [marques]}`, dans l'ordre déclaré. Les sources ne
    sont lues qu'une fois. `tracks` : des pistes DITES SUR PLACE, pour un porteur qu'aucune app ne
    déclare (les flux d'un fichier de données) — `card` est alors ce que lisent leurs sources."""
    cache = _context(card, tracks)
    return {key: _read(card, track, cache) for key, track in cache[_STATED].items()}


def read_track(card, key: str, tracks: Optional[Iterable[Track]] = None) -> List[dict]:
    """Les marques d'UNE piste d'une card, sous les noms communs : `start`, `end` (`None` =
    ouvert) ou `time`, `origin`, ses attributs déclarés, et `parent` (le rang de sa marque parente
    dans la piste parente, `None` si elle n'en a pas) quand la piste en déclare une. L'ordre est
    celui de la source : c'est une donnée (le rang), il n'est pas retrié."""
    cache = _context(card, tracks)
    return _read(card, _track(card, key, cache), cache)


def violations(card, key: str, tolerance: float = TOLERANCE,
               tracks: Optional[Iterable[Track]] = None,
               edits: Optional[Iterable[dict]] = None) -> List[str]:
    """Ce que les marques d'une piste doivent à leurs marques parentes et ne tiennent pas —
    liste vide = la contrainte déclarée est tenue (ou la piste n'en déclare pas). INCLUSION :
    chaque marque a une parente et tient dans ses bornes. PARTITION : en plus, les marques d'une
    même parente la couvrent sans trou ni chevauchement. `edits` : la contrainte se contrôle sur
    la piste DÉRIVÉE par ces gestes (un segment retaillé hors de sa marque parente se voit ici)."""
    cache = _context(card, tracks)
    track = _track(card, key, cache)
    if not track.constraint:
        return []
    marks = _read(card, track, cache)
    if edits is not None:
        marks, _stale = _derived(card, track, edits, cache, tolerance)
    parents = _read(card, _track(card, track.parent, cache), cache)
    problems, children = [], {}
    for rank, mark in enumerate(marks):
        index = mark.get('parent')
        if index is None:
            problems.append(f"{key}[{rank}] : aucune marque parente")
            continue
        parent = parents[index]
        start, end = _starts_at(mark), mark.get('end', _starts_at(mark))
        if start < parent['start'] - tolerance or (
                parent['end'] is not None
                and (end if end is not None else start) > parent['end'] + tolerance):
            problems.append(f"{key}[{rank}] : hors des bornes de {track.parent}[{index}]")
        children.setdefault(index, []).append(mark)
    if track.constraint == PARTITION:
        for index, kids in children.items():
            parent, cursor = parents[index], parents[index]['start']
            for kid in sorted(kids, key=_starts_at):
                if abs(_starts_at(kid) - cursor) > tolerance:
                    problems.append(f"{track.parent}[{index}] : trou ou chevauchement à {cursor:g}")
                cursor = kid.get('end')
                if cursor is None:
                    break
            if cursor is not None and parent['end'] is not None \
                    and abs(parent['end'] - cursor) > tolerance:
                problems.append(f"{track.parent}[{index}] : non couverte après {cursor:g}")
    return problems


# ══════════════════════════════════════════════════════════════════════════════════════════════
# LA PISTE DÉRIVÉE — une piste source + la liste ordonnée des gestes (`ROUTE §10.7.14 ⑰`)
# ══════════════════════════════════════════════════════════════════════════════════════════════
# Une marque d'une piste dérivée porte, en plus de celles de sa source : `source`, les rangs des
# marques de la source dont elle vient (une seule, deux après une fusion, aucune si elle a été
# ajoutée) ; `touched`, les rangs des gestes qui l'ont changée (absent : intacte) ; `masked` quand
# elle est masquée — elle reste dans la piste, c'est `effective_line` qui la saute.

def _near(a, b, tolerance: float) -> bool:
    if a is None or b is None:
        return a is None and b is None
    return abs(a - b) <= tolerance


def _rank(value, low: int, high: int) -> bool:
    """`value` est-il un rang entre `low` et `high` compris ?"""
    return isinstance(value, int) and not isinstance(value, bool) and low <= value <= high


def _bounds(mark: dict) -> dict:
    """Les bornes qu'un geste retient de sa cible (`was`)."""
    if 'time' in mark:
        return {'time': mark['time']}
    return {'start': mark['start'], 'end': mark.get('end')}


def _span(edit: dict) -> int:
    """Le nombre de marques que prend un geste : `count` pour une fusion (la marque désignée et
    celles qui la suivent), une sinon."""
    count = edit.get('count', 2) if edit.get('gesture') == 'merge' else 1
    return count if _rank(count, 1, 10 ** 9) else 0


def _still(now: dict, was: dict, tolerance: float) -> float:
    """À quel point une marque est ENCORE celle qu'un geste a désignée par ses bornes `was`, de 0
    à 1. Deux segments : leur recouvrement (intersection / union). Un instant, un segment ouvert
    ou sans durée : le même début, à la tolérance près."""
    if 'time' in now:
        at = _number(was.get('time'))
        return 1.0 if at is not None and abs(now['time'] - at) <= tolerance else 0.0
    start, end = _number(was.get('start')), _number(was.get('end'))
    if start is None or 'time' in was:
        return 0.0
    if end is None or now['end'] is None or end - start <= tolerance \
            or now['end'] - now['start'] <= tolerance:
        return 1.0 if abs(now['start'] - start) <= tolerance else 0.0
    return overlap_ratio((now['start'], now['end']), (start, end))


def _target(marks: List[dict], edit: dict, tolerance: float) -> Tuple[Optional[int], Optional[str]]:
    """Le rang de la marque qu'un geste désigne, ou la raison pour laquelle il ne la trouve plus.

    Un geste désigne sa cible par sa PLACE — les bornes qu'il a retenues (`was`) —, pas par un
    rang ni par des bornes exactes : c'est la règle des corrections humaines de WAMA
    (`utils/detections.apply_corrections`, « vivre à part pour survivre à une détection
    relancée »), et son seuil (`CORRECTION_MIN_IOU`). La cible est la marque qui recouvre le
    mieux `was` ; en dessous du seuil, la marque n'est plus là et le geste se saute. `mark`, le
    rang où elle était, ne départage que deux marques à la même place."""
    was = edit.get('was')
    if not isinstance(was, dict):
        return None, "ne dit pas quelle marque il vise (`was`)"
    best, found = 0.0, None
    for rank, mark in enumerate(marks):
        score = _still(_bounds(mark), was, tolerance)
        if score > best or (found is not None and score == best and rank == edit.get('mark')):
            best, found = score, rank
    if found is None or best < CORRECTION_MIN_IOU:
        return None, "la marque qu'il visait n'est plus dans la piste"
    span = _span(edit)
    if span < 1 or found + span > len(marks):
        return None, "ne désigne pas autant de marques dans la piste"
    return found, None


def _settable(track: Track, values) -> Optional[str]:
    """Pourquoi ces attributs ne se posent pas — un geste ne pose que ce que la piste porte, ou
    une étiquette (`LABEL`) ; jamais une borne ni ce que le lecteur écrit (`RESERVED`, qu'aucune
    piste ne porte)."""
    if not isinstance(values, dict) or not values:
        return "`set` attend des attributs"
    allowed = (set(track.carried()) | {LABEL}) - set(RESERVED)
    refused = sorted(str(name) for name in values if name not in allowed)
    return f"attribut(s) que la piste ne porte pas : {', '.join(refused)}" if refused else None


def _set(mark: dict, values: dict) -> None:
    for name, value in values.items():
        if value is None or value == '':
            mark.pop(name, None)
        else:
            mark[name] = value


def _touch(mark: dict, index: int) -> None:
    mark['touched'] = sorted(set(mark.get('touched', ())) | {index})


def _add(track: Track, marks: List[dict], index: int, edit: dict) -> Optional[str]:
    values = edit.get('set') or {}
    reason = _settable(track, values) if values else None
    if reason:
        return reason
    if track.kind == DataType.SEGMENTS:
        start, end = _number(edit.get('start')), _number(edit.get('end'))
        if start is None or 'time' in edit or (end is not None and end < start):
            return "un segment s'ajoute par son début (`start`) et sa fin (`end`, absente = ouvert)"
        mark = {'start': start, 'end': end}
    else:
        time = _number(edit.get('time'))
        if time is None or {'start', 'end'} & set(edit):
            return "un événement s'ajoute à un instant (`time`)"
        mark = {'time': time}
    rank = edit.get('mark')
    if rank is None:
        # À sa place sur l'axe : après la dernière marque qui commence avant elle.
        rank = max((i + 1 for i, other in enumerate(marks)
                    if _starts_at(other) <= _starts_at(mark)), default=0)
    elif not _rank(rank, 0, len(marks)):
        return "`mark` attend le rang où l'ajouter"
    _set(mark, values)
    mark.update(origin=ADDED, source=[], touched=[index])
    if track.parent:
        mark['parent'] = None              # le lecteur la retrouve par contenance (`read_derived`)
    marks.insert(rank, mark)
    return None


def _apply(track: Track, marks: List[dict], index: int, edit, tolerance: float) -> Optional[dict]:
    """Applique UN geste à `marks` (sur place) et rend ce qu'il y a à en DIRE, None quand il s'est
    fait sur la marque même qu'il visait : `{'applied': False, 'reason'}` s'il est sauté (rien
    n'a changé : un geste se fait en entier ou pas du tout) ; `{'applied': True, 'reason', 'was',
    'now'}` s'il s'est fait sur une marque dont les bornes ont bougé depuis."""
    found = {}
    reason = _do(track, marks, index, edit, tolerance, found)
    if reason:
        return {'applied': False, 'reason': reason}
    was, now = edit.get('was'), found.get('bounds')
    if now is not None and not all(_near(_number(was.get(name)), now[name], tolerance)
                                   for name in now):
        return {'applied': True, 'reason': "fait sur une marque dont les bornes ont bougé",
                'was': dict(was), 'now': now}
    return None


def _do(track: Track, marks: List[dict], index: int, edit, tolerance: float,
        found: Optional[dict] = None) -> Optional[str]:
    """Applique UN geste à `marks` (sur place), ou rend la raison de son refus — sans rien avoir
    changé. `found` reçoit les bornes de la marque désignée, telles qu'elles étaient avant lui."""
    if not isinstance(edit, dict):
        return "n'est pas un geste"
    gesture = edit.get('gesture')
    if gesture not in EDIT_DETAILS:
        return "n'est pas un geste qui change une piste"
    unknown = sorted(str(name) for name in set(edit) - {'gesture', 'mark', 'was'}
                     - set(EDIT_DETAILS[gesture]) - set(EDIT_TRACE))
    if unknown:
        return f"champ(s) que ce geste ne prend pas : {', '.join(unknown)}"
    if gesture not in track.gestures:
        return "la piste ne le permet pas"
    segments = track.kind == DataType.SEGMENTS
    if gesture in SEGMENT_GESTURES and not segments:
        return "ne se fait que sur un segment"
    if gesture == 'add':
        return _add(track, marks, index, edit)
    rank, reason = _target(marks, edit, tolerance)
    if reason:
        return reason
    mark = marks[rank]
    if found is not None:
        found['bounds'] = _bounds(mark)

    if gesture == 'split':
        at = _number(edit.get('at'))
        if at is None or at <= mark['start'] + tolerance \
                or (mark['end'] is not None and at >= mark['end'] - tolerance):
            return "le point de coupe n'est pas à l'intérieur du segment"
        second = dict(mark, start=at, source=list(mark['source']))
        mark['end'] = at
        marks.insert(rank + 1, second)
        _touch(mark, index)
        _touch(second, index)
    elif gesture == 'merge':
        group = marks[rank:rank + _span(edit)]
        if len(group) < 2:
            return "une fusion prend au moins deux segments"
        if any(after['start'] < before['start'] for before, after in zip(group, group[1:])):
            return "les segments ne se suivent pas sur l'axe"
        if len({member.get('parent') for member in group}) > 1:
            return "les segments n'ont pas la même marque parente"
        if len({bool(member.get('masked')) for member in group}) > 1:
            return "mêlerait un segment masqué et un segment gardé"
        ends = [member['end'] for member in group]
        mark['end'] = None if None in ends else max(ends)
        mark['source'] = sorted({origin for member in group for origin in member['source']})
        mark['touched'] = sorted({i for member in group for i in member.get('touched', ())})
        del marks[rank + 1:rank + len(group)]
        _touch(mark, index)
    elif gesture == 'mask':
        mark['masked'] = True
        _touch(mark, index)
    elif gesture == 'label':
        reason = _settable(track, edit.get('set'))
        if reason:
            return reason
        _set(mark, edit['set'])
        _touch(mark, index)
    elif gesture == 'delete':
        del marks[rank]
    elif gesture == 'retime':
        if not {'start', 'end'} & set(edit):
            return "ni début ni fin à poser"
        start = _number(edit['start']) if 'start' in edit else mark['start']
        end = _number(edit['end']) if 'end' in edit else mark['end']
        if start is None or (end is not None and end < start):
            return "bornes impossibles"
        mark['start'], mark['end'] = start, end
        _touch(mark, index)
    elif gesture == 'move':
        to = _number(edit.get('to'))
        if to is None:
            return "`to` attend une position sur l'axe"
        if segments:
            if mark['end'] is not None:
                mark['end'] += to - mark['start']
            mark['start'] = to
        else:
            mark['time'] = to
        _touch(mark, index)
    elif gesture == 'reorder':
        to = edit.get('to')
        if not _rank(to, 0, len(marks) - 1) or to == rank:
            return "`to` attend un autre rang de la piste"
        marks.insert(to, marks.pop(rank))
        _touch(mark, index)
    return None


def apply_edits(track: Track, marks: Iterable[dict], edits: Optional[Iterable[dict]],
                tolerance: float = TOLERANCE) -> Tuple[List[dict], List[dict]]:
    """REJOUE une liste de gestes sur les marques d'une piste : rend les marques de la piste
    DÉRIVÉE, et un COMPTE RENDU pour chaque geste qui ne s'est pas fait tel quel —
    `{'edit': son rang dans la liste, 'gesture', 'applied', 'reason'}`. `applied` faux : le geste
    est SAUTÉ (la piste ne le déclare pas, sa cible n'est plus là, il n'a pas de sens où il
    tombe) — jamais fait à côté. `applied` vrai : il s'est fait sur une marque dont les bornes
    ont bougé (`was`, `now`) — la piste a été remesurée, ou un geste d'avant a été retiré : à
    montrer, pour qu'on le revoie. Liste vide : tout s'est fait sur les marques visées. Les
    marques reçues ne sont pas modifiées."""
    out = [dict(mark, source=[rank]) for rank, mark in enumerate(marks)]
    reports = []
    for index, edit in enumerate(edits or ()):
        report = _apply(track, out, index, edit, tolerance)
        if report:
            name = edit.get('gesture') if isinstance(edit, dict) else None
            reports.append(dict(edit=index, gesture=name, **report))
    return out, reports


def new_edit(gesture: str, marks: Iterable[dict] = (), mark: Optional[int] = None,
             **details) -> dict:
    """Un geste en DONNÉE, prêt à ranger : ses `was` sont LUS sur `marks`, la piste telle qu'elle
    est au moment du geste (dérivée comprise). Ne contrôle rien — `extend_edits` le fait."""
    marks = list(marks)
    edit = {'gesture': gesture}
    if mark is not None:
        edit['mark'] = mark
    edit.update(details)
    if gesture != 'add' and _rank(mark, 0, len(marks) - 1):
        edit['was'] = _bounds(marks[mark])
    return edit


def extend_edits(track: Track, marks: Iterable[dict], edits: Optional[Iterable[dict]],
                 gesture: str, mark: Optional[int] = None, tolerance: float = TOLERANCE,
                 **details) -> List[dict]:
    """La liste des gestes AUGMENTÉE d'un geste fait sur la piste telle qu'elle se montre (la
    source `marks` rejouée par `edits`) : `mark` est le rang de la marque DANS CETTE PISTE-LÀ.
    C'est par ici qu'un geste entre dans une liste — il est appliqué avant d'être rendu, et
    `InvalidEdit` dit pourquoi il ne peut pas se faire. La liste reçue n'est pas modifiée ;
    DÉFAIRE un geste, c'est le retirer de la liste (un masque se lève ainsi)."""
    edits = list(edits or ())
    current, _reports = apply_edits(track, marks, edits, tolerance)
    edit = new_edit(gesture, current, mark, **details)
    reason = _do(track, current, len(edits), edit, tolerance)
    if reason:
        raise InvalidEdit(f"piste « {track.key} », {gesture} : {reason}")
    return edits + [edit]


def _derived(card, track: Track, edits, cache: dict, tolerance: float) -> Tuple[List[dict], List[dict]]:
    marks, problems = apply_edits(track, _read(card, track, cache), edits, tolerance)
    if track.parent:
        parents = _read(card, _track(card, track.parent, cache), cache)
        for mark in marks:
            if not mark['source']:          # ajoutée par un geste : sa parente par contenance
                mark['parent'] = _holder(parents, mark)
    return marks, problems


def read_derived(card, key: str, edits: Optional[Iterable[dict]],
                 tracks: Optional[Iterable[Track]] = None,
                 tolerance: float = TOLERANCE) -> Tuple[List[dict], List[dict]]:
    """Les marques de la piste DÉRIVÉE d'une card — sa piste `key` rejouée par la liste de gestes
    `edits` — et le compte rendu des gestes sautés ou faits sur une marque qui a bougé
    (`apply_edits`). La piste source se lit comme toujours
    (`read_track`) et n'est jamais modifiée : sans geste, on retrouve ses marques (avec `source`).
    Où se range `edits` est l'affaire du monde du porteur ; ce lecteur ne fait que rejouer."""
    cache = _context(card, tracks)
    return _derived(card, _track(card, key, cache), edits, cache, tolerance)


def effective_line(marks: Iterable[dict], end: Optional[float] = None) -> List[dict]:
    """La LIGNE EFFECTIVE d'une piste : ses marques GARDÉES (non masquées), dans l'ordre de la
    piste — pour chacune `{'rank', 'mark'}` (son rang dans la piste, la marque telle quelle) et,
    pour un segment, `at` : sa place sur la ligne une fois les masques retirés (la somme des
    durées gardées avant lui). C'est ce que lit un aperçu à travers une coupe, et ce qu'un
    traitement reçoit d'une entrée coupée.

    Un segment OUVERT se ferme à `end` (la fin du porteur) pour placer ce qui le suit ; sans elle
    sa durée est inconnue, et ce qui le suit n'a pas de place (`at` vaut None)."""
    out, cursor = [], 0.0
    for rank, mark in enumerate(marks):
        if mark.get('masked'):
            continue
        kept = {'rank': rank, 'mark': mark}
        if 'start' in mark:
            kept['at'] = cursor
            stop = mark['end'] if mark['end'] is not None else end
            if cursor is not None:
                cursor = None if stop is None else cursor + max(0.0, stop - mark['start'])
        out.append(kept)
    return out
