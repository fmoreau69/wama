#!/usr/bin/env python3
"""
Rôle « codegen » — corps de GLU d'une tâche d'app depuis le MANIFESTE COMPOSÉ (marche B).

Pilote BORNÉ, sur le patron de `run_librarian.py` (tâche étroite, one-shot, jamais
d'auto-application) :
  1. rassemble la MATIÈRE : contrat de la brique `task_skeleton` (docstring = le contrat),
     fichier mince rendu par le gabarit A2b (le trou à remplir, nom imposé), manifeste de
     l'app + manifestes RÉSOLUS de ses `requires` (modèles + librairies), 2 glus RÉELLES en
     few-shot (converter `_convert`, reader `_read` — extraites par AST, jamais recopiées) ;
  2. un seul appel LLM (rôle `codegen` : chaîne de repli de config.py en local, ou
     `--provider albert`) ;
  3. la sortie est contrôlée MÉCANIQUEMENT : compile(), fonction au nom imposé de signature
     (item, ctx), drapeaux d'interdits (écriture de statut/progress, MUTATION du cache HF,
     imports lourds en tête de bloc) ;
  4. écrit dans `outputs/` avec PENDING_HUMAN_VALIDATION — n'écrit JAMAIS dans wama/.
     Le juge profond reste le harnais C (`app_regen_check`) dans le worktree, après
     application HUMAINE de la glu.

Usage (racine du repo) :
    python wama-dev-ai/run_codegen.py --app converter --task convert_media_task \
        --truth wama.converter.tasks:_convert          # banc : vérité terrain jointe
    python wama-dev-ai/run_codegen.py --app reader --task read_document_task --model qwen3.8:latest
    python wama-dev-ai/run_codegen.py --app reader --task read_document_task --provider albert
"""
import argparse
import ast
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'wama.settings')
import django
django.setup()

# Helpers COMMUNS aux rôles — adoptés le 2026-09-07 (audit « la route est-elle unique ? »).
# Ce fichier portait sa PROPRE copie de `ollama_host`, `_OPENER_DIRECT`, `call_ollama` et de
# l'écriture de sortie : 4 rôles sur 5 adoptaient déjà `role_utils`, celui-ci non.
from role_utils import (  # noqa: E402
    add_llm_arguments, call_llm, consigne_role, resolve_model, write_output)

# ⚠ Ce chemin était ÉCRIT EN DUR ici — la 3ᵉ lecture du même dossier, et la seule qui ne
# passait même pas par `config.PROMPTS_DIR`. Même défaut que les copies de `ollama_host` et
# `call_ollama` soldées le 07/09 : le fichier avait adopté `role_utils` pour tout SAUF ça.
PROMPT = consigne_role('codegen')
MAX_MATTER_CHARS = 60000   # tâche étroite : tronquer plutôt que faire dériver
FEWSHOT = (('converter', 'wama/converter/tasks.py', ('convert_media_task', '_convert')),
           ('reader', 'wama/reader/tasks.py', ('read_document_task', '_read')))


def _source_de(path: Path, noms: tuple) -> str:
    """Segments source des fonctions demandées, par AST (le code réel, jamais recopié)."""
    src = path.read_text(encoding='utf-8')
    morceaux = []
    for node in ast.parse(src).body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in noms:
            morceaux.append(ast.get_source_segment(src, node) or '')
    return '\n\n'.join(morceaux)


