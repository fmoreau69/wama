"""
Annotations opérateur — portage d'une toolbox tierce (paquet `+Annotation` + `ProcCleanTag`),
capability-first.

L'opérateur de la navette tapait des annotations en conduite (situation bien/mal gérée,
incident, refus de priorité, traversée piéton…). Ce module :
- consolide le dictionnaire de tags brouillon → canonique (`clean_tag`, cf. ProcCleanTag) ;
- déduit pour chaque situation : issue gérée (bien/mal, GetGestion), validité (annulée par
  `taguage_supprimé`, GetIsValid) et tags de contexte voisins (GetNearAnnotation).

⚠️ Les VALEURS du dictionnaire (`NV_AnnotationTag`, 36 entrées) sont spécifiques au projet
ENA/Navya : `CANONICAL_TAGS` ci-dessous consolide les doublons connus mais doit être
complété/remplacé par le vrai dictionnaire quand le flux d'annotations est branché côté WAMA.
Le MÉCANISME (fenêtres, gestion, validité, voisins) est générique.
"""
from __future__ import annotations

from wama.common.catalog.data_types import DataType, TypedFrame
from wama.common.catalog.function_catalog import (FunctionSpec, PortSpec, ParamSpec,
                                FunctionCategory, register)

# Consolidation des variantes vers un libellé canonique (extrait — à compléter avec le
# vrai NV_AnnotationTag). Clé = variante brute (lower, sans accents superflus), val = canonique.
CANONICAL_TAGS = {
    'rabattemt_proche': 'Rabattement_proche',
    'rabattement_proche': 'Rabattement_proche',
    'refus_prio': 'Refus_de_priorité',
    'refus_de_priorité': 'Refus_de_priorité',
    'traversée_hors': 'Traversée_hors_PP',
    'traversée_hors_pp': 'Traversée_hors_PP',
    'traversée_pp': 'Traversée_PP',
    'bien_gérée': 'Bien_gérée',
    'mal_gérée': 'Mal_gérée',
    'incident': 'Incident',
    'vitesse_excessive': 'Vitesse_excessive',
    'sortie_de_stationnement': 'Sortie_de_stationnement',
    'taguage_supprimé': 'taguage_supprimé',
}
CANCEL_TAG = 'taguage_supprimé'
GESTION_GOOD = 'Bien_gérée'
GESTION_BAD = 'Mal_gérée'


def clean_tag(tag):
    """Remap d'un tag brut vers sa forme canonique (ProcCleanTag). Inconnu → tel quel."""
    if tag is None:
        return None
    key = str(tag).strip().lower()
    return CANONICAL_TAGS.get(key, str(tag).strip())


def _within(times, tags, t0, window, predicate):
    """Cherche un tag satisfaisant `predicate` dans [t0-window, t0+window]."""
    for tt, tg in zip(times, tags):
        if abs(tt - t0) <= window and predicate(tg):
            return tg
    return None


def process_annotations(events: TypedFrame, *, gestion_window_s=10.0,
                        cancel_window_s=10.0, near_max=3,
                        tag_field='tag', type_field='annotation_type') -> TypedFrame:
    """Enrichit un flux d'annotations opérateur (events : time, annotation_type, tag) :
    ajoute `clean_tag`, `gestion` (1=bien, 2=mal, 0=?), `valid` (bool), `near_tags` (liste).
    Enricher sur `events`."""
    import pandas as pd
    df = events.df.copy()
    if tag_field not in df.columns or 'time' not in df.columns or len(df) == 0:
        for c in ('clean_tag', 'gestion', 'valid', 'near_tags'):
            df[c] = None
        return TypedFrame(df, DataType.EVENTS, meta=events.meta)

    times = df['time'].to_numpy(dtype=float)
    ctags = [clean_tag(t) for t in df[tag_field].tolist()]
    df['clean_tag'] = ctags

    gestion, valid, near = [], [], []
    for i, t0 in enumerate(times):
        # gestion : bien/mal dans la fenêtre autour de l'annotation
        g = 0
        found = _within(times, ctags, t0, gestion_window_s,
                        lambda tg: tg in (GESTION_GOOD, GESTION_BAD))
        if found == GESTION_GOOD:
            g = 1
        elif found == GESTION_BAD:
            g = 2
        gestion.append(g)
        # validité : invalidée si un taguage_supprimé suit dans la fenêtre
        cancelled = any(0 < (tt - t0) <= cancel_window_s and tg == CANCEL_TAG
                        for tt, tg in zip(times, ctags))
        valid.append(not cancelled)
        # tags de contexte voisins (non-gestion, non-annulation)
        nb = []
        for tt, tg in zip(times, ctags):
            if tt == t0:
                continue
            if abs(tt - t0) <= gestion_window_s and tg not in (
                    GESTION_GOOD, GESTION_BAD, CANCEL_TAG, None):
                nb.append(tg)
            if len(nb) >= near_max:
                break
        near.append(nb)
    df['gestion'] = gestion
    df['valid'] = valid
    df['near_tags'] = near
    return TypedFrame(df, DataType.EVENTS, meta=events.meta)


SPEC = register(FunctionSpec(
    key='operator_annotations',
    name='Annotations opérateur',
    description="Consolide et enrichit les taps de l'opérateur : tag canonique, issue "
                "gérée (bien/mal), validité (annulation), tags de contexte voisins.",
    category=FunctionCategory.ENRICHER,
    tags=['events', 'annotations'],
    inputs=[
        PortSpec('events', DataType.EVENTS, required_fields=['time', 'tag'],
                 description='Taps opérateur bruts (time, annotation_type, tag).'),
    ],
    outputs=[
        PortSpec('events', DataType.EVENTS,
                 produced_fields=['clean_tag', 'gestion', 'valid', 'near_tags']),
    ],
    params=[
        ParamSpec('gestion_window_s', 'float', 10.0, 1.0, 60.0, unit='s',
                  description='Fenêtre de recherche de l\'issue gérée / des tags voisins.'),
        ParamSpec('cancel_window_s', 'float', 10.0, 1.0, 60.0, unit='s',
                  description='Fenêtre pour l\'annulation (taguage_supprimé).'),
        ParamSpec('near_max', 'int', 3, 1, 10,
                  description='Nombre max de tags de contexte voisins collectés.'),
    ],
    cost={'cpu_bound': True},
    projects=['ENA'],
    fn=process_annotations,
))
