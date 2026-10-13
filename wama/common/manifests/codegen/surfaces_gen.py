"""
Gabarit `surfaces.py` — les SURFACES d'une app, déclarées dans son manifeste (2026-10-13, 2ᵉ
surface du chantier SURFACES : le fond du Writer).

Une surface (`common/surfaces.py`) est une page d'édition COMPOSÉE de briques universelles,
servie par les vues communes (`common/surface_views.py`) : une app la DÉCLARE, elle n'écrit pas
de page. Ce gabarit rend cette déclaration depuis la facette `surfaces` du manifeste `app`, au
lieu de la faire écrire à la main dans l'app (règle D5, ROUTE §10.5 : seul le manifeste se
rédige à la main ; le reste se génère).

Ce qui est rendu : un `register_surface(Surface(...))` par surface — emplacements (brique,
position et taille par défaut), rôles lus, champ écrit, process rejoué.

Ce qui est REFUSÉ, en le disant (rien n'est deviné) :
  • une brique absente du registre (`surfaces.BRICKS`) ;
  • un emplacement hors de la grille ;
  • un champ écrit qui n'est pas un FICHIER produit par un process déclaré : seul un texte se
    valide sans code (`surfaces.validate_text`). Une couche de données (les corrections de
    l'anonymizer) porte sa validation en Python — elle s'écrit dans l'app, pas ici ;
  • un process rejoué (`reruns`) qui n'est pas un process déclaré.

Le LABEL de l'app n'est jamais écrit en dur : le module le lit de son propre nom de paquet (même
règle que `function_specs_gen` — une jumelle `writer_01` déclare `writer_01.edit`).
"""
from __future__ import annotations

import re

from wama.common.manifests.codegen.pipeline_decl import declared_pipeline, process_specs

_KEY_RE = re.compile(r'^[a-z][a-z0-9_]*$')


def declared_surfaces(manifest: dict) -> list:
    """La facette `surfaces` du manifeste (liste), vide si absente."""
    return list(((manifest.get('body') or {}).get('surfaces')) or [])


def _check(surface: dict, outputs: dict, processes: set) -> str:
    """'' si la surface se génère, sinon la raison du refus."""
    from wama.common.surfaces import BRICKS, GRID_COLUMNS
    key = surface.get('key') or ''
    if not _KEY_RE.match(key):
        return f"clé de surface invalide : {key!r} (underscore_case)"
    if not surface.get('label'):
        return f"surface {key} : libellé absent"
    slots = surface.get('slots') or []
    if not slots:
        return f"surface {key} : aucun emplacement"
    for slot in slots:
        if slot.get('brick') not in BRICKS:
            return (f"surface {key} : brique inconnue {slot.get('brick')!r} "
                    f"(connues : {', '.join(sorted(BRICKS))})")
        x, w = int(slot.get('x', 0)), int(slot.get('w', 0))
        if not slot.get('id') or w <= 0 or int(slot.get('h', 0)) <= 0 or x < 0 or x + w > GRID_COLUMNS:
            return f"surface {key} : emplacement {slot.get('id')!r} hors de la grille ({GRID_COLUMNS} colonnes)"
    edits = surface.get('edits') or ''
    if edits not in outputs:
        return (f"surface {key} : « {edits} » n'est la sortie d'aucun process déclaré — un gabarit "
                "ne génère que l'édition d'un FICHIER texte produit par un process ; une couche de "
                "données porte sa validation en Python, dans l'app")
    reruns = surface.get('reruns') or ''
    if reruns and reruns not in processes:
        return f"surface {key} : process rejoué inconnu {reruns!r} (déclarés : {', '.join(sorted(processes))})"
    if not all(isinstance(r, str) and isinstance(f, str) for r, f in (surface.get('reads') or {}).items()):
        return f"surface {key} : `reads` attend {{rôle: champ}}"
    return ''


def _slot(slot: dict) -> str:
    args = [repr(slot['id']), repr(slot['brick'])] + [str(int(slot.get(k, 0))) for k in 'xywh']
    if slot.get('options'):
        args.append(repr(dict(slot['options'])))
    return f"BrickSlot({', '.join(args)})"


def render_surfaces(manifest: dict) -> tuple:
    """(source, raison) — `surfaces.py` complet, ou (None, raison) sans surface déclarée ou si une
    surface est refusée."""
    from ..builtin.app import _GEN_MARK
    surfaces = declared_surfaces(manifest)
    app_key = manifest.get('key') or ''
    if not surfaces:
        return None, f"aucune surface déclarée pour {app_key} (une app sans page d'édition — le cas normal)"
    item_model = ((manifest.get('body') or {}).get('processing') or {}).get('item_model') or ''
    if not item_model:
        return None, "modèle de l'élément inconnu (`processing.item_model`)"
    pipeline, _functions = declared_pipeline(app_key)
    specs = process_specs(pipeline) if pipeline else []
    outputs = {field: s['key'] for s in specs for field in s['outputs']}
    processes = {s['key'] for s in specs}
    for surface in surfaces:
        reason = _check(surface, outputs, processes)
        if reason:
            return None, reason

    mark = _GEN_MARK.format(app_id=app_key)
    lines = [
        '"""',
        f"{mark} — surfaces.py GÉNÉRÉ (gabarit surfaces_gen).",
        '',
        "Les pages d'édition de l'app, COMPOSÉES de briques universelles (`common/surfaces.py`) et",
        'servies par les vues communes (`common/surface_views.py`). Source : la facette `surfaces` du',
        "manifeste de l'app. Ne pas éditer : régénérer.",
        '"""',
        'from wama.common.surfaces import BrickSlot, Surface, register_surface',
        '',
        "#: Le LABEL réel de l'app (jumelle comprise), lu de son paquet — jamais écrit en dur.",
        "_APP = __name__.rsplit('.', 2)[-2]",
    ]
    for surface in surfaces:
        slots = ',\n           '.join(_slot(s) for s in surface['slots'])
        args = [
            f"app=_APP, key={surface['key']!r}, label={surface['label']!r}",
            f"model=f'{{_APP}}.{item_model}'",
            f"slots=({slots},)",
            f"reads={dict(surface.get('reads') or {})!r}",
            f"edits={surface['edits']!r}",
        ]
        if surface.get('reruns'):
            args.append(f"reruns={surface['reruns']!r}")
        lines += ['', '', 'register_surface(Surface(', '    ' + ',\n    '.join(args) + '))']
    return '\n'.join(lines) + '\n', None
