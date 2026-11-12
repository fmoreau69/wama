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


#: Les règles de clé D'AVANT la bascule du 2026-11-12, telles que chaque `params.py` les déclarait
#: (`user_setting_key`) — recopiées ICI ce jour-là, quand les apps ont cessé de les porter : la
#: commande reste rejouable sur une base restaurée d'avant la bascule, et c'est le seul endroit où
#: ces règles existent encore. `'name'` : le nom du param du volet ; `'dom_id'` : l'identifiant
#: du volet ; un dict : {nom du param: ancienne clé}, les autres params du volet sous leur nom
#: (`None` = seuls ceux du dict se retenaient). Une app absente (jumelle, app née) : `'name'`,
#: la règle que le générateur émettait.
LEGACY_RULES = {
    'anonymizer': 'name', 'reader': 'name', 'describer': 'name', 'composer': 'name',
    'enhancer': 'dom_id', 'converter': 'dom_id', 'imager': 'dom_id',
    'transcriber': ({'enable_diarization': 'diarization',
                     'preprocess_audio': 'preprocessing_enabled'}, 'name'),
    'avatarizer': ({'tts_model': 'tts_model', 'language': 'language',
                    'voice_preset': 'voice_preset', 'animation_model': None}, 'name'),
    'synthesizer': ({'tts_model': 'preferred_tts_model', 'language': 'preferred_language',
                     'voice_preset': 'preferred_voice_preset', 'output_format': 'output_format',
                     'output_quality': 'output_quality'}, None),
}


def legacy_rule(app):
    """(règle de clé d'avant la bascule, réglages hors schéma) d'une app — `LEGACY_RULES` ; les
    réglages hors schéma se lisent toujours dans son `params.py` (`USER_SETTINGS_EXTRA`)."""
    from wama.common.utils.param_schema import (_params_location, _pget, panel_dom_id,
                                                panel_name_key)
    module_name, _attr = _params_location(app)
    try:
        module = importlib.import_module(module_name)
    except Exception:
        module = None
    base = {'name': panel_name_key, 'dom_id': panel_dom_id}
    if app in LEGACY_RULES:
        rule = LEGACY_RULES[app]
    elif getattr(module, 'user_setting_key', None):
        # Une jumelle pas encore régénérée porte la règle que le générateur lui a émise.
        return module.user_setting_key, dict(getattr(module, 'USER_SETTINGS_EXTRA', None) or {})
    else:
        # Jumelle au `params` recopié de sa source : la règle de sa source ; app née : le nom.
        from wama.common.sandbox import twin_source
        rule = LEGACY_RULES.get(twin_source(app), 'name')
    if isinstance(rule, tuple):
        named, rest = rule

        def old_key(p, named=named, rest=base.get(rest)):
            name = _pget(p, 'name')
            if name in named:
                return named[name]
            return rest(p) if rest else None
    else:
        old_key = base[rule]
    return old_key, dict(getattr(module, 'USER_SETTINGS_EXTRA', None) or {})


def app_mapping(app):
    """{domaine: {'schema', 'old', 'new', 'extra'}} et {ancienne clé: [nouvelles clés]} d'une app,
    ou (None, None) si elle ne déclare aucun domaine. `old`/`new` : la règle de clé, en fonction ;
    `extra` : {nom hors schéma: (ancienne clé, nouvelle clé, défaut)}."""
    from wama.common.utils.app_modes import domain_schema, get_domains, home_domain
    from wama.common.utils.param_schema import domain_key
    domains = [d.get('id') for d in get_domains(app)]
    if not domains:
        return None, None
    old_key, extra = legacy_rule(app)
    # Un réglage hors schéma va avec le schéma PRINCIPAL de l'app — c'est avec lui que le volet le
    # lit et le garde (`PANEL_SETTINGS`, l'anonymizer : `classes2blur` et l'image / vidéo, pas le
    # document, 2026-11-02). Il appartient donc au domaine qui porte ce schéma, s'il est seul ;
    # sinon la question n'a pas de réponse ici, et on refuse de deviner.
    home = home_domain(app)                # la règle que la brique `user_settings` applique
    homes = [home] if home else []
    surfaces, moves = {}, {}
    for dom in domains:
        schema = domain_schema(app, dom)
        new_key = domain_key(dom)
        dom_extra = ({n: (n, f'{dom}.{n}', dflt) for n, dflt in extra.items()}
                     if homes == [dom] else {})
        surfaces[dom] = {'schema': schema, 'old': old_key, 'new': new_key, 'extra': dom_extra}
        pairs = [(old_key(p), new_key(p)) for p in schema] + [(o, n) for o, n, _d in dom_extra.values()]
        for old, new in pairs:
            if old and new and new not in moves.setdefault(old, []):
                moves[old].append(new)
    if extra and len(homes) != 1:
        raise CommandError(f'{app} : réglages hors schéma sur une app à {len(domains)} domaines, '
                           'sans domaine unique pour son schéma principal')
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
