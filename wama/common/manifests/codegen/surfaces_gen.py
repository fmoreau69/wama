"""
Gabarit `surfaces.py` — les SURFACES d'une app, déclarées dans son manifeste (2026-10-13, 2ᵉ
surface du chantier SURFACES : le fond du Writer).

Une surface (`common/surfaces.py`) est une page d'édition COMPOSÉE de briques universelles,
servie par les vues communes (`common/surface_views.py`) : une app la DÉCLARE, elle n'écrit pas
de page. Ce gabarit rend cette déclaration depuis la facette `surfaces` du manifeste `app`, au
lieu de la faire écrire à la main dans l'app (règle D5, ROUTE §10.5 : seul le manifeste se
rédige à la main ; le reste se génère).

Ce qui est rendu : un `register_surface(Surface(...))` par surface — emplacements (brique,
position et taille par défaut), rôles lus, champ écrit, process rejoué, et l'élément TÉMOIN des
vignettes du catalogue des briques (`witness`, 2026-10-18).

LES CROCHETS DE CODE (2026-11-10, demande de Fabien : la facette `surfaces` d'une app EXISTANTE
est extraite, `builtin/app._surfaces`) — `available` et `validate` se déclarent par CHEMIN POINTÉ,
comme `ProcessSpec.eta` : un crochet du COMMUN est importé (`validate_text`), un crochet de l'app
devient un TROU DE GLU dans le module qu'il désigne (`tasks_gen._DECLARED_GLUE`, le même geste
`app_sandbox glue` le remplit). Tant que la glu manque, la page se dit indisponible
(`Surface.can_open` ne lève pas). Un champ de DONNÉE s'édite alors s'il déclare sa validation.

Ce qui est REFUSÉ, en le disant (rien n'est deviné) :
  • une brique absente du registre (`surfaces.BRICKS`), ou une brique de PAGE (2026-10-19 :
    card d'entrée, inspecteur, visionneuse — une page d'app les monte) ;
  • un emplacement hors de la grille ;
  • un champ écrit qui n'est ni un FICHIER produit par un process déclaré, ni validé par un
    `validate` DÉCLARÉ : seul un texte se valide sans code (`surfaces.validate_text`) ;
  • un process rejoué (`reruns`) qui n'est pas un process déclaré ;
  • un crochet hors de l'app et du commun, une fonction anonyme (`_unsupported` de l'extraction),
    ou un crochet de PAGE (`value`, `saved`, `edit_state`…) — ⏳ ils se lisent au rendu de la page,
    un trou de glu y casserait la page au lieu de la fermer.

Le LABEL de l'app n'est jamais écrit en dur : le module le lit de son propre nom de paquet (même
règle que `function_specs_gen` — une jumelle `writer_01` déclare `writer_01.edit`).
"""
from __future__ import annotations

import re

from wama.common.manifests.codegen.pipeline_decl import declared_pipeline, process_specs

_KEY_RE = re.compile(r'^[a-z][a-z0-9_]*$')

#: Les crochets de code qu'une surface déclare par chemin pointé et que ce gabarit rend — ceux
#: que la règle commune lit sans casser une vue (`Surface.can_open`) ou à l'écriture (`clean`).
SURFACE_HOOKS = ('available', 'validate')
#: Les champs de `Surface` que la facette ne porte PAS en données : l'identité, le modèle de
#: l'élément (`processing.item_model`) et les emplacements, écrits à part — l'extraction
#: (`builtin/app._surfaces`) et ce gabarit lisent cette déclaration.
SURFACE_OWN = ('app', 'key', 'label', 'model', 'slots')
#: Les données qu'une app née d'un manifeste déclarait déjà, rendues à leur place historique.
_FIRST = ('reads', 'edits', 'reruns', 'witness')


def _surface_fields() -> dict:
    """`{nom: type annoté}` des champs de `Surface` — lus sur la dataclass, jamais recopiés : un
    champ ajouté à la surface passe par l'extraction et par ce gabarit sans une ligne ici."""
    import dataclasses
    from wama.common.surfaces import Surface
    return {f.name: str(f.type) for f in dataclasses.fields(Surface)}


def _data_fields() -> list:
    """Les DONNÉES d'une surface rendues telles quelles, au-delà de `_FIRST` : ni identité, ni
    crochet de code (un type `Callable`)."""
    return [n for n, kind in _surface_fields().items()
            if n not in SURFACE_OWN and n not in _FIRST and 'Callable' not in kind]


