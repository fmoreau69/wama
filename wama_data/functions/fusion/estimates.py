"""Fusion pondérée d'estimations INDÉPENDANTES d'une même grandeur — 1ᵉʳ consommateur de la
facette estimateur (`PortSpec.estimates/uncertainty/derived_from`, ⑤b, 2026-09-09).

Pourquoi ce module existe (`CAM_ANALYZER_CHAINE_TRAITEMENT §INVENTAIRE E`) : la chaîne
cam_analyzer compte 43 leviers de correction et UN seul chiffre A/B ; aucun levier ne dit à
quel point il est sûr, et « fusionner » revenait à poser des poids arbitraires — un réglage
caché de plus. Ici la pondération n'est pas un réglage : c'est 1/σ², et σ vient de ce que
chaque producteur DÉCLARE sur son port.

Les deux règles qui ne se discutent pas
---------------------------------------
1. **Le critère fusion / confrontation est l'INDÉPENDANCE, jamais la qualité.** Deux sources
   dont `derived_from` se recouvrent (leviers 1 et 40 : la même bbox) sont CORRÉLÉES — les
   fusionner donnerait l'illusion de deux confirmations. `fuse_estimates` REFUSE (ValueError
   nommant la donnée native partagée) plutôt que de rendre un chiffre faux.
2. **Une incertitude non chiffrée exclut de la fusion.** `{'model': 'declared'}` dit « je ne
   sais pas ce que je vaux » : la source est écartée et le rapport le dit — elle se confronte
   ailleurs, elle ne pèse pas ici.

Ce que ça fait : aligne les sources sur le temps (tolérance), évalue σ ligne à ligne selon la
forme déclarée (constante, colonne, relative, tenue), écarte les lignes invalides (cap tenu à
l'arrêt = pas une mesure), puis moyenne pondérée — VECTORIELLE pour une grandeur circulaire
(cap : 350° et 10° font 0°, pas 180°). σ fusionnée = 1/√Σ(1/σᵢ²).

Deux étages (patron `geometry/placement_metrics`) : `fuse_series` (noyau, listes, sans pandas)
et `fuse_estimates` (wrapper `TypedFrame`, ce que le catalogue appelle).
"""
from __future__ import annotations

import math


def sigma_of(row: dict, uncertainty, value) -> float | None:
    """σ d'UNE ligne selon la forme déclarée sur le port. `None` = ligne invalide (à écarter).

    Formes (cf. `function_catalog.UNCERTAINTY_MODELS`) : nombre → constante ; `{'field'}` →
    colonne ; `{'model': 'relative', 'ratio'}` → r·|valeur| ; `{'model': 'held', 'field',
    'sigma'}` → σ, ou invalide si le drapeau est vrai ; `{'model': 'declared'}` → invalide
    (non chiffrée : la source ne pèse pas).
    """
    if uncertainty is None:
        return None
    if isinstance(uncertainty, (int, float)) and not isinstance(uncertainty, bool):
        return float(uncertainty) if uncertainty > 0 else None
    if not isinstance(uncertainty, dict):
        return None
    model = uncertainty.get('model')
    if model is None and 'field' in uncertainty:
        s = row.get(uncertainty['field'])
        try:
            s = float(s)
        except (TypeError, ValueError):
            return None
        return s if s > 0 and math.isfinite(s) else None
    if model == 'relative':
        try:
            s = float(uncertainty['ratio']) * abs(float(value))
        except (TypeError, ValueError, KeyError):
            return None
        return s if s > 0 else None
    if model == 'held':
        if row.get(uncertainty.get('field')):
            return None
        s = uncertainty.get('sigma')
        return float(s) if isinstance(s, (int, float)) and s > 0 else None
    return None      # 'declared' et tout modèle inconnu : non chiffré


def shared_native_source(sources) -> tuple | None:
    """Première paire de sources dont `derived_from` se recouvrent — `None` si toutes sont
    indépendantes deux à deux. `sources` : itérable de dicts portant `derived_from` et `name`."""
    src = list(sources)
    for i, a in enumerate(src):
        da = set(a.get('derived_from') or [])
        for b in src[i + 1:]:
            common = da & set(b.get('derived_from') or [])
            if common:
                return a.get('name', i), b.get('name', '?'), sorted(common)
    return None


