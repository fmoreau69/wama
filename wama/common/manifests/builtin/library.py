"""
Kind `library` — brique logicielle externe (dépôt, licence, install), SPEC §7.1/§7.4-3.

Frontière (§7.1) : le manifeste `library` possède le dépôt, la licence, la version,
l'install, les points d'entrée et les contraintes techniques — JAMAIS l'usage qu'une
app en fait (ça, c'est le `requires` de l'app).

Extraction MÉCANIQUE depuis les métadonnées du paquet INSTALLÉ (`importlib.metadata`) :
ce qui n'est pas extractible (contraintes GPU/OS, capacités techniques fines) reste
absent plutôt qu'inventé — c'est le rôle wama-dev-ai « projet GitHub → manifeste
library » (§7.4-4) de les remplir, ce corpus servant d'exemples.

`key` = nom de distribution (PyPI), p.ex. 'faster-whisper'.

Une librairie VENDORISÉE qui importe le code d'une AUTRE librairie que pip ne sait pas installer
la déclare dans son `requires` d'enveloppe (2026-11-13) — `body.dependencies` reste la liste des
noms PyPI, dans le venv ; `requires` désigne un manifeste qui doit exister et s'installer d'abord.
"""

from __future__ import annotations

import functools
import re
from typing import Optional

from ..kinds import ManifestKind, register_kind


def validate_library_body(body: dict) -> list[str]:
    errs: list[str] = []
    if not isinstance(body, dict):
        return ["body 'library' doit être un dict"]

    ident = body.get('identity') or {}
    if not isinstance(ident, dict):
        errs.append("identity doit être un dict")
    elif not ident.get('version'):
        errs.append("identity.version manquant (une library sans version n'est pas installable)")
    elif ident.get('license') and (len(str(ident['license'])) > LICENCE_MAX
                                   or '\n' in str(ident['license'])):
        # Un manifeste porte un IDENTIFIANT de licence, jamais son texte : le registre le
        # projette dans 128 caractères, et un texte y faisait échouer la projection (07/09).
        errs.append(f"identity.license est un TEXTE ({len(str(ident['license']))} car.), "
                    f"pas un identifiant (≤ {LICENCE_MAX}, sans retour à la ligne)")
    elif ident.get('author') and len(str(ident['author'])) > AUTHOR_MAX:
        # Même raison que la licence (2026-11-06) : le registre projette l'auteur dans 200
        # caractères, et la liste d'adresses de `pydantic` (513) y faisait échouer la projection.
        errs.append(f"identity.author dépasse le registre ({len(str(ident['author']))} car., "
                    f"≤ {AUTHOR_MAX}) — l'extraction le borne (`author_name`)")

    install = body.get('install') or {}
    if not isinstance(install, dict):
        errs.append("install doit être un dict")
    elif install.get('pip') and install.get('vendor'):
        errs.append("install.pip ET install.vendor : une librairie s'installe par pip OU se "
                    "vendorise, jamais les deux")
    elif install.get('vendor'):
        err = vendor_spec_error(install['vendor'])
        if err:
            errs.append(f"install.vendor : {err}")
    elif not install.get('pip'):
        errs.append("install.pip manquant (spécificateur d'installation) — ou install.vendor "
                    "pour une librairie que pip ne sait pas installer")

    for cle in ('entry_points', 'constraints'):
        v = body.get(cle)
        if v is not None and not isinstance(v, dict):
            errs.append(f"{cle} doit être un dict")
    # `constraints.pip` (2026-09-15) : versions du venv que l'installation ne doit pas déplacer,
    # passées à pip par `-c`. Le verrou « nom==version » s'applique à l'installation
    # (`model_installer.pip_constraint_errors`) ; ici on ne garde que la FORME.
    pins = (body.get('constraints') or {}).get('pip') if isinstance(body.get('constraints'), dict) else None
    if pins is not None and (not isinstance(pins, list)
                             or not all(isinstance(p, str) for p in pins)):
        errs.append("constraints.pip doit être une liste de spécificateurs « nom==version »")
    # `constraints.no_deps` (2026-10-01) : installer SANS les dépendances — le pendant du
    # `PIP_NO_DEPS` des backends, pour une librairie dont la résolution déplacerait le venv
    # (accelerate 1.12 : pip rétrogradait nvidia-nccl-cu12 pour satisfaire le pin de torch).
    no_deps = (body.get('constraints') or {}).get('no_deps') if isinstance(body.get('constraints'), dict) else None
    if no_deps is not None and not isinstance(no_deps, bool):
        errs.append("constraints.no_deps doit être un booléen")
    deps = body.get('dependencies')
    if deps is not None and not isinstance(deps, list):
        errs.append("dependencies doit être une liste")
    return errs


