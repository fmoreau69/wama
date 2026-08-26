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
from ...core.segmentation import autour, conditionnelle, etats, jonction, marges, present_dans
#: RÉEXPORT délibéré — `manquant` a été remonté au cœur (`core/valeurs.py`) quand le Calculator
#: en est devenu le 4ᵉ consommateur : `core/` ne peut pas dépendre de `functions/`. Le garder
#: importable d'ici évite de toucher les 3 importateurs existants pour un simple déménagement.
from ...core.valeurs import manquant  # noqa: F401  (réexporté pour `coding.py` et les tests)

#: Champs canoniques d'un segment produit — `start`/`end` viennent de la taxonomie, le reste est
#: la traçabilité systématique (voir `_tracer` dans l'implémentation).
CHAMPS_SEGMENT = CANONICAL_FIELDS[DataType.SEGMENTS] + ['name', 'origin']


def _colonne(frame: TypedFrame, nom: str) -> list:
    """Une colonne d'un `TypedFrame`, en liste Python. Lève si elle manque — un port typé qui
    reçoit un cadre sans son champ requis est une erreur de chaînage, pas un cas à contourner."""
    try:
        return list(frame.df[nom])
    except Exception:
        raise ValueError(
            f"colonne '{nom}' absente (disponibles : {', '.join(frame.fields) or '—'})")


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


def _fin(valeur):
    """Fin d'un segment lue depuis un cadre : `NaN` (venu d'ailleurs) est traité comme inconnu."""
    return None if manquant(valeur) else valeur


# ──────────────────────────────────────────────────────────────────────────────────────────────

def segments_autour(events: TypedFrame, offset_debut: float = 0.0, offset_fin: float = 15.0,
                    nom: str = '') -> TypedFrame:
    """Fenêtre `[ancre+o₁, ancre+o₂]` autour de chaque événement."""
    return _segments(autour(_colonne(events, 'time'), offset_debut, offset_fin, nom=nom),
                     meta=events.meta)


def segments_jonction(debuts: TypedFrame, fins: TypedFrame, nom: str = '',
                      depuis_debut: int = 0, depuis_fin: int = 0,
                      offset_debut: float = 0.0, offset_fin: float = 0.0,
                      repeter: bool = True, fermer_dernier: bool = False) -> TypedFrame:
    """Début pris dans un flux, fin dans l'autre — appariement par le temps.

    ⚠ Les curseurs et offsets existaient dans le CŒUR sans être DÉCLARÉS ici (trou ② de §11.9) :
    l'UI se générant des `ParamSpec`, l'écran « Double » n'aurait eu ni offsets, ni curseurs
    d'occurrence, ni « Répéter ». Une capacité non déclarée est une capacité invisible.
    """
    return _segments(jonction(_colonne(debuts, 'time'), _colonne(fins, 'time'), nom=nom,
                              depuis_debut=depuis_debut, depuis_fin=depuis_fin,
                              offset_debut=offset_debut, offset_fin=offset_fin,
                              repeter=repeter, fermer_dernier=fermer_dernier),
                     meta=debuts.meta)


def segments_marges(segments: TypedFrame, avant: float = 0.0, apres: float = 0.0) -> TypedFrame:
    """Élargit (ou rétrécit) chaque segment : `start − avant`, `end + apres`."""
    rows = [dict(r, end=_fin(r.get('end'))) for r in segments.df.to_dict('records')]
    return _segments(marges(rows, avant=avant, apres=apres), meta=segments.meta)


