"""Ce qu'un manifeste `app` peut faire entrer dans le CODE que la génération écrit.

Les gabarits (`models_gen`, `views_gen`, `tasks_gen`…) composent du Python par chaînes : un nom de
modèle devient `class <nom>(…)`, un champ d'entrée `<nom> = models.FileField(…)`, une expression de
la facette `data` est recopiée telle quelle comme argument d'un champ. Un manifeste d'app peut être
PROPOSÉ par un rôle LLM (`run_app_manifest`, chaîne `repo_app`) : une valeur qui n'est pas un nom
ferait écrire, puis importer au rechargement du serveur, du code que personne n'a relu.

Le contrôle vit ICI, une fois, et le validateur du kind (`builtin/app.validate_app_body`) l'appelle :
les trois portes d'un manifeste venu d'ailleurs passent par lui (ingest, « Valider » d'une
proposition, création d'une app depuis un fichier). Les gabarits n'ont donc rien à refaire.

Ce qui est admis — mesuré sur le corpus le 2026-11-08 (18 manifestes, 1122 expressions) :
  - un NOM : un identifiant Python qui n'est pas un mot réservé ;
  - un CHEMIN : des noms séparés par des points, enraciné dans `django` ou `wama` ;
  - un IMPORT : `import <chemin>` ou `from <chemin> import <nom>, …` sur les mêmes racines ;
  - une EXPRESSION de la facette `data` : littéraux, listes, tuples, dictionnaires, références à
    des chemins enracinés dans `django`, `wama`, `settings`, `models` (le module des champs,
    importé par le gabarit), `dict` ou `list` (les `default=` appelables), et APPELS des seuls
    constructeurs de `CALLABLE_PREFIXES`. Rien d'autre : ni lambda, ni compréhension, ni nom
    commençant par `_` (pas de `__import__`, pas de `__class__`).
"""
from __future__ import annotations

import ast
import keyword
import re

#: Racines d'un chemin désigné par le manifeste (classe de champ, base, gestionnaire, import).
PATH_ROOTS = ('django', 'wama')
#: Noms qu'une expression de la facette `data` peut nommer en tête : les racines, plus ce que le
#: gabarit importe lui-même (`models`, `settings` par son import déclaré) et deux types appelables.
EXPRESSION_ROOTS = frozenset(PATH_ROOTS + ('settings', 'models', 'dict', 'list'))
#: Ce qu'une expression peut APPELER — un appel s'exécute au chargement du `models.py` généré.
#: Les seuls mesurés au corpus : validateurs et champs de Django, chemin de dépôt commun. Une
#: référence non appelée (`default=dict`, `on_delete=…CASCADE`, `choices=<fonction>`) désigne du
#: code EXISTANT, relu ; un appel hors de cette liste se déclare ici, par un humain.
CALLABLE_PREFIXES = ('django.core.validators.', 'django.db.models.', 'models.',
                     'wama.common.utils.media_paths.')
_EXPRESSION_NODES = (ast.Expression, ast.Constant, ast.Name, ast.Attribute, ast.Load, ast.Call,
                     ast.keyword, ast.List, ast.Tuple, ast.Dict, ast.Set, ast.UnaryOp, ast.USub,
                     ast.UAdd)
_DOTTED = r'[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*'
_IMPORT = re.compile(rf'import ({_DOTTED})|from ({_DOTTED}) import [A-Za-z_]\w*(?:, [A-Za-z_]\w*)*')


def is_name(value) -> bool:
    """Un identifiant Python, hors mot réservé."""
    return isinstance(value, str) and value.isidentifier() and not keyword.iskeyword(value)


def is_path(value) -> bool:
    """`racine.module.Nom`, chaque segment un nom, la racine dans `PATH_ROOTS`."""
    if not isinstance(value, str):
        return False
    parts = value.split('.')
    return len(parts) >= 2 and parts[0] in PATH_ROOTS and all(is_name(p) for p in parts)


def is_import(value) -> bool:
    match = isinstance(value, str) and _IMPORT.fullmatch(value)
    return bool(match) and (match.group(1) or match.group(2)).split('.')[0] in PATH_ROOTS


def expression_error(text) -> str:
    """'' si `text` est une expression admise, sinon la raison."""
    if not isinstance(text, str):
        return 'expression non textuelle'
    try:
        tree = ast.parse(text, mode='eval')
    except SyntaxError:
        return 'pas une expression Python'
    for node in ast.walk(tree):
        if not isinstance(node, _EXPRESSION_NODES):
            return f'construction refusée ({type(node).__name__})'
        if isinstance(node, ast.Name) and node.id not in EXPRESSION_ROOTS:
            return f'nom refusé ({node.id})'
        if isinstance(node, ast.Attribute) and node.attr.startswith('_'):
            return f'attribut refusé ({node.attr})'
        if isinstance(node, ast.keyword) and not is_name(node.arg or ''):
            return 'argument nommé refusé'
        if isinstance(node, ast.Call) and not (_chain(node.func) or '').startswith(CALLABLE_PREFIXES):
            return f'appel refusé ({_chain(node.func) or type(node.func).__name__})'
    return ''


