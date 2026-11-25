"""
Les données d'annuaire d'un profil sont ajoutées AVEC la personne (2026-11-25, décision de Fabien —
`PROFILES_PERMISSIONS.md §1.12`).

Jusqu'ici chaque connexion écrivait sur le profil tout ce que l'annuaire rend du rattachement de
la personne. Désormais :
  - à la CRÉATION du compte (pré-inscription comme première connexion), le profil ne reçoit que le
    minimum (`ldap.MINIMUM_FIELDS`) ;
  - chaque autre donnée est PROPOSÉE à la personne, qui l'ajoute ou la retire, une par une ou d'un
    geste — au panneau d'accueil de sa première connexion, puis depuis son profil ;
  - une donnée RETIRÉE est effacée du profil et n'y revient pas ; une donnée ajoutée se
    rafraîchit à chaque connexion ; tant que la personne n'a pas choisi, rien de NEUF ne s'ajoute
    et ce que le profil portait déjà reste tenu à jour (aucun compte existant ne perd rien).

Les VALEURS viennent toujours de l'annuaire (`directory.person_org`), jamais du navigateur : une
unité de rattachement ouvre des partages, elle ne se déclare pas.
"""
import logging

from django.utils import timezone

from .ldap import MINIMUM_FIELDS, apply_org, readable

logger = logging.getLogger(__name__)

#: Les données que l'annuaire propose — clé → déclaration. `fields` : les champs du profil que la
#: donnée écrit (clés de `ldap._parse_org`) ; `derived` : ceux qui s'en déduisent et s'effacent
#: avec elle ; `opens` : ce que la donnée OUVRE dans WAMA, dit à la personne avant qu'elle choisisse.
DIRECTORY_DATA = {
    'main_unit': {
        'label': 'Unité principale',
        'fields': ('org_entity_code',), 'derived': ('org_entity_name', 'org_hierarchy'),
        'opens': "Partager avec votre unité et lire ce qu'elle partage ; elle s'affiche à "
                 "côté de votre nom pour les administrateurs.",
    },
    'other_units': {
        'label': 'Autres unités de rattachement',
        'fields': ('org_affiliations',), 'derived': (),
        'opens': "Partager avec vos autres unités (équipe, département) et lire ce qu'elles "
                 "partagent.",
    },
    'establishment': {
        'label': 'Établissement',
        'fields': ('establishment',), 'derived': (),
        'opens': "Affiché sur votre profil. Rien d'autre ne s'en sert aujourd'hui.",
    },
    'status': {
        'label': 'Qualité (chercheur, personnel, étudiant…)',
        'fields': ('ldap_affiliation',), 'derived': (),
        'opens': "Affichée sur votre profil ; aide un administrateur à vous proposer un rôle.",
    },
}

ACCEPTED, DECLINED, UNDECIDED = 'accepted', 'declined', 'undecided'


def applies(user) -> bool:
    """Ce compte reçoit-il des données de l'annuaire ? Un compte d'annuaire
    (`permissions.is_directory_account`)."""
    from .permissions import is_directory_account
    return is_directory_account(user)


def pending(user) -> bool:
    """La personne doit-elle encore voir le panneau d'accueil ? Elle n'a jamais choisi."""
    profile = getattr(user, 'profile', None)
    return applies(user) and profile is not None and profile.directory_consent_at is None


def choice(profile, key: str) -> str:
    """Le choix de la personne pour la donnée `key`."""
    value = (profile.directory_consent or {}).get(key)
    return ACCEPTED if value is True else DECLINED if value is False else UNDECIDED


def _stored(profile, datum) -> bool:
    return any(getattr(profile, field, None) for field in datum['fields'])


def writable(profile, org: dict, *, created: bool = False) -> dict:
    """Ce que l'annuaire vient de rendre (`org`, clés de `ldap._parse_org`) et que le profil a le
    droit de recevoir : une donnée AJOUTÉE par la personne ; une donnée sur laquelle elle n'a pas
    encore choisi, si le profil la porte déjà ou, à la création du compte, si elle est du minimum.
    Jamais une donnée retirée."""
    allowed = {}
    for key, datum in DIRECTORY_DATA.items():
        chosen = choice(profile, key)
        if chosen == DECLINED:
            continue
        kept = chosen == ACCEPTED or _stored(profile, datum)
        for field in datum['fields']:
            if field in org and (kept or (created and field in MINIMUM_FIELDS)):
                allowed[field] = org[field]
    return allowed