#: Longueur du champ `Library.license` (un IDENTIFIANT — 'MIT', 'Apache-2.0' — jamais un texte).
LICENCE_MAX = 128

#: Longueur du champ `Library.author`.
AUTHOR_MAX = 200


# ── Route VENDOR (ROADMAP D-a, décision de Fabien le 2026-09-30) ─────────────────────────
# La norme reste pip. Mais certaines librairies ne sont PAS des paquets (MuseTalk, CodeFormer,
# TripoSR : dépôts sans `setup.py`, lancés par chemin en sous-processus) : pip n'a rien à
# installer, et elles vivaient dans des scripts shell qui clonaient `main` sans épingle (`git
# pull`) et réappliquaient leurs correctifs à la main — ou jamais (le correctif MuseTalk du
# 07/09 n'était réappliqué par rien). Une librairie vendorisée se déclare donc comme les autres,
# avec les MÊMES verrous transposés : pas d'URL libre (le dépôt se dit « owner/name », l'adresse
# se dérive de la source déclarée `github`), un COMMIT exact (jamais une branche ni un tag, qui
# bougent), un correctif versionné dans `patches/`, et la même allowlist humaine.
_VENDOR_REPO_RE = re.compile(r'^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$')
_VENDOR_COMMIT_RE = re.compile(r'^[0-9a-f]{40}$')
_VENDOR_ENGINE_RE = re.compile(r'^[a-z][a-z0-9_]*$')
_VENDOR_PATCH_RE = re.compile(r'^patches/[A-Za-z0-9._-]+\.(diff|patch)$')
_VENDOR_IGNORE_RE = re.compile(r'^[A-Za-z0-9_.-]+(/[A-Za-z0-9_.-]+)*/?$')
#: `import_root` (2026-11-13) : le dossier du clone d'où ses paquets s'IMPORTENT (`src` pour un dépôt
#: en disposition src/), vide = la racine. Lu quand une AUTRE librairie vendorisée la requiert
#: (`required_vendor_roots`) : son code fait `import dacvae`, le clone doit être sur le chemin.
VENDOR_FIELDS = ('repo', 'commit', 'engine', 'patch', 'ignore', 'import_root')


