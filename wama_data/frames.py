"""
LE PONT — `Signal` / `TemporalReferential` ↔ `TypedFrame`.

Ce module existe parce que WAMA Data avait **deux mondes parallèles que rien ne reliait**
(constat mesuré le 2026-08-23, `WAMA_DATA_WORLD.md §9quater.7`) :

    sources/ + core/temporal.py  →  Signal / TemporalReferential   (paresseux, indexé, SANS pandas)
    functions/                   →  TypedFrame                     (pandas — Segmenter, Calculator,
                                                                    Exporter, tout le catalogue)

On savait charger un enregistrement en référentiel. On savait calculer sur un cadre typé. On ne
savait **pas prendre un flux de l'enregistrement chargé et lui appliquer une fonction du catalogue.**

⚠ LE DÉPÔT LE DISAIT DÉJÀ, sans que le lien soit fait : le blocage déclaré du Référentiel dans
`modules.py` était « **AUCUN consommateur** — la brique est inerte tant qu'un module ne s'en sert
pas ». Il n'avait aucun consommateur **parce que rien ne pouvait convertir sa sortie**. Ce n'était
pas « personne ne s'en est encore servi », c'était « personne ne POUVAIT s'en servir ».

POURQUOI ICI, À LA RACINE DU MONDE, et pas dans `core/` ni dans `functions/` :
  • `core/` est PUR (ni pandas ni Django) — y mettre `TypedFrame` le romprait ;
  • `sources/` l'est aussi, et n'a pas à connaître le catalogue ;
  • `functions/<domaine>/` héberge des **fonctions déclarées au catalogue** ; le pont n'en est pas
    une, il est ce qui permet de les alimenter.
C'est donc une frontière à part entière, et elle mérite son fichier — au même niveau que
`modules.py`, la seule autre pièce qui parle du monde entier.

LES QUATRE PIÈGES QUE CE MODULE TRAITE — tous MESURÉS dans le code, aucun supposé.

  ① LE TEMPS DE SESSION N'EST PAS LE TEMPS DU FLUX. `TemporalReferential` travaille en temps de
     SESSION et chaque `Signal` en temps LOCAL ; la conversion est un `± offset` que le référentiel
     applique à chacune de ses requêtes (`at`, `range`, `decimate`…). Un pont bâti sur le `Signal`
     seul produirait des temps locaux, et **deux flux d'offsets différents seraient silencieusement
     désalignés dans le même cadre**. D'où : passer par le référentiel quand il y en a un.

  ② LA COLONNE TEMPORELLE BRUTE PEUT ÊTRE PÉRIMÉE. Les accesseurs de lignes font un `SELECT *` :
     les lignes portent donc encore `timecode` / `startTimecode` telles qu'en base. Or les instants
     du `Signal` ont pu être **RÉ-HORODATÉS** à l'import (`ResamplingTS`, appliqué à la demande).
     Prendre le temps dans la ligne rendrait alors l'ANCIENNE valeur. **Le temps vient toujours des
     `times` du signal**, et les colonnes temporelles brutes sont RETIRÉES du cadre — les laisser
     mettrait dans le même tableau deux colonnes de temps qui se contredisent.

  ③ LE CONTRAT DES LIGNES EST RÉEL MAIS N'ÉTAIT PAS DÉCLARÉ. `StreamSpec.rows` est typé
     `Callable[[int, int], Any]`. Les deux lecteurs existants rendent en fait une
     `List[Dict[str, Any]]` (vérifié : `trip.py::_row_accessor`, `tabular.py::read`). Ce module en
     dépend, donc il le VÉRIFIE au lieu de l'espérer : un troisième lecteur qui rendrait des
     tuples échouerait ici avec un message clair, pas plus loin avec un `KeyError` obscur.

  ④ UN CADRE QUI REVIENT D'UN CALCUL N'EST PAS UNE DONNÉE ACQUISE. `SignalMeta.is_base` existait
     DÉJÀ pour ça — « Acquis (True) vs dérivé d'un calcul (False). C'est la PROVENANCE : sans elle,
     impossible de savoir ce qu'un recalcul peut écraser sans perte. » Le champ était là, inemployé
     dans ce sens. `signal_from_frame()` force donc `is_base=False` : **on ne peut pas fabriquer
     un flux « acquis » par ce chemin.**

⚠ CE PONT NE SAVAIT PAS distinguer un flux de DONNÉES d'un flux d'ÉVÉNEMENTS — CORRIGÉ le
2026-08-24, et la correction mérite d'être lue. Le `Signal` ne portait pas sa famille : seulement
ses instants, ses fins éventuelles et un `comments` libre — or « des instants + des colonnes »
décrit les deux familles à l'identique.

Mais **le lecteur `.trip` CONNAISSAIT la famille** : il la tire du préfixe de table
(`data_`/`event_`/`situation_`) et la jetait dans le commentaire (`comments=f"{famille} · …"`).
Le fait existait ; il n'était pas porté comme DONNÉE. Et le relire depuis un libellé aurait été
prendre une TRACE pour une RÈGLE. D'où `SignalMeta.data_type`, rempli par les lecteurs avec les
constantes de la taxonomie partagée. `default_type()` préfère désormais la famille DÉCLARÉE et
ne retombe sur la structure que si la source ne dit rien.
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from wama.common.catalog.data_types import CANONICAL_FIELDS, DataType, TypedFrame
from wama.common.catalog.marks import DERIVED, RESERVED, Track, read_tracks

from .core.naming import TIME_AXES
from .core.temporal import NEAREST, PREVIOUS, Signal, SignalMeta, TemporalReferential


def _verifier_lignes(rows: Any, name: str) -> List[Dict[str, Any]]:
    """Piège ③ — le contrat `rows` est vérifié, pas espéré."""
    if rows is None:
        return []
    rows = list(rows)
    if rows and not isinstance(rows[0], Mapping):
        raise TypeError(
            f"flux '{name}' : l'accesseur `rows` doit rendre une liste de dicts "
            f"(champ → valeur), reçu {type(rows[0]).__name__}. C'est le contrat que "
            "respectent les lecteurs existants ; `StreamSpec.rows` le type `Any` par commodité, "
            "ce qui ne l'annule pas.")
    return rows


def default_type(signal: Signal) -> str:
    """Type de cadre : la FAMILLE DÉCLARÉE d'abord, la structure en repli.

    ⚠ L'ORDRE EST LE POINT (corrigé le 2026-08-24). `SignalMeta.data_type` porte désormais la
    famille que la source connaît — le lecteur `.trip` la tire du préfixe de table
    (`data_`/`event_`/`situation_`) et la jetait auparavant dans un commentaire. **Une donnée
    déclarée prime toujours sur une déduction structurelle** : c'est la seule façon de distinguer
    un flux d'ÉVÉNEMENTS d'un flux de DONNÉES, que la structure (« des instants + des colonnes »)
    décrit à l'identique.

    Repli quand la source ne dit rien : des fins ⇒ `segments`, sinon `timeseries`. Il reste juste,
    simplement moins fin.

    ⚠ Ce qu'on ne fait TOUJOURS PAS : lire la famille dans `meta.comments`. Un libellé est une
    TRACE, pas une règle — c'est précisément pour cela que le champ a été créé.
    """
    if signal.meta.data_type:
        return signal.meta.data_type
    return DataType.SEGMENTS if signal.is_segments else DataType.TIMESERIES


def _session_rows(signal: Signal, i0: int, i1: int, offset: float, segments: bool,
                  columns: Optional[Iterable[str]] = None) -> List[Dict[str, Any]]:
    """Les lignes `[i0, i1[` d'un flux sous les noms canoniques (`time`, ou `start` / `end`), en
    temps de SESSION — ce que lisent le cadre typé ET les pistes de marques, d'une seule façon."""
    rows = _verifier_lignes(signal.rows(i0, i1), signal.meta.name)
    kept = set(columns) if columns is not None else None
    out: List[Dict[str, Any]] = []
    for k in range(i0, i1):
        raw = rows[k - i0] if (k - i0) < len(rows) else {}
        # ② Le temps vient des `times` du signal — jamais de la ligne, qui peut être périmée.
        line: Dict[str, Any] = {}
        if segments:
            line['start'] = signal.time_at(k) + offset
            end = signal.end_at(k)
            line['end'] = None if end is None else end + offset
        else:
            line['time'] = signal.time_at(k) + offset
        for key, val in raw.items():
            if key.lower() in TIME_AXES:
                continue                      # ② colonne d'axe brute : retirée
            if kept is not None and key not in kept:
                continue
            line[key] = val
        out.append(line)
    return out


