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
    propriétaire OBLIGATOIRE refuse (`ValueError`), comme `promote_row`.

    `source` n'est une TRACE que si c'est un champ JSON : celui d'`AIModel` dit d'où vient le
    modèle (« huggingface »), il ne se touche pas."""
    from django.db.models import JSONField

    from wama.common.models import ScopedVisibility
    meta = type(row)._meta
    if not meta.get_field('owner').null:
        raise ValueError(f"{type(row).__name__} : le propriétaire est obligatoire, pas de système")
    fields = {'owner': None, 'visibility': ScopedVisibility.VIS_PUBLIC, 'scope_org_unit': None,
              'scope_project': None}
    if any(f.name == 'source' and isinstance(f, JSONField) for f in meta.fields):
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


def promote_element(user, row):
    """« Rendre système » un élément d'auteur, quelle que soit sa famille (`ROADMAP §29`) : un
    administrateur seul (décision b), une ligne qui a un auteur. Sa famille se lit à son registre
    porté : si elle a un kind de MANIFESTE (un modèle), le manifeste du magasin est promu avec la
    ligne (`ingest.promote`), sinon la ligne seule (`promote_owned_row`) ; puis le corpus suit le
    registre (seul le système y entre, `corpus.follow`). La demande en attente est accordée et son
    auteur prévenu (`access_requests.close_promotion`). Lève `PermissionError` ou `ValueError`."""
    import logging

    from wama.common.services.access_requests import close_promotion, promotion_family
    if not _is_admin(user):
        raise PermissionError("Rendre un élément système est réservé aux administrateurs.")
    if row.owner_id is None:
        raise ValueError("Cet élément est déjà système.")
    registry = promotion_family(row)
    if registry is None:
        raise ValueError("Cet élément ne devient pas système par une promotion.")
    key = getattr(row, registry.owner_key, None) if registry.owner_key else None
    manifest = None
    if registry.manifest_kind and key:
        from wama.common.models import Manifest
        manifest = Manifest.objects.filter(manifest_kind=registry.manifest_kind, key=key).first()
    if manifest is not None:
        from .ingest import promote
        promote(manifest, by=user)
        row.refresh_from_db()
    if row.owner_id is not None:            # pas de manifeste, ou une ligne qu'il ne portait pas
        promote_owned_row(row, by=user)
    if registry.manifest_kind and key:
        try:
            from .corpus import follow
            follow(key, kind=registry.manifest_kind)
        except Exception as exc:             # le corpus est un miroir : il se rattrape à l'export
            logging.getLogger(__name__).warning('[promotion] corpus de %s non suivi : %s', key, exc)
    close_promotion(row, user)
    return row


def provenance_of(row, user) -> dict:
    """Ce qu'une ligne portée (`owner` vide = système) dit d'elle à `user`, comme partout dans
    WAMA — « Système », « à moi », « partagé par X » —, sa portée (`sharing.scope_value`,
    `scope_label`) et les gestes que `user` peut y faire : la partager (son auteur), la retirer
    (son auteur ou un administrateur), la rendre système (un administrateur, si elle a un auteur),
    DEMANDER sa promotion (son auteur, une fois) et VOIR la demande en attente (`ObjectGrant` de
    niveau `system`, `access_requests.request_promotion` : la page où un admin la tranche).
    Née au Profil pour les thèmes de charte (`themes.charter_choices`), sortie ici à la
    revérification du 2026-10-20, quand les skills de prompt la recopiaient."""
    from wama.common.services.access_requests import (pending_promotion, promotion_family,
                                                      request_page_url)
    from wama.common.services.sharing import scope_label, scope_value
    owner_id = row.owner_id
    mine = bool(owner_id) and owner_id == getattr(user, 'pk', None)
    admin = _is_admin(user)
    promotable = bool(owner_id) and promotion_family(row) is not None
    pending = pending_promotion(row) if promotable else None
    return {'provenance': ('Système' if not owner_id else 'à moi' if mine
                           else f'partagé par {row.owner.get_username()}'),
            'owner': row.owner.get_username() if owner_id else '', 'system': not owner_id,
            'mine': mine, 'scope': scope_value(row), 'scope_label': scope_label(row),
            'can_share': mine, 'can_delete': may_remove(user, row),
            'can_promote': admin and promotable,
            'promotion_pending': pending is not None,
            'can_request_promotion': mine and promotable and pending is None,
            # La demande se voit par son auteur et par ceux qui la tranchent.
            'promotion_request_url': (request_page_url(pending)
                                      if pending is not None and (mine or admin) else '')}


def _is_admin(user) -> bool:
    from wama.accounts.permissions import is_admin_tier
    return is_admin_tier(user)


def may_remove(user, row) -> bool:
    """Retirer une ligne portée : son auteur, ou un administrateur."""
    return (bool(row.owner_id) and row.owner_id == getattr(user, 'pk', None)) or _is_admin(user)


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
