"""
Range les préférences des volets sous LA clé commune `<domaine>.<nom>` (2026-10-21, chantier ⑥
« une seule règle pour tous », `param_schema.domain_key`).

Trois règles coexistaient en base (mesuré) : le `dom_id` du volet (enhancer, converter, imager —
le défaut de `user_settings`), le NOM du param (reader, describer, anonymizer, composer, et les
jumelles générées), et des règles écrites en code (transcriber : deux noms anciens ; avatarizer :
la voix retenue hors du volet, le modèle d'animation jamais ; synthesizer : la voix sous
`preferred_*`). Chaque règle est lue ICI dans le `params.py` de l'app (`user_setting_key`, sinon le
`dom_id`), une fois, pour écrire le PLAN — après quoi les apps n'ont plus à la garder.

Trois temps, et rien ne s'écrit sans le second :
  1. sans option : le RELEVÉ, et le plan écrit dans `logs/setting_keys/plan_<horodatage>.json` —
     chaque ligne déplacée (compte, app, ancienne clé, nouvelles clés, valeur) et la PREUVE, par
     compte, app et domaine : le volet que la brique rendrait avant et après est le même ;
  2. `--apply <plan>` : exécute CE plan, et lui seul — il refuse tout si une ligne a changé
     depuis (valeur modifiée, ligne retirée, clé cible déjà prise avec une autre valeur) ;
  3. `--revert <plan>` : remet les lignes d'avant, à l'identique, et retire celles créées.
Le cache de lecture (`user_settings`) des clés touchées est vidé dans les deux sens.

Ce que la commande ne déplace pas, et le dit : les lignes d'une app sans domaine déclaré
(`assistant`, `common` — des réglages de surface, pas de volet d'app) et les lignes qu'aucune
règle ne désigne (`last_format_*` du converter, retenu par nature hors de la cascade).
"""
import importlib
import json
from datetime import datetime
from pathlib import Path

from django.conf import settings
from django.core.cache import cache
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

PLAN_DIR = Path(settings.BASE_DIR) / 'logs' / 'setting_keys'


def legacy_rule(app):
    """(règle de clé d'avant, réglages hors schéma) d'une app — lus dans son `params.py`."""
    from wama.common.utils.param_schema import _params_location, panel_dom_id
    module_name, _attr = _params_location(app)
    try:
        module = importlib.import_module(module_name)
    except Exception:
        return panel_dom_id, {}
    return (getattr(module, 'user_setting_key', None) or panel_dom_id,
            dict(getattr(module, 'USER_SETTINGS_EXTRA', None) or {}))


def app_mapping(app):
    """{domaine: {'schema', 'old', 'new', 'extra'}} et {ancienne clé: [nouvelles clés]} d'une app,
    ou (None, None) si elle ne déclare aucun domaine. `old`/`new` : la règle de clé, en fonction ;
    `extra` : {nom hors schéma: (ancienne clé, nouvelle clé, défaut)}."""
    from wama.common.utils.app_modes import domain_schema, get_domains
    from wama.common.utils.param_schema import domain_key
    domains = [d.get('id') for d in get_domains(app)]
    if not domains:
        return None, None
    old_key, extra = legacy_rule(app)
    surfaces, moves = {}, {}
    for dom in domains:
        schema = domain_schema(app, dom)
        new_key = domain_key(dom)
        # Un réglage hors schéma appartient au domaine quand il n'y en a qu'un ; à plusieurs, la
        # question n'a pas de réponse ici — aucune app ne le fait (mesuré), on refuse de deviner.
        dom_extra = {n: (n, f'{dom}.{n}', dflt) for n, dflt in extra.items()} if len(domains) == 1 else {}
        surfaces[dom] = {'schema': schema, 'old': old_key, 'new': new_key, 'extra': dom_extra}
        pairs = [(old_key(p), new_key(p)) for p in schema] + [(o, n) for o, n, _d in dom_extra.values()]
        for old, new in pairs:
            if old and new and new not in moves.setdefault(old, []):
                moves[old].append(new)
    if extra and len(domains) > 1:
        raise CommandError(f'{app} : réglages hors schéma sur une app à {len(domains)} domaines')
    return surfaces, moves


