"""
Gabarit `function_specs.py` — le PIPELINE d'une app à plusieurs process (2026-10-05, session Writer).

Le patron est celui du pilote composer (`wama/composer/function_specs.py`, décision n°11 de
`WAMA_APP_GENERATION_ROUTE.md §10.6`) : chaque process un `FunctionSpec binding: app` du
catalogue, le registre déclaré par `register_app_pipeline`. Ce gabarit le REND depuis les
manifestes `pipeline` et `function` de l'app (`pipeline_decl`), au lieu de le faire écrire à la main.

Ce qui est rendu, et rien d'autre :
  • un `FunctionSpec` par process (nom, description, catégorie, ports — ceux du manifeste) ;
  • `PIPELINE = register_app_pipeline(...)` : un `ProcessSpec` par nœud (dépendances = liens,
    réglages surveillés, degré, part de barre, sorties déclarées) ;
  • `model_of` — « le modèle que la card demande » — DÉRIVÉ du select de modèle du schéma
    (`options_source: catalog`) : `None` sous « auto », la tâche tranchera.
Ce qui n'est PAS rendu : `applies` / `available` (logique de moteur — un process qui n'a pas
toujours lieu s'écrit à la main, comme le `plan` du composer) ; le corps des process (la GLU,
`tasks.py`, marche B).

Le LABEL de l'app n'est jamais écrit en dur : le module le lit de son propre nom de paquet. Une
jumelle (`writer_01`) déclare donc ses fonctions `writer_01.<process>` et son pipeline sous
`writer_01` — piège vécu par la 1ʳᵉ glu du Writer (`'writer'` en dur, cible de prompt perdue).
"""
from __future__ import annotations

from wama.common.manifests.codegen.pipeline_decl import (OUTPUT_PROCESS_KEY, declared_pipeline,
                                                         process_specs)

_CATEGORIES = {'transform', 'enricher', 'detector', 'indicator', 'resampler', 'join', 'aggregate'}


def _port(p: dict) -> str:
    args = [repr(p['key']), repr(p.get('data_type') or 'document')]
    if p.get('optional'):
        args.append('optional=True')
    if p.get('group') and p.get('group') != 'travail':
        args.append(f"group={p['group']!r}")
    if p.get('description'):
        args.append(f"description={p['description']!r}")
    return f"PortSpec({', '.join(args)})"


def _model_field(manifest: dict) -> str:
    """Le select de modèle du schéma (`options_source: catalog`), ou ''."""
    params = (manifest.get('body') or {}).get('params') or {}
    schema = (params.get('schemas') or {}).get(params.get('primary') or '') or []
    return next((f.get('name') for f in schema
                 if isinstance(f, dict) and f.get('options_source') == 'catalog'), '') or ''


