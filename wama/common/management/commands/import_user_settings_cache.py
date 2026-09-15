"""
Recopie en BASE les réglages utilisateur qui ne vivaient que dans le cache Redis (2026-09-15).

La brique `common/utils/user_settings.py` est devenue durable (`ROADMAP §23.3bis`). Les réglages
déjà posés avant la bascule sont dans le cache, sous des clés `user_{id}_{app}_{nom}` — et au
format HISTORIQUE (la valeur brute, sans l'enveloppe de la brique durable). Cette commande les
recopie une fois ; elle ne supprime rien du cache (l'expiration s'en charge).

⚠ Une clé ne se découpe pas au `_` : un nom d'app en contient (`describer_01`, `face_analyzer`), un
nom de réglage aussi (`last_format_image`). L'app est reconnue parmi les apps CONNUES (catalogue,
jumelles de bac à sable comprises), la plus longue qui convient ; une clé sans app connue est
signalée et laissée de côté.

    python manage.py import_user_settings_cache            # simulation
    python manage.py import_user_settings_cache --apply
"""
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.management.base import BaseCommand


def known_apps() -> set:
    from wama.common.app_registry import APP_CATALOG
    return set(APP_CATALOG)


def parse_key(key: str, apps) -> tuple | None:
    """`user_{id}_{app}_{nom}` → (id, app, nom), ou None si aucune app connue ne convient."""
    if not key.startswith('user_'):
        return None
    head, _, rest = key[len('user_'):].partition('_')
    if not head.isdigit() or not rest:
        return None
    for app in sorted(apps, key=len, reverse=True):
        if rest.startswith(app + '_') and len(rest) > len(app) + 1:
            return int(head), app, rest[len(app) + 1:]
    return None


class Command(BaseCommand):
    help = "Recopie en base les réglages utilisateur encore stockés dans le seul cache Redis."

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true', help="Écrire en base (sinon : simulation).")

    def handle(self, *args, **opts):
        from wama.common.models import UserAppSetting

        client = cache._cache.get_client(None, write=False)
        pattern = cache.make_key('user_*')
        apps = known_apps()
        users = set(get_user_model().objects.values_list('pk', flat=True))
        copied, skipped, unknown = 0, 0, []
        for raw in client.scan_iter(match=pattern):
            full = raw.decode() if isinstance(raw, bytes) else raw
            key = full.split(':', 2)[2] if full.count(':') >= 2 else full
            parsed = parse_key(key, apps)
            if parsed is None:
                unknown.append(key)
                continue
            user_id, app, name = parsed
            if user_id not in users:
                skipped += 1
                continue
            value = cache.get(key)
            if isinstance(value, tuple) and len(value) == 2 and value[0] == 'v':
                value = value[1]                        # déjà au format de la brique durable
            if opts['apply']:
                _, created = UserAppSetting.objects.get_or_create(
                    user_id=user_id, app=app, name=name, defaults={'value': value})
                copied += int(created)
            else:
                copied += 1
        verbe = 'recopiés' if opts['apply'] else 'à recopier (simulation)'
        self.stdout.write(f"réglages {verbe} : {copied} ; utilisateur disparu : {skipped} ; "
                          f"app inconnue : {len(unknown)}")
        for key in unknown[:20]:
            self.stdout.write(f"  inconnue : {key}")