def panel_view(stored, surface, side):
    """Le volet tel que la brique le rend (`user_settings.read_panel_settings`), sur `stored` —
    par NOM de param : défauts du schéma sous ce qui est stocké, réglages hors schéma compris."""
    from wama.common.utils.param_schema import panel_defaults, panel_values_by_name
    key = surface[side]
    defaults = panel_defaults(surface['schema'], key=key)
    full = {k: stored.get(k, v) for k, v in defaults.items()}
    values = panel_values_by_name(full, surface['schema'], key=key)
    for name, (old, new, default) in surface['extra'].items():
        values[name] = stored.get(old if side == 'old' else new, default)
    return values


def build_plan():
    """Le plan entier (dict JSON) : lignes déplacées, lignes laissées et pourquoi, preuve."""
    from wama.common.models import UserAppSetting
    from wama.common.utils.param_schema import _pget
    rows = list(UserAppSetting.objects.order_by('app', 'user_id', 'name')
                .values('user_id', 'app', 'name', 'value'))
    plan = {'created': datetime.now().isoformat(timespec='seconds'), 'moves': [], 'left': [],
            'proof': []}
    for app in sorted({r['app'] for r in rows}):
        surfaces, moves = app_mapping(app)
        app_rows = [r for r in rows if r['app'] == app]
        if surfaces is None:
            plan['left'] += [dict(r, why='app sans domaine déclaré') for r in app_rows]
            continue
        for r in app_rows:
            if r['name'] in moves:
                plan['moves'].append(dict(r, new=moves[r['name']]))
            elif r['name'].split('.', 1)[0] in surfaces and '.' in r['name']:
                plan['left'].append(dict(r, why='déjà sous la clé commune'))
            else:
                plan['left'].append(dict(r, why='aucune règle ne désigne cette clé'))
        for user_id in sorted({r['user_id'] for r in app_rows}):
            before = {r['name']: r['value'] for r in app_rows if r['user_id'] == user_id}
            after = {k: v for k, v in before.items() if k not in moves}
            for old, news in moves.items():
                if old in before:
                    after.update({n: before[old] for n in news})
            for dom, surface in surfaces.items():
                was, now = panel_view(before, surface, 'old'), panel_view(after, surface, 'new')
                default = panel_view({}, surface, 'old')
                # Un réglage qu'une règle ne retient pas s'affiche à son défaut du schéma.
                schema_default = {_pget(p, 'name'): _pget(p, 'default') for p in surface['schema']}
                diff = sorted(n for n in set(was) | set(now)
                              if was.get(n, schema_default.get(n)) != now.get(n, schema_default.get(n)))
                plan['proof'].append({'user_id': user_id, 'app': app, 'domain': dom,
                                      'identical': not diff, 'differs': diff,
                                      'set_by_user': sorted(n for n, v in was.items()
                                                            if v != default.get(n))})
    return plan


def _forget_cache(user_id, app, names):
    cache.delete_many([f'user_{user_id}_{app}_{n}' for n in names])