def offer(user) -> dict:
    """Ce que l'annuaire porte AUJOURD'HUI pour ce compte (champs de profil), ou {} — annuaire
    muet, compte inconnu de lui, compte local. Une lecture, par la liste fermée de la brique."""
    if not applies(user):
        return {}
    from . import directory
    try:
        return directory.person_org(user.get_username())
    except directory.DirectoryUnavailable:
        logger.info("données d'annuaire : annuaire indisponible pour une proposition")
        return {}


def _display(field: str, value) -> str:
    """Une valeur d'annuaire telle qu'on la MONTRE : le nom d'une unité plutôt que son code."""
    if not value:
        return ''
    if field in ('org_entity_code', 'org_affiliations'):
        from wama.common.models import OrgUnit
        codes = [value] if isinstance(value, str) else list(value)
        names = dict(OrgUnit.local().filter(code__in=codes).values_list('code', 'name'))
        return ', '.join(dict.fromkeys(readable(code, names.get(code, ''))[0] for code in codes))
    if field == 'establishment':
        return readable(value)[0]
    return str(value)


def state(user, proposed: dict = None) -> list:
    """Une ligne par donnée, pour le panneau d'accueil, le profil et l'assistant :
    `{key, label, opens, choice, stored, value, offer}` — `value` ce que le profil porte, `offer`
    ce que l'annuaire propose (`proposed`, sinon lu par `offer`)."""
    profile = user.profile
    proposed = offer(user) if proposed is None else proposed
    rows = []
    for key, datum in DIRECTORY_DATA.items():
        field = datum['fields'][0]
        rows.append({
            'key': key, 'label': datum['label'], 'opens': datum['opens'],
            'choice': choice(profile, key), 'stored': _stored(profile, datum),
            'value': _display(field, getattr(profile, field, None)),
            'offer': _display(field, proposed.get(field)),
        })
    return rows


def decide(user, accept=(), decline=()) -> list:
    """Enregistre le choix de la personne : les données `accept` sont ajoutées (leur valeur LUE de
    l'annuaire à l'instant, ou à la prochaine connexion s'il est muet), les données `decline`
    effacées du profil. Rend l'état qui en résulte (`state`). `ValueError` : clé inconnue, ou une
    même clé des deux côtés."""
    accept, decline = list(dict.fromkeys(accept or ())), list(dict.fromkeys(decline or ()))
    unknown = [key for key in accept + decline if key not in DIRECTORY_DATA]
    if unknown or set(accept) & set(decline):
        raise ValueError("donnée d'annuaire inconnue ou choisie deux fois : "
                         + ', '.join(unknown or sorted(set(accept) & set(decline))))
    if not applies(user):
        raise ValueError("ce compte n'est pas un compte d'annuaire")
    profile = user.profile
    consent = dict(profile.directory_consent or {})
    for key in decline:
        consent[key] = False
        datum = DIRECTORY_DATA[key]
        for field in (*datum['fields'], *datum['derived']):
            setattr(profile, field, profile._meta.get_field(field).get_default())
    for key in accept:
        consent[key] = True
    profile.directory_consent, profile.directory_consent_at = consent, timezone.now()
    profile.save()
    proposed = offer(user) if accept else {}
    if accept:
        apply_org(profile, {field: proposed[field] for key in accept
                            for field in DIRECTORY_DATA[key]['fields'] if proposed.get(field)})
    logger.info("données d'annuaire de %s : %s ajoutée(s), %s retirée(s)",
                user.get_username(), len(accept), len(decline))
    return state(user, proposed if accept else None)


def acknowledge(user) -> None:
    """La personne a VU le panneau et ne change rien (« Garder ainsi ») : on ne le lui remontre
    pas, ses choix restent ce qu'ils sont."""
    profile = user.profile
    if profile.directory_consent_at is None:
        profile.directory_consent_at = timezone.now()
        profile.save(update_fields=['directory_consent_at'])