# ══════════════════════════════════════════════════════════════════════════════════════════════
# 1. Référentiel / Signal → TypedFrame
# ══════════════════════════════════════════════════════════════════════════════════════════════

def frame_from_signal(signal: Signal, *, t0: Optional[float] = None,
                        t1: Optional[float] = None, offset: float = 0.0,
                        data_type: Optional[str] = None,
                        champs: Optional[Iterable[str]] = None,
                        meta: Optional[Mapping[str, Any]] = None) -> TypedFrame:
    """Une FENÊTRE d'un flux, en cadre typé prêt pour le catalogue.

    `t0`/`t1` sont exprimés dans le **temps de session** (`offset` compris) ; omis, on prend tout
    le flux. La fenêtre est la règle et non l'exception : le motif de la lecture paresseuse
    (1,28 Go pour une passation réelle) vaut ici aussi — matérialiser un flux entier en pandas est
    l'exception qu'on demande, pas le défaut qu'on subit.

    `champs` restreint les colonnes de données. Les champs canoniques (`time`, ou `start`/`end`)
    sont TOUJOURS présents : ce sont eux qui rendent le cadre chaînable.
    """
    import pandas as pd

    name = signal.meta.name
    if t0 is None or t1 is None:
        i0, i1 = 0, len(signal)
    else:
        i0, i1 = signal.range_indices(t0 - offset, t1 - offset)

    dt = data_type or default_type(signal)
    segments = dt == DataType.SEGMENTS
    out = _session_rows(signal, i0, i1, offset, segments, champs)

    champs = CANONICAL_FIELDS.get(dt, ['time'])
    df = pd.DataFrame(out) if out else pd.DataFrame(columns=champs)
    # `end` peut porter des fins inconnues : même précaution que `functions/temporal/segmentation.py`
    # — pandas convertirait un `None` mêlé à des flottants en `NaN`, c'est-à-dire la sentinelle
    # numérique que le modèle refuse.
    if segments and out and any(r.get('end') is None for r in out):
        df['end'] = pd.Series([r.get('end') for r in out], dtype=object)

    infos: Dict[str, Any] = {'source_signal': name, 'is_base': signal.meta.is_base}
    if signal.meta.units:
        infos['units'] = dict(signal.meta.units)
    if t0 is not None and t1 is not None:
        infos['fenetre'] = (t0, t1)
    infos.update(meta or {})
    return TypedFrame(df, dt, meta=infos)


