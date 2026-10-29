"""CAP DES GARÉS PAR LEUR RANGÉE : en bataille ou en créneau, d'après l'espacement des voisins.

Pourquoi (Fabien, 2026-10-29, session `4da52df3`) : « ils sont tous stationnés en créneau alors qu'ils
sont en réalité tous en bataille ». Le cap d'un garé venait du rapport largeur/hauteur de ses boîtes
(`multicam_tracker._ratio_heading_candidates`) ; rejoué sur les 21 garés vus à l'image 6130, ce rapport
vaut la largeur d'une voiture (E/W médian 0,81–1,33) — la voisine masque le flanc —, les deux candidats
retombent sur la ligne de visée, et le lissage par voisinage ramène tout dans l'axe de la route.
L'ESPACEMENT tranche, lui : deux voitures en créneau ont leurs centres à ≥ 4,5 m, en bataille à
≈ 2,3–2,5 m ; sur les 667 ancres de la session, 80 % ont un voisin à moins de 3 m.

Règles (fonction pure ; l'appelant donne la position fixe de chaque garé, en mètres) :
  · la rangée d'un garé = ses voisins à moins de `radius_m`, s'ils s'alignent (axe principal, écart
    perpendiculaire ≤ `max_offset_m`) ; moins de `min_row` garés alignés : on ne sait pas ;
  · l'espacement = la médiane des écarts successifs le long de la rangée, les écarts sous `min_gap_m`
    écartés (un même objet vu à deux passages, deux ancres d'un même garé) ;
  · sous `angled_gap_m` : en bataille, le cap est PERPENDICULAIRE à la rangée ; au-dessus de
    `parallel_gap_m` : en créneau, le cap est celui de la rangée ; entre les deux : on ne sait pas.
Le cap est un cap compas (degrés depuis le nord, sens horaire), modulo 180°.
"""
from __future__ import annotations

import math
import statistics

from wama.common.catalog.data_types import DataType, TypedFrame
from wama.common.catalog.function_catalog import (FunctionSpec, PortSpec, ParamSpec,
                                                  FunctionCategory, register)

#: Rayon (m) où chercher la rangée d'un garé.
ROW_RADIUS_M = 10.0
#: Écart perpendiculaire maximal (m) à l'axe de la rangée.
ROW_OFFSET_M = 1.5
#: Nombre minimal de garés alignés, celui-ci compris.
MIN_ROW = 3
#: Un écart plus court (m) n'est pas entre deux voitures.
MIN_GAP_M = 1.6
#: Espacement médian (m) sous lequel la rangée est en bataille.
ANGLED_GAP_M = 3.5
#: Espacement médian (m) au-dessus duquel la rangée est en créneau.
PARALLEL_GAP_M = 4.5


def _principal_axis(points):
    """(ue, un) unitaire de l'axe principal d'un nuage de points (e, n)."""
    me = sum(p[0] for p in points) / len(points)
    mn = sum(p[1] for p in points) / len(points)
    see = sum((p[0] - me) ** 2 for p in points)
    snn = sum((p[1] - mn) ** 2 for p in points)
    sen = sum((p[0] - me) * (p[1] - mn) for p in points)
    angle = 0.5 * math.atan2(2 * sen, see - snn)          # depuis l'axe est
    return math.cos(angle), math.sin(angle)


def row_heading(anchor, others, *, radius_m=ROW_RADIUS_M, max_offset_m=ROW_OFFSET_M, min_row=MIN_ROW,
                min_gap_m=MIN_GAP_M, angled_gap_m=ANGLED_GAP_M, parallel_gap_m=PARALLEL_GAP_M):
    """(nature, cap, espacement) d'un garé `anchor` = (e, n) parmi `others` [(e, n)…] : nature 'angled',
    'parallel' ou 'unknown' ; cap compas mod 180° (None si 'unknown') ; espacement médian (m) ou None."""
    e0, n0 = anchor
    near = [(e, n) for e, n in others if 0 < math.hypot(e - e0, n - n0) <= radius_m]
    if len(near) + 1 < min_row:
        return 'unknown', None, None
    ue, un = _principal_axis([anchor] + near)
    row = sorted((e - e0) * ue + (n - n0) * un for e, n in [anchor] + near
                 if abs(-(e - e0) * un + (n - n0) * ue) <= max_offset_m)
    gaps = [b - a for a, b in zip(row, row[1:]) if b - a >= min_gap_m]
    if len(row) < min_row or len(gaps) < min_row - 1:
        return 'unknown', None, None
    spacing = statistics.median(gaps)
    axis = math.degrees(math.atan2(ue, un)) % 180.0       # cap compas de l'axe de la rangée
    if spacing < angled_gap_m:
        return 'angled', round((axis + 90.0) % 180.0, 1), round(spacing, 2)
    if spacing > parallel_gap_m:
        return 'parallel', round(axis, 1), round(spacing, 2)
    return 'unknown', None, round(spacing, 2)


