"""
Index des librairies TIERCES réellement utilisées par le code WAMA — brique de MESURE.

Deux consommateurs, une seule mesure (règle « zéro duplication ») :
  • `manage.py library_candidates` : propose les candidats au semis du corpus `library` ;
  • `builtin/app.py::extract_app`  : remplit la jambe `app → library` de `requires`.

Ce module **ne peuple rien** et n'écrit nulle part. Le semis au corpus reste EXPLICITE
(`manage.py manifest_export --kind library <clé>`, SPEC §7.4-3) : aucun critère automatique ne
décide qu'une librairie mérite d'entrer. C'est délibéré — `venv_linux` contient ~575 distributions
dont l'écrasante majorité sont des dépendances transitives, pas des capacités WAMA.

Méthode : AST sur les sources (pas d'exécution, pas d'import), puis `packages_distributions()`
pour passer du nom de MODULE au nom de DISTRIBUTION (`cv2` → `opencv-python`) — la confusion
entre les deux est la source d'erreur classique de ce genre d'inventaire.
"""
from __future__ import annotations

import ast
import logging
import sys
from functools import lru_cache
from pathlib import Path

logger = logging.getLogger(__name__)

#: Racines de code WAMA à analyser (relatives à BASE_DIR).
RACINES = ('wama', 'wama_lab')

#: Paquets internes : jamais des librairies tierces.
INTERNES = {'wama', 'wama_lab'}

#: ⚠ `wama_lab/face_analyzer` embarque SES PROPRES venv (14 227 + 495 fichiers .py). Sans cette
#: exclusion, l'inventaire remonte les imports de site-packages (`AppKit`, `Carbon`…) et compte
#: 15 336 fichiers au lieu de ~614. Tout parcours AST de l'arbre doit reprendre cette liste.
EXCLUS = {'migrations', '__pycache__', 'venv', 'venv_win', 'venv_linux',
          'site-packages', 'node_modules', '.git', 'staticfiles'}


def _base_dir() -> Path:
    from django.conf import settings
    return Path(settings.BASE_DIR)


def _app_de(chemin: Path, base: Path) -> str | None:
    """
    'wama/transcriber/views.py' → 'transcriber' ; hors app → None.

    `len(parts) >= 3` est nécessaire : sans ce test, les fichiers à la RACINE du paquet
    (`wama/celery.py`, `wama/apps.py`, `wama/views.py`) sont pris pour des noms d'apps et
    polluent la colonne APPS de l'inventaire.
    """
    try:
        parts = chemin.relative_to(base).parts
    except ValueError:
        return None
    return parts[1] if len(parts) >= 3 and parts[0] in RACINES else None


def _modules_du_fichier(chemin: Path) -> set[str]:
    """Modules top-level importés par un fichier (imports globaux ET locaux)."""
    try:
        arbre = ast.parse(chemin.read_text(encoding='utf-8', errors='replace'))
    except (SyntaxError, ValueError, OSError):
        return set()   # un fichier illisible ne doit jamais casser l'inventaire
    out: set[str] = set()
    for n in ast.walk(arbre):
        if isinstance(n, ast.Import):
            out.update(a.name.split('.')[0] for a in n.names)
        elif isinstance(n, ast.ImportFrom) and n.level == 0 and n.module:
            out.add(n.module.split('.')[0])
    return out