def inventaire_app(app_id: str) -> str:
    """Modules RÉELS importables de l'app (backends/utils/services…) — symboles top-level
    par AST. Banc 13/08 : sans cet inventaire, tous les modèles ré-implémentent inline ou
    INVENTENT des imports plausibles ; c'était le 1er trou de matière mesuré."""
    base = REPO_ROOT / 'wama' / app_id
    exclus_fichiers = {'__init__.py', 'admin.py', 'apps.py', 'urls.py', 'views.py',
                       'tasks.py', 'workers.py', 'models.py', 'tool_api.py', 'forms.py'}
    exclus_dossiers = {'migrations', 'tests', 'static', 'templates', 'management'}
    lignes = []
    for p in sorted(base.rglob('*.py')):
        rel = p.relative_to(REPO_ROOT)
        if p.name in exclus_fichiers or exclus_dossiers.intersection(rel.parts):
            continue
        try:
            arbre = ast.parse(p.read_text(encoding='utf-8'))
        except (SyntaxError, OSError):
            continue
        syms = []
        for n in arbre.body:
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and not n.name.startswith('_'):
                syms.append(f"{n.name}({', '.join(a.arg for a in n.args.args)})")
            elif isinstance(n, ast.ClassDef) and not n.name.startswith('_'):
                # Méthodes publiques AVEC signature — delta 13/08 : sans elles, le modèle
                # invente le nom de méthode (`extract` au lieu de `run`).
                # `self` CONSERVÉ : delta v2 13/08 — sans lui, le modèle appelle les
                # méthodes d'instance comme des méthodes de classe (Backend.run(...)).
                meths = [f"{m.name}({', '.join(a.arg for a in m.args.args)})"
                         for m in n.body
                         if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef))
                         and not m.name.startswith('_')]
                syms.append(f"{n.name}{{{'; '.join(meths)}}}" if meths else n.name)
        if syms:
            lignes.append(f"{'.'.join(rel.with_suffix('').parts)} : {', '.join(syms)}")
    return '\n'.join(lignes)[:8000]


def champs_item(item_model: str, app_id: str = '') -> tuple:
    """(champs concrets, propriétés) du modèle d'item — champs = seules clés licites de
    `fields` ; propriétés = attributs LISIBLES légitimes (ex. `filename` du reader — sa
    lecture sur un modèle qui ne l'a pas était un résidu du delta 13/08).
    ⚠ Le manifeste porte un nom de classe NU (`ReadingItem`) : préfixer par l'app."""
    if not item_model:
        return [], []
    from django.apps import apps as dj_apps
    model = None
    for ref in (item_model, f'{app_id}.{item_model}'):
        try:
            model = dj_apps.get_model(ref)
            break
        except Exception:
            continue
    if model is None:
        return [], []
    # Nom ET TYPE (2026-10-01) : sans le type, gpt-oss a pris le `FileField` `source_document`
    # pour une relation vers une autre card (`source_document_id`, `.result_text`) — le document
    # source était ignoré sans un mot.
    champs = sorted(f'{f.name} ({type(f).__name__})' for f in model._meta.get_fields()
                    if getattr(f, 'concrete', False) and not getattr(f, 'auto_created', False))
    props = sorted(n for n in vars(model) if isinstance(vars(model)[n], property)
                   and not n.startswith('_'))
    return champs, props


#: Quelles briques COMMUNES la glu doit voir, selon ce que le manifeste COMPOSÉ déclare :
#: déclencheur → (clé du MÉCANISME, fonctions montrées). L'EMPLACEMENT vient du registre des
#: mécanismes (`wama/common/mecanismes.py` : domicile + annexes), jamais d'ici — une table de
#: chemins écrite ici était un second index des briques (relevé le 2026-10-01).
#: Pourquoi des briques dans la matière : sans elles, une app qui appelle un LLM ne pouvait
#: qu'inventer l'appel ou déclarer un trou (règle 6 du prompt), mesuré sur la 1ʳᵉ app de zéro.
BRICKS_BY_TRIGGER = {
    ('model_type', 'llm'): ('llm', ('chat_with_catalog_model',)),
    # Une facette `prompts` dit que la consigne passe par le pipeline de prompts (traduction,
    # fichiers de RÉFÉRENCE, RAG) : `process_prompt_for` est le point d'entrée d'une app.
    ('facet', 'prompts'): ('prompt_pipeline', ('process_prompt_for',)),
    # Un select de modèle avec « auto » (`options_auto`) : la valeur se TIRE au lancement par la
    # brique commune, avec le domaine, le curseur et les distants déclarés au schéma — le même
    # chemin que la prévision « Prévu : … » (2026-10-01 : la 1ʳᵉ glu du Writer passait `auto`
    # tel quel à la brique LLM, qui tirait par un autre chemin que la prévision).
    ('param_flag', 'options_auto'): ('auto_model', ('resolve_model_choice',)),
}