def segments_conditionnels(signal: TypedFrame, colonne: str = 'value', seuil: float = 0.0,
                           operateur: str = '>=', duree_min: float = 0.0,
                           trou_tolere: float = 0.0, nom: str = '') -> TypedFrame:
    """Plages où le signal satisfait la condition, avec hystérésis.

    Le prédicat est déclaré par (colonne, opérateur, seuil) — la forme qu'emploie l'outil d'origine
    et la seule qui reste sérialisable dans un manifeste. Un prédicat en code arbitraire ne serait
    ni déclarable, ni rejouable, ni exportable en script.
    """
    valeurs = _colonne(signal, colonne)
    tests = {'>=': lambda v: v >= seuil, '>': lambda v: v > seuil,
             '<=': lambda v: v <= seuil, '<': lambda v: v < seuil,
             '==': lambda v: v == seuil, '!=': lambda v: v != seuil}
    if operateur not in tests:
        raise ValueError(f"opérateur '{operateur}' inconnu (attendu : {', '.join(tests)})")
    predicat = tests[operateur]
    masque = [bool(predicat(v)) if isinstance(v, (int, float)) else False for v in valeurs]
    return _segments(conditionnelle(_colonne(signal, 'time'), masque, duree_min=duree_min,
                                    trou_tolere=trou_tolere, nom=nom), meta=signal.meta)


def segments_etats(signal: TypedFrame, colonne: str = 'value', ignorer: str = '',
                   nom: str = '') -> TypedFrame:
    """Plages de valeur constante d'un signal catégoriel — les « états »."""
    a_ignorer = [x.strip() for x in ignorer.split(',') if x.strip()] if ignorer else []
    return _segments(etats(_colonne(signal, 'time'), _colonne(signal, colonne),
                           ignorer=a_ignorer, nom=nom), meta=signal.meta)


def segments_present_dans(segments: TypedFrame, reference: TypedFrame,
                          strict: bool = True) -> TypedFrame:
    """Ne garde que les segments inclus dans un segment de référence."""
    def _lire(f):
        return [{'start': s, 'end': _fin(e)}
                for s, e in zip(_colonne(f, 'start'), _colonne(f, 'end'))]
    gardes = present_dans(_lire(segments), _lire(reference), strict=strict)
    bornes = {(g['start'], g['end']) for g in gardes}
    lignes = [dict(r, end=_fin(r.get('end'))) for r in segments.df.to_dict('records')
              if (r.get('start'), _fin(r.get('end'))) in bornes]
    return _segments(lignes, meta=segments.meta)


# ──────────────────────────────────────────────────────────────────────────────────────────────
# Déclarations
# ──────────────────────────────────────────────────────────────────────────────────────────────

_SORTIE = PortSpec('segments', DataType.SEGMENTS, produced_fields=CHAMPS_SEGMENT,
                   description="Segments produits — l'origine du mode est tracée sur chaque ligne.")

register(FunctionSpec(
    key='segment_autour_event',
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
        ParamSpec('offset_debut', 'float', 0.0, unit='s',
                  description="Décalage du DÉBUT par rapport à l'ancre (négatif = avant)."),
        ParamSpec('offset_fin', 'float', 15.0, unit='s',
                  description="Décalage de la FIN par rapport à l'ancre."),
        ParamSpec('nom', 'str', '', description="Préfixe de nommage des segments."),
    ],
    cost={'cpu_bound': True},
    fn=segments_autour,
))

register(FunctionSpec(
    key='segment_jonction',
    name="Segments par jonction de deux flux",
    description="Début pris dans un flux d'événements, fin dans un autre. L'appariement se fait "
                "par le TEMPS (première fin postérieure au début) et non par index : deux flux "
                "indépendants n'ont pas le même nombre d'occurrences. Un début sans fin donne un "
                "segment OUVERT plutôt qu'un segment perdu.",
    category=FunctionCategory.JOIN,
    tags=['temporel', 'segmentation'],
    inputs=[
        PortSpec('debuts', DataType.EVENTS, required_fields=['time'],
                 description="Flux fournissant les DÉBUTS."),
        PortSpec('fins', DataType.EVENTS, required_fields=['time'],
                 description="Flux fournissant les FINS."),
    ],
    outputs=[_SORTIE],
    params=[
        ParamSpec('offset_debut', 'float', 0.0, unit='s',
                  description="Décalage du DÉBUT après appariement (« le début du bloc moins "
                              "2 s »). Appliqué APRÈS : décaler avant changerait l'appariement."),
        ParamSpec('offset_fin', 'float', 0.0, unit='s',
                  description="Décalage de la FIN après appariement (« la pause suivante plus 5 s »)."),
        ParamSpec('depuis_debut', 'int', 0, 0,
                  description="Occurrences de DÉBUT sautées avant d'apparier — le curseur "
                              "« Table 1 » de l'écran d'origine."),
        ParamSpec('depuis_fin', 'int', 0, 0,
                  description="Occurrences de FIN sautées avant d'apparier — le curseur "
                              "« Table 2 » de l'écran d'origine."),
        ParamSpec('repeter', 'bool', True,
                  description="Un segment par début (défaut) ; décoché : un seul, celui des "
                              "curseurs — la case « Répéter sur les prochains segments »."),
        ParamSpec('nom', 'str', ''),
        ParamSpec('fermer_dernier', 'bool', False,
                  description="Écarter le dernier segment s'il reste ouvert (défaut : le garder)."),
    ],
    cost={'cpu_bound': True},
    fn=segments_jonction,
))

