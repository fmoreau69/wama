"""
À QUI EST un élément — la traduction entre l'enveloppe d'un manifeste et la ligne d'un registre,
dans les deux sens (`ROADMAP §29`, étape 2).

L'enveloppe dit `owner` (un nom de compte, `None` = système), `visibility` et les deux portées
en CODES : un manifeste voyage, une clé étrangère ne voyage pas (`PROFILES_PERMISSIONS §8.6`).
La ligne d'un registre porté (`ScopedVisibility`) dit les mêmes choses en clés étrangères.

Le kind `function` faisait cette traduction lui-même, dans son `extract` et son `write_back`, et
il était le seul à la faire. Elle vit ici pour que chaque kind qui portera la provenance (modèle,
librairie, pipeline, jumelle) l'emprunte au lieu de la réécrire.

SYSTÈME = sans propriétaire. Un élément système public est le commun ; un élément système privé
est un brouillon du projet (`manifests/app_drafts/`). Un élément qui a un propriétaire reste à lui
tant qu'un admin ne l'a pas promu (`ingest.promote`), même partagé à tous. Et seul un élément
système entre au corpus versionné, publié avec le dépôt (`manifest_export`).
"""
from __future__ import annotations


def is_system(manifest: dict) -> bool:
    """Le manifeste décrit-il un élément SYSTÈME (aucun propriétaire) ?"""
    return not (manifest or {}).get('owner')


def envelope_of(row, owner_field: str = 'owner') -> dict:
    """Les champs d'enveloppe d'une ligne `ScopedVisibility` : propriétaire, portée, codes.

    `qualified_code`, pas `code` : le code nu n'est unique que dans son établissement, et c'est
    au moment où il sort de WAMA qu'il doit porter son autorité."""
    owner = getattr(row, owner_field) if getattr(row, f'{owner_field}_id', None) else None
    unit = row.scope_org_unit if getattr(row, 'scope_org_unit_id', None) else None
    project = row.scope_project if getattr(row, 'scope_project_id', None) else None
    return {
        'owner': owner.get_username() if owner is not None else None,
        'visibility': row.visibility,
        'scope_org_unit': unit.qualified_code if unit is not None else None,
        'scope_project': project.code if project is not None else None,
    }


def promote_row(manifest_kind: str, key: str) -> int:
    """La ligne du registre passe au SYSTÈME avec son manifeste (`ingest.promote`) : plus de
    propriétaire, publique, sans portée. Rend le nombre de lignes promues.

    La ligne se trouve par le REGISTRE de ce kind (`manifest_kind`) : `owner_model` la nomme,
    `owner_key` nomme son champ d'identifiant. Un kind sans registre porté, ou dont le registre ne
    déclare pas `owner_key`, n'a rien à promouvoir ici. Une ligne dont le propriétaire est
    OBLIGATOIRE non plus : elle ne peut pas devenir système, c'est le cas d'une fonction
    d'utilisateur (`UserFunction.owner`), dont la promotion la fait entrer au catalogue CODE —
    un geste de développement (`ROADMAP §29` étapes 2 et 4)."""
    from wama.common.models import ScopedVisibility
    from wama.common.registries import carried_rows
    rows = carried_rows(key, manifest_kind=manifest_kind)
    if rows is None or not rows.model._meta.get_field('owner').null:
        return 0
    return rows.update(owner=None, visibility=ScopedVisibility.VIS_PUBLIC, scope_org_unit=None,
                       scope_project=None)


def promote_owned_row(row, *, by=None):
    """UNE ligne portée, sans manifeste, passe au SYSTÈME — la règle d'`ingest.promote` : plus de
    propriétaire, publique, sans portée ; l'auteur reste nommé (`source.proposed_by`, jamais
    écrasé) et le valideur aussi (`source.promoted_by`). Le geste est celui d'un admin, gardé par
    la vue. Premier appelant : le thème d'une charte (`common.UserTheme`, 2026-10-20) ; un
    propriétaire OBLIGATOIRE refuse (`ValueError`), comme `promote_row`."""
    from wama.common.models import ScopedVisibility
    if not type(row)._meta.get_field('owner').null:
        raise ValueError(f"{type(row).__name__} : le propriétaire est obligatoire, pas de système")
    fields = {'owner': None, 'visibility': ScopedVisibility.VIS_PUBLIC, 'scope_org_unit': None,
              'scope_project': None}
    if hasattr(row, 'source'):
        source = dict(row.source or {})
        if row.owner_id and not source.get('proposed_by'):
            source['proposed_by'] = row.owner.get_username()
        if by is not None:
            source['promoted_by'] = by.get_username()
        fields['source'] = source
    type(row).objects.filter(pk=row.pk).update(**fields)
    for name, value in fields.items():
        setattr(row, name, value)
    return row


def row_fields(manifest: dict) -> dict:
    """L'inverse : ce que la ligne d'un registre porté reçoit de l'enveloppe.

    Rend `owner` (compte ou `None`), `visibility`, `scope_org_unit` et `scope_project` (lignes
    ou `None`), plus `unresolved` : le nom ou les codes que cette instance ne connaît pas. Un
    nom inconnu ne devient jamais « système » sans le dire : c'est à l'appelant de refuser."""
    from django.contrib.auth import get_user_model

    from wama.common.models import OrgUnit, Project

    manifest = manifest or {}
    owner_name = manifest.get('owner') or ''
    unit_code = manifest.get('scope_org_unit') or ''
    project_code = manifest.get('scope_project') or ''
    owner = get_user_model().objects.filter(username=owner_name).first() if owner_name else None
    # Les DEUX formes du code d'unité (qualifiée « autorité:code » et nue) : les manifestes
    # écrits avant le 27/08 portent le code nu, et les casser irait contre le but.
    unit = OrgUnit.resolve_qualified(unit_code) if unit_code else None
    project = Project.objects.filter(code=project_code).first() if project_code else None
    unresolved = {name: value for name, value, found in (
        ('owner', owner_name, owner), ('scope_org_unit', unit_code, unit),
        ('scope_project', project_code, project)) if value and found is None}
    return {'owner': owner, 'visibility': manifest.get('visibility') or 'private',
            'scope_org_unit': unit, 'scope_project': project, 'unresolved': unresolved}
