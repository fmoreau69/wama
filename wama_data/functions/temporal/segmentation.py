"""
Déclaration au catalogue des modes de segmentation (implémentation : `wama_data/core/segmentation.py`).

Ce fichier ne contient AUCUNE logique : il expose les modes en fonctions à ports typés, pour que le
canvas studio les voie et puisse les chaîner sans code studio spécifique. C'est le geste que §7ter
appelle « héritage de capacités » — et c'est aussi ce qui empêche qu'une segmentation soit
réécrite à la main dans une app.

⚠ ADAPTATEURS DE PORTS. Les fonctions de `segmentation.py` prennent des listes de flottants (elles
sont pures et sans dépendance) ; le catalogue, lui, fait circuler des `TypedFrame`. Les enveloppes
ci-dessous font la conversion — et c'est leur seul rôle. Mettre la conversion DANS les fonctions
pures les rendrait dépendantes de pandas et intestables sans lui.
"""
from __future__ import annotations

from wama.common.catalog.data_types import CANONICAL_FIELDS, DataType, TypedFrame
from wama.common.catalog.function_catalog import (FunctionCategory, FunctionSpec, ParamSpec, PortSpec, register)
from ...core.segmentation import (around, conditional, states, join, margins, times_within,
                                  within)
#: RÉEXPORT délibéré — `missing` a été remonté au cœur (`core/valeurs.py`) quand le Calculator
#: en est devenu le 4ᵉ consommateur : `core/` ne peut pas dépendre de `functions/`. Le garder
#: importable d'ici évite de toucher les 3 importateurs existants pour un simple déménagement.
from ...core.values import missing  # noqa: F401  (réexporté pour `coding.py` et les tests)

#: Champs canoniques d'un segment produit — `start`/`end` viennent de la taxonomie, le reste est
#: la traçabilité systématique (voir `_tracer` dans l'implémentation).
CHAMPS_SEGMENT = CANONICAL_FIELDS[DataType.SEGMENTS] + ['name', 'origin']


def _colonne(frame: TypedFrame, name: str) -> list:
    """Une colonne d'un `TypedFrame`, en liste Python. Lève si elle manque — un port typé qui
    reçoit un cadre sans son champ requis est une erreur de chaînage, pas un cas à contourner."""
    try:
        return list(frame.df[name])
    except Exception:
        raise ValueError(
            f"colonne '{name}' absente (disponibles : {', '.join(frame.fields) or '—'})")


def _segments(rows: list, meta=None) -> TypedFrame:
    """Cadre typé `segments`, en PRÉSERVANT les fins inconnues.

    ⚠ pandas convertit silencieusement un `None` mêlé à des flottants en `NaN` — c'est-à-dire
    exactement la sentinelle numérique que le modèle refuse. Conséquences si on laisse faire :
    `end is None` devient faux, les segments ouverts deviennent introuvables, et toute durée se
    calcule en `NaN` sans que rien ne le signale. On force donc la colonne en `object` dès qu'une
    fin est inconnue, ce qui laisse `None` survivre à l'aller-retour.
    """
    import pandas as pd
    if not rows:
        return TypedFrame(pd.DataFrame(columns=CHAMPS_SEGMENT), DataType.SEGMENTS, meta=meta)
    df = pd.DataFrame(rows)
    if 'end' in df.columns and any(r.get('end') is None for r in rows):
        df['end'] = pd.Series([r.get('end') for r in rows], dtype=object)
    return TypedFrame(df, DataType.SEGMENTS, meta=meta)


def _fin(value):
    """Fin d'un segment lue depuis un cadre : `NaN` (venu d'ailleurs) est traité comme inconnu."""
    return None if missing(value) else value


# ──────────────────────────────────────────────────────────────────────────────────────────────

def segments_around(events: TypedFrame, offset_start: float = 0.0, offset_end: float = 15.0,
                    name: str = '') -> TypedFrame:
    """Fenêtre `[ancre+o₁, ancre+o₂]` autour de chaque événement."""
    return _segments(around(_colonne(events, 'time'), offset_start, offset_end, name=name),
                     meta=events.meta)


