"""
Doc DÉVELOPPEUR — générée, jamais rédigée (AGENTS.md §Trois docs, trois publics).

POURQUOI CE MODULE (demande de Fabien, 2026-09-11)

    La doc de WAMA est une doc de CONSTRUCTION ; il manquait une doc DÉVELOPPEUR « structurée et
    automatisée ». La règle actée le même jour dit comment la faire : une doc destinée à un public
    est une PROJECTION des registres, jamais une rédaction parallèle. Chaque page ci-dessous est
    donc calculée à la lecture depuis un registre qui existe déjà, et les seules phrases affichées
    sont celles que ces registres portent : description d'un doc, rôle d'un mécanisme, source d'un
    registre, docstring d'un module. Une phrase écrite ici ne pourrait que dériver.

    Les pages sont déclarées dans `docs_catalog.DOCS` (audience `developpeur`, champ `generator`)
    et servies par le même lecteur que la doc de construction.

L'API DES BRIQUES EST LUE PAR AST, JAMAIS PAR IMPORT

    Importer ~150 modules pour lire leurs signatures chargerait backends, services et librairies
    lourdes dans le processus web. `ast` lit le TEXTE : docstrings et signatures exactes, sans
    exécuter une ligne. Le prix — ni décorateurs résolus, ni alias suivis — est acceptable pour
    une carte ; ce n'est pas une introspection.
"""
from __future__ import annotations

import ast
from pathlib import Path
from typing import Dict

#: Ordre de lecture pour ÉTENDRE WAMA — des CLÉS de `docs_catalog`, rien d'autre : le pourquoi de
#: chaque étape est la description que le document déclare déjà dans le catalogue.
PARCOURS = ('agents', 'common-readme', 'mecanismes', 'generation-route', 'app-conventions',
            'manifest-spec', 'verification', 'llm')

_SIG_MAX = 160
_DOC_MAX = 240


def _une_ligne(texte: str, limite: int) -> str:
    t = ' '.join((texte or '').split())
    return t if len(t) <= limite else t[:limite - 1].rstrip() + '…'


def _code(s: str) -> str:
    """Code en ligne markdown, y compris quand le texte contient lui-même un backtick."""
    return f"`` {s} ``" if '`' in s else f"`{s}`"


def _signature(node) -> str:
    if isinstance(node, ast.ClassDef):
        bases = ', '.join(ast.unparse(b) for b in node.bases)
        sig = f"class {node.name}({bases})" if bases else f"class {node.name}"
    else:
        sig = f"{node.name}({ast.unparse(node.args)})"
        if node.returns is not None:
            sig += f" -> {ast.unparse(node.returns)}"
    return _une_ligne(sig, _SIG_MAX)


def module_api(path) -> dict:
    """`{'doc', 'items', 'lisible'}` d'un module Python, lu par AST : le premier paragraphe de sa
    docstring, et ses fonctions et classes PUBLIQUES de premier niveau (signature + première
    ligne de docstring)."""
    try:
        arbre = ast.parse(Path(path).read_text(encoding='utf-8', errors='replace'))
    except (OSError, SyntaxError, ValueError):
        return {'doc': '', 'items': [], 'lisible': False}
    items = []
    for node in arbre.body:
        if (isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
                and not node.name.startswith('_')):
            doc = (ast.get_docstring(node) or '').strip()
            items.append({'name': node.name, 'sig': _signature(node),
                          'doc': _une_ligne(doc.split('\n', 1)[0], _DOC_MAX) if doc else ''})
    doc_module = (ast.get_docstring(arbre) or '').strip().split('\n\n', 1)[0]
    return {'doc': _une_ligne(doc_module, 600), 'items': items, 'lisible': True}


def _lien_doc(doc) -> str:
    """Lien vers un doc du catalogue : son CHEMIN s'il en a un (le lecteur le réécrit vers sa
    page), son URL de lecture sinon (doc générée)."""
    if doc.path:
        return f"[{doc.label}]({doc.path})"
    from django.urls import reverse
    return f"[{doc.label}]({reverse('common:doc_read', args=[doc.key])})"


def _lien_ref(ref: str) -> str:
    """Un champ `doc` de registre (« AGENTS.md §Trois docs ») en lien vers son fichier."""
    cible = ref.split()[0] if ref else ''
    return f"[{ref}]({cible})" if cible.endswith('.md') else ref


def _cellule(texte) -> str:
    return ' '.join(str(texte or '').split()).replace('|', '\\|')


# ──────────────────────────────────────────────────────────────────────────────────────────────
# Les pages
# ──────────────────────────────────────────────────────────────────────────────────────────────