def frame_from_referential(ref: TemporalReferential, name: str, *,
                             t0: Optional[float] = None, t1: Optional[float] = None,
                             data_type: Optional[str] = None,
                             champs: Optional[Iterable[str]] = None) -> TypedFrame:
    """Une fenêtre d'un flux du référentiel, **en temps de session** (piège ①).

    C'est la porte d'entrée normale. `frame_from_signal()` reste utile pour un flux isolé, mais
    l'employer sur un flux qui appartient à un référentiel perdrait son décalage.
    """
    signal = ref.get(name)
    return frame_from_signal(signal, t0=t0, t1=t1, offset=ref.offset(name),
                               data_type=data_type, champs=champs,
                               meta={'referentiel': ref.name})


def frame_from_table(path, data_type: str, *,
                     meta: Optional[Mapping[str, Any]] = None) -> TypedFrame:
    """Un fichier PLAT (CSV, TSV, TXT, XLSX…) en cadre du type DIT — l'entrée « Jeu de données »
    du Studio (2026-10-22).

    Le fichier est lu par le lecteur du registre qui sait en faire une TABLE (`SourceReader.table`,
    le décodage et le typage par colonne du lecteur tabulaire) — jamais par un second décodeur :
    il en existait un, `pandas.read_csv`, à côté. Le type n'est pas déduit du fichier : il est
    DIT par l'utilisateur (`WAMA_DATA_FUNCTION_CARDS §5`). Lève `ValueError` si aucun lecteur ne
    lit ce fichier comme une table."""
    import pandas as pd
    from pathlib import Path

    from .sources import READERS, SourceReader, reader_for

    p = Path(path)
    reader = reader_for(p)
    table = reader.table(p) if reader is not None else None
    if table is None:
        # Les formats dont le lecteur DÉCLARE savoir rendre une table (il redéfinit `table`).
        flat = sorted({e for r in READERS.values() if type(r).table is not SourceReader.table
                       for e in r.extensions})
        raise ValueError(f"« {p.name} » ne se lit pas comme une table "
                         f"(formats tabulaires : {', '.join(flat) or '—'})")
    headers, rows = table
    width = len(headers)
    rows = [list(r[:width]) + [None] * (width - len(r)) for r in rows]
    return TypedFrame(pd.DataFrame(rows, columns=headers), data_type, meta=dict(meta or {}))