def segments_join(starts: TypedFrame, ends: TypedFrame, name: str = '',
                      skip_starts: int = 0, skip_ends: int = 0,
                      offset_start: float = 0.0, offset_end: float = 0.0,
                      repeat: bool = True, drop_last_open: bool = False) -> TypedFrame:
    """Début pris dans un flux, fin dans l'autre — appariement par le temps.

    ⚠ Les curseurs et offsets existaient dans le CŒUR sans être DÉCLARÉS ici (trou ② de §11.9) :
    l'UI se générant des `ParamSpec`, l'écran « Double » n'aurait eu ni offsets, ni curseurs
    d'occurrence, ni « Répéter ». Une capacité non déclarée est une capacité invisible.
    """
    return _segments(join(_colonne(starts, 'time'), _colonne(ends, 'time'), name=name,
                              skip_starts=skip_starts, skip_ends=skip_ends,
                              offset_start=offset_start, offset_end=offset_end,
                              repeat=repeat, drop_last_open=drop_last_open),
                     meta=starts.meta)


def segments_margins(segments: TypedFrame, before: float = 0.0, after: float = 0.0) -> TypedFrame:
    """Élargit (ou rétrécit) chaque segment : `start − avant`, `end + apres`."""
    rows = [dict(r, end=_fin(r.get('end'))) for r in segments.df.to_dict('records')]
    return _segments(margins(rows, before=before, after=after), meta=segments.meta)


def segments_conditional(signal: TypedFrame, column: str = 'value', threshold: float = 0.0,
                           operator: str = '>=', min_duration: float = 0.0,
                           gap_tolerance: float = 0.0, name: str = '') -> TypedFrame:
    """Plages où le signal satisfait la condition, avec hystérésis.

    Le prédicat est déclaré par (colonne, opérateur, seuil) — la forme qu'emploie l'outil d'origine
    et la seule qui reste sérialisable dans un manifeste. Un prédicat en code arbitraire ne serait
    ni déclarable, ni rejouable, ni exportable en script.
    """
    values = _colonne(signal, column)
    tests = {'>=': lambda v: v >= threshold, '>': lambda v: v > threshold,
             '<=': lambda v: v <= threshold, '<': lambda v: v < threshold,
             '==': lambda v: v == threshold, '!=': lambda v: v != threshold}
    if operator not in tests:
        raise ValueError(f"opérateur '{operator}' inconnu (attendu : {', '.join(tests)})")
    predicat = tests[operator]
    masque = [bool(predicat(v)) if isinstance(v, (int, float)) else False for v in values]
    return _segments(conditional(_colonne(signal, 'time'), masque, min_duration=min_duration,
                                    gap_tolerance=gap_tolerance, name=name), meta=signal.meta)


def segments_states(signal: TypedFrame, column: str = 'value', ignore: str = '',
                   name: str = '') -> TypedFrame:
    """Plages de valeur constante d'un signal catégoriel — les « états »."""
    a_ignorer = [x.strip() for x in ignore.split(',') if x.strip()] if ignore else []
    return _segments(states(_colonne(signal, 'time'), _colonne(signal, column),
                           ignore=a_ignorer, name=name), meta=signal.meta)


def segments_within(segments: TypedFrame, reference: TypedFrame,
                          strict: bool = True) -> TypedFrame:
    """Ne garde que les segments inclus dans un segment de référence."""
    def _lire(f):
        return [{'start': s, 'end': _fin(e)}
                for s, e in zip(_colonne(f, 'start'), _colonne(f, 'end'))]
    gardes = within(_lire(segments), _lire(reference), strict=strict)
    bornes = {(g['start'], g['end']) for g in gardes}
    rows = [dict(r, end=_fin(r.get('end'))) for r in segments.df.to_dict('records')
              if (r.get('start'), _fin(r.get('end'))) in bornes]
    return _segments(rows, meta=segments.meta)


# ──────────────────────────────────────────────────────────────────────────────────────────────
# Déclarations
# ──────────────────────────────────────────────────────────────────────────────────────────────

_SORTIE = PortSpec('segments', DataType.SEGMENTS, produced_fields=CHAMPS_SEGMENT,
                   description="Segments produits — l'origine du mode est tracée sur chaque ligne.")

register(FunctionSpec(
    key='segment_around_events',
    name="Segments autour d'événements",
    description="Fenêtre [ancre+o₁, ancre+o₂] autour de chaque événement. Les DEUX offsets sont "
                "indépendants : une fenêtre peut commencer après l'ancre (« de +15 s à +45 s »), "
                "ce qu'une simple durée ne permet pas d'exprimer.",
    category=FunctionCategory.TRANSFORM,
    tags=['temporel', 'segmentation'],
    inputs=[PortSpec('events', DataType.EVENTS, required_fields=['time'],
                     description="Ancres temporelles.")],
    outputs=[_SORTIE],
    params=[
        ParamSpec('offset_start', 'float', 0.0, unit='s',
                  description="Décalage du DÉBUT par rapport à l'ancre (négatif = avant)."),
        ParamSpec('offset_end', 'float', 15.0, unit='s',
                  description="Décalage de la FIN par rapport à l'ancre."),
        ParamSpec('name', 'str', '', description="Préfixe de nommage des segments."),
    ],
    cost={'cpu_bound': True},
    fn=segments_around,
))