def parcours() -> str:
    from .docs_catalog import BY_KEY, DEVELOPER, DOCS

    out = ["# Parcours d'entrée", "",
           "> Page **générée** à chaque lecture (`wama/common/dev_docs.py`). L'ordre est déclaré "
           "(`PARCOURS`) ; chaque étape affiche la description que le document déclare dans le "
           "catalogue des docs — aucune phrase n'est écrite pour cette page.", "",
           "## Lire, dans cet ordre", ""]
    for i, cle in enumerate(PARCOURS, 1):
        d = BY_KEY[cle]
        out.append(f"{i}. **{_lien_doc(d)}** — {d.description}")
    out += ["", "## Les autres pages générées", ""]
    for d in DOCS:
        if d.audience == DEVELOPER and d.key != 'dev-parcours':
            out.append(f"- **{_lien_doc(d)}** — {d.description}")
    return '\n'.join(out) + '\n'


def registres() -> str:
    from django.urls import NoReverseMatch, reverse

    from .manifests import builtin  # noqa: F401 — l'import peuple MANIFEST_KINDS
    from .manifests.kinds import MANIFEST_KINDS
    from .registries import overview

    regs = overview()
    out = ["# Registres", "",
           "> Page **générée** à chaque lecture depuis `registries.overview()` et "
           "`MANIFEST_KINDS`. Un registre dit ce que WAMA sait NOMMER ; sa description dit la "
           "relation entre ses objets.", "",
           f"**{len(regs)} registres** · **{len(MANIFEST_KINDS)} kinds de manifeste**", ""]
    for r in regs:
        out += [f"## {r['label']}", "",
                f"- **Clé** : `{r['key']}` — {r['nature_label']}"]
        if r['total']:
            out.append(f"- **Entrées** : {r['total']}")
        out.append(f"- **Source** : {r['source']}")
        if r['url_name']:
            try:
                url = reverse(r['url_name'])
                out.append(f"- **Page** : [{url}]({url})")
            except NoReverseMatch:
                pass
        if r['doc']:
            out.append(f"- **Doc** : {_lien_ref(r['doc'])}")
        if r['manifest_kind']:
            out.append(f"- **Kind de manifeste** : `{r['manifest_kind']}`")
        if r['description']:
            out += ["", r['description']]
        out.append("")
    out += ["## Kinds de manifeste", "",
            "| kind | description | écrit dans les registres |", "|---|---|---|"]
    for k in sorted(MANIFEST_KINDS):
        mk = MANIFEST_KINDS[k]
        ecrit = 'oui (`write_back`)' if mk.write_back else 'non — stocké et diffable'
        out.append(f"| `{k}` | {_cellule(mk.description) or '—'} | {ecrit} |")
    return '\n'.join(out) + '\n'


#: Cache de la page « briques » : son coût est la lecture AST d'~150 modules. La clé est
#: l'EMPREINTE des domiciles (mtime) — un module modifié est relu à la lecture suivante, la page
#: reste donc dérivée.
_BRIQUES: Dict[str, object] = {}


def briques() -> str:
    from django.conf import settings

    from .mecanismes import MECANISMES

    base = Path(settings.BASE_DIR)
    empreinte = []
    for m in MECANISMES:
        try:
            empreinte.append((m.cle, (base / m.domicile).stat().st_mtime_ns))
        except OSError:
            empreinte.append((m.cle, None))
    empreinte = tuple(empreinte)
    if _BRIQUES.get('empreinte') == empreinte:
        return _BRIQUES['texte']

    domaines = list(dict.fromkeys(m.domaine for m in MECANISMES))
    out = ["# Briques communes — API", "",
           "> Page **générée** à chaque lecture depuis le registre des mécanismes "
           "(`wama/common/mecanismes.py`) et le CODE de leurs domiciles, lu par AST (sans import). "
           "Ce qu'une brique FAIT est sa ligne de registre ; comment l'APPELER est ce que son "
           "module expose. Qui l'utilise, et ce qui manque : la "
           "[carte des mécanismes](WAMA_MECANISMES.md).", "",
           f"**{len(MECANISMES)} mécanismes** en {len(domaines)} domaines.", ""]
    for dom in domaines:
        du = sorted((m for m in MECANISMES if m.domaine == dom), key=lambda x: x.nom.lower())
        out += [f"## {dom or 'Sans domaine'}", ""]
        for m in du:
            out += [f"### {m.nom}", "", m.role, ""]
            ligne = f"- **Domicile** : `{m.domicile}`"
            if m.doc:
                ligne += f" · **doc** : {_lien_ref(m.doc)}"
            out.append(ligne)
            if m.domicile.endswith('.py'):
                api = module_api(base / m.domicile)
                if not api['lisible']:
                    out.append("- ⚠ module illisible (absent, ou syntaxe invalide)")
                else:
                    if api['doc']:
                        out.append(f"- **Module** : {api['doc']}")
                    if api['items']:
                        out.append(f"- **API publique** ({len(api['items'])}) :")
                        for it in api['items']:
                            suite = f" — {it['doc']}" if it['doc'] else ''
                            out.append(f"  - {_code(it['sig'])}{suite}")
                    else:
                        out.append("- **API publique** : aucune fonction ni classe publique de "
                                   "premier niveau")
            out.append("")
    texte = '\n'.join(out) + '\n'
    _BRIQUES.update(empreinte=empreinte, texte=texte)
    return texte
