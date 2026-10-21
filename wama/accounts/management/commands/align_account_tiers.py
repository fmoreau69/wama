"""
Aligne les comptes sur LA définition du rôle : le NIVEAU du profil (décision de Fabien, 2026-10-21).

Trois sources disaient « administrateur » ou « développeur » — le niveau du profil, les drapeaux
Django (`is_superuser`, `is_staff`) et les groupes hérités `admin` / `dev` / `user` de la migration
`accounts/0002`. Le code ne lit plus que le niveau (`permissions.user_tier`) ; cette commande
reporte sur lui ce que les deux autres sources accordaient, puis retire ces groupes :

  1. un superutilisateur, ou un membre du groupe `admin`  → niveau `admin` ;
  2. un membre du groupe `dev` / `developpeur`, sous ce niveau → niveau `developpeur` ;
  3. chaque compte : ses drapeaux sont DÉRIVÉS du niveau (`set_account_tier` — administrateur ⇒
     `is_staff` + `is_superuser`, sinon ni l'un ni l'autre) ;
  4. les groupes `admin` / `dev` / `user` / `developpeur` sont supprimés (ils ne portaient aucune
     permission). Les rôles MÉTIER `role:*` ne sont pas touchés.

Le compte de service `anonymous` n'est jamais promu. Lecture seule par défaut : le relevé dit ce
qui changerait ; `--apply` l'écrit. Idempotente : un second passage ne change rien.
"""
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand
from django.db import transaction

#: Les groupes hérités de `accounts/0002` (et `developpeur`, homonyme du niveau, vu en base).
LEGACY_GROUPS = ('admin', 'dev', 'user', 'developpeur')
ADMIN_GROUPS = ('admin',)
DEVELOPER_GROUPS = ('dev', 'developpeur')


def planned_changes():
    """[(user, niveau actuel, niveau cible, drapeaux actuels, drapeaux cibles)] — rien d'écrit."""
    from wama.accounts.permissions import is_guest_account, tier_rank
    from wama.accounts.views import ANONYMOUS_USERNAME

    rows = []
    users = get_user_model().objects.select_related('profile').prefetch_related('groups')
    for user in users:
        stored = getattr(getattr(user, 'profile', None), 'account_tier', None) or 'utilisateur'
        groups = {g.name for g in user.groups.all()}
        target = stored
        if user.username != ANONYMOUS_USERNAME and not is_guest_account(user):
            if user.is_superuser or groups & set(ADMIN_GROUPS):
                target = 'admin'
            # On ne fait jamais DESCENDRE un compte (`tier_rank`, l'ordre des niveaux).
            elif groups & set(DEVELOPER_GROUPS) and tier_rank(stored) < tier_rank('developpeur'):
                target = 'developpeur'
        admin = target == 'admin'
        flags = (user.is_staff, user.is_superuser)
        if target != stored or flags != (admin, admin):
            rows.append((user, stored, target, flags, (admin, admin)))
    return rows


class Command(BaseCommand):
    help = ("Aligne les comptes sur le NIVEAU du profil (seule définition du rôle) et retire les "
            "groupes hérités admin/dev/user. Lecture seule sans --apply.")

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true', help="Écrire les changements.")

    def handle(self, *args, **opts):
        from wama.accounts.permissions import set_account_tier

        rows = planned_changes()
        legacy = list(Group.objects.filter(name__in=LEGACY_GROUPS))
        for user, stored, target, flags, wanted in rows:
            self.stdout.write(
                f"  {user.username:<28} niveau {stored} → {target}"
                f"   is_staff/is_superuser {flags} → {wanted}")
        for group in legacy:
            self.stdout.write(f"  groupe « {group.name} » ({group.user_set.count()} membre(s)) → supprimé")
        if not rows and not legacy:
            self.stdout.write(self.style.SUCCESS("Comptes déjà alignés : rien à faire."))
            return
        if not opts['apply']:
            self.stdout.write(self.style.WARNING(
                f"{len(rows)} compte(s) et {len(legacy)} groupe(s) à aligner — relancer avec --apply."))
            return
        with transaction.atomic():
            for user, _stored, target, _flags, _wanted in rows:
                set_account_tier(user, target)
            for group in legacy:
                group.delete()
        self.stdout.write(self.style.SUCCESS(
            f"{len(rows)} compte(s) alignés, {len(legacy)} groupe(s) hérités supprimés."))
