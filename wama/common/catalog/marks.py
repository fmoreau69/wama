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

CE QUE CE MODULE NE FAIT PAS : il n'écrit rien, ne déplace aucun stockage, et ne calcule rien sur
les marques (« présent dans », filtre, indicateur par segment restent au Segmenter). Ce qu'il rend
a la FORME que ces fonctions lisent déjà (`start`, `end`, `origin`) — c'est tout l'intérêt.

Sans Django : le lecteur ne connaît que des objets et des dictionnaires.
"""
from __future__ import annotations

from dataclasses import dataclass
from importlib import import_module
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple, Union

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


class InvalidTracks(ValueError):
    """Une déclaration de pistes incohérente — refusée à l'enregistrement, pas à la lecture."""


@dataclass(frozen=True)
class Track:
    """Une piste DÉCLARÉE par une app. Trois façons de dire d'où viennent ses lignes :

      • `source` — un attribut de la card (une liste, un champ JSON, un gestionnaire de lignes
        liées), une fonction `f(card)`, ou son chemin pointé `'paquet.module:fonction'` (lu à la
        première lecture : un `apps.py` ne charge pas ses vues au démarrage) ;
      • `within` — la clé de la liste d'enfants DANS chaque ligne de la piste parente (les `words`
        d'une phrase) : l'imbrication écrite en document ;
      • `runs_of` + `by` — une piste DÉRIVÉE : les suites de marques consécutives d'une autre piste
        qui partagent la valeur `by` (les tours de parole, des phrases d'un même locuteur).

    `fields` : nom commun → nom rangé (`{'start': 't_enter', 'end': 't_exit'}`) ; un nom absent se
    lit sous son nom commun. `attributes` : ce que la marque garde en plus, sous son nom commun
    (`'text'`) ou renommé (`('speaker', 'speaker_id')`).

    Le PARENT d'une marque se résout, dans cet ordre : par construction (`within`, `runs_of`), par
    référence (`parent_ref` : le champ de la ligne qui porte le rang de sa marque parente, négatif
    = aucune), sinon par CONTENANCE — la marque parente dont les bornes contiennent son début.
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

    def __post_init__(self):
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
                 'runs_of', 'by', 'origin', 'origin_field'):
        value = getattr(track, name)
        if value != getattr(_DEFAULTS, name):
            data[name] = value
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
    values = {k: v for k, v in data.items() if k not in ('fields', 'attributes')}
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


def validate(tracks: Iterable[Track]) -> List[str]:
    """Les défauts d'une déclaration, en clair — liste vide = cohérente."""
    tracks = list(tracks)
    by_key, problems = {}, []
    for track in tracks:
        if track.key in by_key:
            problems.append(f"piste « {track.key} » déclarée deux fois")
        by_key[track.key] = track
    for track in tracks:
        name = f"piste « {track.key} »"
        if track.kind not in (DataType.SEGMENTS, DataType.EVENTS):
            problems.append(f"{name} : type « {track.kind} » (attendu segments ou events)")
        if track.axis not in AXES:
            problems.append(f"{name} : axe « {track.axis} » inconnu ({', '.join(AXES)})")
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
        # Deux chaînes doivent FINIR : celle des parentes, et celle des dérivations. Elles se
        # suivent à part — une piste dérivée peut être la parente de celle qu'elle regroupe (les
        # tours, suites de phrases d'un même locuteur, sont au-dessus des phrases) : la dérivée se
        # lit sur les marques nues de l'autre, ce n'est pas une boucle.
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
        # Une source se lit UNE fois par lecture (une piste dérivée et sa base la partagent).
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
               tracks: Optional[Iterable[Track]] = None) -> List[str]:
    """Ce que les marques d'une piste doivent à leurs marques parentes et ne tiennent pas —
    liste vide = la contrainte déclarée est tenue (ou la piste n'en déclare pas). INCLUSION :
    chaque marque a une parente et tient dans ses bornes. PARTITION : en plus, les marques d'une
    même parente la couvrent sans trou ni chevauchement."""
    cache = _context(card, tracks)
    track = _track(card, key, cache)
    if not track.constraint:
        return []
    marks = _read(card, track, cache)
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
