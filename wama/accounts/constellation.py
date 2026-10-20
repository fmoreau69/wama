"""La CONSTELLATION des utilisateurs — tout ce que WAMA sait d'un compte, et ce qui relie les comptes.

Demande de Fabien (2026-10-20) : une vue 3D, ouverte depuis la page « Users », où chaque personne
est une étoile — ses droits, ses rôles, ses partages, ce qu'elle fait entrer dans WAMA — et où la
DISTANCE entre deux personnes dit ce qui les lie : un partage les rapproche, un projet commun aussi,
et des sphères translucides regroupent les membres d'une même unité (équipe, labo, service…) ou
d'un même projet.

🔴 RIEN N'EST RECOPIÉ ICI. Chaque fait est lu de sa brique, celle qui décide ailleurs dans WAMA :
  - le profil et les rôles : `permissions.user_tier` / `user_roles`, `account_kind` ;
  - les droits : `permissions.accessible_apps` (la décision du menu, pas une table) ;
  - l'arbre des unités : `OrgUnit` (synchronisé du LDAP/SUPANN), rattachement par CODES comme
    `common.models.user_scope_org_ids` ;
  - les projets : `ProjectMembership` ;
  - les partages : `ObjectGrant.in_force()` — à une personne (`beneficiary`) ou à une portée ;
    celui qui partage est `granted_by`, posé par `sharing.share_with_person` et
    `sharing._record_scope_share` ;
  - ce qui entre dans WAMA : les familles du catalogue qui portent un auteur
    (`sharing.catalogue_owned_rows`, lues des registres), leurs éléments PROMUS au système
    (`source['proposed_by']`, `manifests/ownership.promote_owned_row`) et les jumelles du bac à
    sable (`sandbox.load_registry`, `created_by`) ;
  - l'activité : le journal (`journal.count_by_app_per_user`).
Les familles qui n'ont pas encore d'auteur (`TO_CARRY` : librairies, apps, briques UI…) sont
NOMMÉES dans la réponse, jamais passées sous silence : la page dit ce qu'elle ne peut pas montrer.

La distance elle-même se calcule côté page (`accounts/user-constellation.js`), parce que ses poids
sont des curseurs : le serveur ne livre que des FAITS.
"""
import logging

logger = logging.getLogger(__name__)

#: Plafond d'éléments NOMMÉS par famille et par compte — le compte, lui, est toujours exact.
ITEM_LIMIT = 12


def _org_units(profiles):
    """Les unités qui comptent pour la scène : celles où un compte est rattaché, et leurs ancêtres
    (un membre d'équipe est dans la sphère du labo). Rend `(units, user_unit_ids)`."""
    from wama.common.models import OrgUnit, profile_org_codes
    by_code = {u.code: u for u in OrgUnit.local()}
    by_id = {u.id: u for u in by_code.values()}
    user_units, kept = {}, set()
    for user_id, prof in profiles.items():
        ids = [by_code[c].id for c in profile_org_codes(prof) if c in by_code]
        user_units[user_id] = ids
        # `OrgUnit.ancestors()` en mémoire (même garde anti-cycle) : l'arbre est déjà chargé, le
        # remonter nœud par nœud coûterait une requête par parent et par compte.
        for uid in ids:
            node, guard = by_id.get(uid), 0
            while node is not None and guard < 20 and node.id not in kept:
                kept.add(node.id)
                node = by_id.get(node.parent_id)
                guard += 1
    labels = dict(OrgUnit.TYPE_CHOICES)
    units = [{'id': u.id, 'code': u.code, 'name': u.name, 'type': u.unit_type,
              'type_label': labels.get(u.unit_type, u.unit_type), 'parent': u.parent_id,
              'source': 'orgunit'}
             for u in by_id.values() if u.id in kept]
    # Une entité principale que le profil porte (LDAP, au login) mais que l'arbre `OrgUnit` n'a pas
    # encore (`sync_org_units` pas repassé) : montrée quand même, MARQUÉE comme telle — sinon la
    # personne flotterait hors de toute sphère sans que rien ne dise pourquoi. Elle ne décide rien :
    # les portées de partage lisent `OrgUnit` seul.
    declared = {}
    for user_id, prof in profiles.items():
        code = prof.org_entity_code if prof else ''
        if not code or code in by_code:
            continue
        uid = f'profile:{code}'
        declared.setdefault(uid, {'id': uid, 'code': code, 'name': prof.org_entity_name or code,
                                  'type': 'autre', 'type_label': labels.get('autre', 'autre'),
                                  'parent': None, 'source': 'profile'})
        user_units[user_id] = user_units.get(user_id, []) + [uid]
    return units + list(declared.values()), user_units