register(FunctionSpec(
    key='segment_marges',
    name="Marges autour de segments existants",
    description="Décale les deux bornes de chaque segment : start − avant, end + apres. C'est le "
                "mode « Simple » appliqué à une SITUATION (marges inf/sup), qu'`autour` ne couvre "
                "pas — une situation a deux bornes, pas une ancre. Négatif = rétrécir ; un segment "
                "qui s'inverse est ÉCARTÉ ; une fin ouverte le reste. L'origine d'avant la marge "
                "survit dans `source`.",
    category=FunctionCategory.TRANSFORM,
    tags=['temporel', 'segmentation'],
    inputs=[PortSpec('segments', DataType.SEGMENTS, required_fields=['start', 'end'])],
    outputs=[_SORTIE],
    params=[
        ParamSpec('avant', 'float', 0.0, unit='s',
                  description="Marge ajoutée AVANT chaque segment (start − avant)."),
        ParamSpec('apres', 'float', 0.0, unit='s',
                  description="Marge ajoutée APRÈS chaque segment (end + apres)."),
    ],
    cost={'cpu_bound': True},
    fn=segments_marges,
))

register(FunctionSpec(
    key='segment_conditionnel',
    name="Segments par condition",
    description="Plages où un signal satisfait (colonne, opérateur, seuil), avec HYSTÉRÉSIS. "
                "Sans durée minimale ni trou toléré, un seuil sur un signal réel produit des "
                "centaines de micro-segments dus au bruit.",
    category=FunctionCategory.DETECTOR,
    tags=['temporel', 'segmentation'],
    inputs=[PortSpec('signal', DataType.TIMESERIES, required_fields=['time'])],
    outputs=[_SORTIE],
    params=[
        ParamSpec('colonne', 'str', 'value', description="Colonne testée."),
        ParamSpec('operateur', 'enum', '>=', choices=['>=', '>', '<=', '<', '==', '!='],
                  description="Comparaison — déclarée, donc sérialisable dans un manifeste."),
        ParamSpec('seuil', 'float', 0.0),
        ParamSpec('duree_min', 'float', 0.0, 0.0, unit='s',
                  description="Durée minimale d'une plage retenue."),
        ParamSpec('trou_tolere', 'float', 0.0, 0.0, unit='s',
                  description="Interruption recollée au lieu de couper la plage."),
        ParamSpec('nom', 'str', ''),
    ],
    cost={'cpu_bound': True},
    fn=segments_conditionnels,
))

register(FunctionSpec(
    key='segment_etats',
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
        ParamSpec('colonne', 'str', 'value'),
        ParamSpec('ignorer', 'str', '',
                  description="Valeurs à ne pas segmenter, séparées par des virgules "
                              "(ex. « -1 » pour « aucun état »)."),
        ParamSpec('nom', 'str', ''),
    ],
    cost={'cpu_bound': True},
    fn=segments_etats,
))

register(FunctionSpec(
    key='segment_present_dans',
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
    fn=segments_present_dans,
))
