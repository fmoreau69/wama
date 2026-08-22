"""
Découpage en sections routières — portage d'une toolbox tierce (`generateSection`/`extractSection`)
(parties GÉNÉRIQUES uniquement), capability-first.

`numeroteSection`/`initAttSection` d'origine encodaient le parcours CASA en dur (tables de
numéros, typologie giratoire/stop…) : NON portés — la typologie d'infrastructure doit venir
d'une MÉTADONNÉE (colonne `type` du road_map), pas d'un switch (philosophie métadonnée-driven).

`generate_sections` consomme la sortie du map-matching (colonne `section_id`) et émet des
segments propres : ignore le hors-parcours (None/0), supprime les changements d'1 seul point
(anti-rebond), pose des gardes de 0.3 s aux frontières.
"""
from __future__ import annotations

from wama.common.catalog.data_types import DataType, TypedFrame
from wama.common.catalog.function_catalog import (FunctionSpec, PortSpec, ParamSpec,
                                FunctionCategory, register)


def generate_sections(track: TypedFrame, *, section_field='section_id', time_field='time',
                      guard_s=0.3, min_run=2) -> TypedFrame:
    """De la timeseries de `section_id` → segments (start, end, section_id, direction?).
    Anti-rebond : un `section_id` présent sur < `min_run` points consécutifs est ignoré."""
    import pandas as pd
    df = track.df
    if section_field not in df.columns or time_field not in df.columns or len(df) == 0:
        return TypedFrame(pd.DataFrame(columns=['start', 'end', 'section_id']),
                          DataType.SEGMENTS)
    has_dir = 'direction' in df.columns
    t = df[time_field].to_numpy()
    sid = df[section_field].tolist()
    dirc = df['direction'].tolist() if has_dir else [None] * len(sid)

    # runs consécutifs de même section (hors None/0)
    runs = []      # (value, i0, i1)
    i = 0
    n = len(sid)
    while i < n:
        v = sid[i]
        j = i
        while j < n and sid[j] == v:
            j += 1
        runs.append((v, i, j - 1))
        i = j

    # anti-rebond : jette les runs trop courts et le hors-parcours
    kept = [r for r in runs if r[0] not in (None, 0) and (r[2] - r[1] + 1) >= min_run
            and not (isinstance(r[0], float) and r[0] != r[0])]

    rows = []
    for (v, i0, i1) in kept:
        start = float(t[i0]) + guard_s
        end = float(t[i1]) - guard_s
        if end <= start:
            start, end = float(t[i0]), float(t[i1])
        row = {'start': round(start, 3), 'end': round(end, 3), 'section_id': v}
        if has_dir:
            # direction dominante sur le run
            seg = [d for d in dirc[i0:i1 + 1] if d not in (None,)]
            row['direction'] = max(set(seg), key=seg.count) if seg else None
        rows.append(row)
    cols = ['start', 'end', 'section_id'] + (['direction'] if has_dir else [])
    return TypedFrame(pd.DataFrame(rows, columns=cols), DataType.SEGMENTS, meta=track.meta)


def extract_context(sections: TypedFrame, *, time_event=None, n_prev=3, n_next=2) -> dict:
    """Contexte routier autour d'un instant : section courante + `n_prev` précédentes +
    `n_next` suivantes, avec les temps de frontière. Retourne un dict (pas un TypedFrame :
    c'est une requête ponctuelle, pas un flux). `time_event` requis."""
    df = sections.df
    if time_event is None or len(df) == 0:
        return {'current': None, 'previous': [], 'next': []}
    cur_idx = None
    for idx, r in df.iterrows():
        if r['start'] <= time_event <= r['end']:
            cur_idx = idx
            break
    if cur_idx is None:
        # entre deux sections : prendre la plus proche précédente
        before = df[df['end'] <= time_event]
        cur_idx = before.index[-1] if len(before) else df.index[0]
    rows = df.reset_index(drop=True)
    pos = list(df.index).index(cur_idx)
    to_rec = lambda i: rows.iloc[i].to_dict()
    return {
        'current': to_rec(pos),
        'previous': [to_rec(i) for i in range(max(0, pos - n_prev), pos)],
        'next': [to_rec(i) for i in range(pos + 1, min(len(rows), pos + 1 + n_next))],
    }


SPEC = register(FunctionSpec(
    key='generate_sections',
    name='Découpage en sections',
    description="Segmente la trace en sections routières propres depuis le map-matching "
                "(anti-rebond, hors-parcours ignoré, gardes aux frontières).",
    category=FunctionCategory.TRANSFORM,
    tags=['geo', 'per-section'],
    inputs=[
        PortSpec('track', DataType.GEO_TRACK, required_fields=['time', 'section_id'],
                 description='Trace map-matchée (sortie de gps_map_match).'),
    ],
    outputs=[
        PortSpec('sections', DataType.SEGMENTS,
                 produced_fields=['start', 'end', 'section_id', 'direction']),
    ],
    params=[
        ParamSpec('guard_s', 'float', 0.3, 0.0, 2.0, unit='s',
                  description='Garde temporelle rognée à chaque frontière de section.'),
        ParamSpec('min_run', 'int', 2, 1, 20,
                  description='Longueur minimale (points) d\'une section (anti-rebond).'),
    ],
    cost={'cpu_bound': True},
    projects=['ENA'],
    fn=generate_sections,
))