def vendor_spec_error(vendor) -> Optional[str]:
    """Motif de refus d'une déclaration `install.vendor`, ou None — pendant de `pip_spec_error`.

    Pure (aucune I/O) : la validation d'un manifeste et l'installeur appliquent le même verrou.
    """
    if not isinstance(vendor, dict):
        return "doit être un dict {repo, commit, engine, patch?, ignore?}"
    unknown = sorted(set(vendor) - set(VENDOR_FIELDS))
    if unknown:
        return f"champ(s) inconnu(s) : {', '.join(unknown)}"
    repo, commit = str(vendor.get('repo') or ''), str(vendor.get('commit') or '')
    if not _VENDOR_REPO_RE.match(repo) or '..' in repo:
        return (f"repo refusé : {repo!r} — forme exigée « owner/name » (GitHub, sans URL : "
                "l'adresse se dérive de la source déclarée `github`)")
    if not _VENDOR_COMMIT_RE.match(commit):
        return (f"commit refusé : {commit!r} — un SHA complet de 40 caractères hexadécimaux "
                "(jamais une branche ni un tag, qui bougent)")
    if not _VENDOR_ENGINE_RE.match(str(vendor.get('engine') or '')):
        return ("engine manquant ou invalide — c'est le nom du dossier sous "
                "`settings.BACKEND_VENDOR_DIR`, égal au `ENGINE` du backend qui l'exécute")
    patch = vendor.get('patch')
    if patch and (not _VENDOR_PATCH_RE.match(str(patch)) or '..' in str(patch)):
        return f"patch refusé : {patch!r} — un fichier .diff/.patch directement sous `patches/`"
    ignore = vendor.get('ignore')
    if ignore is not None:
        if not isinstance(ignore, list):
            return "ignore doit être une liste de chemins relatifs au clone"
        for p in ignore:
            if not isinstance(p, str) or not _VENDOR_IGNORE_RE.match(p) or '..' in p:
                return f"ignore refusé : {p!r} — chemin relatif au clone, sans « .. »"
    root = vendor.get('import_root')
    if root and (not isinstance(root, str) or not _VENDOR_IGNORE_RE.match(root) or '..' in root):
        return f"import_root refusé : {root!r} — chemin relatif au clone, sans « .. »"
    return None


# ── Librairies REQUISES par une librairie (2026-11-13, SAM Audio) ───────────────────────────
# Un moteur vendorisé peut importer le code d'AUTRES dépôts que pip ne sait pas installer (SAM
# Audio : `dacvae`, `perception_models`… tirés par `git+`). Chacun est sa propre librairie
# vendorisée (un dépôt, un commit) ; le lien se DÉCLARE par le `requires` de l'enveloppe — le
# champ commun à tous les kinds (`envelope.py`, `resolve_requires`), qu'aucune librairie ne lisait.
# L'installation pose les requises d'abord (`vendor_installer.install_vendor`) et l'import met
# leurs clones sur le chemin (`BaseModelBackend.import_vendored`).

def required_library_keys(key: str) -> list:
    """Les clés des librairies que le manifeste AUTORÉ de `key` requiert (`requires`, kind
    `library`), dans l'ordre déclaré ; [] sans manifeste ni `requires`."""
    manifest = authored_vendor_manifest(key) or {}
    return [ref['key'] for ref in manifest.get('requires') or []
            if isinstance(ref, dict) and ref.get('kind') == 'library' and ref.get('key')]


@functools.lru_cache(maxsize=1)
def _corpus_vendor_engines() -> dict:
    """`{moteur: clé}` des librairies vendorisées du corpus — lu UNE fois par processus (la
    disponibilité d'un backend se demande à chaque rendu de page) ; l'installation vendor l'oublie
    (`forget_vendor_engines`)."""
    import json
    from pathlib import Path

    from django.conf import settings
    engines = {}
    for path in sorted((Path(settings.BASE_DIR) / 'manifests' / 'libraries').glob('*.json')):
        try:
            manifest = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            continue
        vendor = ((manifest.get('body') or {}).get('install') or {}).get('vendor') or {}
        if vendor.get('engine') and manifest.get('key'):
            engines.setdefault(vendor['engine'], manifest['key'])
    return engines


def forget_vendor_engines() -> None:
    """Oublie la lecture du corpus (après une installation ou une validation vendor)."""
    _corpus_vendor_engines.cache_clear()


def vendor_library_key(engine: str) -> str:
    """La clé de la librairie vendorisée dont le moteur est `engine` — '' sans elle. Lue au corpus
    (`install.vendor.engine`), puis au registre pour une librairie validée pas encore exportée."""
    key = _corpus_vendor_engines().get(engine)
    if key:
        return key
    from wama.common.models import Library
    return Library.objects.filter(vendor__engine=engine).values_list('key', flat=True).first() or ''