def _chain(node) -> str:
    """`a.b.c` pour une suite d'attributs sur un nom, sinon ''."""
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    return '.'.join([node.id, *reversed(parts)]) if isinstance(node, ast.Name) else ''


def _data_errors(data) -> list[str]:
    errs = []
    for m in (data or {}).get('models') or []:
        where = f"data.models[{m.get('name')!r}]"
        if not is_name(m.get('name')):
            errs.append(f'{where} : nom de modèle invalide')
        for path in m.get('bases') or []:
            if not is_path(path):
                errs.append(f'{where}.bases : chemin refusé {path!r}')
        if m.get('manager') and not is_path(m['manager']):
            errs.append(f"{where}.manager : chemin refusé {m['manager']!r}")
        for f in m.get('fields') or []:
            if not is_name(f.get('name')):
                errs.append(f"{where}.fields : nom de champ invalide {f.get('name')!r}")
            if f.get('_error'):
                # Champ insérialisable : le gabarit n'en émet qu'un COMMENTAIRE — qu'une fin de
                # ligne ferait sortir.
                if not isinstance(f['_error'], str) or '\n' in f['_error'] or '\r' in f['_error']:
                    errs.append(f"{where}.fields[{f.get('name')!r}] : _error sur plusieurs lignes")
                continue
            if not is_path(f.get('class')):
                errs.append(f"{where}.fields[{f.get('name')!r}] : classe refusée {f.get('class')!r}")
            kwargs = f.get('kwargs') or {}
            for k in kwargs:
                if not is_name(k):
                    errs.append(f"{where}.fields[{f.get('name')!r}] : argument nommé refusé {k!r}")
            for value in list(f.get('args') or []) + list(kwargs.values()):
                if (reason := expression_error((value or {}).get('expr'))):
                    errs.append(f"{where}.fields[{f.get('name')!r}] : {reason}")
                for line in (value or {}).get('imports') or []:
                    if not is_import(line):
                        errs.append(f"{where}.fields[{f.get('name')!r}] : import refusé {line!r}")
    return errs


#: Un texte recopié ENTRE GUILLEMETS (dans un `.py`, ou dans une balise `{% %}` d'un gabarit) : rien
#: qui ferme la chaîne, la ligne ou la balise.
_TEXT_FORBIDDEN = ("'", '"', '\\', '\n', '\r', '{%', '%}', '{{', '}}', '</')
#: Une aide d'entrée de réglage, recopiée comme indication de saisie : l'apostrophe y est remplacée
#: par le gabarit (`templates_gen`), le reste ne l'est pas.
_PROSE_FORBIDDEN = ('\\', '\n', '\r', '{%', '%}', '{{', '}}', '</')


def _is_text(value) -> bool:
    return isinstance(value, str) and not any(c in value for c in _TEXT_FORBIDDEN)


def _is_prose(value) -> bool:
    return isinstance(value, str) and not any(c in value for c in _PROSE_FORBIDDEN)


def _is_dotted(value) -> bool:
    """Un nom pointé quelconque (`wama.describer.tasks.describe`) — un nom de tâche Celery."""
    return isinstance(value, str) and all(is_name(p) for p in value.split('.'))


def _is_view(value) -> bool:
    """La vue d'une route : un nom pointé, éventuellement `.as_view()` (vue de classe)."""
    return _is_dotted(value[:-len('.as_view()')] if isinstance(value, str)
                      and value.endswith('.as_view()') else value)


def _is_named_form(value) -> bool:
    """Un champ du schéma de détail : un NOM quand il est une chaîne (le gabarit en crée la
    colonne) ; ses formes calculées (liste « premier non vide », dict) ne s'écrivent pas en code."""
    return is_name(value) if isinstance(value, str) else True


def _is_attr(value) -> bool:
    """Un champ d'état de la triade : son nom, ou `{'attr': <nom>, …}`."""
    return is_name(value.get('attr') if isinstance(value, dict) else value)