def _brick_file(mechanism_key: str, names: tuple) -> Path:
    """Le fichier du mécanisme (domicile ou annexe) qui DÉFINIT les fonctions demandées."""
    from wama.common.mecanismes import by_key
    m = by_key()[mechanism_key]
    for rel_path in (m.home, *m.annexes):
        p = REPO_ROOT / rel_path
        if p.suffix == '.py' and p.exists():
            defined = {n.name for n in ast.parse(p.read_text(encoding='utf-8')).body
                       if isinstance(n, ast.FunctionDef)}
            if set(names) <= defined:
                return p
    raise SystemExit(f'brique {names} introuvable dans le mécanisme {mechanism_key}')


def _triggered(resolus: list, man: dict) -> list:
    model_types = {((m.get('body') or {}).get('identity') or {}).get('model_type')
                   for m in resolus if m.get('manifest_kind') == 'model'}
    body = (man or {}).get('body') or {}
    facets = set(body)
    param_flags = {flag for schema in ((body.get('params') or {}).get('schemas') or {}).values()
                   for field in schema or [] for flag, on in field.items() if on is True}
    return [v for (kind, value), v in BRICKS_BY_TRIGGER.items()
            if (kind == 'model_type' and value in model_types)
            or (kind == 'facet' and value in facets)
            or (kind == 'param_flag' and value in param_flags)]


def signatures_briques() -> dict:
    """{nom de brique : noms de paramètres acceptés} — pour JUGER les appels de la glu. Une
    brique à `**kwargs` n'est pas jugeable (tout passe) : c'est pourquoi les briques montrées
    ont une signature explicite (`chat_with_catalog_model`, 2026-10-01)."""
    import importlib
    import inspect
    out = {}
    for mechanism_key, names in BRICKS_BY_TRIGGER.values():
        rel_path = _brick_file(mechanism_key, names).relative_to(REPO_ROOT)
        module = importlib.import_module('.'.join(rel_path.with_suffix('').parts))
        for name in names:
            params = inspect.signature(getattr(module, name)).parameters
            if not any(p.kind == p.VAR_KEYWORD for p in params.values()):
                out[name] = set(params)
    return out


def briques_communes(resolus: list, man: dict = None) -> str:
    """Source des briques communes DÉCLENCHÉES par le manifeste composé (par AST)."""
    blocks = []
    for mechanism_key, names in _triggered(resolus, man):
        p = _brick_file(mechanism_key, names)
        module = '.'.join(p.relative_to(REPO_ROOT).with_suffix('').parts)
        blocks.append(f'# from {module} import {", ".join(names)}   (mécanisme `{mechanism_key}`)\n'
                      + _source_de(p, names))
    return '\n\n'.join(blocks)