class Command(BaseCommand):
    help = ("Range les préférences des volets sous la clé commune <domaine>.<nom>. Sans option : "
            "relevé, preuve et plan écrit ; --apply <plan> l'exécute ; --revert <plan> le défait.")

    def add_arguments(self, parser):
        group = parser.add_mutually_exclusive_group()
        group.add_argument('--apply', metavar='PLAN', help="Exécuter ce plan (et lui seul).")
        group.add_argument('--revert', metavar='PLAN', help="Remettre les lignes d'avant ce plan.")

    def handle(self, *args, **opts):
        if opts['apply']:
            return self._apply(self._load(opts['apply']))
        if opts['revert']:
            return self._revert(self._load(opts['revert']))
        plan = build_plan()
        PLAN_DIR.mkdir(parents=True, exist_ok=True)
        path = PLAN_DIR / f"plan_{plan['created'].replace(':', '').replace('-', '')}.json"
        path.write_text(json.dumps(plan, ensure_ascii=False, indent=1, default=str), encoding='utf-8')
        self._report(plan)
        self.stdout.write(f'Plan écrit : {path}')

    def _load(self, path):
        try:
            return json.loads(Path(path).read_text(encoding='utf-8'))
        except (OSError, ValueError) as exc:
            raise CommandError(f'Plan illisible : {exc}')

    def _report(self, plan):
        by_app = {}
        for m in plan['moves']:
            by_app.setdefault(m['app'], []).append(m)
        for app, moves in sorted(by_app.items()):
            self.stdout.write(f"{app} — {len(moves)} ligne(s), "
                              f"{len({m['user_id'] for m in moves})} compte(s)")
            for old, new in sorted({(m['name'], ', '.join(m['new'])) for m in moves}):
                self.stdout.write(f'    {old} → {new}')
        for why in sorted({l['why'] for l in plan['left']}):
            names = sorted({f"{l['app']}:{l['name']}" for l in plan['left'] if l['why'] == why})
            self.stdout.write(f"laissées ({why}) : {len(names)} — {', '.join(names[:12])}"
                              + (' …' if len(names) > 12 else ''))
        bad = [p for p in plan['proof'] if not p['identical']]
        for p in bad:
            self.stdout.write(self.style.ERROR(
                f"  DIFFÉRENT compte {p['user_id']} {p['app']}/{p['domain']} : {', '.join(p['differs'])}"))
        n = len(plan['proof'])
        style = self.style.SUCCESS if not bad else self.style.ERROR
        self.stdout.write(style(f'Preuve : {n - len(bad)}/{n} volet(s) identique(s) avant/après '
                                f"({len({p['user_id'] for p in plan['proof']})} compte(s))."))

    def _apply(self, plan):
        from wama.common.models import UserAppSetting
        if any(not p['identical'] for p in plan['proof']):
            raise CommandError('La preuve de ce plan n’est pas identique partout : refusé.')
        with transaction.atomic():
            for m in plan['moves']:
                row = UserAppSetting.objects.select_for_update().filter(
                    user_id=m['user_id'], app=m['app'], name=m['name']).first()
                if row is None or row.value != m['value']:
                    raise CommandError(f"{m['app']}:{m['name']} (compte {m['user_id']}) a changé "
                                       'depuis le plan : refait le relevé.')
                for new in m['new']:
                    taken = UserAppSetting.objects.filter(user_id=m['user_id'], app=m['app'],
                                                          name=new).first()
                    if taken is not None and taken.value != m['value']:
                        raise CommandError(f"{m['app']}:{new} (compte {m['user_id']}) existe déjà "
                                           'avec une autre valeur.')
                    UserAppSetting.objects.update_or_create(
                        user_id=m['user_id'], app=m['app'], name=new, defaults={'value': m['value']})
                row.delete()
        for m in plan['moves']:
            _forget_cache(m['user_id'], m['app'], [m['name'], *m['new']])
        self.stdout.write(self.style.SUCCESS(f"{len(plan['moves'])} ligne(s) rangée(s) sous la clé commune."))

    def _revert(self, plan):
        from wama.common.models import UserAppSetting
        with transaction.atomic():
            for m in plan['moves']:
                UserAppSetting.objects.filter(user_id=m['user_id'], app=m['app'],
                                              name__in=m['new']).delete()
                UserAppSetting.objects.update_or_create(
                    user_id=m['user_id'], app=m['app'], name=m['name'], defaults={'value': m['value']})
        for m in plan['moves']:
            _forget_cache(m['user_id'], m['app'], [m['name'], *m['new']])
        self.stdout.write(self.style.SUCCESS(f"{len(plan['moves'])} ligne(s) remise(s) comme avant le plan."))