#: Chaque valeur du corps que les gabarits recopient dans du code, et la forme qu'elle doit avoir.
#: Relevé sur les générateurs le 2026-11-08 (`models_gen`, `views_gen`, `tasks_gen`, `urls_gen`,
#: `apps_gen`, `params_gen`, `templates_gen`, et les projecteurs de `builtin/app.py`). Syntaxe d'un
#: chemin : `a.b` descend, `[]` parcourt une liste, `{}` prend les CLÉS d'un dict, `*` ses valeurs.
#: Une valeur ABSENTE n'est pas une erreur : le gabarit prend alors son défaut, qui est à lui.
DECLARED_VALUES = (
    (is_name, ('processing.model_spec.item.name', 'processing.model_spec.item.input_field',
               'processing.model_spec.item.user_related_name',
               'processing.model_spec.item.params_fields[]',
               'processing.model_spec.batch.name', 'processing.model_spec.batch.link_name',
               'processing.model_spec.batch.link_item_field',
               'processing.model_spec.batch.link_batch_field',
               'processing.model_spec.batch.link_batch_related',
               'processing.model_spec.batch.user_related_name',
               'processing.model_spec.batch.link_item_related',
               'processing.ingest.target', 'processing.ingest.name_field', 'processing.ingest.source',
               'processing.tasks[].function', 'processing.item_model',
               'processing.batch_link_model', 'processing.endpoints[]',
               'processing.backend_nature_field', 'processing.backend_result.field',
               'inspector.preview.file_field',
               'prompts.targets[].field', 'ports.inputs[].id', 'params.primary',
               'params.schemas{}', 'params.schemas*[].name', 'modes{}', 'surfaces[].key')),
    (_is_named_form, ('inspector.detail_spec.result_file', 'inspector.detail_spec.result_text',
                      'inspector.detail_spec.source_text')),
    (_is_attr, ('tool_api.triad_spec.status_fields*',)),
    # Les crochets d'une surface (2026-11-10, `surfaces_gen.SURFACE_HOOKS`) : un import ou un nom.
    (is_path, ('surfaces[].available', 'surfaces[].validate')),
    (_is_view, ('processing.extra_routes[].view',)),
    (_is_dotted, ('processing.tasks[].task_name',)),
    (_is_text, ('processing.extra_routes[].pattern', 'processing.extra_routes[].name',
                'identity.url_name', 'identity.input_extensions[]', 'identity.verbose_name',
                'ports.inputs[].label')),
    (_is_prose, ('params.schemas*[].help',)),
)
_STEP = re.compile(r'([^.\[\]{}*]+)|(\[\])|(\{\})|(\*)')


def _values(node, path: str):
    """Les valeurs désignées par `path` dans `node` (vide si un maillon manque)."""
    current = [node]
    for name, each, keys, values in _STEP.findall(path):
        following = []
        for item in current:
            if name and isinstance(item, dict) and item.get(name) is not None:
                following.append(item[name])
            elif each and isinstance(item, list):
                following.extend(item)
            elif keys and isinstance(item, dict):
                following.extend(item)
            elif values and isinstance(item, dict):
                following.extend(item.values())
        current = following
    return current


def _declared_errors(body: dict) -> list[str]:
    return [f'{path} : valeur refusée dans du code généré {value!r}'
            for rule, paths in DECLARED_VALUES for path in paths
            for value in _values(body, path) if not rule(value)]


def pipeline_source_safety_errors(body: dict) -> list[str]:
    """Le pipeline d'une app (manifeste `pipeline`) : ses process DÉCLARÉS (un nœud qui porte
    `process`) deviennent du code — `tasks_gen` en tire `_process_<fonction>_<id>`, ses sorties des
    colonnes (`models_gen`), son libellé et ses dépendances une docstring. Les nœuds d'un pipeline
    du Studio, qui ne déclarent pas de process, ne sont pas concernés."""
    if not isinstance(body, dict):
        return []
    errs, declared = [], set()
    for node in body.get('nodes') or []:
        if not isinstance(node, dict) or 'process' not in node:
            continue
        nid = node.get('id')
        declared.add(nid)
        # Un id n'entre dans le code qu'À L'INTÉRIEUR d'un nom (`_process_<fonction>_<id>`) ou entre
        # guillemets : un mot réservé y est un nom comme un autre (`import` au transcriber).
        if not (isinstance(nid, str) and nid.isidentifier()):
            errs.append(f'nodes : id de process refusé dans du code généré {nid!r}')
        process = node.get('process') if isinstance(node.get('process'), dict) else {}
        for output in process.get('outputs') or []:
            if not is_name(output):
                errs.append(f'nodes[{nid!r}].process.outputs : nom refusé {output!r}')
        if not _is_prose(process.get('label') or '') or '"""' in (process.get('label') or ''):
            errs.append(f'nodes[{nid!r}].process.label : texte refusé dans du code généré')
    for link in body.get('links') or []:
        if (isinstance(link, dict) and link.get('to') in declared
                and not (isinstance(link.get('from'), str) and link['from'].isidentifier())):
            errs.append(f"links : dépendance refusée dans du code généré {link.get('from')!r}")
    return errs


def source_safety_errors(body: dict) -> list[str]:
    """Les valeurs du manifeste qui, recopiées dans le code généré, n'y seraient pas qu'un nom, un
    chemin, un texte inerte ou une expression admise. Liste vide = rien à refuser."""
    if not isinstance(body, dict):
        return []
    return _declared_errors(body) + _data_errors(body.get('data'))