def matiere_manifeste(app_id: str, manifest_path: str = '') -> tuple:
    """(manifeste app compacté, manifestes des requires résolus). Extraction LIVE de l'app, ou
    — app créée DE ZÉRO (`app_sandbox create --from-manifest`) — le manifeste AUTORÉ : c'est
    lui qui porte les `requires`, qu'une extraction de l'app générée ne retrouverait pas."""
    from wama.common.manifests.ingest import extract
    if manifest_path:
        path = Path(manifest_path)
        man = json.loads((path if path.is_absolute() else REPO_ROOT / path)
                         .read_text(encoding='utf-8'))
    else:
        man = extract('app', app_id)
    if not man:
        raise SystemExit(f"app inconnue : {app_id}")
    body = man.get('body') or {}
    # Compaction : la glu n'a pas besoin des facettes UI (modes/studio/inspector/tool_api).
    # `prompts` GARDÉE (2026-10-01) : elle dit que la consigne passe par le pipeline de prompts.
    garde = {k: body[k] for k in ('identity', 'params', 'processing', 'models',
                                  'capabilities', 'ports', 'prompts') if k in body}
    compact = {k: v for k, v in man.items() if k != 'body'} | {'body': garde}
    resolus = []
    for r in man.get('requires') or []:
        try:
            m = extract(r.get('kind'), r.get('key'))
            if m:
                resolus.append(m)
        except Exception:
            continue
    return compact, resolus


#: Réglages PROPRES au codegen, conservés À L'IDENTIQUE lors de l'adoption du commun
#: (2026-09-07). Ils ne sont PAS cosmétiques : la matière servie va jusqu'à
#: `MAX_MATTER_CHARS` (60 000 caractères), illisible au num_ctx de 16384 du défaut commun —
#: et écrire du code prend plus longtemps qu'un verdict JSON.
CODEGEN_NUM_CTX, CODEGEN_TEMPERATURE, CODEGEN_TIMEOUT = 32768, 0.2, 900


def extract_code(text: str) -> str:
    """Le bloc ```python de la réponse, de sa clôture OUVRANTE à la DERNIÈRE clôture ; à
    défaut, le texte brut (modèle discipliné).

    ⚠ Jusqu'au 2026-10-01 le bloc s'arrêtait à la PREMIÈRE clôture rencontrée : une glu qui
    encadre du Markdown dans une chaîne (```` ``` ```` dans son prompt — le process de mise en
    forme de l'Editor) était coupée en plein code, et le contrôle signalait une « f-string non
    terminée » que le modèle n'avait pas écrite."""
    opening = re.search(r'```(?:python|py)?[ \t]*\n', text)
    closing = text.rfind('```')
    if opening and closing > opening.end():
        return text[opening.end():closing].strip()
    return text.strip()


def _returned_field_keys(fn_node) -> set:
    """Clés littérales des dicts `'fields': {…}` construits dans la fonction (retours compris)."""
    keys = set()
    for n in ast.walk(fn_node):
        if not isinstance(n, ast.Dict):
            continue
        for k, v in zip(n.keys, n.values):
            if isinstance(k, ast.Constant) and k.value == 'fields' and isinstance(v, ast.Dict):
                keys |= {kk.value for kk in v.keys if isinstance(kk, ast.Constant)}
    return keys