def row_headings(anchors, **kw):
    """`anchors` : itérable de (id, e, n). Rend {id: (nature, cap, espacement)} (cf. `row_heading`)."""
    objs = list(anchors)
    points = [(o[1], o[2]) for o in objs]
    return {o[0]: row_heading((o[1], o[2]), points, **kw) for o in objs}


def row_heading_counts(result):
    """Bilan d'un `row_headings` : {'angled', 'parallel', 'unknown'} → nombre."""
    out = {'angled': 0, 'parallel': 0, 'unknown': 0}
    for kind, _heading, _spacing in result.values():
        out[kind] += 1
    return out


def parked_row_frame(anchors: TypedFrame, *, radius_m=ROW_RADIUS_M, angled_gap_m=ANGLED_GAP_M,
                     parallel_gap_m=PARALLEL_GAP_M) -> TypedFrame:
    """Wrapper FunctionSpec : une ligne par garé (id, e, n) → (id, nature, cap, espacement)."""
    import pandas as pd
    res = row_headings(anchors.df[['id', 'e', 'n']].itertuples(index=False, name=None), radius_m=radius_m,
                       angled_gap_m=angled_gap_m, parallel_gap_m=parallel_gap_m)
    rows = [{'id': k, 'kind': v[0], 'heading': v[1], 'spacing': v[2]} for k, v in res.items()]
    return TypedFrame(pd.DataFrame(rows, columns=['id', 'kind', 'heading', 'spacing']), DataType.TABLE,
                      meta=row_heading_counts(res))


SPEC = register(FunctionSpec(
    key='parked_row_headings',
    name='Cap des garés par leur rangée',
    description="Décide si un garé est en bataille ou en créneau d'après l'espacement de sa rangée : les "
                "garés voisins alignés (moins de 10 m), l'écart médian le long de leur axe — sous 3,5 m en "
                "bataille (cap perpendiculaire à la rangée), au-dessus de 4,5 m en créneau (cap de la rangée), "
                "entre les deux on ne sait pas. Le rapport largeur/hauteur des boîtes ne le dit pas quand la "
                "voiture voisine masque le flanc.",
    category=FunctionCategory.TRANSFORM,
    tags=['tracking', 'parked', 'heading', 'geometry'],
    inputs=[
        PortSpec('anchors', DataType.TABLE, required_fields=['id', 'e', 'n'],
                 description="Une ligne par garé : identifiant, position fixe (m, repère local est/nord)."),
    ],
    outputs=[
        PortSpec('headings', DataType.TABLE, produced_fields=['id', 'kind', 'heading', 'spacing'],
                 description="Nature (angled, parallel, unknown), cap compas modulo 180° et espacement médian "
                             "de la rangée ; le bilan par nature est dans meta."),
    ],
    params=[
        ParamSpec('radius_m', 'float', ROW_RADIUS_M, 4.0, 30.0, unit='m',
                  description="Rayon où chercher la rangée d'un garé."),
        ParamSpec('angled_gap_m', 'float', ANGLED_GAP_M, 2.0, 5.0, unit='m',
                  description="Espacement médian sous lequel la rangée est en bataille."),
        ParamSpec('parallel_gap_m', 'float', PARALLEL_GAP_M, 3.0, 8.0, unit='m',
                  description="Espacement médian au-dessus duquel la rangée est en créneau."),
    ],
    cost={'cpu_bound': True},
    fn=parked_row_frame,
))
