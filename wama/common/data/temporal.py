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
    #: Cadence théorique en Hz. `None` = irrégulier ou inconnu — c'est un cas NORMAL.
    fs: Optional[float] = None
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

    __slots__ = ('meta', '_times', '_rows')

    def __init__(self, meta: SignalMeta, times: Sequence[float],
                 rows: Optional[Callable[[int, int], Any]] = None):
        self.meta = meta
        self._times = times
        self._rows = rows

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

    def decimate(self, t0: float, t1: float, buckets: int) -> List[dict]:
        """Découpe [t0, t1] en `buckets` tranches et rend, pour chacune, les INDEX extrêmes.

        Rend des index et non des valeurs : la couche ne sait pas lire les valeurs (c'est le rôle
        de l'accesseur), mais elle sait dire QUELS échantillons représentent une tranche. Un tracé
        qui prend le premier et le dernier de chaque tranche conserve la forme ET les extrema
        apparents, là où un simple « 1 point sur N » invente des artefacts.
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
                out.append({'t_start': t0 + b * pas, 't_end': fin_t,
                            'i_first': i, 'i_last': j - 1, 'count': j - i})
            i = j
        return out


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

    def snapshot(self, t: float, how: Optional[str] = None) -> Dict[str, Optional[int]]:
        """Index résolvant `t` pour CHAQUE flux — l'état de la session à un instant.

        C'est la primitive que consommera toute vue synchronisée : un seul instant, N flux à des
        cadences différentes, un échantillon par flux, aucune valeur inventée.
        """
        return {n: self.at(n, t, how=how) for n in self._signals}

    def __repr__(self) -> str:
        return f'<TemporalReferential {self.name!r} flux={len(self._signals)}>'
