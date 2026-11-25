"""
Remontée de l'appartenance organisationnelle (SUPANN/eduPerson) depuis le LDAP vers
le `UserProfile`, à la connexion.

Le LDAP est déjà branché au login (django_auth_ldap). Ici on lit les attributs SUPANN
de la fiche personne (aucune requête supplémentaire : ils arrivent avec le bind) et on
les écrit sur le profil (axe C — voir docs/construction/mondes/WAMA_VISION_COMPLET.md §Les quatre mondes,
memory/reference_ldap_supann_orgunit.md).

Flux :
1. signal `populate_user` (django_auth_ldap) → on range les attributs sur `user._ldap_org` ;
2. signal `post_save` (User) → le profil existe (créé par accounts.models) → on l'applique.

⚠️ Les NOMS lisibles + la HIÉRARCHIE (institut→…→équipe) vivent dans `ou=structures` et
demandent une requête additionnelle : celle de la synchro des unités (`sync_org_units`, par la
liaison de `accounts/directory.py`), qui les range dans `OrgUnit` ; `_apply_ldap_org` les y relit.
"""
import logging
import re

from django.contrib.auth.models import User
from django.db.models.signals import post_save
from django.dispatch import receiver

logger = logging.getLogger(__name__)


#: Forme SUPANN `{namespace}valeur` — `{UAI}0772894C`, `{IFSTTAR}LESCOT`. La norme préfixe la
#: valeur par l'AUTORITÉ qui l'émet. WAMA garde le code BRUT partout (décision du modèle
#: `OrgUnit` : « le code doit rester celui de l'annuaire, sinon chaque synchro devient de la
#: chirurgie de chaîne ») — la séparation ci-dessous ne sert donc qu'à l'AFFICHAGE.
_SUPANN_NAMESPACE = re.compile(r'^\{([^}]+)\}\s*(.*)$')


def split_namespace(code: str):
    """`'{IFSTTAR}LESCOT'` → `('IFSTTAR', 'LESCOT')` ; un code sans préfixe → `('', code)`.

    Ajouté le 2026-09-26 : la page de profil affichait `{UAI}0772894C` et
    `{IFSTTAR} › {IFSTTAR}DG › {IFSTTAR}LESCOT` tels quels, c'est-à-dire la syntaxe d'un
    annuaire à un utilisateur qui n'en a pas le manuel. Le code brut reste la donnée et
    reste montré ; c'est le LIBELLÉ qui devient lisible.
    """
    m = _SUPANN_NAMESPACE.match((code or '').strip())
    return (m.group(1), m.group(2).strip()) if m else ('', (code or '').strip())


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


#: L'attribut qui RATTACHE une personne à une unité : son unité PRINCIPALE. Nommé une fois — la
#: remontée au profil ci-dessous et la lecture de l'annuaire par unité (`accounts/directory.py`)
#: lisent le même. WAMA ne lit plus « toutes ses unités » (décision de Fabien, 2026-11-25 : une
#: seule appartenance, la principale — les autres codes d'une fiche sont souvent les codes
#: hérités de la même unité, et rien ne s'en sert).
MAIN_UNIT_ATTRIBUTE = 'supannEntiteAffectationPrincipale'

ESTABLISHMENT_ATTRIBUTE = 'supannEtablissement'
#: La qualité de la personne : la principale si la fiche la porte, sinon toutes ses qualités.
#: (Mesuré le 2026-11-25 : la première n'était portée par aucune fiche lue, la seconde par toutes
#: — le champ du profil restait vide.)
STATUS_ATTRIBUTES = ('eduPersonPrimaryAffiliation', 'eduPersonAffiliation')

#: La liste FERMÉE de ce que `_parse_org` lit d'une fiche — celle que la lecture d'une personne
#: hors connexion réclame (`directory.person_org`), et rien de plus.
ORG_ATTRIBUTES = (ESTABLISHMENT_ATTRIBUTE, MAIN_UNIT_ATTRIBUTE, *STATUS_ATTRIBUTES)

#: Ce qu'un compte reçoit de l'annuaire À SA CRÉATION (pré-inscription comme première connexion),
#: avant tout choix de sa titulaire : son unité principale, rien d'autre. Le reste s'ajoute AVEC
#: elle (`accounts/directory_consent.py` — décision de Fabien, 2026-11-25).
MINIMUM_FIELDS = ('org_entity_code',)


def readable(code: str, name: str = ''):
    """`(libellé, autorité)` d'un code d'annuaire pour un humain : le nom de l'unité s'il en a un,
    sinon le code SANS son préfixe d'autorité (`{AUTORITÉ}UNITÉ` → « UNITÉ »). Un code réduit à
    son seul préfixe (`{AUTORITÉ}`, la racine d'une chaîne) se nomme par lui."""
    namespace, value = split_namespace(code)
    if name and name != code:
        return name, namespace
    return (value or namespace or code), namespace


def _parse_org(attrs):
    """Attributs LDAP (fiche personne) → dict de champs profil (codes bruts)."""
    status = _first(attrs, STATUS_ATTRIBUTES[0]) or ', '.join(_list(attrs, STATUS_ATTRIBUTES[1]))
    return {
        'establishment': _first(attrs, ESTABLISHMENT_ATTRIBUTE),  # forme `{UAI}0772894C`
        'org_entity_code': _first(attrs, MAIN_UNIT_ATTRIBUTE),
        'ldap_affiliation': status[:64],
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
def _apply_ldap_org(sender, instance, created=False, **kwargs):
    """Applique au profil ce que l'annuaire vient de rendre (juste après une connexion, ou à la
    création du compte) — et seulement ce que sa titulaire a choisi d'y voir
    (`directory_consent.writable` : le minimum à la création, rien de NEUF sans son accord)."""
    org = getattr(instance, '_ldap_org', None)
    if not org:
        return
    instance._ldap_org = None   # une seule application
    try:
        from .directory_consent import writable
        from .models import UserProfile
        prof, _ = UserProfile.objects.get_or_create(user=instance)
        apply_org(prof, writable(prof, org, created=created))
    except Exception:
        logger.warning('application org au profil échouée', exc_info=True)


def apply_org(prof, org) -> bool:
    """Écrit sur le profil les champs `org` (codes bruts d'annuaire), puis le nom et la hiérarchie
    lisibles de l'unité principale depuis l'arbre `OrgUnit` — l'écriture de la connexion ET celle
    d'un choix de la personne (`directory_consent.decide`). Rend True si le profil a changé."""
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
            # `.local()` : le code vient de l'annuaire de CET établissement (§8.6).
            unit = OrgUnit.local().filter(code=code).first()
            if unit:
                prof.org_entity_name = unit.name
                prof.org_hierarchy = [{'code': u.code, 'name': u.name, 'type': u.unit_type}
                                      for u in unit.ancestors()]
                changed = True
        except Exception:
            pass
    if changed:
        prof.save()
    return changed