register(FunctionSpec(
    key='segment_join',
    name="Segments par jonction de deux flux",
    description="Début pris dans un flux d'événements, fin dans un autre. L'appariement se fait "
                "par le TEMPS (première fin postérieure au début) et non par index : deux flux "
                "indépendants n'ont pas le même nombre d'occurrences. Un début sans fin donne un "
                "segment OUVERT plutôt qu'un segment perdu.",
    category=FunctionCategory.JOIN,
    tags=['temporel', 'segmentation'],
    inputs=[
        PortSpec('starts', DataType.EVENTS, required_fields=['time'],
                 description="Flux fournissant les DÉBUTS."),
        PortSpec('ends', DataType.EVENTS, required_fields=['time'],
                 description="Flux fournissant les FINS."),
    ],
    outputs=[_SORTIE],
    params=[
        ParamSpec('offset_start', 'float', 0.0, unit='s',
                  description="Décalage du DÉBUT après appariement (« le début du bloc moins "
                              "2 s »). Appliqué APRÈS : décaler avant changerait l'appariement."),
        ParamSpec('offset_end', 'float', 0.0, unit='s',
                  description="Décalage de la FIN après appariement (« la pause suivante plus 5 s »)."),
        ParamSpec('skip_starts', 'int', 0, 0,
                  description="Occurrences de DÉBUT sautées avant d'apparier — le curseur "
                              "« Table 1 » de l'écran d'origine."),
        ParamSpec('skip_ends', 'int', 0, 0,
                  description="Occurrences de FIN sautées avant d'apparier — le curseur "
                              "« Table 2 » de l'écran d'origine."),
        ParamSpec('repeat', 'bool', True,
                  description="Un segment par début (défaut) ; décoché : un seul, celui des "
                              "curseurs — la case « Répéter sur les prochains segments »."),
        ParamSpec('name', 'str', ''),
        ParamSpec('drop_last_open', 'bool', False,
                  description="Écarter le dernier segment s'il reste ouvert (défaut : le garder)."),
    ],
    cost={'cpu_bound': True},
    fn=segments_join,
))

register(FunctionSpec(
    key='segment_margins',
    name="Marges autour de segments existants",
    description="Décale les deux bornes de chaque segment : start − avant, end + apres. C'est le "
                "mode « Simple » appliqué à une SITUATION (marges inf/sup), qu'`around` ne couvre "
                "pas — une situation a deux bornes, pas une ancre. Négatif = rétrécir ; un segment "
                "qui s'inverse est ÉCARTÉ ; une fin ouverte le reste. L'origine d'avant la marge "
                "survit dans `source`.",
    category=FunctionCategory.TRANSFORM,
    tags=['temporel', 'segmentation'],
    inputs=[PortSpec('segments', DataType.SEGMENTS, required_fields=['start', 'end'])],
    outputs=[_SORTIE],
    params=[
        ParamSpec('before', 'float', 0.0, unit='s',
                  description="Marge ajoutée AVANT chaque segment (start − avant)."),
        ParamSpec('after', 'float', 0.0, unit='s',
                  description="Marge ajoutée APRÈS chaque segment (end + apres)."),
    ],
    cost={'cpu_bound': True},
    fn=segments_margins,
))

register(FunctionSpec(
    key='segment_conditional',
    name="Segments par condition",
    description="Plages où un signal satisfait (colonne, opérateur, seuil), avec HYSTÉRÉSIS. "
                "Sans durée minimale ni trou toléré, un seuil sur un signal réel produit des "
                "centaines de micro-segments dus au bruit.",
    category=FunctionCategory.DETECTOR,
    tags=['temporel', 'segmentation'],
    inputs=[PortSpec('signal', DataType.TIMESERIES, required_fields=['time'])],
    outputs=[_SORTIE],
    params=[
        ParamSpec('column', 'str', 'value', description="Colonne testée."),
        ParamSpec('operator', 'enum', '>=', choices=['>=', '>', '<=', '<', '==', '!='],
                  description="Comparaison — déclarée, donc sérialisable dans un manifeste."),
        ParamSpec('threshold', 'float', 0.0),
        ParamSpec('min_duration', 'float', 0.0, 0.0, unit='s',
                  description="Durée minimale d'une plage retenue."),
        ParamSpec('gap_tolerance', 'float', 0.0, 0.0, unit='s',
                  description="Interruption recollée au lieu de couper la plage."),
        ParamSpec('name', 'str', ''),
    ],
    cost={'cpu_bound': True},
    fn=segments_conditional,
))

