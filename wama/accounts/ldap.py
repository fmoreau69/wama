"""
Remontée de l'appartenance organisationnelle (SUPANN/eduPerson) depuis le LDAP vers
le `UserProfile`, à la connexion.

Le LDAP est déjà branché au login (django_auth_ldap). Ici on lit les attributs SUPANN
de la fiche personne (aucune requête supplémentaire : ils arrivent avec le bind) et on
les écrit sur le profil (axe C — voir docs/VISION_STATUS.md §MONDES,
memory/reference_ldap_supann_orgunit.md).

Flux :
1. signal `populate_user` (django_auth_ldap) → on range les attributs sur `user._ldap_org` ;
2. signal `post_save` (User) → le profil existe (créé par accounts.models) → on l'applique.

⚠️ Les NOMS lisibles + la HIÉRARCHIE (institut→…→équipe) vivent dans `ou=structures` et
demandent une requête additionnelle : `resolve_org_hierarchy` (best-effort, à activer quand
la base DN des structures est configurée). Pour l'instant on peuple les CODES bruts, gratuits.
"""
import logging

from django.contrib.auth.models import User
from django.db.models.signals import post_save
from django.dispatch import receiver

logger = logging.getLogger(__name__)


def _first(attrs, key):
    v = attrs.get(key)
    if isinstance(v, (list, tuple)):
        return str(v[0]) if v else ''
    return str(v) if v else ''


def _list(attrs, key):
    v = attrs.get(key)
    if isinstance(v, (list, tuple)):
        return [str(x) for x in v]
    return [str(v)] if v else []


def _parse_org(attrs):
    """Attributs LDAP (fiche personne) → dict de champs profil (codes bruts)."""
    return {
        'establishment': _first(attrs, 'supannEtablissement'),
        'org_entity_code': _first(attrs, 'supannEntiteAffectationPrincipale'),
        'org_affiliations': _list(attrs, 'supannEntiteAffectation'),
        'ldap_affiliation': _first(attrs, 'eduPersonPrimaryAffiliation'),
    }


try:
    from django_auth_ldap.backend import populate_user

    @receiver(populate_user)
    def _stash_ldap_org(sender, user, ldap_user, **kwargs):
        """django_auth_ldap : range les attributs SUPANN sur l'instance user (post_save les applique)."""
        try:
            attrs = getattr(ldap_user, 'attrs', {}) or {}
            user._ldap_org = _parse_org(attrs)
        except Exception:
            logger.warning('parsing SUPANN échoué', exc_info=True)
except Exception:
    logger.debug('django_auth_ldap indisponible — pas de remontée org', exc_info=True)


@receiver(post_save, sender=User)
def _apply_ldap_org(sender, instance, **kwargs):
    """Applique les attributs SUPANN stashés au profil (uniquement juste après login LDAP)."""
    org = getattr(instance, '_ldap_org', None)
    if not org:
        return
    instance._ldap_org = None   # une seule application
    try:
        from .models import UserProfile
        prof, _ = UserProfile.objects.get_or_create(user=instance)
        changed = False
        for k, v in org.items():
            if v and getattr(prof, k, None) != v:
                setattr(prof, k, v)
                changed = True
        # Si l'entité principale correspond à un OrgUnit connu (synchro structures), on
        # renseigne nom + hiérarchie lisibles depuis l'arbre en BDD (sans requête LDAP).
        code = org.get('org_entity_code')
        if code:
            try:
                from wama.common.models import OrgUnit
                unit = OrgUnit.objects.filter(code=code).first()
                if unit:
                    prof.org_entity_name = unit.name
                    prof.org_hierarchy = [{'code': u.code, 'name': u.name, 'type': u.unit_type}
                                          for u in unit.ancestors()]
                    changed = True
            except Exception:
                pass
        if changed:
            prof.save()
    except Exception:
        logger.warning('application org au profil échouée', exc_info=True)


def resolve_org_hierarchy(entity_code, structures_base_dn=None):
    """Best-effort : résout un code d'entité → chaîne [{code,name,type}] institut→…→équipe
    en suivant `supannCodeEntiteParent` dans `ou=structures`. Nécessite une connexion LDAP
    et la base DN des structures (settings.LDAP_STRUCTURES_BASE_DN). Retourne [] si indispo.

    À câbler quand la DSI a fourni la base structures — voir reference_ldap_supann_orgunit.
    """
    from django.conf import settings
    base = structures_base_dn or getattr(settings, 'LDAP_STRUCTURES_BASE_DN', None)
    if not base or not entity_code:
        return []
    try:
        import ldap  # python-ldap (dépendance de django_auth_ldap)
        conn = ldap.initialize(getattr(settings, 'AUTH_LDAP_SERVER_URI', ''))
        bdn = getattr(settings, 'AUTH_LDAP_BIND_DN', '') or ''
        if bdn:
            conn.simple_bind_s(bdn, getattr(settings, 'AUTH_LDAP_BIND_PASSWORD', ''))
        chain, code, guard = [], entity_code, 0
        while code and guard < 12:
            guard += 1
            res = conn.search_s(base, ldap.SCOPE_SUBTREE,
                                f'(supannCodeEntite={code})',
                                ['description', 'supannTypeEntite', 'supannCodeEntiteParent'])
            if not res:
                break
            a = res[0][1]
            chain.append({
                'code': code,
                'name': (a.get('description', [b''])[0] or b'').decode('utf-8', 'ignore'),
                'type': (a.get('supannTypeEntite', [b''])[0] or b'').decode('utf-8', 'ignore'),
            })
            parent = a.get('supannCodeEntiteParent')
            code = parent[0].decode('utf-8', 'ignore') if parent else None
        chain.reverse()   # du plus large (institut) au plus fin (équipe)
        return chain
    except Exception:
        logger.warning('resolve_org_hierarchy échouée pour %s', entity_code, exc_info=True)
        return []
