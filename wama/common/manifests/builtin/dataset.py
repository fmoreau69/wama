"""
Kind `dataset` — généralisation du manifeste toolbox tierce (`ENA_NAVYA/manifest.xml`, référence quasi-idéale).

À la différence de `app`/`model` (EXTRAITS du code existant), un `dataset` est AUTORÉ : le manifeste EST
l'origine (wama-dev-ai explore un dossier projet → infère un brouillon → l'humain valide). Donc PAS de
`extract` : ce kind est validate + store. La projection (instancier le dataset dans les apps via un reader
source-agnostique) est un chantier ultérieur.

Généralisation toolbox tierce → WAMA (cf. mémoire project_manifests_projects) :
  - `das`/`channel`/`signal` typés + unités        → `signals[]` typés sur `data_types` (source-agnostique)
  - `reference_table` (enums : NV_AnnotationTag…)   → `reference_tables{}`
  - `record`/`timeseries` (GNSS→geo_track, …)       → `records[]` (groupements de signaux)
  - couche propriété/projet/visibilité (absente toolbox tierce) → portée par l'ENVELOPPE commune (world/visibility/scope)
"""

from __future__ import annotations

from ..kinds import ManifestKind, register_kind

# Sources brutes reconnues (le reader WAMA sera source-AGNOSTIQUE — pas que rtMapsOutputName).
DATASET_SOURCES = ('rtmaps', 'lsl', 'rosbag', 'csv', 'parquet', 'db', 'docs', 'other')


def _valid_data_types() -> set:
    from wama.common.data.data_types import DataType
    return {v for k, v in vars(DataType).items() if k.isupper() and isinstance(v, str)}


def validate_dataset_body(body: dict) -> list[str]:
    errs: list[str] = []
    if not isinstance(body, dict):
        return ["body 'dataset' doit être un dict"]

    # source ------------------------------------------------------------------
    src = body.get('source')
    if not isinstance(src, dict):
        errs.append("source manquant ou non-dict {type, ref}")
    else:
        if src.get('type') and src['type'] not in DATASET_SOURCES:
            errs.append(f"source.type '{src['type']}' inconnu (attendu: {', '.join(DATASET_SOURCES)})")
        if not src.get('ref'):
            errs.append("source.ref manquant (chemin/dossier/URI du jeu brut)")

    # signals -----------------------------------------------------------------
    dtypes = _valid_data_types()
    signals = body.get('signals')
    signal_ids: set = set()
    if not isinstance(signals, list) or not signals:
        errs.append("signals doit être une liste non vide")
    else:
        for i, s in enumerate(signals):
            if not isinstance(s, dict):
                errs.append(f"signals[{i}] doit être un dict"); continue
            sid = s.get('id')
            if not sid:
                errs.append(f"signals[{i}] : 'id' manquant")
            else:
                if sid in signal_ids:
                    errs.append(f"signals : id '{sid}' dupliqué")
                signal_ids.add(sid)
            dt = s.get('data_type')
            if not dt:
                errs.append(f"signals[{sid or i}] : 'data_type' manquant")
            elif dt not in dtypes:
                errs.append(f"signals[{sid or i}] : data_type '{dt}' hors taxonomie ({', '.join(sorted(dtypes))})")

    # reference_tables --------------------------------------------------------
    rts = body.get('reference_tables', {})
    if rts and not isinstance(rts, dict):
        errs.append("reference_tables doit être un dict {name: {...}}")
    elif isinstance(rts, dict):
        for name, tbl in rts.items():
            if not isinstance(tbl, dict):
                errs.append(f"reference_tables['{name}'] doit être un dict"); continue
            if 'values' not in tbl and 'mapping' not in tbl:
                errs.append(f"reference_tables['{name}'] exige 'values' (liste) ou 'mapping' (code→label)")

    # records (groupements de signaux) ----------------------------------------
    records = body.get('records', [])
    if records and not isinstance(records, list):
        errs.append("records doit être une liste")
    elif isinstance(records, list):
        for i, r in enumerate(records):
            if not isinstance(r, dict):
                errs.append(f"records[{i}] doit être un dict"); continue
            for ref in (r.get('signals') or []):
                if signal_ids and ref not in signal_ids:
                    errs.append(f"records[{r.get('id', i)}] référence un signal inconnu: '{ref}'")
    return errs


register_kind(ManifestKind(
    kind='dataset',
    validate=validate_dataset_body,
    extract=None,      # AUTORÉ (pas de registre code) — le manifeste est l'origine
    description="Jeu de données brut typé (généralisation toolbox tierce) : source-agnostique + signals typés sur "
                "data_types + reference_tables (enums) + records. Validate+store (projection = chantier).",
))