# ══════════════════════════════════════════════════════════════════════════════════════════════
# 2. TypedFrame → Signal (le retour d'un calcul dans le référentiel)
# ══════════════════════════════════════════════════════════════════════════════════════════════

def signal_from_frame(frame: TypedFrame, name: str, *, fs: Optional[float] = None,
                        units: Optional[Mapping[str, str]] = None,
                        comments: str = '') -> Signal:
    """Un cadre typé redevient un flux — **toujours DÉRIVÉ, jamais acquis** (piège ④).

    `is_base=False` n'est pas un défaut modifiable : aucun paramètre ne permet de le forcer à
    `True`. Fabriquer un flux « acquis » à partir d'un calcul rendrait indécidable ce qu'un
    recalcul peut écraser sans perte — la raison même pour laquelle le champ existe.

    Le `default_lookup` suit la nature : `PREVIOUS` pour des segments (un état vaut jusqu'au
    suivant), `NEAREST` pour un signal échantillonné. Reprendre celui du flux d'origine serait
    faux dès que le calcul change la granularité.
    """
    from .core.values import missing

    segments = frame.data_type == DataType.SEGMENTS
    key = 'start' if segments else 'time'
    if key not in frame.fields:
        raise ValueError(
            f"cadre sans champ '{key}' — un flux se construit sur des instants "
            f"(champs présents : {', '.join(frame.fields) or '—'})")

    rows: List[Dict[str, Any]] = frame.df.to_dict('records')
    times = [r[key] for r in rows]
    if any(t is None or missing(t) for t in times):
        raise ValueError(f"flux '{name}' : un instant manquant rend le flux inindexable — "
                         "les temps sont la clé, pas une colonne comme les autres")
    if any(times[i] < times[i - 1] for i in range(1, len(times))):
        raise ValueError(
            f"flux '{name}' : instants non croissants — trier avant de construire le flux "
            "(l'indexation par dichotomie donnerait des réponses fausses SANS erreur)")

    ends = None
    if segments and 'end' in frame.fields:
        # Une fin inconnue reste inconnue : `Signal.containing` la traite, pas une sentinelle.
        ends = [None if missing(r.get('end')) else r.get('end') for r in rows]

    meta = SignalMeta(
        name=name, fs=fs, units=dict(units or {}),
        is_base=False,                                   # ④ non négociable
        default_lookup=PREVIOUS if segments else NEAREST,
        comments=comments or f"dérivé · {len(frame.fields)} colonne(s)",
    )
    return Signal(meta, times, rows=lambda i0, i1: rows[i0:i1], ends=ends)