def required_vendor_roots(engine: str) -> list:
    """`[(moteur, chemin d'import)]` des librairies VENDORISÉES que le moteur `engine` requiert,
    transitivement, les plus profondes d'abord — chacune sous la racine déclarée
    (`BACKEND_VENDOR_DIR/<moteur>/<import_root>`). Une requise PyPI n'y figure pas : elle est dans
    le venv."""
    from pathlib import Path

    from django.conf import settings
    found, seen = [], {engine}

    def walk(key):
        for required in required_library_keys(key):
            manifest = authored_vendor_manifest(required) or {}
            vendor = ((manifest.get('body') or {}).get('install') or {}).get('vendor') or {}
            dep = vendor.get('engine') or ''
            if not dep or dep in seen:
                continue
            seen.add(dep)
            walk(required)
            root = Path(settings.BACKEND_VENDOR_DIR) / dep
            found.append((dep, root / vendor['import_root'] if vendor.get('import_root') else root))

    key = vendor_library_key(engine)
    if key:
        walk(key)
    return found


def licence_courte(meta) -> Optional[str]:
    """Identifiant de licence depuis des métadonnées de distribution — ou None, jamais un TEXTE.

    ⚠ Défaut MESURÉ le 2026-09-07, au premier semis mécanique de 12 moteurs : `kokoro`,
    `python-doctr`, `sam3` et `suno-bark` mettent le texte INTÉGRAL de leur licence (1 à 11 Ko)
    dans le champ `License` des métadonnées, et l'extracteur le recopiait tel quel dans
    `identity.license` — que le registre projette dans un `CharField(128)`. La projection
    s'arrêtait en `DataError` au 6ᵉ manifeste. Trois d'entre eux portent pourtant un
    classifieur propre (« Apache Software License », « MIT License »).

    Ordre, du plus DÉCLARÉ au plus déduit :
      1. `License-Expression` (PEP 639) — l'identifiant SPDX, quand le paquet le fournit ;
      2. `License` s'il est COURT (≤ LICENCE_MAX) : c'est alors un identifiant, pas un texte ;
      3. le classifieur `License :: …`, débarrassé de ses préfixes — le libellé Trove tel quel
         (« MIT License »), sans table de traduction vers SPDX : on ne devine pas ;
      4. sinon None — une licence inconnue se dit, elle ne s'invente pas (`suno-bark` : texte
         seul, aucun classifieur ; `pyannote-audio`, `vibevoice`, `kokoro-onnx` : rien du tout,
         leur licence au registre est un enrichissement HUMAIN que l'extraction ne remplace pas).
    """
    expr = (meta.get('License-Expression') or '').strip()
    if expr:
        return expr[:LICENCE_MAX]
    brut = (meta.get('License') or '').strip()
    if brut and len(brut) <= LICENCE_MAX and '\n' not in brut:
        return brut
    for c in (meta.get_all('Classifier') or []):
        if c.startswith('License ::'):
            return c.split('::')[-1].strip()[:LICENCE_MAX]
    return None


def author_name(meta) -> Optional[str]:
    """L'auteur déclaré d'une distribution, borné au registre (`AUTHOR_MAX`) — ou None.

    ⚠ Défaut MESURÉ le 2026-11-06, au semis des librairies importées par le code WAMA : `pydantic`
    ne remplit que `Author-email`, une liste de douze « Nom <adresse> » (513 caractères), que la
    projection mettait dans un `CharField(200)` — `DataError`, comme la licence-texte du 07/09.

    `Author` d'abord, sinon `Author-email`, TELS QUE DÉCLARÉS quand ils tiennent dans le registre
    (les manifestes déjà semés ne bougent pas). Au-delà seulement : les NOMS sans leurs adresses
    (une attribution de licence cite un nom ; l'adresse quand aucun nom n'est donné), puis les
    premiers noms ENTIERS, la coupure marquée « … » — rien d'inventé, aucun nom coupé.
    """
    from email.utils import getaddresses

    declared = (meta.get('Author') or meta.get('Author-email') or '').strip()
    if not declared:
        return None
    if len(declared) <= AUTHOR_MAX:
        return declared
    names = [name.strip() or addr.strip() for name, addr in getaddresses([declared])]
    declared = ', '.join(n for n in names if n) or declared
    if len(declared) <= AUTHOR_MAX:
        return declared
    kept = ''
    for part in declared.split(', '):
        candidate = f'{kept}, {part}' if kept else part
        if len(candidate) + 2 > AUTHOR_MAX:
            break
        kept = candidate
    return f'{kept} …' if kept else declared[:AUTHOR_MAX - 2] + ' …'


