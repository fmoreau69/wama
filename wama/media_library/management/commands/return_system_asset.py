"""Rend des assets SYSTÈME à leur auteur : ils redeviennent des assets PRIVÉS de sa médiathèque.

    python manage.py return_system_asset 1 2 9 --to-user <identifiant>            # PLAN seul
    python manage.py return_system_asset 1 2 9 --to-user <identifiant> --apply    # applique

POURQUOI (2026-09-29, `MEDIA_STORAGE_TIERING §8.6` D27) : le versement de la galerie d'avatars
(12/09) a fait des photos personnelles d'un utilisateur des assets système — sans propriétaire,
il ne pouvait plus les supprimer. La brique est `media_library.services.return_system_asset` ;
cette commande n'en est que l'appel, un asset après l'autre (un échec n'arrête pas les suivants
et se dit). Même contrat que `organize_system_assets` : le PLAN par défaut, `--apply` pour agir.
"""
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Rend des assets système à leur auteur (assets privés de sa médiathèque)."

    def add_arguments(self, parser):
        parser.add_argument('ids', nargs='+', type=int, help='ids des SystemAsset à rendre')
        parser.add_argument('--to-user', required=True, help="identifiant (username) de l'auteur")
        parser.add_argument('--apply', action='store_true', help='appliquer (sinon : plan seul)')

    def handle(self, *args, **opts):
        from wama.media_library.models import SystemAsset
        from wama.media_library.services import SystemAssetStillNamed, return_system_asset

        try:
            user = get_user_model().objects.get(username=opts['to_user'])
        except get_user_model().DoesNotExist:
            raise CommandError(f"utilisateur inconnu : {opts['to_user']}")

        mode = 'APPLIQUÉ' if opts['apply'] else 'PLAN (rien n’est écrit — --apply pour agir)'
        self.stdout.write(f'{mode} — vers {user.username} (#{user.id})')
        failures = 0
        for pk in opts['ids']:
            asset = SystemAsset.objects.filter(pk=pk).first()
            if asset is None:
                self.stdout.write(self.style.WARNING(f'  #{pk} : asset système introuvable'))
                failures += 1
                continue
            try:
                plan = return_system_asset(asset, user, apply=opts['apply'])
            except (SystemAssetStillNamed, ValueError, RuntimeError) as exc:
                self.stdout.write(self.style.ERROR(f'  #{pk} « {asset.name} » : REFUSÉ — {exc}'))
                failures += 1
                continue
            refs = ', '.join(f"{r['label']} : {r['mine']}" for r in plan['references']) or 'aucune'
            where = plan.get('to', '(déplacement au --apply)')
            self.stdout.write(f"  #{pk} « {plan['asset']} » {plan['from']} → {where} ; "
                              f"références par nom suivies : {refs}")
        if failures:
            raise CommandError(f'{failures} asset(s) non rendu(s)')