def controles(code: str, nom_impose: str, app_id: str = None, item_fields=None,
              settings_fields=None) -> dict:
    """Contrôles mécaniques du bloc généré — le LLM propose, la chaîne juge. `item_fields` = les
    champs du modèle d'item : la règle 5 du prompt n'admet qu'eux comme clés de `fields`, et ce
    contrôle la rend mécanique (elle n'était qu'une consigne)."""
    out = {'compile_ok': False, 'signature_ok': False, 'warnings': []}
    try:
        arbre = ast.parse(code)
        out['compile_ok'] = True
    except SyntaxError as e:
        out['warnings'].append(f'SyntaxError: {e}')
        return out

    # Imports WAMA INVENTÉS (banc 13/08 : `run_ffmpeg_cmd`, `select_model_by_vram`…) —
    # tout module wama.* ou relatif doit exister sur le disque, sinon c'est une hallucination.
    if app_id:
        for n in ast.walk(arbre):
            if isinstance(n, ast.ImportFrom):
                if n.level:
                    mod = f"wama/{app_id}/{(n.module or '').replace('.', '/')}".rstrip('/')
                elif (n.module or '').startswith('wama.'):
                    mod = n.module.replace('.', '/')
                else:
                    continue
                base = REPO_ROOT / mod
                if not (base.with_suffix('.py').exists() or (base / '__init__.py').exists()):
                    out['warnings'].append(
                        f"import WAMA INEXISTANT : {'.' * n.level}{n.module or ''} (règle 6)")

    fonctions = [n for n in arbre.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    cible = next((f for f in fonctions if f.name == nom_impose), None)
    if cible is None:
        out['warnings'].append(f"fonction imposée `{nom_impose}` absente "
                               f"(reçues : {[f.name for f in fonctions]})")
    else:
        args = [a.arg for a in cible.args.args]
        out['signature_ok'] = args[:2] == ['item', 'ctx']
        if not out['signature_ok']:
            out['warnings'].append(f'signature {args} ≠ (item, ctx)')
        if item_fields:
            hors = sorted(_returned_field_keys(cible) - set(item_fields))
            if hors:
                out['warnings'].append(f'clés de fields hors des champs du modèle (règle 5) : {hors}')
        # Un RÉGLAGE réécrit au succès (2026-10-01 : `'model': <modèle tiré>` — le choix « auto »
        # de l'utilisateur perdu à la première génération). `fields` porte des résultats.
        overwritten = sorted(_returned_field_keys(cible) & set(settings_fields or ()))
        if overwritten:
            out['warnings'].append(f'fields réécrit un RÉGLAGE de l\'utilisateur : {overwritten} '
                                   f'(le modèle employé va dans `models`)')
    # Arguments DEVINÉS d'une brique commune (2026-10-01 : `max_tokens`, `max_new_tokens` passés
    # à la brique LLM — `TypeError` au premier lancement, invisible sans ce contrôle).
    signatures = signatures_briques()
    for n in ast.walk(arbre):
        if isinstance(n, ast.Call):
            nom = getattr(n.func, 'id', None) or getattr(n.func, 'attr', None)
            if nom in signatures:
                inconnus = sorted(k.arg for k in n.keywords
                                  if k.arg and k.arg not in signatures[nom])
                if inconnus:
                    out['warnings'].append(f'argument(s) inconnu(s) de la brique {nom} : '
                                           f'{inconnus} (acceptés : {sorted(signatures[nom])})')
    # Label d'app ÉCRIT EN DUR dans un appel (2026-10-01 : `process_prompt_for('writer', …)` dans
    # la jumelle `writer_01` — aucune cible trouvée, référence ignorée sans un message). Le label
    # qui exécute est `ctx.app_id` ; on compare au label ET à sa forme sans suffixe de jumelle.
    if app_id:
        labels = {app_id, re.sub(r'_\d{2}$', '', app_id)}
        hardcoded = sorted({a.value for n in ast.walk(arbre) if isinstance(n, ast.Call)
                            for a in (*n.args, *(k.value for k in n.keywords))
                            if isinstance(a, ast.Constant) and a.value in labels})
        if hardcoded:
            out['warnings'].append(f'label d\'app écrit en dur {hardcoded} : passer ctx.app_id')
    autres = [n for n in arbre.body
              if not isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Import,
                                    ast.ImportFrom))]
    if autres:
        out['warnings'].append(f'{len(autres)} nœud(s) top-level hors fonctions/imports')
    for n in arbre.body:
        if isinstance(n, (ast.Import, ast.ImportFrom)):
            noms = [a.name for a in n.names] + [getattr(n, 'module', '') or '']
            lourds = [x for x in noms if any(h in (x or '') for h in
                      ('torch', 'transformers', 'diffusers', 'huggingface'))]
            if lourds:
                out['warnings'].append(f'import lourd en tête de bloc (règle 3) : {lourds}')

    # Interdits textuels (règle 2) — la glu ne pilote pas le cycle de vie.
    for motif, raison in ((r'item\.status\s*=', 'écrit item.status (règle 2)'),
                          (r'item\.progress\s*=', 'écrit item.progress (règle 2)'),
                          (r'\.update\(\s*status\s*=', 'update(status=…) (règle 2)'),
                          (r"['\"](RUNNING|SUCCESS|FAILURE)['\"]\s*\)?\s*$",
                           None)):   # lecture tolérée — pas de warning
        if raison and re.search(motif, code):
            out['warnings'].append(raison)
    # Mutation du cache HF (règle 3) — INTERDITE depuis le 2026-09-03 (AGENTS.md). Ce contrôle
    # exigeait l'INVERSE jusqu'au 2026-09-29 : il signalait « import avant HF_HUB_CACHE » quand
    # la glu ne mutait PAS l'environnement, donc il réclamait la faute que la doctrine interdit.
    if re.search(r"os\.(environ\s*\[\s*['\"]|environ\.setdefault\(\s*['\"]|putenv\(\s*['\"])"
                 r"(HF_HUB_CACHE|HUGGINGFACE_HUB_CACHE|HF_HOME)", code):
        out['warnings'].append('mutation du cache HF dans l\'environnement (règle 3)')
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--app', required=True, help="App cible (ex. converter, ou le label d'une "
                                                  "app de zéro : editor_01).")
    ap.add_argument('--manifest', default='',
                    help="Manifeste AUTORÉ d'une app créée de zéro (ex. "
                         "manifests/app_drafts/editor.json) — remplace l'extraction live.")
    ap.add_argument('--task', default=None,
                    help='Fonction de tâche lifecycle (défaut : la seule déclarée).')
    add_llm_arguments(ap, role='codegen')
    ap.add_argument('--truth', default=None,
                    help="Vérité terrain jointe à la revue : 'module.dotted:fonction'.")
    args = ap.parse_args()

    man, resolus = matiere_manifeste(args.app, args.manifest)
    proc = (man.get('body') or {}).get('processing') or {}
    lifecycle = [t['function'] for t in (proc.get('tasks') or []) if t.get('lifecycle')]
    task = args.task or (lifecycle[0] if len(lifecycle) == 1 else None)
    if not task:
        raise SystemExit(f"--task requis (lifecycle déclarées : {lifecycle})")
    nom_impose = f'_process_{task}'

    # Fichier mince du gabarit A2b : montre au modèle le wrapper et le trou EXACTS.
    from wama.common.manifests.codegen.tasks_gen import render_tasks
    mince, raison = render_tasks({**man, 'body': {**man['body'],
                                  'processing': {**proc, 'tasks': [
                                      t for t in proc.get('tasks') or []
                                      if t.get('function') == task]}}})
    if mince is None:
        raise SystemExit(f'gabarit tasks non rendable : {raison}')

    contrat = ast.get_docstring(ast.parse(
        (REPO_ROOT / 'wama/common/utils/task_skeleton.py').read_text(encoding='utf-8')))
    fewshot = '\n\n'.join(
        f'===== GLU RÉELLE ({app}) =====\n{_source_de(REPO_ROOT / chemin, noms)}'
        for app, chemin, noms in FEWSHOT if app != args.app)

    corps = json.dumps(man, ensure_ascii=False, indent=1)
    jambes = '\n'.join(json.dumps(m, ensure_ascii=False) for m in resolus)
    inventaire = inventaire_app(args.app)
    briques = briques_communes(resolus, man)
    champs, props = champs_item(proc.get('item_model') or '', args.app)
    user_msg = (
        f'CONTRAT de la brique run_item_task (docstring de task_skeleton.py) :\n{contrat}\n\n'
        f'EXEMPLES — glus réelles d\'apps WAMA existantes :\n{fewshot}\n\n'
        f'MANIFESTE de l\'app `{args.app}` :\n{corps}\n\n'
        f'MANIFESTES RÉSOLUS de ses requires (modèles + librairies) :\n{jambes}\n\n'
        f'MODULES RÉELS de l\'app (les SEULS imports d\'app autorisés ; les méthodes entre '
        f'{{}} sont les SEULES méthodes des classes) :\n'
        f'{inventaire or "(aucun module métier — pas d\'import d\'app)"}\n\n'
        + (f'BRIQUES COMMUNES à employer pour les modèles requis (imports AUTORISÉS, à '
           f'utiliser plutôt que tout appel direct à un fournisseur) :\n{briques}\n\n'
           if briques else '') +
        f'CHAMPS DU MODÈLE D\'ITEM `{proc.get("item_model") or "?"}` (les clés de `fields` '
        f'du retour DOIVENT en faire partie) :\n{", ".join(champs) or "(inconnus)"}\n'
        f'Propriétés lisibles en plus : {", ".join(props) or "(aucune)"} — tout autre '
        f'attribut d\'item est INTERDIT.\n\n'
        f'FICHIER MINCE généré (le wrapper appelle ta glu) :\n{mince}\n\n'
        f'Écris la fonction `{nom_impose}(item, ctx)` qui remplit ce trou '
        f'(bloc ```python seul).')[:MAX_MATTER_CHARS]

    model = resolve_model(args.provider, 'codegen', args.model)
    print(f'[codegen] {args.provider} / {model} | app : {args.app} | glu : {nom_impose}')
    reponse = call_llm(args.provider, model, PROMPT, user_msg, num_ctx=CODEGEN_NUM_CTX,
                       temperature=CODEGEN_TEMPERATURE, timeout=CODEGEN_TIMEOUT)
    code = extract_code(reponse)
    verif = controles(code, nom_impose, args.app,
                      item_fields=[c.split(' (')[0] for c in champs],
                      settings_fields=((proc.get('model_spec') or {}).get('item') or {})
                      .get('params_fields'))
    # Une brique que le manifeste DÉCLENCHE et que la glu n'appelle pas (2026-10-01 : `auto`
    # passé tel quel à la brique LLM au lieu d'être tiré par `resolve_model_choice`) — la
    # montrer dans la matière ne suffit pas, l'oubli doit se voir.
    if verif['compile_ok']:
        called = {getattr(n.func, 'id', None) or getattr(n.func, 'attr', None)
                  for n in ast.walk(ast.parse(code)) if isinstance(n, ast.Call)}
        for _key, names in _triggered(resolus, man):
            verif['warnings'] += [f'brique déclenchée par le manifeste non appelée : {name}'
                                  for name in names if name not in called]

    verite = None
    if args.truth:
        module, _, fn = args.truth.partition(':')
        chemin = REPO_ROOT.joinpath(*module.split('.')).with_suffix('.py')
        verite = {'ref': args.truth, 'source': _source_de(chemin, (fn,))}

    # `write_output` produit EXACTEMENT le même fichier qu'avant : le nom se compose
    # `{role}_{slug}_{horodatage}.json`, donc `codegen_{app}_{task}_{horodatage}.json` avec
    # ce slug, et l'enveloppe pose les mêmes `status`/`role` en tête. Vérifié avant bascule.
    sortie = write_output('codegen', f'{args.app}_{task}', {
        'provider': args.provider,
        'model': model,
        'app': args.app, 'task': task, 'function': nom_impose,
        'checks': verif,
        'code': code,
        # La réponse BRUTE (2026-10-01) : un code mal extrait ne se diagnostique qu'en la relisant.
        'raw_response': reponse,
        'truth': verite,
        'matter_chars': len(user_msg),
    })

    print(f'[codegen] → {sortie.relative_to(REPO_ROOT)}')
    print(f"[codegen] compile={verif['compile_ok']} signature={verif['signature_ok']} "
          f"warnings={len(verif['warnings'])}"
          + (f' — {verif["warnings"][:3]}' if verif['warnings'] else ''))
    print('[codegen] juge profond = harnais C après application HUMAINE (worktree).')


if __name__ == '__main__':
    main()