def _projects():
    from wama.common.models import Project, ProjectMembership
    roles = dict(ProjectMembership.ROLE_CHOICES)
    out = {p.id: {'id': p.id, 'code': p.code, 'name': p.name, 'description': p.description,
                  'owner_org': p.owner_org_id, 'lead': p.lead_id, 'members': []}
           for p in Project.objects.all()}
    for m in ProjectMembership.objects.all().only('project_id', 'user_id', 'role'):
        if m.project_id in out:
            out[m.project_id]['members'].append(
                {'user': m.user_id, 'role': m.role, 'role_label': roles.get(m.role, m.role)})
    return list(out.values())


def _shares():
    """Partages EN VIGUEUR : `(edges, scope_shares)`.

    `edges` — d'une personne à une autre, `{from, to, count, levels}` (sans la promotion au
    système, qui ne fait rien voir à personne). `scope_shares` — d'une personne à une portée
    (unité, projet, tout le monde), `{user: [{visibility, unit, project, count}]}`."""
    from django.db.models import Count
    from wama.common.models import ObjectGrant
    live = ObjectGrant.in_force().filter(granted_by__isnull=False).exclude(
        level=ObjectGrant.LEVEL_SYSTEM)
    edges = {}
    for row in (live.filter(beneficiary__isnull=False)
                .values('granted_by_id', 'beneficiary_id', 'level').annotate(n=Count('pk'))
                .order_by()):
        a, b = row['granted_by_id'], row['beneficiary_id']
        if a == b:
            continue
        e = edges.setdefault((a, b), {'from': a, 'to': b, 'count': 0, 'levels': {}})
        e['count'] += row['n']
        e['levels'][row['level']] = e['levels'].get(row['level'], 0) + row['n']
    scopes = {}
    for row in (live.filter(beneficiary__isnull=True)
                .values('granted_by_id', 'visibility', 'scope_org_unit_id', 'scope_project_id')
                .annotate(n=Count('pk')).order_by()):
        scopes.setdefault(row['granted_by_id'], []).append(
            {'visibility': row['visibility'], 'unit': row['scope_org_unit_id'],
             'project': row['scope_project_id'], 'count': row['n']})
    return list(edges.values()), scopes


def _key_field(registry, model):
    """Le champ qui NOMME une ligne de la famille : celui que déclare le registre, sinon `name`."""
    from django.core.exceptions import FieldDoesNotExist
    for name in (registry.owner_key, 'name'):
        if not name:
            continue
        try:
            model._meta.get_field(name)
            return name
        except FieldDoesNotExist:
            continue
    return 'pk'


def _has_json_source(model):
    from django.core.exceptions import FieldDoesNotExist
    from django.db.models import JSONField
    try:
        return isinstance(model._meta.get_field('source'), JSONField)
    except FieldDoesNotExist:
        return False


def _contributions(user_ids_by_name):
    """Ce que chaque compte a fait entrer dans WAMA : `({user_id: {famille: {...}}}, familles)`.

    Trois provenances par famille : `owned` (à lui, privé), `shared` (à lui, partagé à une portée)
    et `promoted` (proposé par lui, devenu système). Les familles sont lues des registres portés —
    aucune n'est nommée ici."""
    from django.db import DatabaseError, transaction
    from wama.common.models import ScopedVisibility
    from wama.common.services.sharing import catalogue_owned_rows

    out, families = {}, []

    def add(user_id, family, status, name):
        fam = out.setdefault(user_id, {}).setdefault(
            family, {'owned': 0, 'shared': 0, 'promoted': 0, 'items': []})
        fam[status] += 1
        if len(fam['items']) < ITEM_LIMIT:
            fam['items'].append({'name': str(name), 'status': status})

    for registry, model in catalogue_owned_rows():
        families.append({'key': registry.key, 'label': registry.label})
        key = _key_field(registry, model)
        try:
            with transaction.atomic():
                for row in (model._default_manager.filter(owner__isnull=False)
                            .values('owner_id', key, 'visibility').order_by(key)):
                    status = ('owned' if row['visibility'] == ScopedVisibility.VIS_PRIVATE
                              else 'shared')
                    add(row['owner_id'], registry.key, status, row[key])
                if _has_json_source(model):
                    for row in (model._default_manager
                                .filter(owner__isnull=True, source__has_key='proposed_by')
                                .values(key, 'source')):
                        uid = user_ids_by_name.get((row['source'] or {}).get('proposed_by'))
                        if uid is not None:
                            add(uid, registry.key, 'promoted', row[key])
        except DatabaseError:
            # Une famille dont la table manque (migration pas encore passée) n'efface pas les autres.
            logger.warning('[constellation] famille %s illisible', registry.key, exc_info=True)

    # Les apps : leurs JUMELLES de bac à sable portent leur créateur (`sandbox_apps.json`).
    from wama.common.sandbox import load_registry
    twins = [e for e in load_registry() if isinstance(e, dict) and e.get('created_by')]
    if twins:
        families.append({'key': 'sandbox_apps', 'label': 'Apps (bac à sable)'})
    for e in twins:
        uid = user_ids_by_name.get(e['created_by'])
        if uid is not None:
            add(uid, 'sandbox_apps', 'owned', e.get('label', ''))
    return out, families


