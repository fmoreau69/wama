"""
Codage — le 5ᵉ mode de segmentation : un **protocole déclaré** + une **exécution**.

C'est le mode qui produit des segments à partir d'une observation, humaine ou automatique. Sa
spécification est `WAMA_DATA_WORLD.md §9ter.4`, tirée d'un mécanisme réel de 2019 dont le découpage
est tout l'intérêt :

    le protocole (un fichier à part, édité par une AUTRE application)
    l'interface de codage — GÉNÉRIQUE, pilotée par le protocole, jamais écrite par projet
    la session — qui exige la vidéo et le transport, synchronisés

Autrement dit : le schéma-driven appliqué au codage, sept ans avant qu'on le nomme ainsi ici. La
conséquence qui compte pour WAMA est celle-ci — **une IA de vision n'est qu'un producteur de plus
des mêmes segments**. Même sortie, même type, origine tracée. Il n'y a donc PAS de « module de
codage IA » à écrire à côté : il y a un `coder` qui change.

CE QUI VIENT DE CHAQUE MONDE (aucun de ces points ne s'invente) :
  • l'outil MATLAB → protocole SÉPARÉ de l'outil d'analyse, interface générique, session qui refuse
    de démarrer sans média ;
  • le logiciel d'éthologie → le vocabulaire (éthogramme, sujet, modificateurs typés, comportements
    mutuellement exclusifs) et surtout l'**état ouvert** : un comportement commencé et pas encore
    refermé. Sans lui, on ne peut pas coder EN COURS de flux — or c'est le cas normal.

CE QUE CE MODULE NE FAIT PAS, délibérément :
  • aucune UI. Le protocole DÉCRIT ce qui est codable ; l'interface s'en génère (métadonnée-driven).
  • aucun accès média. La session porte la référence du média et refuse de coder sans, mais c'est le
    transport (`WamaShuttle`) qui joue, pas ce module.

VOCABULAIRE : `segment` est le MODÈLE ; l'utilisateur lit « situation » ou « état ».
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from .segmentation import OPEN_END, Segment, _trace, _sorted_segments

#: Les deux natures d'un comportement. La distinction est structurante, pas cosmétique : un
#: PONCTUEL n'a pas de durée (il ne se referme jamais), un ÉTAT en a une et peut rester OUVERT.
POINT = 'point'
STATE = 'state'
NATURES = (POINT, STATE)

#: Types de modificateur. `libre` accepte tout ; les autres CONTRAIGNENT — et cette contrainte est
#: la moitié de l'intérêt d'un protocole : elle rend deux codages comparables.
MOD_ONE_OF = 'one'
MOD_MANY_OF = 'many'
MOD_NUMBER = 'number'
MOD_FREE = 'free'
MODIFIER_TYPES = (MOD_ONE_OF, MOD_MANY_OF, MOD_NUMBER, MOD_FREE)


class InvalidProtocol(ValueError):
    """Le protocole lui-même est incohérent — détecté à la déclaration, jamais en cours de codage."""


class CodingRefused(ValueError):
    """Un geste de codage viole le protocole. Refusé À LA SOURCE.

    Un codage qu'on laisse partir faux se découvre à l'analyse, quand la campagne est finie et que
    la vidéo n'est plus regardée par personne. C'est la raison d'être de la validation immédiate.
    """


# ──────────────────────────────────────────────────────────────────────────────────────────────
# 1. LE PROTOCOLE — ce qui est codable. Déclaratif, donc sérialisable, donc un manifeste.
# ──────────────────────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Modifier:
    """Une précision attachée à un comportement (gravité, direction, nombre d'occupants…).

    TYPÉ, et c'est le point : un modificateur libre partout redonne un champ texte, donc des
    variantes d'orthographe, donc des données inexploitables au regroupement.
    """
    key: str
    label: str = ''
    type: str = MOD_ONE_OF
    values: Tuple[Any, ...] = ()
    required: bool = False

    def validate(self, value: Any) -> Any:
        """Renvoie la valeur normalisée, ou lève `CodingRefused`."""
        if value is None or value == '' or value == []:
            if self.required:
                raise CodingRefused(f"modificateur '{self.key}' requis")
            return None
        if self.type == MOD_NUMBER:
            try:
                return float(value)
            except (TypeError, ValueError):
                raise CodingRefused(f"modificateur '{self.key}' : nombre attendu, reçu {value!r}")
        if self.type == MOD_FREE:
            return value
        if self.type == MOD_ONE_OF:
            if self.values and value not in self.values:
                raise CodingRefused(
                    f"modificateur '{self.key}' : {value!r} hors des valeurs déclarées "
                    f"({', '.join(map(str, self.values))})")
            return value
        # MOD_MANY_OF
        received = list(value) if isinstance(value, (list, tuple, set)) else [value]
        if self.values:
            outside = [v for v in received if v not in self.values]
            if outside:
                raise CodingRefused(f"modificateur '{self.key}' : {outside!r} hors des valeurs déclarées")
        return received


@dataclass(frozen=True)
class Behavior:
    """Une entrée de l'éthogramme : ce qu'on peut coder, et sous quelle forme."""
    code: str
    label: str = ''
    nature: str = STATE
    #: Groupe d'exclusion mutuelle. Deux comportements du même groupe ne peuvent pas être ouverts
    #: ensemble : ouvrir l'un FERME l'autre. C'est ce qui modélise un mode de conduite, une phase,
    #: une posture — tout ce dont il n'existe qu'une valeur à la fois.
    exclusive: str = ''
    modifiers: Tuple[Modifier, ...] = ()
    #: Touche de l'interface générée. Déclarée ici parce que c'est une propriété du PROTOCOLE
    #: (le codeur l'apprend par cœur pour la campagne), pas un réglage d'écran.
    hotkey: str = ''
    color: str = ''
    description: str = ''

    @property
    def is_state(self) -> bool:
        return self.nature == STATE


@dataclass(frozen=True)
class Protocol:
    """L'éthogramme : la liste de ce qui est codable, plus les sujets observés.

    Sérialisable dans les deux sens (`to_dict` / `from_dict`) — c'est la forme qu'un manifeste
    prendra. Un protocole est le SEUL endroit où l'on décrit un codage : l'interface s'en génère et
    l'exécution s'y contraint, donc changer le protocole change les deux d'un coup.
    """
    name: str
    behaviors: Tuple[Behavior, ...] = ()
    #: Sujets observés (conducteur, piéton, véhicule…). Vide = un seul sujet implicite. Un codage
    #: multi-sujets suit les états SÉPARÉMENT par sujet : deux personnes peuvent tenir le même état.
    subjects: Tuple[str, ...] = ()
    version: str = '1'
    description: str = ''

    def __post_init__(self):
        seen = set()
        for c in self.behaviors:
            if not c.code:
                raise InvalidProtocol("un comportement sans code")
            if c.code in seen:
                raise InvalidProtocol(f"code de comportement en double : '{c.code}'")
            seen.add(c.code)
            if c.nature not in NATURES:
                raise InvalidProtocol(
                    f"'{c.code}' : nature '{c.nature}' inconnue (attendu {' ou '.join(NATURES)})")
            if c.exclusive and not c.is_state:
                raise InvalidProtocol(
                    f"'{c.code}' : un comportement PONCTUEL ne peut pas être exclusif — il n'a pas "
                    f"de durée, donc rien à fermer")
            for m in c.modifiers:
                if m.type not in MODIFIER_TYPES:
                    raise InvalidProtocol(f"'{c.code}.{m.key}' : type '{m.type}' inconnu")

    def get(self, code: str) -> Behavior:
        for c in self.behaviors:
            if c.code == code:
                return c
        raise CodingRefused(
            f"comportement '{code}' absent du protocole '{self.name}' "
            f"(déclarés : {', '.join(c.code for c in self.behaviors) or '—'})")

    def group(self, code: str) -> str:
        return self.get(code).exclusive

    def to_dict(self) -> dict:
        return {
            'name': self.name, 'version': self.version, 'description': self.description,
            'subjects': list(self.subjects),
            'behaviors': [
                {'code': c.code, 'label': c.label, 'nature': c.nature, 'exclusive': c.exclusive,
                 'key': c.hotkey, 'color': c.color, 'description': c.description,
                 'modifiers': [{'key': m.key, 'label': m.label, 'type': m.type,
                                'values': list(m.values), 'required': m.required}
                               for m in c.modifiers]}
                for c in self.behaviors],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Protocol":
        return cls(
            name=d.get('name', ''), version=str(d.get('version', '1')),
            description=d.get('description', ''),
            subjects=tuple(d.get('subjects') or ()),
            behaviors=tuple(
                Behavior(
                    code=b['code'], label=b.get('label', ''), nature=b.get('nature', STATE),
                    exclusive=b.get('exclusive', ''), hotkey=b.get('key', ''),
                    color=b.get('color', ''), description=b.get('description', ''),
                    modifiers=tuple(
                        Modifier(key=m['key'], label=m.get('label', ''),
                                     type=m.get('type', MOD_ONE_OF),
                                     values=tuple(m.get('values') or ()),
                                     required=bool(m.get('required')))
                        for m in (b.get('modifiers') or ())))
                for b in (d.get('behaviors') or ())))


# ──────────────────────────────────────────────────────────────────────────────────────────────
# 2. L'EXÉCUTION — une session de codage. Produit des segments, comme tout autre mode.
# ──────────────────────────────────────────────────────────────────────────────────────────────

@dataclass
class CodingSession:
    """Un codage en cours. Chaque geste est validé contre le protocole AU MOMENT du geste.

    ⚠ La session refuse de démarrer sans média (`media`), et ce n'est pas une formalité recopiée
    du modèle : coder sans support, c'est produire des bornes temporelles que plus personne ne peut
    vérifier. Le mécanisme d'origine posait déjà la règle en 2019.

    Le `coder` est libre — « fabien », « qwen3-vl », « detector:locate-anything ». C'est ce champ,
    et lui seul, qui distingue un codage humain d'un codage automatique : le reste du chemin est
    identique, ce qui est exactement le but.
    """
    protocol: Protocol
    media: str
    coder: str = ''
    #: États ouverts, indexés par (sujet, code). Un état par sujet : deux sujets peuvent tenir le
    #: même comportement simultanément sans se fermer l'un l'autre.
    _open: Dict[Tuple[str, str], Segment] = field(default_factory=dict, repr=False)
    _closed: List[Segment] = field(default_factory=list, repr=False)
    _points: List[Segment] = field(default_factory=list, repr=False)
    _last_t: Optional[float] = field(default=None, repr=False)

    def __post_init__(self):
        if not self.media:
            raise CodingRefused(
                "codage sans média : une session exige le support qu'elle décrit (règle héritée du "
                "mécanisme d'origine — sans vidéo, les bornes ne sont plus vérifiables)")

    # ── gestes ────────────────────────────────────────────────────────────────────────────────

    def mark(self, t: float, code: str, *, subject: str = '', modifiers: Optional[dict] = None,
             comment: str = '') -> Segment:
        """LE geste unique du codage. Ponctuel → un segment de durée nulle. État → il OUVRE, ou il
        FERME s'il est déjà ouvert (bascule), en fermant au passage l'état exclusif concurrent.

        Une seule fonction plutôt que `open`/`close`/`event` : c'est ce que fait le codeur —
        il appuie sur une touche. La nature du comportement est déclarée dans le protocole, donc
        l'exécution n'a pas à être commandée deux fois.
        """
        comp = self.protocol.get(code)
        subject = self._subject(subject)
        mods = self._validate_modifiers(comp, modifiers)
        self._check_monotonic(t)

        if not comp.is_state:
            seg = _trace({'start': t, 'end': t, 'value': code, 'label': comp.label or code,
                          'subject': subject or None, 'nature': POINT},
                         'codage', coder=self.coder or None, protocol=self.protocol.name,
                         media=self.media, comment=comment or None)
            seg.update(mods)
            self._points.append(seg)
            return seg

        key = (subject, code)
        if key in self._open:                           # bascule : le même geste referme
            return self._close_key(key, t)

        if comp.exclusive:                              # ouvrir ferme le concurrent du groupe
            for (s, c) in list(self._open):
                if s == subject and self.protocol.group(c) == comp.exclusive:
                    self._close_key((s, c), t, cause='exclusive')

        seg = _trace({'start': t, 'end': OPEN_END, 'value': code, 'label': comp.label or code,
                      'subject': subject or None, 'nature': STATE, 'open': True},
                     'codage', coder=self.coder or None, protocol=self.protocol.name,
                     media=self.media, comment=comment or None)
        seg.update(mods)
        self._open[key] = seg
        return seg

    def open(self, t: float, code: str, **kw) -> Segment:
        """Ouverture EXPLICITE — refuse si l'état est déjà ouvert, là où `mark` basculerait.

        Utile au codage automatique, où un modèle propose des ouvertures sans savoir ce qui court
        déjà : la bascule silencieuse y refermerait un état au lieu de signaler l'incohérence.
        """
        comp = self.protocol.get(code)
        if not comp.is_state:
            raise CodingRefused(f"'{code}' est PONCTUEL — il n'a pas d'ouverture, utiliser `mark`")
        if (self._subject(kw.get('subject', '')), code) in self._open:
            raise CodingRefused(f"'{code}' est déjà ouvert pour ce sujet")
        return self.mark(t, code, **kw)

    def close(self, t: float, code: str, *, subject: str = '') -> Segment:
        """Fermeture EXPLICITE — refuse si rien n'est ouvert, plutôt que d'ouvrir par surprise."""
        key = (self._subject(subject), code)
        self.protocol.get(code)
        if key not in self._open:
            raise CodingRefused(f"'{code}' n'est pas ouvert pour ce sujet — rien à fermer")
        self._check_monotonic(t)
        return self._close_key(key, t)

    def undo_last(self) -> Optional[Segment]:
        """Retire la dernière production. Le codage en temps réel produit des erreurs de doigt : ne
        pas offrir le retour arrière, c'est obliger à reprendre la passation."""
        candidates: List[Tuple[float, str, Any]] = []
        if self._points:
            candidates.append((self._points[-1]['start'], 'ponctuel', None))
        if self._closed:
            candidates.append((self._closed[-1]['end'], 'clos', None))
        for key, seg in self._open.items():
            candidates.append((seg['start'], 'ouvert', key))
        if not candidates:
            return None
        t, what, key = max(candidates, key=lambda x: x[0])
        if what == 'ponctuel':
            return self._points.pop()
        if what == 'clos':                             # un segment refermé redevient OUVERT
            seg = self._closed.pop()
            seg['end'] = OPEN_END
            seg['open'] = True
            seg.pop('closed_by', None)
            self._open[(seg.get('subject') or '', seg['value'])] = seg
            return seg
        return self._open.pop(key)

    # ── sorties ───────────────────────────────────────────────────────────────────────────────

    def segments(self, *, session_end: Optional[float] = None) -> List[Segment]:
        """Tous les états, y compris ceux restés OUVERTS.

        `session_end` ferme d'office les états en cours et TRACE cette fermeture (`closed_at`) :
        une durée refermée par la fin de l'enregistrement n'a pas le statut d'une durée observée, et
        confondre les deux fausse toute statistique de durée.
        """
        out = list(self._closed) + list(self._open.values())
        if session_end is not None:
            from .segmentation import close as _close_segments
            out = _close_segments(out, session_end)
        return _sorted_segments(out)

    def events(self) -> List[Segment]:
        """Les comportements ponctuels — même forme, durée nulle. Ils rejoignent le flux `events`."""
        return sorted(self._points, key=lambda s: s['start'])

    def open_ones(self) -> List[Segment]:
        return sorted(self._open.values(), key=lambda s: s['start'])

    def summary(self) -> dict:
        """De quoi alimenter un bandeau d'interface sans que celle-ci connaisse le modèle."""
        return {'protocol': self.protocol.name, 'media': self.media, 'coder': self.coder,
                'states': len(self._closed) + len(self._open), 'open': len(self._open),
                'events': len(self._points), 'last_time': self._last_t}

    # ── interne ───────────────────────────────────────────────────────────────────────────────

    def _subject(self, subject: str) -> str:
        if self.protocol.subjects:
            if not subject:
                if len(self.protocol.subjects) == 1:
                    return self.protocol.subjects[0]
                raise CodingRefused(
                    f"sujet requis (déclarés : {', '.join(self.protocol.subjects)})")
            if subject not in self.protocol.subjects:
                raise CodingRefused(f"sujet '{subject}' absent du protocole")
        return subject

    def _validate_modifiers(self, comp: Behavior, received: Optional[dict]) -> dict:
        received = dict(received or {})
        known = {m.key for m in comp.modifiers}
        unknown = set(received) - known
        if unknown:
            raise CodingRefused(
                f"'{comp.code}' : modificateur(s) non déclaré(s) {sorted(unknown)}")
        out = {}
        for m in comp.modifiers:
            v = m.validate(received.get(m.key))
            if v is not None:
                out[m.key] = v
        return out

    def _check_monotonic(self, t: float) -> None:
        """Le codage suit le temps du média. Un geste antérieur au précédent signale un transport
        qui a sauté en arrière sans que la session le sache — mieux vaut le dire que produire un
        segment à durée négative."""
        if self._last_t is not None and t < self._last_t:
            raise CodingRefused(
                f"geste à t={t:g} antérieur au précédent (t={self._last_t:g}) — reprendre le "
                f"codage après un retour arrière du transport exige de rouvrir la session")
        self._last_t = t

    def _close_key(self, key: Tuple[str, str], t: float, *, cause: str = '') -> Segment:
        seg = self._open.pop(key)
        seg['end'] = t
        seg.pop('open', None)
        if cause:
            seg['closed_by'] = cause
        self._closed.append(seg)
        return seg


# ──────────────────────────────────────────────────────────────────────────────────────────────
# 3. REJOUER un codage — la même session, alimentée par une liste de gestes
# ──────────────────────────────────────────────────────────────────────────────────────────────

def replay(protocol: Protocol, media: str, gestures: Iterable[dict], *, coder: str = '',
            session_end: Optional[float] = None) -> Tuple[List[Segment], List[Segment]]:
    """Rejoue une liste de gestes `{t, code, subject?, modifiers?, comment?}`.

    C'est le point d'entrée du codage AUTOMATIQUE : un modèle de vision produit une liste de gestes,
    on la rejoue, et l'on obtient exactement la même sortie qu'un codage humain — validée par le
    même protocole. Rien d'autre à écrire côté IA que la production des gestes.

    Renvoie `(segments, événements)`.
    """
    s = CodingSession(protocol=protocol, media=media, coder=coder)
    for g in gestures:
        s.mark(g['t'], g['code'], subject=g.get('subject', ''),
               modifiers=g.get('modifiers'), comment=g.get('comment', ''))
    return s.segments(session_end=session_end), s.events()


def agreement(a: Sequence[Segment], b: Sequence[Segment], *, tolerance: float = 1.0) -> dict:
    """Compare DEUX codages du même média (deux humains, ou un humain et un modèle).

    Mesure volontairement simple — appariement par code et par proximité des débuts, dans une
    tolérance. Ce n'est pas un kappa : c'est ce qu'il faut pour dire « ce que la machine a proposé
    correspond-il à ce que l'humain a codé », qui est la question posée quand on valide un codage
    assisté. Le calcul d'indicateurs d'accord plus fins est du ressort du module Calculator.
    """
    remaining = list(b)
    matched: List[Tuple[Segment, Segment]] = []
    for sa in sorted(a, key=lambda s: s['start']):
        nearest, gap = None, None
        for sb in remaining:
            if sb.get('value') != sa.get('value') or sb.get('subject') != sa.get('subject'):
                continue
            d = abs(sb['start'] - sa['start'])
            if d <= tolerance and (gap is None or d < gap):
                nearest, gap = sb, d
        if nearest is not None:
            remaining.remove(nearest)
            matched.append((sa, nearest))
    return {'matched': len(matched), 'only_a': len(a) - len(matched), 'only_b': len(remaining),
            'mean_offset': (sum(abs(y['start'] - x['start']) for x, y in matched) / len(matched)
                            if matched else None)}