def _fuse_values(pairs, circular: bool):
    """(valeur, σ) fusionnés d'une liste [(v, σ)] — pondération 1/σ²."""
    w = [1.0 / (s * s) for _, s in pairs]
    wsum = sum(w)
    if circular:
        x = sum(wi * math.cos(math.radians(v)) for (v, _), wi in zip(pairs, w))
        y = sum(wi * math.sin(math.radians(v)) for (v, _), wi in zip(pairs, w))
        fused = math.degrees(math.atan2(y, x)) % 360.0
        if fused > 360.0 - 1e-9:      # −1e-16° % 360 rend 360.0 : c'est 0°
            fused = 0.0
    else:
        fused = sum(wi * v for (v, _), wi in zip(pairs, w)) / wsum
    return fused, 1.0 / math.sqrt(wsum)


def fuse_series(sources, *, circular: bool = False, tolerance_s: float = 0.05,
                time_field: str = 'time'):
    """NOYAU — fusionne N séries temporelles d'une même grandeur.

    `sources` : liste de dicts `{name, rows: [dict…], field, uncertainty, derived_from}` ; chaque
    ligne porte `time_field` et `field`. Rend `(lignes, rapport)` : une ligne par instant où AU
    MOINS une source est valide — `{time, value, sigma, n_sources}` ; le rapport chiffre ce que
    chaque source a apporté (lignes valides / écartées) et la σ moyenne fusionnée.

    Lève `ValueError` si deux sources partagent une donnée native (règle 1 de l'en-tête).
    """
    src = list(sources)
    clash = shared_native_source(src)
    if clash:
        raise ValueError(f"fusion refusée : « {clash[0]} » et « {clash[1]} » dérivent de la même "
                         f"donnée native {clash[2]} — corrélées, elles se confrontent")
    # Regroupement par temps arrondi à la tolérance (pas de pandas : noyau pur).
    quantum = max(float(tolerance_s), 1e-9)
    buckets: dict = {}
    report_src = []
    for s in src:
        valid = dropped = 0
        for row in s.get('rows') or []:
            t = row.get(time_field)
            v = row.get(s['field'])
            if t is None or v is None:
                dropped += 1
                continue
            try:
                t, v = float(t), float(v)
            except (TypeError, ValueError):
                dropped += 1
                continue
            sig = sigma_of(row, s.get('uncertainty'), v)
            if sig is None or not math.isfinite(v):
                dropped += 1
                continue
            buckets.setdefault(round(t / quantum), []).append((t, v, sig))
            valid += 1
        report_src.append({'name': s.get('name', '?'), 'valid': valid, 'dropped': dropped,
                           'derived_from': list(s.get('derived_from') or [])})
    rows = []
    for key in sorted(buckets):
        items = buckets[key]
        fused, sig = _fuse_values([(v, sg) for _, v, sg in items], circular)
        rows.append({'time': round(items[0][0], 6), 'value': round(fused, 6),
                     'sigma': round(sig, 6), 'n_sources': len(items)})
    sigmas = [r['sigma'] for r in rows]
    report = {'sources': report_src, 'n': len(rows), 'circular': circular,
              'sigma_mean': round(sum(sigmas) / len(sigmas), 6) if sigmas else None,
              'rows_multi_source': sum(1 for r in rows if r['n_sources'] > 1)}
    return rows, report