def adjoin(ref: TemporalReferential, name: str, frame: TypedFrame, *,
              offset: float = 0.0, **kwargs) -> Signal:
    """Ajoute au référentiel un flux issu d'un calcul, et le rend.

    ⚠ `TemporalReferential.add()` REFUSE un nom déjà pris — délibérément, et on ne contourne pas :
    écraser un flux en place rendrait irrécupérable ce qui l'a produit. Un recalcul se range sous
    un nom dérivé, comme une colonne calculée (`derived_name()`, `chain_name()`).
    """
    return ref.add(signal_from_frame(frame, name, **kwargs), offset=offset)


# ══════════════════════════════════════════════════════════════════════════════════════════════
# 3. Référentiel → PISTES de marques (`ROUTE §10.7`, marche 1)
# ══════════════════════════════════════════════════════════════════════════════════════════════

#: Les familles de flux qui SONT des pistes de marques. Un signal échantillonné (une ligne par
#: instant de mesure) est un flux de données, pas une piste (`ROUTE §10.7.11`).
MARK_TYPES = (DataType.SEGMENTS, DataType.EVENTS)

#: La colonne où le Segmenter et le codage tracent l'origine d'un segment (`segmentation._trace`).
ORIGIN_COLUMN = 'origin'

#: Ce qu'on peut faire d'une marque MESURÉE (`ROUTE §10.7.12 ⑤`, `§10.7.14` E4) : le temps mesuré
#: est un fait — ni déplacée, ni retaillée, ni réordonnée, ni supprimée. On l'étiquette, on la
#: masque, on en tire une card ; un segment se scinde et se fusionne. Ces gestes vont TOUJOURS dans
#: une piste dérivée : la piste du fichier reste intacte.
MEASURED_GESTURES = {DataType.SEGMENTS: ('extract', 'label', 'mask', 'merge', 'split'),
                     DataType.EVENTS: ('extract', 'label', 'mask')}


def _stream_rows(name: str, segments: bool):
    """La source d'une piste : les lignes du flux `name` du référentiel qu'on lui passe."""
    def rows(ref: TemporalReferential) -> List[Dict[str, Any]]:
        signal = ref.get(name)
        return _session_rows(signal, 0, len(signal), ref.offset(name), segments)
    return rows


def referential_tracks(ref: TemporalReferential) -> Tuple[Track, ...]:
    """Les flux d'ÉVÉNEMENTS et de SEGMENTS d'un référentiel, dits comme des pistes — sans
    déclaration d'app : la source est le FICHIER (`.wdat`, `.trip`… tout ce qu'un lecteur du
    registre charge). La famille est celle que le flux porte (`default_type`), les attributs sont
    ses colonnes (lues sur sa première ligne), l'origine celle que chaque ligne trace quand le
    Segmenter l'a produite. Aucune piste parente n'est dite : un conteneur ne range pas encore ce
    lien, et le deviner par contenance en inventerait un."""
    tracks = []
    for name in ref.names:
        signal = ref.get(name)
        kind = default_type(signal)
        if kind not in MARK_TYPES:
            continue
        first = _verifier_lignes(signal.rows(0, 1), name) if len(signal) else []
        columns = [c for c in (first[0] if first else {}) if c.lower() not in TIME_AXES]
        tracks.append(Track(
            key=name, label=name, kind=kind,
            source=_stream_rows(name, kind == DataType.SEGMENTS),
            # Une colonne qui porte un nom que le lecteur écrit (`source`, `parent`…) se lit sous
            # ce nom suivi d'un souligné : aucune colonne du fichier n'est écrasée ni perdue.
            attributes=tuple((f'{c}_', c) if c in RESERVED else c
                             for c in columns if c != ORIGIN_COLUMN),
            origin_field=ORIGIN_COLUMN if ORIGIN_COLUMN in columns else '',
            gestures=MEASURED_GESTURES[kind], edits=DERIVED))
    return tuple(tracks)


def read_referential_tracks(ref: TemporalReferential) -> Dict[str, List[dict]]:
    """Les marques des pistes d'un référentiel, par le lecteur COMMUN (`catalog/marks.read_tracks`)
    et sous ses noms (`start`, `end` absent = ouvert, ou `time` ; `origin`), en temps de SESSION :
    la forme même que rend la piste d'une card d'un autre monde."""
    return read_tracks(ref, referential_tracks(ref))