def declared_surfaces(manifest: dict) -> list:
    """La facette `surfaces` du manifeste (liste), vide si absente."""
    return list(((manifest.get('body') or {}).get('surfaces')) or [])


def _edited_fields(surface: dict) -> list:
    """Les champs que la surface ÉCRIT : `edits` (un nom, des alternatifs, rien en lecture seule)
    puis `also_edits` — la lecture de `Surface.fields`, côté manifeste."""
    edits = surface.get('edits')
    fields = list(edits) if isinstance(edits, (list, tuple)) else ([edits] if edits else [])
    return fields + list(surface.get('also_edits') or [])


def _hook_ref(path: str, app_key: str) -> tuple:
    """`(nom, ligne d'import ou '', raison du refus ou '')` d'un crochet déclaré. Le module de
    surfaces de l'app : le trou de glu posé dans ce fichier (aucun import) ; un autre module de
    l'app : import RELATIF (une jumelle lit le sien) ; le commun : import absolu."""
    from wama.common.manifests.codegen.tasks_gen import split_declared_path
    module, name, _sep = split_declared_path(path)
    if not name.isidentifier():
        return '', '', f"crochet illisible {path!r}"
    if module == f'{app_key}.surfaces':
        return name, '', ''
    if module.startswith(f'{app_key}.'):
        return name, f"from .{module[len(app_key) + 1:]} import {name}", ''
    if module.startswith('common.'):
        return name, f"from wama.{module} import {name}", ''
    return '', '', f"crochet {path!r} hors de l'app et du commun"


def _check(surface: dict, outputs: dict, processes: set, app_key: str = '') -> str:
    """'' si la surface se génère, sinon la raison du refus."""
    from wama.common.surfaces import BRICKS, GRID_COLUMNS, PANEL_COLUMNS, ZONES
    key = surface.get('key') or ''
    if not _KEY_RE.match(key):
        return f"clé de surface invalide : {key!r} (underscore_case)"
    if not surface.get('label'):
        return f"surface {key} : libellé absent"
    if surface.get('_unsupported'):
        return (f"surface {key} : crochet(s) sans chemin, une fonction anonyme ne se déclare pas "
                f"({', '.join(surface['_unsupported'])})")
    known = {'key', 'label', 'slots', *_FIRST, *_data_fields(), *SURFACE_HOOKS, '_unsupported'}
    unknown = sorted(set(surface) - known)
    if unknown:
        return (f"surface {key} : {', '.join(unknown)} non généré(s) par ce gabarit (crochets "
                f"rendus : {', '.join(SURFACE_HOOKS)})")
    for hook in SURFACE_HOOKS:
        if surface.get(hook):
            _name, _line, refused = _hook_ref(surface[hook], app_key)
            if refused:
                return f"surface {key} : {hook} — {refused}"
    slots = surface.get('slots') or []
    if not slots:
        return f"surface {key} : aucun emplacement"
    for slot in slots:
        if slot.get('brick') not in BRICKS:
            return (f"surface {key} : brique inconnue {slot.get('brick')!r} "
                    f"(connues : {', '.join(sorted(BRICKS))})")
        if BRICKS[slot['brick']].is_page:
            return (f"surface {key} : {slot['brick']!r} est une brique de PAGE — une page d'app la "
                    "monte, une surface ne la pose pas")
        # La zone (2026-10-21) : la grille, ou la colonne du volet (une colonne).
        zone = slot.get('zone') or 'grid'
        if zone not in ZONES:
            return f"surface {key} : zone inconnue {zone!r} pour {slot.get('id')!r} ({', '.join(ZONES)})"
        columns = PANEL_COLUMNS if zone == 'panel' else GRID_COLUMNS
        x, w = int(slot.get('x', 0)), int(slot.get('w', 0))
        if not slot.get('id') or w <= 0 or int(slot.get('h', 0)) <= 0 or x < 0 or x + w > columns:
            return f"surface {key} : emplacement {slot.get('id')!r} hors de sa zone ({zone}, {columns} colonne(s))"
    # Un champ écrit est un FICHIER sorti d'un process (validation commune), ou une DONNÉE dont
    # la surface déclare la validation (`validate`, un crochet) — jamais une donnée sans elle.
    if not surface.get('validate'):
        for edits in _edited_fields(surface):
            if edits not in outputs:
                return (f"surface {key} : « {edits} » n'est la sortie d'aucun process déclaré — un "
                        "gabarit ne génère que l'édition d'un FICHIER texte produit par un process, "
                        "ou d'une donnée dont la surface déclare la validation (`validate`)")
    reruns = surface.get('reruns') or ''
    if reruns and reruns not in processes:
        return f"surface {key} : process rejoué inconnu {reruns!r} (déclarés : {', '.join(sorted(processes))})"
    if not all(isinstance(r, str) and isinstance(f, str) for r, f in (surface.get('reads') or {}).items()):
        return f"surface {key} : `reads` attend {{rôle: champ}}"
    # Le témoin des vignettes (2026-10-18) : {champ: valeur} ; leur SENS (contenu d'un champ
    # fichier, ou valeur littérale — une case, une liste de segments) se juge une fois le modèle
    # connu (`Surface.witness_problems`, tenu par `tests_surfaces`).
    if not all(isinstance(f, str) and isinstance(v, (str, bool, int, float, list, dict))
               for f, v in (surface.get('witness') or {}).items()):
        return f"surface {key} : `witness` attend {{champ: valeur}}"
    return ''