def authored_vendor_manifest(key: str) -> Optional[dict]:
    """Le manifeste AUTORÉ d'une librairie vendorisée, lu au corpus — ou None.

    Une librairie vendorisée n'est pas un paquet : `importlib.metadata` ne la connaît pas, donc
    rien à extraire. Comme un `dataset`, son manifeste EST l'origine. Sans ce retour,
    `manifest_export` la déclarait « extraction impossible » et ne la VALIDAIT jamais — le même
    angle mort que celui des manifestes autorés du 2026-09-07.

    Un manifeste PyPI déclaré AUTORÉ (`source.type`, 2026-10-16) fait foi de la même façon : il
    porte ce que les métadonnées du paquet ne disent pas — `constraints.no_deps` et la raison de
    l'écart (muscriptor, beat-this, rotary-embedding-torch). Ré-extrait du paquet installé, il
    perdait ces contraintes : la réinstallation suivante aurait tiré les dépendances que la
    contrainte écartait (starlette, épinglé pour le serveur MCP).
    """
    import json
    from pathlib import Path

    from django.conf import settings

    path = Path(settings.BASE_DIR) / 'manifests' / 'libraries' / f'{key}.json'
    try:
        manifest = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return _vendor_manifest_from_registry(key)
    install = ((manifest.get('body') or {}).get('install') or {})
    authored = (manifest.get('source') or {}).get('type') == 'authored'
    return manifest if install.get('vendor') or authored else None


def _vendor_manifest_from_registry(key: str) -> Optional[dict]:
    """Le manifeste d'une librairie vendorisée PAS ENCORE au corpus, relu au registre `Library`.

    C'est l'inverse exact de `write_back_library` : le geste « Valider » d'une proposition
    projette au registre PUIS exporte au corpus (`proposals.apply` → `manifest_export`). Sans ce
    retour, l'export d'une première librairie vendorisée ne trouvait rien — ni corpus, ni paquet
    installé — et le geste annonçait un corpus écrit qui ne l'était pas (2026-10-01, YuE).
    """
    from wama.common.models import Library, Manifest
    lib = Library.objects.filter(key=key).exclude(vendor={}).first()
    if lib is None or not lib.vendor:
        return None
    # Le `requires` n'est pas une facette du registre (ce que la librairie EST) : il vient du
    # magasin, où la proposition validée l'a déposé (2026-11-13 — sinon l'export le perdait).
    stored = Manifest.objects.filter(manifest_kind='library', key=key).first()
    requires = list(getattr(stored, 'requires', None) or [])
    return {
        'manifest_kind': 'library', 'key': lib.key, 'schema_version': '1.0',
        'name': lib.name or lib.key, 'description': (lib.summary or '')[:500],
        'world': 'transverse', 'visibility': 'public', 'projects': [],
        **({'requires': requires} if requires else {}),
        'source': {'type': 'authored',
                   'ref': f"github:{lib.vendor.get('repo')}@{lib.vendor.get('commit')}"},
        'body': {
            'identity': {'version': lib.version, 'license': lib.license or None,
                         'author': lib.author or None, 'summary': lib.summary or None,
                         'repository': lib.repository or None},
            'install': {'vendor': dict(lib.vendor)},
            'entry_points': lib.entry_points or {},
            'dependencies': list(lib.dependencies or []),
            'constraints': lib.constraints or {},
        },
    }


