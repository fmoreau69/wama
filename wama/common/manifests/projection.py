"""
Projection (kind `app`) — INSTRUMENTS DE MESURE du round-trip (aucune écriture ici).

Ne pas lire « pas de code-gen » comme « pas de write-back » : le write-back existe, par kind,
dans `builtin/` (`app` → facettes `access` (DB) + `identity` (code, §10.3) ; `library` → crée la
ligne `common.models.Library` ; `model` → projette license/platform_ref). Ce qui reste du
CODE-GEN, c'est la COUCHE MINCE déclarative des facettes `backend=code` non encore couvertes par
un projecteur (registres en code, params.py, gabarit) — l'UI, elle, est générée au runtime par
les briques communes. Ce module MESURE, sans écrire une ligne dans les registres fonctionnels :

  1. `facet_report(app_id)`   : par facette, peut-on reconstruire l'app depuis le manifeste ? Quel
                               registre est la cible ? write_back sait-il l'écrire (`writeback_ready`,
                               lu depuis `builtin.app.PROJECTED_FACETS`) ou reste-t-elle en CODE-GEN ?
  2. `studio_redundancy(app_id)` : ROUND-TRIP réel ciblé sur la redondance connue APP_CATALOG⟷GENERIC_APPS.
                               On dérive les E/S depuis la facette `ports` (issue d'app_registry) et on
                               les diffe contre `GENERIC_APPS` (l'AUTRE source, saisie à la main). Concordance
                               ⇒ fusion des deux registres SÛRE. Divergence ⇒ incohérence réelle trouvée.

(Historique : jusqu'au 2026-08-11 ce docstring disait « access identifiée mais pas encore
écrite » — c'était périmé depuis le 2026-07-23. Le contrat docstring=code vaut aussi ici.)
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
    """Classe chaque facette : présente dans le manifeste ? cible ? projetable (write_back sait
    l'écrire — DB ou code) ou code-gen restant ? La liste des facettes que write_back sait écrire
    vit dans `builtin.app.PROJECTED_FACETS` (une entrée = un projecteur) : ce rapport la LIT,
    il ne la redéclare pas — c'était la dérive corrigée le 2026-08-11 (deux listes divergentes)."""
    from .builtin.app import PROJECTED_FACETS
    projected = set(PROJECTED_FACETS)
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
            'projectable_now': facet in projected,
            'gap': _classify_gap(facet, val, present, backend, projected),
        })
    return {
        'app': app_id,
        'world': man.get('world'),
        'facets': facets,
        'missing_facets': body.get('_missing_facets', []),
        # `runtime_projectable` garde sa sémantique historique (backend DB) ; `writeback_ready`
        # est la mesure du chantier §10.3 : facettes présentes que write_back sait écrire.
        'runtime_projectable': [f['facet'] for f in facets if f['backend'] == 'db'],
        'writeback_ready': [f['facet'] for f in facets if f['present'] and f['projectable_now']],
        'codegen_required': [f['facet'] for f in facets
                             if f['backend'] == 'code' and f['present'] and f['facet'] not in projected],
    }


def _classify_gap(facet, val, present, backend, projected):
    if not present:
        return 'MISSING'            # facette absente du manifeste → trou de schéma OU app non conforme
    if facet in projected:
        return 'PROJECTABLE'        # write_back sait l'écrire (DB au runtime, ou code marqué)
    return 'CODEGEN'                # reconstruit par génération de code (chantier §10.3)


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

    # Depuis §10.1 (2026-08-11), GENERIC_APPS DÉRIVE ses E/S des ports (`_io_derived`) : la
    # concordance y est par construction. Un écart n'est légitime que RÉTRÉCI DÉCLARÉ
    # (`io_scope`, ex. nœud imager V1 = txt2img). Écart sans io_scope = vraie dérive.
    io_scope = actual.get('io_scope') or ''
    verdict = ('derived' if not diffs and actual.get('_io_derived')
               else 'ok' if not diffs
               else 'narrowed_by_declaration' if io_scope
               else 'drift')
    return {
        'app': app_id, 'runnable': True,
        'from_ports': e, 'from_generic_apps': a,
        'agree': not diffs or bool(io_scope), 'diffs': diffs,
        'verdict': verdict, 'io_scope': io_scope or None,
    }