register(FunctionSpec(
    key='segment_states',
    name="Segments d'état (plages de valeur constante)",
    description="Découpe un signal catégoriel en plages de valeur constante. C'est la conversion "
                "entre les deux représentations d'un segment : implicite (une colonne "
                "échantillonnée) et explicite (des bornes) — sans elle, un état déclaré dans un "
                "signal reste inexploitable comme segment.",
    category=FunctionCategory.TRANSFORM,
    tags=['temporel', 'segmentation', 'categoriel'],
    inputs=[PortSpec('signal', DataType.TIMESERIES, required_fields=['time'])],
    outputs=[PortSpec('segments', DataType.SEGMENTS,
                      produced_fields=CHAMPS_SEGMENT + ['value', 'samples'])],
    params=[
        ParamSpec('column', 'str', 'value'),
        ParamSpec('ignore', 'str', '',
                  description="Valeurs à ne pas segmenter, séparées par des virgules "
                              "(ex. « -1 » pour « aucun état »)."),
        ParamSpec('name', 'str', ''),
    ],
    cost={'cpu_bound': True},
    fn=segments_states,
))

register(FunctionSpec(
    key='segment_within',
    name="Restreindre des segments à un contexte",
    description="Ne garde que les segments inclus dans l'un des segments de référence. "
                "Opération ENSEMBLISTE et non un mode de segmentation : elle sert aussi à "
                "l'export, où l'on restreint un tableau à un contexte d'analyse.",
    category=FunctionCategory.TRANSFORM,
    tags=['temporel', 'segmentation', 'ensembliste'],
    inputs=[
        PortSpec('segments', DataType.SEGMENTS, required_fields=['start', 'end']),
        PortSpec('reference', DataType.SEGMENTS, required_fields=['start', 'end'],
                 description="Contexte auquel on restreint."),
    ],
    outputs=[_SORTIE],
    params=[ParamSpec('strict', 'bool', True,
                      description="Bornes strictement intérieures (défaut) ou égalité admise.")],
    cost={'cpu_bound': True},
    fn=segments_within,
))


def events_within(events: TypedFrame, reference: TypedFrame, strict: bool = True) -> TypedFrame:
    """Ne garde que les événements dont l'INSTANT tombe dans un segment de référence.

    Le pendant événement de `segments_within` — la restriction « Situation : … » que l'écran
    conditionnel d'origine applique à sa sortie ÉVÉNEMENTS (le point « mineur, à vérifier au
    câblage » de §11.9, désormais câblé).
    """
    ref = [{'start': s, 'end': _fin(e)}
           for s, e in zip(_colonne(reference, 'start'), _colonne(reference, 'end'))]
    mask = times_within(_colonne(events, 'time'), ref, strict=strict)
    keep = [i for i, m in enumerate(mask) if m]
    return TypedFrame(events.df.iloc[keep].copy(), events.data_type, meta=events.meta)


register(FunctionSpec(
    key='event_within',
    name="Restreindre des événements à un contexte",
    description="Ne garde que les événements dont l'instant tombe dans l'un des segments de "
                "référence — la restriction « Situation : … » appliquée à une sortie ÉVÉNEMENTS. "
                "Opération ensembliste, comme « Restreindre des segments à un contexte » ; une "
                "fin OUVERTE de la référence contient tout instant postérieur à son début.",
    category=FunctionCategory.TRANSFORM,
    tags=['temporel', 'segmentation', 'ensembliste', 'evenement'],
    inputs=[
        PortSpec('events', DataType.EVENTS, required_fields=['time']),
        PortSpec('reference', DataType.SEGMENTS, required_fields=['start', 'end'],
                 description="Contexte auquel on restreint."),
    ],
    outputs=[PortSpec('events', DataType.EVENTS,
                      description="Les événements retenus, colonnes inchangées.")],
    params=[ParamSpec('strict', 'bool', True,
                      description="Bornes strictement intérieures (défaut) ou égalité admise.")],
    cost={'cpu_bound': True},
    fn=events_within,
))
