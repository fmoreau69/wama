"""
Index des librairies TIERCES réellement utilisées par le code WAMA — brique de MESURE.

Deux consommateurs, une seule mesure (règle « zéro duplication ») :
  • `manage.py library_candidates` : propose les candidats au semis du corpus `library` ;
  • `builtin/app.py::extract_app`  : remplit la jambe `app → library` de `requires`.

Ce module **ne peuple rien** et n'écrit nulle part. Le semis au corpus passe par la route
(`manage.py manifest_export --kind library <clé>`, SPEC §7.4-3). Son CRITÈRE est une décision de
Fabien (2026-11-06) : toute distribution que le code WAMA IMPORTE est au registre — `unseeded()`
doit être vide (`tests_manifest_library.EveryImportedLibraryIsSeededTest`). Les dépendances
TRANSITIVES n'y entrent pas : `venv_linux` contient ~575 distributions, que le code n'importe pas.

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

from wama.common.file_cache import FileCache, file_stamp

logger = logging.getLogger(__name__)

#: Racines de code WAMA à analyser (relatives à BASE_DIR) — les trois mondes (`AGENTS.md`, « un
#: monde n'est pas un sous-dossier du substrat ») ; `wama_data` en manquait jusqu'au 2026-11-06.
RACINES = ('wama', 'wama_lab', 'wama_data')

#: Paquets internes : jamais des librairies tierces.
INTERNES = {'wama', 'wama_lab', 'wama_data'}

#: ⚠ `wama_lab/face_analyzer` embarque SES PROPRES venv (14 227 + 495 fichiers .py). Sans cette
#: exclusion, l'inventaire remonte les imports de site-packages (`AppKit`, `Carbon`…) et compte
#: 15 336 fichiers au lieu de ~614. Tout parcours AST de l'arbre doit reprendre cette liste.
EXCLUS = {'migrations', '__pycache__', 'venv', 'venv_win', 'venv_linux',
          'site-packages', 'node_modules', '.git', 'staticfiles'}

#: SOCLE PLATEFORME (strate 1, SPEC §7.4) — contrat d'exécution commun aux 10 apps, PAS une
#: dépendance de workload : ne se déclare JAMAIS dans le `requires` d'une app (même semé, il
#: en est exclu). Même logique que k8s/Backstage : la plateforme n'est pas une dépendance de
#: l'application. Étendre cette liste est une décision d'ARCHITECTURE, pas un réglage.
#: (torch/transformers n'y sont PAS : capacités ML citées là où elles sont importées — elles
#: portent l'information dont la génération de backends a besoin, marche B.)
SOCLE_PLATEFORME = frozenset({'django', 'celery', 'redis', 'numpy', 'requests'})


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


#: Imports par fichier, gardés sur l'empreinte du fichier (`common/file_cache.py`) : la jambe
#: backends d'`extract_app` relit les modules de backends à CHAQUE extraction.
_IMPORTS = FileCache()


def _modules_du_fichier(chemin: Path) -> frozenset[str]:
    """Modules top-level importés par un fichier (imports globaux ET locaux)."""
    try:
        return _IMPORTS.get(chemin, _lire_modules)
    except OSError:
        return frozenset()   # un fichier illisible ne doit jamais casser l'inventaire


def _lire_modules(chemin: Path) -> frozenset[str]:
    try:
        arbre = ast.parse(chemin.read_text(encoding='utf-8', errors='replace'))
    except (SyntaxError, ValueError, OSError):
        return frozenset()
    out: set[str] = set()
    for n in ast.walk(arbre):
        if isinstance(n, ast.Import):
            out.update(a.name.split('.')[0] for a in n.names)
        elif isinstance(n, ast.ImportFrom) and n.level == 0 and n.module:
            out.add(n.module.split('.')[0])
    return frozenset(out)


_DISTRIBUTIONS: tuple = ((), None)


def _distributions() -> dict:
    """`importlib.metadata.packages_distributions()` (module → distributions), mis en cache.

    ~3,8 s par appel ici (76 000 `stat` dans `site-packages`), et il était appelé à CHAQUE
    extraction de manifeste (mesuré le 2026-09-14). Gardé tant que les dossiers d'installation
    n'ont pas bougé : installer, mettre à jour ou retirer une distribution y crée ou y efface un
    `*.dist-info`, ce qui change la date du DOSSIER — l'empreinte le voit.
    """
    global _DISTRIBUTIONS
    import importlib.metadata as im
    empreinte = tuple((p, file_stamp(p)) for p in sys.path
                      if p and p.rstrip('\\/').endswith(('site-packages', 'dist-packages')))
    if _DISTRIBUTIONS[1] is None or _DISTRIBUTIONS[0] != empreinte:
        _DISTRIBUTIONS = (empreinte, im.packages_distributions())
    return _DISTRIBUTIONS[1]


def code_files():
    """Les fichiers Python du code WAMA, ceux dont les imports disent ce que WAMA utilise.

    Les trois racines (`RACINES`), hors `EXCLUS` — et hors du code tiers VENDORISÉ sous
    `settings.BACKEND_VENDOR_DIR` (2026-11-06) : la route `vendor` y clone des moteurs entiers
    (ACE-Step : 413 fichiers), dont les imports sont LEURS dépendances — gradio, loguru, mlx… —, pas
    des usages de WAMA ; la librairie vendorisée est elle-même au registre. Les compter les
    attribuait à `common` et en faisait des candidats au semis.
    """
    from django.conf import settings

    base = _base_dir()
    vendor = getattr(settings, 'BACKEND_VENDOR_DIR', None)
    vendor = Path(vendor) if vendor else None
    for root in RACINES:
        for path in (base / root).rglob('*.py'):
            if EXCLUS & set(path.parts):
                continue
            if vendor is not None and path.is_relative_to(vendor):
                continue
            yield path


@lru_cache(maxsize=1)
def scan_imports() -> dict[str, dict]:
    """
    Distribution PyPI → {'modules': [...], 'apps': [...]}.

    Mis en cache : `extract_app` est appelé pour les 10 apps d'affilée (roundtrip, export) et
    re-scanner l'arbre à chaque fois serait absurde.
    """
    base = _base_dir()
    par_module: dict[str, set[str]] = {}

    for chemin in code_files():
        app = _app_de(chemin, base)
        for m in _modules_du_fichier(chemin):
            if m in INTERNES or m in sys.stdlib_module_names or m.startswith('_'):
                continue
            par_module.setdefault(m, set())
            if app:
                par_module[m].add(app)

    mapping = _distributions()

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
            name = _distribution_name(ligne)
            if name:
                out.add(_normalise(name))
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
            'socle': norm in SOCLE_PLATEFORME,
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


def unseeded() -> list[str]:
    """Distributions que le code WAMA importe et que le corpus ne porte pas — attendu : aucune
    (décision de Fabien, 2026-11-06 : une librairie utilisée par WAMA est au registre).

    Une distribution dont CHAQUE module importé est déjà fourni par une distribution semée n'en
    est pas une : c'est une variante (`opencv-contrib-python` à côté d'`opencv-python`, la variante
    retenue le 2026-11-02) ou une installation masquée (`phonemizer-fork`, dont les fichiers ont
    été recouverts par ceux de `phonemizer`). Le socle n'est pas exclu : semé, il reste hors de tout
    `requires` (`librairies_de`).
    """
    sem, mapping = semees(), _distributions()
    out = []
    for dist, info in scan_imports().items():
        if dist == '__non_resolus__' or _normalise(dist) in sem:
            continue
        if all(any(_normalise(d) in sem for d in (mapping.get(m) or ())) for m in info['modules']):
            continue
        out.append(dist)
    return sorted(out)


def librairies_de(app_id: str) -> list[str]:
    """
    Librairies à citer dans le `requires` du manifeste de l'app `app_id`.

    RÈGLE (trois conditions, toutes nécessaires) :
      1. l'app IMPORTE réellement la distribution (fait mesuré, pas déclaré) ;
      2. la distribution est SEMÉE au corpus (décision humaine explicite) ;
      3. elle n'est PAS du SOCLE PLATEFORME (strate 1 : Django/celery/… — contrat d'exécution
         commun, jamais une dépendance de workload, même si quelqu'un la semait un jour).

    La condition 2 n'est pas une précaution de style : `ingest.valider()` traite une référence
    `requires` pendante comme une ERREUR de manifeste. Citer une librairie non semée rendrait
    donc invalides les 10 manifestes d'apps d'un coup.
    """
    sem = semees()
    return sorted(
        c['dist'] for c in candidats()
        if app_id in c['apps'] and _normalise(c['dist']) in sem
        and _normalise(c['dist']) not in SOCLE_PLATEFORME
    )


def librairies_des_backends(catalog_keys) -> list[str]:
    """
    Librairies que les MODÈLES d'une app exigent — par le lien modèle → backend → paquets.

    POURQUOI UNE 2ᵉ JAMBE (2026-09-07) : `librairies_de` mesure ce que le DOSSIER de l'app importe.
    Depuis que les backends vivent au substrat (`wama/common/backends/`), c'est `common` qui
    importe torch, diffusers ou soundfile — et les 8 manifestes d'apps à backends ont perdu leurs
    librairies au premier `manifest_export`. Or ce que l'app exige n'a pas changé : ses modèles
    tournent sur ces librairies. La dépendance passe donc par le lien DÉCLARÉ — le modèle porte
    son moteur, le backend résolu déclare ses paquets (`REQUIRED_PACKAGES`, noms d'import ;
    `PIP_PACKAGES`, noms de distribution) — et non par l'emplacement d'un fichier.

    Mêmes trois conditions que `librairies_de` : distribution INSTALLÉE (sinon on ne sait pas la
    nommer), SEMÉE au corpus, hors SOCLE. La résolution est CIBLÉE (un import par backend, à la
    demande) — jamais un balayage.
    """
    try:
        from wama.common.services.backend_inventory import resolvable_entries
        from wama.model_manager.models import AIModel
    except Exception:
        return []
    # Le vivier lu UNE fois pour toutes les clés : sans lui, chaque résolution relisait
    # l'inventaire — 48 fois pour les 48 modèles de l'anonymizer (mesuré le 2026-09-14).
    try:
        vivier = resolvable_entries()
    except Exception:
        vivier = None
    out = set()
    for row in AIModel.objects.filter(model_key__in=list(catalog_keys or ())):
        executor = model_executor(row, entries=vivier)
        if executor is None:
            continue
        # ① ce que le modèle exige par son EXÉCUTANT — la dérivation du manifeste de modèle,
        #    la même pour les deux (`model_libraries`) ;
        out.update(executor_libraries(executor))
        # ② pour un backend, ce que son MODULE importe réellement — même mesure AST que la 1ʳᵉ
        #    jambe, sur le bon fichier : `REQUIRED_PACKAGES` sert la disponibilité, pas
        #    l'exhaustivité (mesuré : l'audiocraft ne déclare que `audiocraft` et importe torch,
        #    soundfile, torchaudio). Pas pour un module `loaded_by` : une brique qui charge un
        #    modèle fait aussi autre chose (le banc importe ultralytics et transformers pour
        #    d'autres mesures que LPIPS) — son moteur déclaré dit ce que CE modèle exige.
        if isinstance(executor, type):
            source = getattr(sys.modules.get(executor.__module__), '__file__', None)
            if source:
                out.update(seeded_libraries(modules=_third_party(_modules_du_fichier(Path(source)))))
    return sorted(out)


def _third_party(modules) -> list[str]:
    """Les modules tiers d'un relevé d'imports (ni WAMA, ni la bibliothèque standard, ni privés)."""
    return [m for m in modules
            if m not in INTERNES and m not in sys.stdlib_module_names and not m.startswith('_')]


def _distribution_name(spec: str) -> str:
    """`pyannote.audio>=3.3.1` → `pyannote.audio` : le nom d'un spécificateur pip, sans extra,
    version ni marqueur — la lecture d'une ligne de `requirements*.txt` (`declarees`) comme d'un
    `PIP_PACKAGES` (`seeded_libraries`). Le `=` seul tolère une ligne de requirements mal écrite."""
    name = spec.split('[')[0]
    for sep in ('==', '>=', '<=', '~=', '!=', '>', '<', ';', '@', '='):
        name = name.split(sep)[0]
    return name.strip()


def seeded_libraries(distributions=(), modules=()) -> list[str]:
    """Clés du corpus `manifests/libraries/` que désignent des noms de DÉPENDANCE — le seul
    traducteur nom → librairie, que la jambe d'app et le manifeste de modèle partagent.

    Deux natures de nom, deux lectures, jamais confondues (la source d'erreur classique,
    en-tête de ce module) :
      • `distributions` — un nom ou un spécificateur pip (`PIP_PACKAGES`) : lu tel quel ;
      • `modules` — un nom d'IMPORT (`REQUIRED_PACKAGES`, un import mesuré) : traduit par les
        distributions INSTALLÉES qui le fournissent (`doctr` → `python-doctr`, `onnxruntime` →
        `onnxruntime-gpu` sur ce venv, `cv2` → `opencv-python`).
    Rendu sous la clé CANONIQUE du corpus : un `requires` cite le manifeste tel qu'il est semé
    (`pyannote-audio`), jamais la graphie d'un spécificateur (`pyannote.audio`) — une référence
    pendante invalide le manifeste entier (`ingest.valider`). Une distribution non semée ne se
    cite pas ; le SOCLE PLATEFORME jamais.
    """
    corpus = _base_dir() / 'manifests' / 'libraries'
    canon = {_normalise(p.stem): p.stem for p in corpus.glob('*.json')} if corpus.is_dir() else {}
    dists = {_distribution_name(d) for d in distributions or ()}
    if modules:
        mapping = _distributions()
        for module in modules:
            dists.update(mapping.get(module.split('.')[0]) or ())
    return sorted(canon[n] for n in {_normalise(d) for d in dists if d}
                  if n in canon and n not in SOCLE_PLATEFORME)


def engine_libraries(engine: str) -> list[str]:
    """Librairies semées que désigne un MOTEUR — « un moteur est une LIBRAIRIE » (registre
    `backends`), pour un modèle qu'aucun backend n'exécute (`loaded_by`).

    Dans l'ordre : le moteur se lit comme un nom d'IMPORT (`faster-whisper` → `faster_whisper`,
    `onnxruntime`, `doctr`) — c'est la distribution que le venv installe pour lui qui fait foi,
    pas une homonyme semée (`onnxruntime`, la version processeur, masque la version GPU) — puis
    comme un nom de distribution (`lpips`, `mediapipe`). Un moteur qui n'est pas une librairie
    par son nom (`torchscript` : `torch.jit.load`) se lit chez les backends qui le pilotent : les
    paquets qu'ils déclarent pour lui (`declared_engines`, inventaire statique). Vide si rien ne
    le nomme — le dire est l'affaire de la garde, jamais d'une supposition ici.
    """
    if not engine:
        return []
    found = (seeded_libraries(modules=[engine, engine.replace('-', '_')])
             or seeded_libraries(distributions=[engine]))
    if found:
        return found
    try:
        from wama.common.services.backend_inventory import declared_engines
        carrier = declared_engines().get(engine)
    except Exception:
        carrier = None
    return seeded_libraries(modules=getattr(carrier, 'packages', None) or ())


def model_executor(model, entries=None):
    """Ce qui EXÉCUTE `model` (ligne de catalogue, ou tout porteur de `composition`,
    `model_key`, `capabilities`) : la classe de backend que la porte commune résout
    (`backend_for_model`), ou, pour un modèle qu'une brique charge elle-même, son `runtime`
    déclaré (dict qui porte `loaded_by`). None : aucun exécutant connu."""
    runtime = ((getattr(model, 'composition', None) or {}).get('runtime') or {})
    if runtime.get('loaded_by'):
        return runtime
    try:
        from wama.common.backends.manager import backend_for_model
        return backend_for_model(model, entries)
    except Exception:
        return None


def executor_libraries(executor) -> list[str]:
    """Librairies semées qu'exige un exécutant de `model_executor`.

    Un BACKEND : les DEUX moitiés de son contrat — ce qu'il installe (`PIP_PACKAGES`, des noms
    de distribution) et ce qui doit s'importer pour qu'il soit disponible (`REQUIRED_PACKAGES`,
    des noms d'import). L'une seule ne suffit pas : Qwen3-ASR n'installe que `qwen-asr` (en
    `--no-deps`) et ne tourne qu'avec transformers, soundfile et librosa présents.
    Un module `loaded_by` : la librairie que nomme le moteur déclaré du modèle
    (`engine_libraries`)."""
    if executor is None:
        return []
    if isinstance(executor, dict):
        return engine_libraries(executor.get('engine') or '')
    return seeded_libraries(distributions=getattr(executor, 'PIP_PACKAGES', None) or (),
                            modules=getattr(executor, 'REQUIRED_PACKAGES', None) or ())


def model_libraries(model, entries=None) -> list[str]:
    """Librairies semées qu'exige UN modèle, par son exécutant déclaré — le `requires` de son
    manifeste (`builtin/model.py`) et la 1ʳᵉ moitié de la jambe backends d'une app."""
    return executor_libraries(model_executor(model, entries))
