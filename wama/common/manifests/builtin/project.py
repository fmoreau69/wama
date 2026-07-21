"""
Kind `project` — EXTRAIT du modèle `Project` (couche projet cross-org, common.models).

`key` = `Project.code` (unique). Un projet TRAVERSE l'arbre org : org propriétaire (`owner_org`) + membres
EXPLICITES pouvant venir d'AUTRES orgs (partenaires). Le manifeste capte cette composition.
"""

from __future__ import annotations

from typing import Optional

from ..kinds import ManifestKind, register_kind

PROJECT_ROLES = {'lead', 'member', 'partner', 'viewer'}


def validate_project_body(body: dict) -> list[str]:
    errs: list[str] = []
    if not isinstance(body, dict):
        return ["body 'project' doit être un dict"]
    members = body.get('members', [])
    if members and not isinstance(members, list):
        errs.append("members doit être une liste")
    elif isinstance(members, list):
        for i, m in enumerate(members):
            if not isinstance(m, dict):
                errs.append(f"members[{i}] doit être un dict"); continue
            if not m.get('user'):
                errs.append(f"members[{i}] : 'user' manquant")
            r = m.get('role')
            if r and r not in PROJECT_ROLES:
                errs.append(f"members[{i}] : role '{r}' invalide ({', '.join(sorted(PROJECT_ROLES))})")
    return errs


def extract_project(key: str) -> Optional[dict]:
    from wama.common.models import Project

    p = Project.objects.filter(code=key).select_related('owner_org', 'lead').first()
    if p is None:
        return None

    members = []
    for mem in p.memberships.select_related('user', 'org').all():
        members.append({
            'user': mem.user.get_username() if mem.user_id else None,
            'role': mem.role,
            'org': mem.org.code if mem.org_id else None,
        })

    body = {
        'owner_org': p.owner_org.code if p.owner_org_id else None,
        'lead': p.lead.get_username() if p.lead_id else None,
        'members': members,
    }

    return {
        'manifest_kind': 'project',
        'key': p.code,
        'schema_version': '1.0',
        'name': p.name,
        'description': p.description or '',
        'world': 'transverse',
        'visibility': 'unit',
        'scope_org_unit': p.owner_org.code if p.owner_org_id else None,
        'projects': [p.code],
        'source': {'type': 'extract', 'ref': f'Project:{p.code}'},
        'body': body,
    }


register_kind(ManifestKind(
    kind='project',
    validate=validate_project_body,
    extract=extract_project,
    description="Projet cross-org (extrait de Project) : owner_org + lead + membres explicites (rôle + org "
                "d'origine, potentiellement partenaire d'un autre établissement).",
))