def extract_library(key: str) -> Optional[dict]:
    import importlib.metadata as im

    # Vendorisée ou AUTORÉE : le manifeste du corpus fait foi, AVANT toute recherche de
    # distribution — un paquet PyPI homonyme ne doit jamais se substituer au dépôt épinglé, ni ses
    # métadonnées effacer les contraintes déclarées.
    authored = authored_vendor_manifest(key)
    if authored is not None:
        return authored

    try:
        dist = im.distribution(key)
    except im.PackageNotFoundError:
        return None

    meta = dist.metadata
    urls = {}
    for ligne in (meta.get_all('Project-URL') or []):
        nom, _, url = ligne.partition(',')
        urls[nom.strip().lower()] = url.strip()
    depot = (urls.get('source') or urls.get('repository') or urls.get('homepage')
             or meta.get('Home-page') or None)

    console = sorted(ep.name for ep in dist.entry_points if ep.group == 'console_scripts')
    deps = dependency_names(dist.requires)

    body = {
        'identity': {
            'version': dist.version,
            'license': licence_courte(meta),
            # `Author` est souvent vide au profit de `Author-email` (« Nom <a@b.c> ») dans les
            # métadonnées PyPI modernes : on prend le premier des deux qui est renseigné plutôt
            # que de conclure « pas d'auteur » sur le seul champ historique — borné au registre,
            # les noms sans leurs adresses (`author_name`, 2026-11-06).
            'author': author_name(meta),
            'summary': meta.get('Summary') or None,
            'repository': depot,
        },
        'install': {
            'pip': f"{dist.name}=={dist.version}",
            'requires_python': meta.get('Requires-Python') or None,
        },
        'entry_points': {'console_scripts': console} if console else {},
        'dependencies': deps,
        # Non extractible mécaniquement (GPU/OS/points d'entrée sémantiques) : rempli par
        # le rôle wama-dev-ai (§7.4-4), jamais inventé ici.
        'constraints': {},
    }

    return {
        'manifest_kind': 'library',
        'key': dist.name,
        'schema_version': '1.0',
        'name': dist.name,
        'description': (meta.get('Summary') or '')[:500],
        'world': 'transverse',          # une brique logicielle est un asset transverse
        'visibility': 'public',
        'projects': [],
        'source': {'type': 'extract', 'ref': f'importlib.metadata:{dist.name}=={dist.version}'},
        'body': body,
    }


# ── PROJECTION (write-back) ──────────────────────────────────────────────────────
# `library` est le kind PILOTE du manifeste-first (ROADMAP §16.7) : contrairement aux modèles
# (`AIModel` préexistait aux manifestes), il n'a AUCUN registre historique à réconcilier — son
# registre `common.models.Library` NAÎT de cette projection. Même contrat que `write_back_app` :
# `apply=False` = DRY-RUN qui retourne le plan ; `apply=True` écrit, idempotent et transactionnel.
#
# Ce que la projection n'écrit PAS, volontairement :
#   • `is_allowed` — l'allowlist est le verrou n°2 transposé d'Hermes. Si un manifeste ingéré
#     pouvait la positionner, il s'auto-autoriserait à installer et le verrou ne vaudrait rien.
#   • `is_installed` / `installed_version` — état runtime de CET hôte ; un manifeste est portable.