def render_function_specs(manifest: dict) -> tuple:
    """(source, raison) — `function_specs.py` complet, ou (None, raison) sans pipeline déclaré."""
    from ..builtin.app import _GEN_MARK
    app_key = manifest.get('key') or ''
    pipeline, functions = declared_pipeline(app_key)
    if not pipeline:
        return None, f"aucun pipeline déclaré pour {app_key} (app à un seul process — le cas normal)"
    specs = process_specs(pipeline)
    if len(specs) < 2:
        return None, "un pipeline d'un seul process ne se déclare pas (§10.6 : c'est le cas normal)"
    proc = (manifest.get('body') or {}).get('processing') or {}
    lifecycle = [t['function'] for t in proc.get('tasks') or [] if t.get('lifecycle')]
    if len(lifecycle) != 1:
        return None, f"une tâche lifecycle attendue pour porter le pipeline (déclarées : {lifecycle})"
    task = lifecycle[0]
    missing = [s['key'] for s in specs if not s['function']]
    if missing:
        return None, f"nœud(s) sans fonction déclarée : {', '.join(missing)}"
    unknown = [s['function'] for s in specs if s['function'] not in functions]
    if unknown:
        return None, f"fonction(s) sans manifeste `function` : {', '.join(unknown)}"
    model_field = _model_field(manifest)
    mark = _GEN_MARK.format(app_id=app_key)

    lines = [
        '"""',
        f"{mark} — function_specs.py GÉNÉRÉ (gabarit function_specs_gen, patron composer).",
        '',
        f"Le PIPELINE de l'app : {len(specs)} process, chacun un `FunctionSpec binding: app` du catalogue",
        'commun, le registre déclaré par `register_app_pipeline` (décision n°11, ROUTE §10.6).',
        'Source : les manifestes `pipeline` et `function` de l\'app. Ne pas éditer : régénérer.',
        '"""',
        'from wama.common.catalog.function_catalog import (Binding, FunctionCategory as FC, FunctionSpec,',
        '                                                  PortSpec, register)',
        'from wama.common.services.process_pipeline import ProcessSpec, register_app_pipeline',
        *(['from wama.common.services.output_process import output_spec']
          if any(s['key'] == OUTPUT_PROCESS_KEY for s in specs) else []),
        '',
        "#: Le LABEL réel de l'app (jumelle comprise), lu de son paquet — jamais écrit en dur.",
        "_APP = __name__.rsplit('.', 2)[-2]",
        f"_IMPL = f'{{_APP}}.tasks:{task}'",
        '',
    ]
    for s in specs:
        body = functions[s['function']].get('body') or {}
        f_manifest = functions[s['function']]
        category = (body.get('category') or 'transform').lower()
        if category not in _CATEGORIES:
            category = 'transform'
        tags = list(body.get('tags') or [])
        inputs = ', '.join(_port(p) for p in body.get('inputs') or [])
        outputs = ', '.join(_port(p) for p in body.get('outputs') or [])
        lines += [
            '',
            'register(FunctionSpec(',
            f"    key=f'{{_APP}}.{s['key']}', name={(f_manifest.get('name') or s['key'])!r},",
            f"    description={(f_manifest.get('description') or '')!r},",
            f"    category=FC.{category.upper()}, binding=Binding.APP, app=_APP, impl=_IMPL,",
            f"    tags={tags!r},",
            f"    inputs=[{inputs}],",
            f"    outputs=[{outputs}]))",
        ]
    if model_field:
        lines += [
            '',
            '',
            'def _requested_model(item):',
            '    """Le modèle que la card DEMANDE : `None` sous « auto » — connu au lancement seulement."""',
            '    from wama.common.utils.auto_model import is_auto',
            f"    value = getattr(item, {model_field!r}, '') or ''",
            '    return None if is_auto(value) else value',
        ]
    lines += ['', '', 'PIPELINE = register_app_pipeline(_APP, (']
    for s in specs:
        if s['key'] == OUTPUT_PROCESS_KEY:
            # Le process « Sortie » COMMUN : sa déclaration est la brique (réglages de sortie
            # surveillés, toujours joué) — jamais recopiée champ par champ.
            share = f", share={s['share']}" if s['share'] != 1 else ''
            lines.append(f"    output_spec(depends_on={tuple(s['depends_on'])!r}{share}),")
            continue
        args = [repr(s['key'])]
        if s['label']:
            args.append(f"label={s['label']!r}")
        if s['depends_on']:
            args.append(f"depends_on={tuple(s['depends_on'])!r}")
        if s['watched']:
            args.append(f"watched={tuple(s['watched'])!r}")
        if s['degree'] != 'required':
            args.append(f"degree={s['degree']!r}")
        if s['gpu']:
            args.append('gpu=True')
        if s['share'] != 1:
            args.append(f"share={s['share']}")
        if s['outputs']:
            args.append(f"outputs={tuple(s['outputs'])!r}")
        if s['toggle']:
            args.append(f"toggle={s['toggle']!r}")
        if s.get('eta'):
            args.append(f"eta={s['eta']!r}")
        lines.append(f"    ProcessSpec({', '.join(args)}),")
    model_kw = ', model_of=_requested_model' if model_field else ''
    lines += [f"), label={(pipeline.get('name') or app_key)!r},",
              f"   source_ref=f'{{_APP}}.function_specs:PIPELINE'{model_kw})", '']
    return '\n'.join(lines), None
