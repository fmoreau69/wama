"""
Référentiel temporel de WAMA Data — la couche qui répond « que vaut ce signal à l'instant t ».

POURQUOI CETTE COUCHE EXISTE, ET POURQUOI ELLE EST SÉPARÉE DU TRANSPORT
    Un curseur de lecture (une position qui avance, une vitesse, un sens) n'est PAS une gestion du
    temps : c'est du transport. Le référentiel, lui, ignore qu'on lit — il sait seulement aligner
    des flux hétérogènes et répondre à des questions temporelles. Recadrage Fabien du 2026-08-19,
    après une première tentative où j'avais confondu les deux ; cf. `WAMA_DATA_WORLD.md` §2, qui
    décrit la pile en 4 couches (référentiel · curseur · télécommande · vues).

CE QUE LA DONNÉE RÉELLE IMPOSE (mesuré sur une base d'expérimentation de 1,28 Go, §6.7)
  • **Cadences incommensurables** : 1000 Hz (physio), 123,1 Hz (oculométrie), 56,3 Hz (véhicule),
    40 Hz (caméras), 18,7 Hz (fixations) — dans le MÊME jeu. Aucune grille commune, donc des
    requêtes par temps `t` et jamais par index.
  • **Pas de temps variable = une CAPACITÉ**, pas un défaut. Certains flux sont légitimement
    irréguliers (événements, détections, fixations). `fs` est donc optionnel : `None` = irrégulier.
  • **On n'interpole JAMAIS une valeur.** `at()` rend l'échantillon le plus proche (ou exact), et
    c'est tout. Interpoler une mesure scientifique est un faux ami, et sur une variable catégorielle
    c'est simplement faux. Décision D6/D10 : le ré-horodatage et le rééchantillonnage sont des
    gestes d'INGESTION explicites, jamais un effet de bord de la consultation.
  • **La décimation est une condition d'existence**, pas une optimisation : tracer 2 M de points sur
    2000 px, c'est 1000 points par pixel. Sans `decimate()`, aucune vue n'est viable.

CE QUE CETTE COUCHE NE FAIT PAS
    Pas de lecture, pas de vitesse, pas d'UI, pas de souscription. Le curseur de session et la
    télécommande sont des couches AU-DESSUS et vivront ailleurs.
"""
from __future__ import annotations

from bisect import bisect_left, bisect_right
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

#: Politique de résolution d'un instant. Volontairement PAUVRE : il n'y a pas d'`INTERPOLATE`.
#: L'ajouter un jour supposerait de le refuser pour les types catégoriels — donc de connaître le
#: type ici, ce qui rendrait cette couche dépendante de la taxonomie. Tant qu'on s'en tient à
#: « rendre un échantillon existant », le référentiel reste vrai pour tous les types.
NEAREST = 'nearest'     #: l'échantillon le plus proche, avant ou après
PREVIOUS = 'previous'   #: le dernier échantillon à `t` ou avant (sémantique d'ÉTAT — le bon défaut
                        #: pour un signal catégoriel : un état vaut jusqu'à ce qu'il change)
EXACT = 'exact'         #: uniquement si un échantillon tombe pile (à `tolerance` près)