_CHAMPS_PROJETES = (
    ('name',            lambda m, b: m.get('name') or m.get('key') or ''),
    ('summary',         lambda m, b: (b.get('identity') or {}).get('summary') or m.get('description') or ''),
    ('version',         lambda m, b: (b.get('identity') or {}).get('version') or ''),
    ('license',         lambda m, b: (b.get('identity') or {}).get('license') or ''),
    ('author',          lambda m, b: (b.get('identity') or {}).get('author') or ''),
    ('repository',      lambda m, b: (b.get('identity') or {}).get('repository') or ''),
    ('pip_spec',        lambda m, b: (b.get('install') or {}).get('pip') or ''),
    ('requires_python', lambda m, b: (b.get('install') or {}).get('requires_python') or ''),
    ('entry_points',    lambda m, b: b.get('entry_points') or {}),
    ('dependencies',    lambda m, b: b.get('dependencies') or []),
    ('constraints',     lambda m, b: b.get('constraints') or {}),
    ('vendor',          lambda m, b: (b.get('install') or {}).get('vendor') or {}),
)


def dependency_names(requirements) -> list:
    """Les dépendances d'une distribution — noms triés, depuis ses exigences PEP 508 (`Requires-Dist`
    du paquet installé, `requires_dist` de PyPI). Le nom est le préfixe du spécificateur ; une
    exigence d'EXTRA (`; extra == "gui"`) n'est pas une dépendance. Une règle pour les deux
    lectures (`extract_library`, et le rôle `librarian` sur un paquet publié, 2026-11-06)."""
    return sorted({m.group(0)
                   for d in (requirements or [])
                   if (';' not in d or 'extra' not in d.split(';', 1)[1])
                   for m in [re.match(r'[A-Za-z0-9._-]+', d.strip())] if m})


def write_back_library(manifest: dict, *, apply: bool = False) -> dict:
    """Projette un manifeste `library` vers le registre `Library`. Retourne le plan (dry-run)
    ou le résultat appliqué. Idempotent : re-projeter un manifeste inchangé ne change rien."""
    from django.db import transaction
    from wama.common.models import Library

    key = manifest.get('key') or ''
    if not key:
        return {'library': None, 'error': "manifeste sans `key`"}
    body = manifest.get('body') or {}

    voulu = {champ: calc(manifest, body) for champ, calc in _CHAMPS_PROJETES}
    existant = Library.objects.filter(key=key).first()
    actuel = {champ: getattr(existant, champ) for champ, _ in _CHAMPS_PROJETES} if existant else None
    deltas = {c: {'de': (actuel or {}).get(c), 'vers': v}
              for c, v in voulu.items() if actuel is None or actuel.get(c) != v}

    if not apply:
        return {'library': key, 'created': existant is None,
                'would_change': sorted(deltas), 'target': voulu,
                'preserved': ['is_allowed', 'is_installed', 'installed_version']}

    with transaction.atomic():
        obj, cree = Library.objects.update_or_create(key=key, defaults=voulu)
    return {'library': key, 'created': cree, 'changed': sorted(deltas),
            'preserved': {'is_allowed': obj.is_allowed, 'is_installed': obj.is_installed}}


def un_write_back_library(manifest: dict, *, apply: bool = False) -> dict:
    """Retire l'entrée de registre créée par la projection (réversibilité, SPEC §2.1).
    Ne touche à rien si la librairie est INSTALLÉE : on ne rend pas orphelin un paquet présent."""
    from wama.common.models import Library

    key = manifest.get('key') or ''
    obj = Library.objects.filter(key=key).first()
    if obj is None:
        return {'library': key, 'removed': False, 'reason': 'absent du registre'}
    if obj.is_installed:
        return {'library': key, 'removed': False,
                'reason': 'librairie installée — retrait du registre refusé'}
    if not apply:
        return {'library': key, 'would_remove': True}
    obj.delete()
    return {'library': key, 'removed': True}


register_kind(ManifestKind(
    kind='library',
    validate=validate_library_body,
    extract=extract_library,
    write_back=write_back_library,
    un_write_back=un_write_back_library,
    description="Brique logicielle externe (dépôt/licence/version/install/entry points). "
                "Extraite des métadonnées du paquet installé ; les contraintes fines "
                "relèvent du rôle wama-dev-ai (SPEC §7.4-4). PROJECTION → registre `Library` "
                "(hors allowlist `is_allowed` et hors état runtime, volontairement).",
))
