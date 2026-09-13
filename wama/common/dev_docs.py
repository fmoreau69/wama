"""
Doc DÉVELOPPEUR — les FAITS calculés depuis les registres (AGENTS.md §Trois docs, trois publics).

POURQUOI CE MODULE (demande de Fabien, 2026-09-11)

    La doc de WAMA est une doc de CONSTRUCTION ; il manquait une doc DÉVELOPPEUR « structurée et
    automatisée ». Recadrage du même jour : elle DÉRIVE de la doc de construction, et y injecte
    les faits des registres. Ce module fournit la moitié « faits » : des générateurs qui rendent
    du markdown depuis un registre, que les PLANS de `docs_catalog.py` citent (`Facts`) et que
    `doc_facts` écrit en `.md`. Les seules phrases affichées sont celles que les registres portent
    (description d'un doc, rôle d'un mécanisme, source d'un registre, docstring d'un module) — une
    phrase écrite ici dériverait.

    ⚠ Un générateur écrit dans un fichier VERSIONNÉ : il n'y met aucun nombre lu en base (il
    changerait d'une installation à l'autre et le fichier serait toujours périmé), et ses liens
    partent de la RACINE du dépôt (`doc_plans.build` les recale sur le fichier cible).

    Jusqu'au 2026-09-14, deux pages (parcours, briques) étaient CALCULÉES à la lecture et
    n'existaient que dans WAMA, pour les administrateurs. Reversées en fichiers (ROADMAP §25.1 ⑥) :
    la cible est « tout en `.md`, lisible depuis le dépôt ET depuis WAMA » (Fabien, 2026-09-13) —
    un agent ne lit pas une page réservée aux administrateurs.

L'API DES BRIQUES EST LUE PAR AST, JAMAIS PAR IMPORT

    Importer ~150 modules pour lire leurs signatures chargerait backends, services et librairies
    lourdes. `ast` lit le TEXTE : docstrings et signatures exactes, sans exécuter une ligne. Le
    prix — ni décorateurs résolus, ni alias suivis — est acceptable pour une carte ; ce n'est pas
    une introspection.
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
    """Lien vers un doc du catalogue, par son chemin depuis la racine (recalé par le plan)."""
    return f"[{doc.label}]({doc.path})"


def _lien_ref(ref: str) -> str:
    """Un champ `doc` de registre (« AGENTS.md §Trois docs ») en lien vers son fichier.

    Un NOM NU (« ROADMAP.md §25 ») se résout par le catalogue : depuis le déménagement de la doc
    (2026-09-14) la plupart des docs ne sont plus à la racine, et un lien écrit depuis la racine
    pointerait dans le vide. Un nom qui ne se résout pas UNE seule fois reste tel quel."""
    cible = ref.split()[0] if ref else ''
    if not cible.endswith('.md'):
        return ref
    if '/' not in cible:
        from .docs_catalog import BY_PATH
        trouves = [p for p in BY_PATH if p == cible or p.endswith('/' + cible)]
        if len(trouves) == 1:
            cible = trouves[0]
    return f"[{ref}]({cible})"


def _cellule(texte) -> str:
    return ' '.join(str(texte or '').split()).replace('|', '\\|')


# ──────────────────────────────────────────────────────────────────────────────────────────────
# Faits pour les PLANS (fichiers versionnés) — ni nombre lu en base, ni lien de site
# ──────────────────────────────────────────────────────────────────────────────────────────────

def parcours_etapes() -> str:
    """L'ordre de lecture pour étendre WAMA, puis les autres pages développeur."""
    from .docs_catalog import BY_KEY, DEVELOPER, DOCS

    out = ["## Lire, dans cet ordre", ""]
    for i, cle in enumerate(PARCOURS, 1):
        d = BY_KEY[cle]
        out.append(f"{i}. **{_lien_doc(d)}** — {d.description}")
    out += ["", "## Les autres pages développeur", ""]
    for d in DOCS:
        if d.audience == DEVELOPER and d.key != 'dev-parcours':
            out.append(f"- **{_lien_doc(d)}** — {d.description}")
    return '\n'.join(out) + '\n'


