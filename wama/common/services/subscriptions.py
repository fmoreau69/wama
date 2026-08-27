"""ABONNEMENT aux éléments de catalogue — la couche PRÉFÉRENCE (PROFILES_PERMISSIONS §8).

CE QUE CE MODULE EST, ET CE QU'IL N'EST PAS
-------------------------------------------
Il répond à « **est-ce que je VEUX m'en servir ?** ». Il ne répond JAMAIS à « **est-ce que j'ai le
DROIT de m'en servir ?** » — cette question-là a un point de décision unique, `accessible()`
(`wama/accounts/permissions.py`), et ce module ne l'appelle pas, ne le double pas, ne le contourne
pas.

🔴 **INVARIANT : une préférence ne peut que RESTREINDRE.** Elle s'applique à l'intérieur du
sous-ensemble déjà autorisé. Concrètement, tout appelant compose dans cet ordre :

    ids_autorises = [i for i in ids if accessible(user, i)]      # LE DROIT — ailleurs
    ids_affiches  = filtrer(user, 'app', ids_autorises)          # LA PRÉFÉRENCE — ici

Inverser cet ordre, ou n'appliquer que le second, n'ouvrirait rien de plus : ce module ne sait
qu'enlever. Mais l'ordre reste écrit pour que l'intention se lise à la relecture.

POURQUOI SEULES LES EXCEPTIONS SONT STOCKÉES
--------------------------------------------
Le défaut est « abonné à tout ce que mon rôle autorise » : un compte neuf n'a AUCUNE ligne et voit
tout ce à quoi il a droit — pas d'écran de bienvenue à quarante cases. Stocker l'état complet
aurait exigé de semer une ligne par (utilisateur × élément) à la création du compte PUIS à chaque
élément installé ensuite : un invariant à maintenir est un invariant qui dérive (leçon du compte
`anonymous`, 27/08). Ici, se désabonner écrit une ligne, se réabonner l'efface.

Corollaire mesurable : `ElementPreference.objects.count()` est le nombre de choix EXPLICITES des
utilisateurs, jamais un volume de plomberie.
"""
from wama.common.models import ElementPreference

#: Natures d'éléments abonnables. DÉCLARATIF : ajouter une nature = une entrée ici, et la page
#: de catalogue correspondante hérite du mécanisme. `catalogue` sert aux liens « voir tout ».
#: ⚠ Les natures NON encore câblées côté page sont volontairement absentes : déclarer une nature
#: sans surface produirait un mécanisme muet, exactement ce que le dépôt traque.
KINDS = {
    'app': {'label': 'Application', 'catalogue': 'common:apps_catalog'},
}


def _valide(kind):
    if kind not in KINDS:
        raise ValueError(f"nature d'élément inconnue : {kind!r} (attendu : {', '.join(KINDS)})")
    return kind


def _actif(user):
    """Un utilisateur porte-t-il des préférences ? Le compte anonyme n'en a pas : il n'a pas de
    session personnelle à personnaliser, et lui en écrire vaudrait pour TOUS ses visiteurs."""
    return bool(user and getattr(user, 'is_authenticated', False)
                and getattr(user, 'username', '') != 'anonymous')


def masques(user, kind):
    """Ensemble des `element_id` que l'utilisateur a explicitement masqués pour cette nature.

    C'est la SEULE lecture en base du mécanisme : une requête par page, pas une par card."""
    _valide(kind)
    if not _actif(user):
        return set()
    return set(ElementPreference.objects
               .filter(user=user, kind=kind, subscribed=False)
               .values_list('element_id', flat=True))


def est_abonne(user, kind, element_id):
    """Abonné par DÉFAUT — seule une ligne explicite `subscribed=False` dit le contraire."""
    return element_id not in masques(user, kind)


def filtrer(user, kind, element_ids):
    """Sous-liste des éléments auxquels l'utilisateur est abonné (ordre préservé).

    ⚠ Ne filtre RIEN sur le droit : `element_ids` doit déjà être le sous-ensemble autorisé."""
    hors = masques(user, kind)
    return [e for e in element_ids if e not in hors]


def definir(user, kind, element_id, abonne):
    """Pose ou lève un masquage. Retourne l'état effectif (bool).

    Se réabonner EFFACE la ligne au lieu de la basculer à `True` : l'absence de ligne EST le
    défaut, et deux représentations du même état (pas de ligne / ligne à True) finiraient par
    diverger. `subscribed=True` reste possible en base pour un usage futur (un abonnement
    explicite à un élément dont le défaut deviendrait « non abonné »), mais rien ne l'écrit ici."""
    _valide(kind)
    if not _actif(user):
        return True
    if abonne:
        ElementPreference.objects.filter(user=user, kind=kind, element_id=element_id).delete()
        return True
    ElementPreference.objects.update_or_create(
        user=user, kind=kind, element_id=element_id, defaults={'subscribed': False})
    return False


def definir_lot(user, kind, element_ids, abonne):
    """Sélecteur TOUT / RIEN. Retourne le nombre d'éléments effectivement concernés.

    « Tout » efface les masquages de la nature ENTIÈRE (pas seulement des ids passés) : c'est ce
    que le geste promet à l'utilisateur, et ça évite qu'un élément absent de la page courante
    reste masqué sans qu'il puisse le retrouver."""
    _valide(kind)
    if not _actif(user):
        return 0
    if abonne:
        n, _ = ElementPreference.objects.filter(user=user, kind=kind).delete()
        return n
    existants = masques(user, kind)
    nouveaux = [e for e in element_ids if e not in existants]
    ElementPreference.objects.bulk_create(
        [ElementPreference(user=user, kind=kind, element_id=e, subscribed=False)
         for e in nouveaux])
    return len(nouveaux)


def resume(user, kind, element_ids):
    """`{'total', 'abonnes', 'masques'}` sur un ensemble d'éléments AUTORISÉS — de quoi rendre
    le bandeau « 7 sur 12 » et décider si le sélecteur tout/rien a un sens."""
    hors = masques(user, kind)
    total = len(element_ids)
    caches = sum(1 for e in element_ids if e in hors)
    return {'total': total, 'abonnes': total - caches, 'masques': caches}