def fuse_estimates(estimates: 'list[TypedFrame]', *, tolerance_s: float = 0.05,
                   time_field: str = 'time') -> 'TypedFrame':
    """Wrapper FunctionSpec : N `TypedFrame` porteurs d'une facette `meta['estimate']` (posée
    par le producteur ou par l'exécuteur depuis `port_estimate_meta`) → `TypedFrame` TIMESERIES
    `{time, <grandeur>, <grandeur>_sigma, n_sources}` ; rapport dans `meta['fusion']`.

    Refuse (ValueError) : une entrée sans facette, des grandeurs différentes, des sources
    corrélées. Un seul `TypedFrame` est accepté (cardinalité `many` = 1 ou plus) — la fusion
    d'une source seule rend la source, avec sa σ : c'est le cas dégénéré, pas une erreur.
    """
    import pandas as pd
    from wama.common.catalog.data_types import TypedFrame, DataType

    frames = list(estimates) if isinstance(estimates, (list, tuple)) else [estimates]
    if not frames:
        raise ValueError("fuse_estimates : aucune entrée")
    sources, quantity, circular = [], None, False
    for i, f in enumerate(frames):
        facet = (f.meta or {}).get('estimate') if hasattr(f, 'meta') else None
        if not facet or not facet.get('quantity'):
            raise ValueError(f"fuse_estimates : l'entrée {i} ne déclare pas ce qu'elle estime "
                             f"(meta['estimate'] absent — port sans facette `estimates`)")
        if quantity is None:
            quantity, circular = facet['quantity'], bool(facet.get('circular'))
        elif facet['quantity'] != quantity:
            raise ValueError(f"fuse_estimates : grandeurs différentes ({quantity} ≠ "
                             f"{facet['quantity']}) — rien à fusionner")
        tf = time_field if time_field in f.df.columns else ('ts' if 'ts' in f.df.columns else time_field)
        rows = f.df.to_dict('records')
        if tf != 'time':
            for r in rows:
                r.setdefault('time', r.get(tf))
        sources.append({'name': facet.get('name') or f"source {i}", 'rows': rows,
                        'field': facet.get('field') or 'value',
                        'uncertainty': facet.get('uncertainty'),
                        'derived_from': facet.get('derived_from') or []})
    fused, report = fuse_series(sources, circular=circular, tolerance_s=tolerance_s)
    out = pd.DataFrame([{'time': r['time'], quantity: r['value'],
                         f'{quantity}_sigma': r['sigma'], 'n_sources': r['n_sources']}
                        for r in fused],
                       columns=['time', quantity, f'{quantity}_sigma', 'n_sources'])
    return TypedFrame(out, DataType.TIMESERIES,
                      meta={'fusion': report,
                            'estimate': {'quantity': quantity, 'field': quantity,
                                         'uncertainty': {'field': f'{quantity}_sigma'},
                                         'derived_from': sorted({d for s in sources
                                                                 for d in s['derived_from']}),
                                         'circular': circular}})


# ── Manifeste ─────────────────────────────────────────────────────────────────────────
from wama.common.catalog.function_catalog import (  # noqa: E402
    FunctionCategory, FunctionSpec, ParamSpec, PortSpec, register)
from wama.common.catalog.data_types import DataType  # noqa: E402

SPEC = register(FunctionSpec(
    key='fuse_estimates',
    name="Fusion d'estimations (1/σ²)",
    description="Combine N sorties qui estiment la MÊME grandeur (facette `estimates` de leur "
                "port) en une série pondérée par 1/σ², alignée sur le temps ; moyenne vectorielle "
                "pour un cap. REFUSE deux sources dérivées de la même donnée native (corrélées : "
                "elles se confrontent, ne se fusionnent pas) et ÉCARTE ce qui n'est pas chiffré.",
    category=FunctionCategory.JOIN,
    tags=['fusion', 'uncertainty', 'ab-metric', 'timeseries'],
    inputs=[PortSpec('estimates', DataType.TABLE, cardinality='many',
                     description="Sorties porteuses d'une facette estimateur (meta.estimate).")],
    outputs=[PortSpec('fused', DataType.TIMESERIES,
                      produced_fields=['time', 'value', 'sigma', 'n_sources'],
                      description="Grandeur fusionnée + σ ; rapport par source dans meta.fusion.")],
    params=[
        ParamSpec('tolerance_s', 'float', 0.05, 0.0, 5.0, unit='s',
                  description="Deux instants plus proches que cela sont le même instant."),
        ParamSpec('time_field', 'str', 'time', description="Colonne de temps des entrées."),
    ],
    cost={'cpu_bound': True},
    fn=fuse_estimates,
))