@lru_cache(maxsize=1)
def scan_imports() -> dict[str, dict]:
    """
    Distribution PyPI → {'modules': [...], 'apps': [...]}.

    Mis en cache : `extract_app` est appelé pour les 10 apps d'affilée (roundtrip, export) et
    re-scanner l'arbre à chaque fois serait absurde.
    """
    base = _base_dir()
    par_module: dict[str, set[str]] = {}

    for racine in RACINES:
        for chemin in (base / racine).rglob('*.py'):
            if EXCLUS & set(chemin.parts):
                continue
            app = _app_de(chemin, base)
            for m in _modules_du_fichier(chemin):
                if m in INTERNES or m in sys.stdlib_module_names or m.startswith('_'):
                    continue
                par_module.setdefault(m, set())
                if app:
                    par_module[m].add(app)

    import importlib.metadata as im
    mapping = im.packages_distributions()

    resultat: dict[str, dict] = {}
    for module, apps in par_module.items():
        for dist in mapping.get(module) or ():
            e = resultat.setdefault(dist, {'modules': set(), 'apps': set()})
            e['modules'].add(module)
            e['apps'].update(apps)
    # `non_resolus` : modules sans distribution connue (code vendoré, submodule, dep optionnelle
    # absente du venv). On les EXPOSE au lieu de les deviner — « null plutôt que plausible ».
    resultat['__non_resolus__'] = {
        'modules': {m for m in par_module if not mapping.get(m)}, 'apps': set()}
    return {k: {'modules': sorted(v['modules']), 'apps': sorted(v['apps'])}
            for k, v in resultat.items()}


@lru_cache(maxsize=1)
def declarees() -> frozenset[str]:
    """Distributions déclarées dans les `requirements*.txt` (nom normalisé PyPI)."""
    base = _base_dir()
    out: set[str] = set()
    for f in sorted(base.glob('requirements*.txt')):
        for ligne in f.read_text(encoding='utf-8', errors='replace').splitlines():
            ligne = ligne.split('#')[0].strip()
            if not ligne or ligne.startswith('-'):
                continue
            nom = ligne.split('[')[0]
            for sep in ('==', '>=', '<=', '~=', '>', '<', ';', '='):
                nom = nom.split(sep)[0]
            if nom.strip():
                out.add(_normalise(nom))
    return frozenset(out)


def _normalise(nom: str) -> str:
    """PEP 503 : les noms de distribution sont insensibles à la casse et à -/_/. ."""
    return nom.strip().lower().replace('_', '-').replace('.', '-')


@lru_cache(maxsize=1)
def semees() -> frozenset[str]:
    """Clés déjà semées au corpus `manifests/libraries/*.json` (nom normalisé)."""
    dossier = _base_dir() / 'manifests' / 'libraries'
    if not dossier.is_dir():
        return frozenset()
    return frozenset(_normalise(p.stem) for p in dossier.glob('*.json'))


def candidats() -> list[dict]:
    """
    Inventaire trié : une ligne par distribution tierce importée par le code WAMA.

    Chaque ligne porte sa PROVENANCE, pour que la décision de semis soit informée et non devinée.
    """
    import importlib.metadata as im

    scan = scan_imports()
    decl, sem = declarees(), semees()
    out = []
    for dist, info in scan.items():
        if dist == '__non_resolus__':
            continue
        norm = _normalise(dist)
        try:
            version = im.version(dist)
        except Exception:
            version = ''
        out.append({
            'dist': dist,
            'version': version,
            'declaree': norm in decl,
            'semee': norm in sem,
            'apps': info['apps'],
            'modules': info['modules'],
            'nb_apps': len(info['apps']),
        })
    # Les plus transverses d'abord : une lib utilisée par 6 apps est plus probablement une
    # capacité structurante qu'une lib utilisée par une seule.
    out.sort(key=lambda c: (-c['nb_apps'], c['dist'].lower()))
    return out


def non_resolus() -> list[str]:
    """Modules tiers importés dont aucune distribution n'est connue (à inspecter à la main)."""
    return sorted(scan_imports().get('__non_resolus__', {}).get('modules', []))


def librairies_de(app_id: str) -> list[str]:
    """
    Librairies à citer dans le `requires` du manifeste de l'app `app_id`.

    RÈGLE (deux conditions, toutes deux nécessaires) :
      1. l'app IMPORTE réellement la distribution (fait mesuré, pas déclaré) ;
      2. la distribution est SEMÉE au corpus (décision humaine explicite).

    La condition 2 n'est pas une précaution de style : `ingest.valider()` traite une référence
    `requires` pendante comme une ERREUR de manifeste. Citer une librairie non semée rendrait
    donc invalides les 10 manifestes d'apps d'un coup.
    """
    sem = semees()
    return sorted(
        c['dist'] for c in candidats()
        if app_id in c['apps'] and _normalise(c['dist']) in sem
    )
