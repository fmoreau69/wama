"""
Seed du modèle d'accès (idempotent) :
  - crée les Groups de rôles métier ('role:<clé>') ;
  - crée/complète les AppAccessPolicy depuis DEFAULT_APP_ACCESS (sans écraser les éditions manuelles).
Relançable sans danger. Ne modifie PAS les politiques déjà éditées (option --reset pour réinitialiser).
"""
from django.core.management.base import BaseCommand
from django.contrib.auth.models import Group


class Command(BaseCommand):
    help = "Seed les rôles métier (Groups) et les politiques d'accès des apps (AppAccessPolicy)."

    def add_arguments(self, parser):
        parser.add_argument('--reset', action='store_true',
                            help="Réinitialise les politiques existantes aux valeurs par défaut.")
        parser.add_argument('--prune', action='store_true',
                            help="Supprime les politiques d'apps inconnues (hors registre + extras).")

    def handle(self, *args, **opts):
        from wama.accounts.permissions import ROLES, GROUP_PREFIX, DEFAULT_APP_ACCESS
        from wama.accounts.models import AppAccessPolicy
        try:
            from wama.common.app_registry import APP_CATALOG
        except Exception:
            APP_CATALOG = {}

        # 1) Groups de rôles métier
        role_groups = {}
        created_g = 0
        for key, label in ROLES.items():
            g, was = Group.objects.get_or_create(name=GROUP_PREFIX + key)
            role_groups[key] = g
            created_g += int(was)

        # 2) Politiques d'accès — liste d'apps pilotée par le REGISTRE (APP_CATALOG) + extras déclarés
        #    (studio, médiathèque, lab…). Les rôles viennent de DEFAULT_APP_ACCESS (défaut : commune).
        app_ids = list(dict.fromkeys(list(APP_CATALOG.keys()) + list(DEFAULT_APP_ACCESS.keys())))
        created_p = updated_p = 0
        for app_id in app_ids:
            d = DEFAULT_APP_ACCESS.get(app_id, {'roles': []})
            pol, was = AppAccessPolicy.objects.get_or_create(app_id=app_id)
            created_p += int(was)
            if was or opts['reset']:
                pol.public = d.get('public', False)
                pol.min_tier = d.get('min_tier') or ''
                pol.save()
                pol.roles.set([role_groups[r] for r in d.get('roles', []) if r in role_groups])
                if not was:
                    updated_p += 1

        # 3) Élagage optionnel des politiques d'apps inconnues (placeholders supprimés, etc.).
        pruned = 0
        if opts.get('prune'):
            known = set(app_ids)
            stale = AppAccessPolicy.objects.exclude(app_id__in=known)
            pruned = stale.count()
            stale.delete()

        self.stdout.write(self.style.SUCCESS(
            f"Rôles : {created_g} créé(s)/{len(ROLES)} total. "
            f"Politiques : {created_p} créée(s), {updated_p} réinitialisée(s), "
            f"{pruned} élaguée(s), {AppAccessPolicy.objects.count()} au total."
        ))