def registres_natures() -> str:
    """Les natures d'actualisation déclarables par un registre, et où chacune s'exécute."""
    from .registries import EXECUTION_BY_NATURE, EXECUTIONS, NATURES

    out = ["## Les natures d'actualisation", "",
           "| nature | ce qu'elle déclare | où tourne l'actualisation |", "|---|---|---|"]
    for cle, libelle in NATURES.items():
        lieu = EXECUTIONS.get(EXECUTION_BY_NATURE.get(cle, ''), 'rien à actualiser')
        out.append(f"| `{cle}` | {_cellule(libelle)} | {_cellule(lieu)} |")
    return '\n'.join(out) + '\n'


def registres_fiches() -> str:
    """Chaque registre de WAMA : clé, nature, source, page, doc, et s'il est citable par balise."""
    from django.urls import NoReverseMatch, reverse

    from .registries import NATURES, REGISTRIES

    # Les DÉCLARATIONS, jamais `overview()` : celui-ci compte les entrées de chaque registre EN
    # BASE, ce qu'aucune ligne de ce fichier n'affiche. Première version faite avec lui : la
    # génération d'une doc dépendait de la base sans raison — et a bloqué le 2026-09-11 pendant
    # une relance de WAMA. Tout ce qui est écrit ici est déclaré dans le code.
    regs = sorted(REGISTRIES.values(), key=lambda r: r.label)
    out = ["## Les registres, un par un", "",
           f"**{len(regs)} registres**, par ordre alphabétique de libellé.", ""]
    for r in regs:
        out += [f"### {r.label}", "",
                f"- **Clé** : `{r.key}` — {NATURES[r.nature]}",
                f"- **Source** : {r.source}"]
        if r.url_name:
            try:
                out.append(f"- **Page dans WAMA** : `{reverse(r.url_name)}`")
            except NoReverseMatch:
                pass
        if r.doc:
            out.append(f"- **Doc** : {_lien_ref(r.doc)}")
        if r.manifest_kind:
            out.append(f"- **Kind de manifeste** : `{r.manifest_kind}`")
        if r.entries is not None:
            out.append(f"- **Citable dans une doc** : `WAMA:FAIT({r.key}/<clé>/<champ>)`")
        if r.description:
            out += ["", r.description]
        out.append("")
    return '\n'.join(out) + '\n'


def kinds_manifeste() -> str:
    """Les kinds de manifeste, et lesquels écrivent dans les registres."""
    from .manifests import builtin  # noqa: F401 — l'import peuple MANIFEST_KINDS
    from .manifests.kinds import MANIFEST_KINDS

    out = ["## Kinds de manifeste", "",
           "| kind | description | écrit dans les registres |", "|---|---|---|"]
    for k in sorted(MANIFEST_KINDS):
        mk = MANIFEST_KINDS[k]
        ecrit = 'oui (`write_back`)' if mk.write_back else 'non — stocké et diffable'
        out.append(f"| `{k}` | {_cellule(mk.description) or '—'} | {ecrit} |")
    return '\n'.join(out) + '\n'


#: Cache de l'API des briques : son coût est la lecture AST d'~150 modules. La clé est
#: l'EMPREINTE des domiciles (mtime) — un module modifié est relu au passage suivant.
_BRIQUES: Dict[str, object] = {}


def briques_api() -> str:
    """Chaque mécanisme transversal, par domaine, avec l'API publique de son domicile."""
    from django.conf import settings

    from .docs_catalog import BY_KEY
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
    carte = BY_KEY['mecanismes']
    out = [f"**{len(MECANISMES)} mécanismes** en {len(domaines)} domaines. Ce qu'une brique FAIT "
           f"est sa ligne de registre (`wama/common/mecanismes.py`) ; comment l'APPELER est ce que "
           f"son module expose, lu dans le code par AST. Qui l'utilise, et ce qui manque : la "
           f"[{carte.label.lower()}]({carte.path}).", ""]
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
