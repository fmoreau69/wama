"""
Déploiement « soft » des rôles métier (non-régressif) : attribue des rôles aux utilisateurs existants
pour qu'ils gardent l'accès qu'ils avaient avant l'activation des permissions. À curer ensuite via l'admin.

Par défaut : **tous** les rôles, aux users **non-superuser** **sans aucun rôle** (n'écrase pas les
attributions déjà faites). Le compte de service `anonymous` est TOUJOURS exclu — il est sans rôle
par construction, donc c'est justement lui que la cible « sans aucun rôle » attrapait.
Options :
  --roles communication,recherche   limiter aux rôles donnés
  --all-users                       (ré)appliquer même aux users ayant déjà des rôles
  --include-superusers              inclure les superusers (inutile : ils bypassent)
Idempotent.
"""
from django.core.management.base import BaseCommand
from django.contrib.auth.models import User, Group

from wama.accounts.views import ANONYMOUS_USERNAME


class Command(BaseCommand):
    help = "Attribue des rôles métier aux utilisateurs existants (déploiement soft non-régressif)."

    def add_arguments(self, parser):
        parser.add_argument('--roles', default='', help="Clés de rôles séparées par des virgules (défaut : tous).")
        parser.add_argument('--all-users', action='store_true', help="Inclure les users ayant déjà des rôles.")
        parser.add_argument('--include-superusers', action='store_true')

    def handle(self, *args, **opts):
        from wama.accounts.permissions import ROLES, GROUP_PREFIX

        keys = [k.strip() for k in opts['roles'].split(',') if k.strip()] or list(ROLES.keys())
        groups = list(Group.objects.filter(name__in=[GROUP_PREFIX + k for k in keys]))
        if not groups:
            self.stdout.write(self.style.ERROR("Aucun groupe de rôle trouvé — lance d'abord `seed_access`."))
            return

        # Le compte de service anonyme est EXCLU sans option de contournement (2026-08-27) : il
        # est sans rôle par construction, donc il rentrait pile dans la cible « users sans aucun
        # rôle » et cette commande lui rendait les 4 rôles retirés le 22/08. Mesuré : rôles seuls,
        # l'accès reste à 0/11 (le tier `anonymous` tranche avant) — mais combiné à un compte
        # RECRÉÉ au tier par défaut `utilisateur`, on retrouve 10 apps sur 11. On ne compte pas
        # sur un seul des deux verrous.
        qs = User.objects.exclude(username=ANONYMOUS_USERNAME)
        if not opts['include_superusers']:
            qs = qs.filter(is_superuser=False)

        touched = 0
        for u in qs:
            has_role = u.groups.filter(name__startswith=GROUP_PREFIX).exists()
            if has_role and not opts['all_users']:
                continue
            u.groups.add(*groups)
            touched += 1

        self.stdout.write(self.style.SUCCESS(
            f"Rôles {keys} attribués à {touched} utilisateur(s)."
        ))