@dataclass
class SignalMeta:
    """Ce qu'on DÉCLARE d'un flux — l'équivalent des `MetaDatas`/`MetaDataVariables` d'un `.trip`.

    `fs` est optionnel À DESSEIN : mesuré sur une base réelle, le champ fréquence valait 0 pour les
    10 flux, la cadence étant une propriété émergente de la donnée. On ne l'exige donc pas ; quand
    elle est connue elle sert d'indication (et de base au ré-horodatage à l'ingestion), jamais de
    contrainte.
    """

    name: str
    #: FAMILLE du flux — une valeur de `DataType` (`timeseries`, `events`, `segments`…), vide si
    #: la source ne la connaît pas.
    #:
    #: ⚠ POURQUOI CE CHAMP EXISTE (ajouté le 2026-08-24). La famille était CONNUE du lecteur
    #: `.trip` — il la calcule depuis le préfixe de table (`data_`/`event_`/`situation_`) — et
    #: **jetée dans une chaîne de commentaire** (`comments=f"{famille} · …"`). Le pont
    #: (`frames.py`) refusait, à raison, de la relire de là : un libellé est une TRACE, pas une
    #: règle. Résultat, il devait déduire le type de la seule STRUCTURE (des fins ⇒ segments,
    #: sinon timeseries) et ne pouvait pas distinguer données et événements. Le fait existait,
    #: il n'était pas porté comme DONNÉE.
    #:
    #: ⚠ Typé `str` et non `DataType` À DESSEIN : `core/` reste sans dépendance (« moteur sans
    #: Django »). Ce sont les LECTEURS, un étage plus haut, qui remplissent ce champ avec les
    #: constantes de la taxonomie partagée — le vocabulaire n'est donc recopié nulle part.
    data_type: str = ''
    #: Cadence théorique en Hz. `None` = irrégulier ou inconnu — c'est un cas NORMAL.
    fs: Optional[float] = None
    #: Échantillons PERDUS à l'acquisition, détectés à l'ingestion (index non consécutifs).
    #:
    #: ⚠ Porté comme DONNÉE, pas comme message (ajouté le 2026-08-24). RTMaps numérote ses
    #: échantillons ; un index qui saute signale une perte réelle. `pynd` la détecte
    #: (`DataParser.check_idx`) et se contente d'un `log.error` — son propre `TODO` reconnaît que
    #: ce n'est pas suffisant. Une perte écrite dans un journal n'est pas exploitable : elle ne
    #: remonte ni au compte-rendu d'import, ni à l'`Ecart` du manifeste, ni à l'utilisateur.
    #: `0` signifie « aucune perte détectée », jamais « non mesuré » — un lecteur qui ne sait pas
    #: compter laisse le champ à 0 et le dit dans `comments`.
    pertes: int = 0
    #: Unité par variable, ex. {'speed': 'm/s'}. Porte le vocabulaire qu'un manifeste doit exposer.
    units: Dict[str, str] = field(default_factory=dict)
    #: Acquis (True) vs dérivé d'un calcul (False). C'est la PROVENANCE : sans elle, impossible de
    #: savoir ce qu'un recalcul peut écraser sans perte.
    is_base: bool = True
    #: Politique de résolution par défaut pour ce flux.
    default_lookup: str = NEAREST
    comments: str = ''


