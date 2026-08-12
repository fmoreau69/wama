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
"""

from __future__ import annotations

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

    install = body.get('install') or {}
    if not isinstance(install, dict):
        errs.append("install doit être un dict")
    elif not install.get('pip'):
        errs.append("install.pip manquant (spécificateur d'installation)")

    for cle in ('entry_points', 'constraints'):
        v = body.get(cle)
        if v is not None and not isinstance(v, dict):
            errs.append(f"{cle} doit être un dict")
    deps = body.get('dependencies')
    if deps is not None and not isinstance(deps, list):
        errs.append("dependencies doit être une liste")
    return errs


def extract_library(key: str) -> Optional[dict]:
    import importlib.metadata as im

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

    import re
    console = sorted(ep.name for ep in dist.entry_points if ep.group == 'console_scripts')
    # Nom de distribution = préfixe [nom] du spécificateur PEP 508 ; on écarte les extras.
    deps = sorted({m.group(0)
                   for d in (dist.requires or [])
                   if (';' not in d or 'extra' not in d.split(';', 1)[1])
                   for m in [re.match(r'[A-Za-z0-9._-]+', d.strip())] if m})

    body = {
        'identity': {
            'version': dist.version,
            'license': meta.get('License-Expression') or meta.get('License') or None,
            # `Author` est souvent vide au profit de `Author-email` (« Nom <a@b.c> ») dans les
            # métadonnées PyPI modernes : on prend le premier des deux qui est renseigné plutôt
            # que de conclure « pas d'auteur » sur le seul champ historique.
            'author': meta.get('Author') or meta.get('Author-email') or None,
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
)


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