def _slot(slot: dict) -> str:
    args = [repr(slot['id']), repr(slot['brick'])] + [str(int(slot.get(k, 0))) for k in 'xywh']
    if slot.get('options'):
        args.append(repr(dict(slot['options'])))
    if (slot.get('zone') or 'grid') != 'grid':
        args.append(f"zone={slot['zone']!r}")
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
        reason = _check(surface, outputs, processes, app_key)
        if reason:
            return None, reason

    mark = _GEN_MARK.format(app_id=app_key)
    imports = {line for s in surfaces for hook in SURFACE_HOOKS if s.get(hook)
               for line in [_hook_ref(s[hook], app_key)[1]] if line}
    lines = [
        '"""',
        f"{mark} — surfaces.py GÉNÉRÉ (gabarit surfaces_gen).",
        '',
        "Les pages d'édition de l'app, COMPOSÉES de briques universelles (`common/surfaces.py`) et",
        'servies par les vues communes (`common/surface_views.py`). Source : la facette `surfaces` du',
        "manifeste de l'app. Ne pas éditer : régénérer.",
        '"""',
        'from wama.common.surfaces import BrickSlot, Surface, register_surface',
        *sorted(imports),
        '',
        "#: Le LABEL réel de l'app (jumelle comprise), lu de son paquet — jamais écrit en dur.",
        "_APP = __name__.rsplit('.', 2)[-2]",
    ]
    # Les crochets que les surfaces logent dans CE module : un trou de glu chacun, AVANT les
    # déclarations qui les nomment (`tasks_gen.declared_glue_holes`, la marque de tous les trous).
    from wama.common.manifests.codegen.tasks_gen import declared_glue_holes
    lines += declared_glue_holes(manifest, [], mark, set(), modules={'surfaces'})
    for surface in surfaces:
        slots = ',\n           '.join(_slot(s) for s in surface['slots'])
        edits = surface.get('edits')
        args = [
            f"app=_APP, key={surface['key']!r}, label={surface['label']!r}",
            f"model=f'{{_APP}}.{item_model}'",
            f"slots=({slots},)",
            f"reads={dict(surface.get('reads') or {})!r}",
            f"edits={(tuple(edits) if isinstance(edits, list) else edits)!r}",
        ]
        if surface.get('reruns'):
            args.append(f"reruns={surface['reruns']!r}")
        for hook in SURFACE_HOOKS:
            if surface.get(hook):
                args.append(f"{hook}={_hook_ref(surface[hook], app_key)[0]}")
        kinds = _surface_fields()
        for name in _data_fields():
            if name in surface:
                value = surface[name]
                args.append(f"{name}={(tuple(value) if kinds[name] == 'tuple' else value)!r}")
        if surface.get('witness'):
            args.append(f"witness={dict(surface['witness'])!r}")
        lines += ['', '', 'register_surface(Surface(', '    ' + ',\n    '.join(args) + '))']
    return '\n'.join(lines) + '\n', None