class Signal:
    """Un flux temporel : des instants triés + un accès aux valeurs.

    Volontairement agnostique du stockage : `times` est une séquence croissante, et `rows` un
    accesseur `(i0, i1) -> lignes`. Une implémentation SQLite, un DataFrame ou un tableau en mémoire
    conviennent également — c'est ce qui permettra de brancher un `.trip` sans que cette couche
    connaisse SQLite.
    """

    __slots__ = ('meta', '_times', '_ends', '_rows', '_extent', '_extents')

    def __init__(self, meta: SignalMeta, times: Sequence[float],
                 rows: Optional[Callable[[int, int], Any]] = None,
                 ends: Optional[Sequence[float]] = None,
                 extent: Optional[Callable[[float, float, str], Tuple[Any, Any]]] = None,
                 extents: Optional[Callable[[float, float, int, str], Dict[int, Any]]] = None):
        """
        `ends` : bornes de FIN, si le flux est une collection de segments. Sans elles, un segment
        ne serait indexé que par son début — et « quel segment contient `t` ? » deviendrait
        indécidable, alors que c'est LA question qu'on pose à des situations.

        `extent` : `(t0, t1, colonne) -> (min, max)`, fourni par la source quand elle sait agréger
        elle-même (une base SQL le fait en SQL). Les bornes sont TEMPORELLES et non des index :
        une source indexée sur le temps agrège alors directement, là où des index l'obligeraient à
        compter les lignes depuis le début. Sans `extent`, `decimate_values` lit les lignes — ce qui
        reste correct mais coûte le transfert de tout l'intervalle.
        """
        self.meta = meta
        self._times = times
        self._ends = ends
        self._rows = rows
        self._extent = extent
        self._extents = extents

    @property
    def is_segments(self) -> bool:
        """Le flux porte-t-il des intervalles (deux bornes) plutôt que des instants ?"""
        return self._ends is not None

    # ── Propriétés temporelles ────────────────────────────────────────────────────────────────
    def __len__(self) -> int:
        return len(self._times)

    @property
    def span(self) -> Optional[Tuple[float, float]]:
        """(premier, dernier) instant, ou None si le flux est vide."""
        if not len(self._times):
            return None
        return self._times[0], self._times[-1]

    def measured_fs(self) -> Optional[float]:
        """Cadence MESURÉE (moyenne), à distinguer de `meta.fs` qui est la cadence DÉCLARÉE.

        Les deux peuvent diverger — c'est même le signal qu'un ré-horodatage serait pertinent à
        l'ingestion. On ne corrige rien ici : constater n'est pas agir.
        """
        n = len(self._times)
        if n < 2:
            return None
        lo, hi = self._times[0], self._times[-1]
        return (n - 1) / (hi - lo) if hi > lo else None

    def is_regular(self, tolerance: float = 0.05) -> bool:
        """Le pas est-il régulier à `tolerance` près (écart-type relatif) ? Informatif."""
        n = len(self._times)
        if n < 3:
            return True
        pas = [self._times[i + 1] - self._times[i] for i in range(n - 1)]
        moy = sum(pas) / len(pas)
        if moy <= 0:
            return False
        var = sum((p - moy) ** 2 for p in pas) / len(pas)
        return (var ** 0.5) / moy <= tolerance

    # ── Requêtes ──────────────────────────────────────────────────────────────────────────────
    def index_at(self, t: float, how: Optional[str] = None,
                 tolerance: float = float('inf')) -> Optional[int]:
        """Index de l'échantillon résolvant `t`, ou None. AUCUNE interpolation."""
        n = len(self._times)
        if n == 0:
            return None
        how = how or self.meta.default_lookup
        i = bisect_left(self._times, t)

        if how == EXACT:
            for j in (i, i - 1):
                if 0 <= j < n and abs(self._times[j] - t) <= tolerance:
                    return j
            return None

        if how == PREVIOUS:
            j = bisect_right(self._times, t) - 1
            if j < 0:
                return None
            return j if (t - self._times[j]) <= tolerance else None

        # NEAREST
        cands = [j for j in (i - 1, i) if 0 <= j < n]
        if not cands:
            return None
        j = min(cands, key=lambda k: abs(self._times[k] - t))
        return j if abs(self._times[j] - t) <= tolerance else None

    def range_indices(self, t0: float, t1: float) -> Tuple[int, int]:
        """Bornes [i0, i1) des échantillons dans [t0, t1]. Vide si t0 > t1."""
        if t1 < t0:
            return 0, 0
        return bisect_left(self._times, t0), bisect_right(self._times, t1)

    def time_at(self, index: int) -> Optional[float]:
        return self._times[index] if 0 <= index < len(self._times) else None

    def rows(self, i0: int, i1: int):
        """Lignes [i0, i1) via l'accesseur fourni ; None si aucun accesseur n'a été donné."""
        return self._rows(i0, i1) if self._rows else None

    # ── Segments : « quel intervalle contient t ? » ───────────────────────────────────────────
    def containing(self, t: float) -> List[int]:
        """Index des segments contenant `t` (bornes incluses). [] si le flux n'est pas segmenté.

        Gère le CHEVAUCHEMENT et l'IMBRICATION : on ne peut pas se contenter du dernier segment
        commencé avant `t` (ce que ferait `PREVIOUS`), car ce segment peut être terminé, et
        plusieurs peuvent contenir `t` à la fois — des fenêtres d'analyse emboîtées, c'est le cas
        courant. On borne le balayage par le début : au-delà de `t`, plus rien ne peut contenir `t`.
        """
        if self._ends is None:
            return []
        fin = bisect_right(self._times, t)      # tous les segments commencés à t ou avant
        return [i for i in range(fin) if self._fin(i) >= t]

    def overlapping(self, t0: float, t1: float) -> List[int]:
        """Index des segments intersectant [t0, t1] — un segment à cheval sur la borne compte.

        `range_indices` ne suffit pas : elle ne voit que les segments COMMENCÉS dans la fenêtre et
        raterait celui qui l'englobe.
        """
        if self._ends is None:
            i0, i1 = self.range_indices(t0, t1)
            return list(range(i0, i1))
        fin = bisect_right(self._times, t1)
        return [i for i in range(fin) if self._fin(i) >= t0]

    def _fin(self, index: int) -> float:
        """Fin d'un segment pour les COMPARAISONS — une fin inconnue vaut `+∞`.

        ⚠ BUG CORRIGÉ LE 2026-08-24, et il répond à **D15** (« `Signal.ends` accepte-t-il
        `None` ? »). La réponse mesurée était : **structurellement oui, à l'interrogation non** —
        `containing()` et `overlapping()` comparaient `None >= float` et levaient un `TypeError`.
        Un segment encore OUVERT rendait donc le flux entier ininterrogeable.

        ⚠ Et la convention existait DÉJÀ, deux fichiers plus loin : `present_dans()` et
        `chevauche()` (`core/segmentation.py`) écrivent depuis toujours
        `fin = s['end'] if s['end'] is not None else float('inf')`. Elle n'avait simplement pas été
        portée ici. Sixième occurrence du même motif — le fait est établi ailleurs dans le dépôt et
        n'est pas relié à sa conséquence.

        `+∞` est la sémantique juste : un état commencé et non refermé **court encore**, donc il
        contient tout instant postérieur à son début. Le refermer d'office à la fin du média
        donnerait une durée mesurée là où rien n'a été mesuré (cf. `fermer()`, qui exige un acte
        explicite et le trace).
        """
        f = self._ends[index] if self._ends is not None else None
        return float('inf') if f is None or f != f else f

    def end_at(self, index: int) -> Optional[float]:
        if self._ends is None:
            return None
        return self._ends[index] if 0 <= index < len(self._ends) else None

    def duration_at(self, index: int) -> Optional[float]:
        d, f = self.time_at(index), self.end_at(index)
        return None if (d is None or f is None) else f - d

    # ── Événements : « et après ? » ───────────────────────────────────────────────────────────
    def next_index(self, t: float) -> Optional[int]:
        """Premier échantillon STRICTEMENT après `t` — « l'événement suivant »."""
        i = bisect_right(self._times, t)
        return i if i < len(self._times) else None

    def previous_index(self, t: float) -> Optional[int]:
        """Dernier échantillon à `t` ou avant."""
        i = bisect_right(self._times, t) - 1
        return i if i >= 0 else None

    def decimate(self, t0: float, t1: float, buckets: int) -> List[dict]:
        """Découpe [t0, t1] en `buckets` tranches et rend, pour chacune, les INDEX extrêmes.

        ⚠ Ce que cette méthode NE fait PAS : préserver les extrema. Prendre le premier et le
        dernier point d'une tranche conserve l'allure générale, mais **une pointe au milieu d'une
        tranche disparaît**. Pour un tracé fidèle, c'est `decimate_values()` qu'il faut — elle
        calcule le min et le max réels par tranche. La présente méthode reste utile quand on n'a
        pas de colonne de valeur à agréger (événements, segments) ou qu'on veut seulement savoir
        quels échantillons couvrent quelle tranche.
        """
        if buckets <= 0 or t1 <= t0:
            return []
        i0, i1 = self.range_indices(t0, t1)
        if i1 <= i0:
            return []
        pas = (t1 - t0) / buckets
        out, i = [], i0
        for b in range(buckets):
            fin_t = t0 + (b + 1) * pas
            j = i
            while j < i1 and self._times[j] < fin_t:
                j += 1
            if j > i:
                out.append({'bucket': b, 't_start': t0 + b * pas, 't_end': fin_t,
                            'i_first': i, 'i_last': j - 1, 'count': j - i})
            i = j
        return out

    def decimate_values(self, t0: float, t1: float, buckets: int, column: str) -> List[dict]:
        """Vue décimée FIDÈLE : min et max RÉELS de `column` par tranche.

        C'est la primitive qui rend un tracé viable — 2 M de points sur 2000 px, c'est 1000 points
        par pixel : sans agrégation, soit on transfère tout, soit on échantillonne et on invente des
        artefacts. Rendre (min, max) par tranche conserve l'enveloppe du signal : une pointe reste
        visible même si elle ne dure qu'un échantillon.

        L'agrégation est DÉLÉGUÉE à la source quand elle sait la faire (`extent`) — une base SQL
        calcule `MIN`/`MAX` sans rien transférer. Sinon on lit les lignes, ce qui reste juste mais
        coûte le transfert de l'intervalle.
        """
        tranches = self.decimate(t0, t1, buckets)

        # Niveau 1 — la source sait tout agréger EN UNE PASSE. C'est le seul niveau viable pour
        # une vue d'interface : mesuré, 2000 tranches sur 2 M de points coûtent ~1 s ainsi contre
        # 24,9 s en interrogeant tranche par tranche.
        if self._extents is not None and tranches:
            try:
                groupes = self._extents(t0, t1, buckets, column) or {}
            except Exception:
                groupes = None
            if groupes is not None:
                # On réutilise l'ordinal PORTÉ par la tranche. Le recalculer depuis
                # `t_start` paraissait équivalent et ne l'est pas : `int((t0 + b*pas - t0)/pas)`
                # peut rendre `b-1` par arrondi flottant, et les valeurs se retrouvent alors
                # attribuées à la tranche voisine — constaté sur données réelles, deux
                # tranches consécutives rendant le même min/max.
                for b in tranches:
                    lo, hi = groupes.get(b['bucket'], (None, None))
                    b['min'], b['max'] = lo, hi
                if any(b['min'] is not None for b in tranches):
                    return tranches

        for b in tranches:
            i0, i1 = b['i_first'], b['i_last'] + 1
            lo = hi = None
            if self._extent is not None:
                # Bornes TEMPORELLES : une source indexée sur le temps agrège alors sans
                # re-parcourir. Passer des index l'obligerait à compter les lignes depuis le
                # début à chaque tranche — mesuré, c'est quadratique et inutilisable.
                try:
                    lo, hi = self._extent(b['t_start'], b['t_end'], column)
                except Exception:
                    lo = hi = None
            if lo is None and hi is None and self._rows is not None:
                vals = []
                for r in (self._rows(i0, i1) or []):
                    v = r.get(column) if isinstance(r, dict) else None
                    if isinstance(v, (int, float)):
                        vals.append(v)
                if vals:
                    lo, hi = min(vals), max(vals)
            b['min'], b['max'] = lo, hi
        return tranches