def _uncarried_families():
    """Les familles du catalogue dont aucune ligne ne porte encore d'auteur (`ROADMAP §29`)."""
    from wama.common.registries import REGISTRIES, TO_CARRY
    return [{'key': r.key, 'label': r.label}
            for r in REGISTRIES.values() if r.provenance == TO_CARRY]


def constellation():
    """Les FAITS de la constellation, pour la page `accounts:user-constellation`."""
    from django.contrib.auth.models import User

    from wama.accounts.permissions import (ACCOUNT_KINDS, ROLES, TIER_CHOICES, account_kind,
                                           accessible_apps, presented_apps, user_roles,
                                           user_tier)
    from wama.common.app_registry import WORLD_SECTIONS, app_identity, app_world
    from wama.common.models import ObjectGrant
    from wama.common.services.journal import count_by_app_per_user
    from wama.common.services.sharing import PORTEES

    users = list(User.objects.all().select_related('profile').prefetch_related('groups')
                 .order_by('username'))
    profiles = {u.id: getattr(u, 'profile', None) for u in users}
    # Les outils montrés : ceux de la scène des droits de la présentation, dans le même ordre.
    app_ids = presented_apps()

    units, user_units = _org_units(profiles)
    projects = _projects()
    edges, scope_shares = _shares()
    contributions, families = _contributions({u.username: u.id for u in users})
    activity = count_by_app_per_user()
    tiers = dict(TIER_CHOICES)

    people = []
    for u in users:
        prof = profiles[u.id]
        tier = user_tier(u)
        people.append({
            'id': u.id,
            'username': u.username,
            'name': u.get_full_name() or u.username,
            'kind': account_kind(u),
            'tier': tier,
            'tier_label': tiers.get(tier, tier),
            'roles': sorted(user_roles(u)),
            'active': u.is_active,
            'joined': u.date_joined.isoformat() if u.date_joined else None,
            'last_login': u.last_login.isoformat() if u.last_login else None,
            'org': {
                'path': prof.org_path() if prof else '',
                'entity': (prof.org_entity_name or prof.org_entity_code) if prof else '',
                'establishment': prof.establishment if prof else '',
                'affiliation': prof.ldap_affiliation if prof else '',
            },
            'units': user_units.get(u.id, []),
            'apps': accessible_apps(u, app_ids) if u.is_active else [],
            'contributions': contributions.get(u.id, {}),
            'activity': activity.get(u.id, []),
            'scope_shares': scope_shares.get(u.id, []),
        })

    return {
        'users': people,
        'units': units,
        'projects': projects,
        'shares': edges,
        'apps': [{'id': a, 'label': app_identity(a)['label'], 'world': app_world(a)}
                 for a in app_ids],
        'worlds': {w: s['label'] for w, s in WORLD_SECTIONS.items()},
        'tiers': [{'key': k, 'label': l} for k, l in TIER_CHOICES],
        'roles': [{'key': k, 'label': l} for k, l in ROLES.items()],
        # Libellés DÉCLARÉS ailleurs, transmis tels quels — la page n'en écrit aucun.
        'levels': dict(ObjectGrant.LEVEL_CHOICES),
        'scopes': dict(PORTEES),
        'account_kinds': dict(ACCOUNT_KINDS),
        'families': families,
        'uncarried_families': _uncarried_families(),
    }
