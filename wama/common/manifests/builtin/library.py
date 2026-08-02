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


register_kind(ManifestKind(
    kind='library',
    validate=validate_library_body,
    extract=extract_library,
    description="Brique logicielle externe (dépôt/licence/version/install/entry points). "
                "Extraite des métadonnées du paquet installé ; les contraintes fines "
                "relèvent du rôle wama-dev-ai (SPEC §7.4-4).",
))