class TemporalReferential:
    """L'ensemble des flux d'une session, alignés sur une même origine.

    Ce que cette classe garantit : les flux sont interrogeables PAR LE TEMPS, quelles que soient
    leurs cadences respectives, sans qu'aucun n'ait été altéré. L'alignement des origines est un
    problème d'INGESTION (résolu en amont, flux par flux) — ici on suppose les instants déjà
    exprimés dans la même base de temps, et on n'offre qu'un `offset` par flux pour les médias
    externes qui ne sont pas ré-horodatés (une vidéo, typiquement).
    """

    def __init__(self, name: str = ''):
        self.name = name
        self._signals: Dict[str, Signal] = {}
        self._offsets: Dict[str, float] = {}

    # ── Composition ───────────────────────────────────────────────────────────────────────────
    def add(self, signal: Signal, offset: float = 0.0) -> Signal:
        if signal.meta.name in self._signals:
            raise ValueError(f"flux '{signal.meta.name}' déjà enregistré")
        self._signals[signal.meta.name] = signal
        self._offsets[signal.meta.name] = offset
        return signal

    def get(self, name: str) -> Signal:
        try:
            return self._signals[name]
        except KeyError:
            raise KeyError(
                f"flux '{name}' inconnu (enregistrés : {', '.join(sorted(self._signals)) or '—'})"
            ) from None

    @property
    def names(self) -> List[str]:
        return sorted(self._signals)

    def offset(self, name: str) -> float:
        """Décalage du flux vis-à-vis de la base de temps commune (médias externes)."""
        return self._offsets.get(name, 0.0)

    # ── Étendue ───────────────────────────────────────────────────────────────────────────────
    def span(self) -> Optional[Tuple[float, float]]:
        """Étendue couverte par AU MOINS un flux (union). None si tout est vide."""
        bornes = [(s.span[0] + self.offset(n), s.span[1] + self.offset(n))
                  for n, s in self._signals.items() if s.span]
        if not bornes:
            return None
        return min(b[0] for b in bornes), max(b[1] for b in bornes)

    def common_span(self) -> Optional[Tuple[float, float]]:
        """Étendue couverte par TOUS les flux (intersection) — utile pour comparer des flux entre
        eux sans extrapoler aux bords. None si l'intersection est vide."""
        bornes = [(s.span[0] + self.offset(n), s.span[1] + self.offset(n))
                  for n, s in self._signals.items() if s.span]
        if not bornes:
            return None
        lo, hi = max(b[0] for b in bornes), min(b[1] for b in bornes)
        return (lo, hi) if hi >= lo else None

    # ── Requêtes ──────────────────────────────────────────────────────────────────────────────
    def at(self, name: str, t: float, how: Optional[str] = None,
           tolerance: float = float('inf')) -> Optional[int]:
        """Index de l'échantillon de `name` résolvant l'instant `t` (temps de la session)."""
        sig = self.get(name)
        return sig.index_at(t - self.offset(name), how=how, tolerance=tolerance)

    def range(self, name: str, t0: float, t1: float) -> Tuple[int, int]:
        sig = self.get(name)
        off = self.offset(name)
        return sig.range_indices(t0 - off, t1 - off)

    def decimate(self, name: str, t0: float, t1: float, buckets: int) -> List[dict]:
        sig = self.get(name)
        off = self.offset(name)
        out = sig.decimate(t0 - off, t1 - off, buckets)
        for b in out:               # re-exprimer dans le temps de la session
            b['t_start'] += off
            b['t_end'] += off
        return out

    def decimate_values(self, name: str, t0: float, t1: float, buckets: int,
                        column: str) -> List[dict]:
        sig = self.get(name)
        off = self.offset(name)
        out = sig.decimate_values(t0 - off, t1 - off, buckets, column)
        for b in out:
            b['t_start'] += off
            b['t_end'] += off
        return out

    def next_event(self, name: str, t: float) -> Optional[int]:
        """Index du prochain échantillon de `name` strictement après `t`."""
        sig = self.get(name)
        return sig.next_index(t - self.offset(name))

    def previous_event(self, name: str, t: float) -> Optional[int]:
        sig = self.get(name)
        return sig.previous_index(t - self.offset(name))

    def containing(self, name: str, t: float) -> List[int]:
        """Index des segments de `name` contenant `t` (chevauchement et imbrication compris)."""
        sig = self.get(name)
        return sig.containing(t - self.offset(name))

    def overlapping(self, name: str, t0: float, t1: float) -> List[int]:
        sig = self.get(name)
        off = self.offset(name)
        return sig.overlapping(t0 - off, t1 - off)

    def segments_at(self, t: float) -> Dict[str, List[int]]:
        """Pour CHAQUE flux segmenté, les segments contenant `t`.

        C'est la question que pose toute vue synchronisée sur une session d'analyse : « dans quelles
        situations suis-je à cet instant ? » — plusieurs à la fois si les fenêtres sont emboîtées.
        """
        return {n: s.containing(t - self.offset(n))
                for n, s in self._signals.items() if s.is_segments}

    def snapshot(self, t: float, how: Optional[str] = None) -> Dict[str, Optional[int]]:
        """Index résolvant `t` pour CHAQUE flux — l'état de la session à un instant.

        C'est la primitive que consommera toute vue synchronisée : un seul instant, N flux à des
        cadences différentes, un échantillon par flux, aucune valeur inventée.
        """
        return {n: self.at(n, t, how=how) for n in self._signals}

    def __repr__(self) -> str:
        return f'<TemporalReferential {self.name!r} flux={len(self._signals)}>'
