"""
Projection (kind `app`) — étape 1 : DRY-RUN + rapport d'écarts, PAS de code-gen encore.

Le write-back complet (générer models.py/urls/views depuis le manifeste) est du CODE-GEN = le gros
chantier. Avant de l'engager, on a besoin de la liste des « trous et manquements » qui le CADRE.
Ce module produit ça, sans écrire une ligne dans les registres fonctionnels :

  1. `facet_report(app_id)`   : par facette, peut-on reconstruire l'app depuis le manifeste ? Quel
                               registre est la cible ? Est-ce projetable au RUNTIME (DB) ou en CODE-GEN ?
  2. `studio_redundancy(app_id)` : ROUND-TRIP réel ciblé sur la redondance connue APP_CATALOG⟷GENERIC_APPS.
                               On dérive les E/S depuis la facette `ports` (issue d'app_registry) et on
                               les diffe contre `GENERIC_APPS` (l'AUTRE source, saisie à la main). Concordance
                               ⇒ fusion des deux registres SÛRE. Divergence ⇒ incohérence réelle trouvée.

Aucune écriture : c'est le rapport qui informera le code-gen. La seule facette projetable au runtime
(`access` → AppAccessPolicy, DB) est identifiée mais pas encore écrite (discipline : on projette après
accord sur le rapport).
"""

from __future__ import annotations

from typing import Optional

from .ingest import extract, diff_dicts

# Cible + backend de chaque facette du kind `app`. backend='db' ⇒ projetable au RUNTIME ; 'code' ⇒ code-gen.
FACET_TARGETS = {
    'identity':     ('APP_CATALOG (app_registry.py)', 'code'),
    'ports':        ('app_registry.py / app_modes.py', 'code'),
    'capabilities': ('APP_CATALOG.conventions', 'code'),
    'modes':        ('app_modes.py (APP_MODES)', 'code'),
    'params':       ('<app>/params.py (PARAMS_JSON)', 'code'),
    'inspector':    ('Detail/PreviewRegistry (apps.py)', 'code'),
    'models':       ('<app>/utils/model_config.py', 'code'),
    'processing':   ('models.py / urls.py / tasks.py', 'code'),   # le gros code-gen
    'prompts':      ('app_metadata.PROMPT_TARGETS / prompt_skills', 'code'),
    'tool_api':     ('tool_api.py (TOOL_REGISTRY)', 'code'),
    'access':       ('AppAccessPolicy (DB)', 'db'),               # SEULE projetable au runtime
    'studio':       ('generic_runner.GENERIC_APPS', 'code'),
}


def facet_report(app_id: str) -> Optional[dict]:
    """Classe chaque facette : présente dans le manifeste ? cible ? projetable runtime ou code-gen ?"""
    man = extract('app', app_id)
    if man is None:
        return None
    body = man.get('body', {})
    facets = []
    for facet, (target, backend) in FACET_TARGETS.items():
        val = body.get(facet)
        present = bool(val) and not (isinstance(val, dict) and val.get('_error'))
        facets.append({
            'facet': facet,
            'present': present,
            'target': target,
            'backend': backend,
            'projectable_now': backend == 'db',
            'gap': _classify_gap(facet, val, present, backend),
        })
    return {
        'app': app_id,
        'world': man.get('world'),
        'facets': facets,
        'missing_facets': body.get('_missing_facets', []),
        'runtime_projectable': [f['facet'] for f in facets if f['projectable_now']],
        'codegen_required': [f['facet'] for f in facets if f['backend'] == 'code' and f['present']],
    }


def _classify_gap(facet, val, present, backend):
    if not present:
        return 'MISSING'            # facette absente du manifeste → trou de schéma OU app non conforme
    if backend == 'db':
        return 'PROJECTABLE'        # écriture runtime possible dès maintenant
    return 'CODEGEN'                # reconstruit par génération de code (chantier)


# ── Round-trip réel : redondance APP_CATALOG ⟷ GENERIC_APPS ─────────────────────
def derive_io_from_ports(manifest: dict) -> dict:
    """Reconstruit les E/S studio à partir de la SEULE facette `ports` (issue d'app_registry).
    C'est l'inverse de studio_node_ports : si ça reproduit GENERIC_APPS, les 2 sources concordent."""
    ports = (manifest.get('body', {}) or {}).get('ports', {}) or {}
    inputs = ports.get('inputs', []) or []
    outputs = ports.get('outputs', []) or []

    travail_types, has_prompt = set(), False
    for p in inputs:
        grp = p.get('group')
        if grp == 'prompt':
            has_prompt = True
        elif grp == 'travail':
            for t in (p.get('types') or []):
                if t and t != 'prompt':
                    travail_types.add(t)

    io = {}
    if travail_types:
        io['input_kinds'] = sorted(travail_types)
    elif has_prompt:
        io['primary_input'] = 'prompt'

    out_types = sorted({t for p in outputs for t in (p.get('types') or []) if t})
    if len(out_types) == 1:
        io['output_type'] = out_types[0]
    elif len(out_types) == 0:
        io['output_type'] = None
    else:
        io['output_type'] = 'auto'      # sorties multiples/dynamiques → sentinelle
    return io


def studio_redundancy(app_id: str) -> Optional[dict]:
    """Diffe les E/S dérivées des `ports` (app_registry) contre GENERIC_APPS (source parallèle)."""
    try:
        from wama.studio.services.generic_runner import GENERIC_APPS
    except Exception as e:
        return {'app': app_id, 'error': f'GENERIC_APPS indisponible: {e!r}'}
    actual = GENERIC_APPS.get(app_id)
    if actual is None:
        return {'app': app_id, 'runnable': False}   # app pas dans le studio

    man = extract('app', app_id)
    expected = derive_io_from_ports(man)

    # normaliser les champs comparables
    def norm_io(d):
        out = {}
        if d.get('input_kinds') is not None:
            out['input_kinds'] = sorted(list(d['input_kinds']))
        if d.get('primary_input') is not None:
            out['primary_input'] = d['primary_input']
        out['output_type'] = d.get('output_type')
        return out

    a = norm_io({'input_kinds': actual.get('input_kinds'), 'primary_input': actual.get('primary_input'),
                 'output_type': actual.get('output_type')})
    e = norm_io(expected)
    diffs = diff_dicts(e, a)
    return {
        'app': app_id, 'runnable': True,
        'from_ports': e, 'from_generic_apps': a,
        'agree': not diffs, 'diffs': diffs,
    }
