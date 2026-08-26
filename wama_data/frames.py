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
     dans ce sens. `signal_depuis_frame()` force donc `is_base=False` : **on ne peut pas fabriquer
     un flux « acquis » par ce chemin.**

⚠ CE PONT NE SAVAIT PAS distinguer un flux de DONNÉES d'un flux d'ÉVÉNEMENTS — CORRIGÉ le
2026-08-24, et la correction mérite d'être lue. Le `Signal` ne portait pas sa famille : seulement
ses instants, ses fins éventuelles et un `comments` libre — or « des instants + des colonnes »
décrit les deux familles à l'identique.

Mais **le lecteur `.trip` CONNAISSAIT la famille** : il la tire du préfixe de table
(`data_`/`event_`/`situation_`) et la jetait dans le commentaire (`comments=f"{famille} · …"`).
Le fait existait ; il n'était pas porté comme DONNÉE. Et le relire depuis un libellé aurait été
prendre une TRACE pour une RÈGLE. D'où `SignalMeta.data_type`, rempli par les lecteurs avec les
constantes de la taxonomie partagée. `type_par_defaut()` préfère désormais la famille DÉCLARÉE et
ne retombe sur la structure que si la source ne dit rien.
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

from wama.common.catalog.data_types import CANONICAL_FIELDS, DataType, TypedFrame

from .core.noms import AXES_TEMPORELS as _AXES_BRUTS  # noqa: F401 — nom local historique
from .core.temporal import NEAREST, PREVIOUS, Signal, SignalMeta, TemporalReferential


def _verifier_lignes(lignes: Any, name: str) -> List[Dict[str, Any]]:
    """Piège ③ — le contrat `rows` est vérifié, pas espéré."""
    if lignes is None:
        return []
    lignes = list(lignes)
    if lignes and not isinstance(lignes[0], Mapping):
        raise TypeError(
            f"flux '{name}' : l'accesseur `rows` doit rendre une liste de dicts "
            f"(champ → valeur), reçu {type(lignes[0]).__name__}. C'est le contrat que "
            "respectent les lecteurs existants ; `StreamSpec.rows` le type `Any` par commodité, "
            "ce qui ne l'annule pas.")
    return lignes


def type_par_defaut(signal: Signal) -> str:
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


# ══════════════════════════════════════════════════════════════════════════════════════════════
# 1. Référentiel / Signal → TypedFrame
# ══════════════════════════════════════════════════════════════════════════════════════════════

def frame_depuis_signal(signal: Signal, *, t0: Optional[float] = None,
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

    lignes = _verifier_lignes(signal.rows(i0, i1), name)
    garde = set(champs) if champs is not None else None

    dt = data_type or type_par_defaut(signal)
    segments = dt == DataType.SEGMENTS

    out: List[Dict[str, Any]] = []
    for k in range(i0, i1):
        brute = lignes[k - i0] if (k - i0) < len(lignes) else {}
        # ② Le temps vient des `times` du signal — jamais de la ligne, qui peut être périmée.
        ligne: Dict[str, Any] = {}
        if segments:
            ligne['start'] = signal.time_at(k) + offset
            fin = signal.end_at(k)
            ligne['end'] = None if fin is None else fin + offset
        else:
            ligne['time'] = signal.time_at(k) + offset
        for cle, val in brute.items():
            if cle.lower() in _AXES_BRUTS:
                continue                      # ② colonne d'axe brute : retirée
            if garde is not None and cle not in garde:
                continue
            ligne[cle] = val
        out.append(ligne)

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


def frame_depuis_referentiel(ref: TemporalReferential, name: str, *,
                             t0: Optional[float] = None, t1: Optional[float] = None,
                             data_type: Optional[str] = None,
                             champs: Optional[Iterable[str]] = None) -> TypedFrame:
    """Une fenêtre d'un flux du référentiel, **en temps de session** (piège ①).

    C'est la porte d'entrée normale. `frame_depuis_signal()` reste utile pour un flux isolé, mais
    l'employer sur un flux qui appartient à un référentiel perdrait son décalage.
    """
    signal = ref.get(name)
    return frame_depuis_signal(signal, t0=t0, t1=t1, offset=ref.offset(name),
                               data_type=data_type, champs=champs,
                               meta={'referentiel': ref.name})


# ══════════════════════════════════════════════════════════════════════════════════════════════
# 2. TypedFrame → Signal (le retour d'un calcul dans le référentiel)
# ══════════════════════════════════════════════════════════════════════════════════════════════

def signal_depuis_frame(frame: TypedFrame, name: str, *, fs: Optional[float] = None,
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
    from .core.valeurs import manquant

    segments = frame.data_type == DataType.SEGMENTS
    cle = 'start' if segments else 'time'
    if cle not in frame.fields:
        raise ValueError(
            f"cadre sans champ '{cle}' — un flux se construit sur des instants "
            f"(champs présents : {', '.join(frame.fields) or '—'})")

    lignes: List[Dict[str, Any]] = frame.df.to_dict('records')
    times = [r[cle] for r in lignes]
    if any(t is None or manquant(t) for t in times):
        raise ValueError(f"flux '{name}' : un instant manquant rend le flux inindexable — "
                         "les temps sont la clé, pas une colonne comme les autres")
    if any(times[i] < times[i - 1] for i in range(1, len(times))):
        raise ValueError(
            f"flux '{name}' : instants non croissants — trier avant de construire le flux "
            "(l'indexation par dichotomie donnerait des réponses fausses SANS erreur)")

    ends = None
    if segments and 'end' in frame.fields:
        # Une fin inconnue reste inconnue : `Signal.containing` la traite, pas une sentinelle.
        ends = [None if manquant(r.get('end')) else r.get('end') for r in lignes]

    meta = SignalMeta(
        name=name, fs=fs, units=dict(units or {}),
        is_base=False,                                   # ④ non négociable
        default_lookup=PREVIOUS if segments else NEAREST,
        comments=comments or f"dérivé · {len(frame.fields)} colonne(s)",
    )
    return Signal(meta, times, rows=lambda i0, i1: lignes[i0:i1], ends=ends)


def adjoindre(ref: TemporalReferential, name: str, frame: TypedFrame, *,
              offset: float = 0.0, **kwargs) -> Signal:
    """Ajoute au référentiel un flux issu d'un calcul, et le rend.

    ⚠ `TemporalReferential.add()` REFUSE un nom déjà pris — délibérément, et on ne contourne pas :
    écraser un flux en place rendrait irrécupérable ce qui l'a produit. Un recalcul se range sous
    un nom dérivé, comme une colonne calculée (`nom_produit()`, `nom_chaine()`).
    """
    return ref.add(signal_depuis_frame(frame, name, **kwargs), offset=offset)
