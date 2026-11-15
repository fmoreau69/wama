"""
WAMA Common — les touches d'une brique RÉGLÉES PAR UN COMPTE (2026-11-15, `WAMA_VOLETS §3-ter`,
décision de Fabien du 12/11 : « un utilisateur personnalise ses raccourcis, par brique »).

Troisième étage de la résolution : défaut de la brique (`UIBrick.shortcuts`), puis préréglage de
la page (`surfaces.KEYS_OPTION`), puis CE réglage. Une surcharge par brique, `{action: [touches]}`
— la forme même du préréglage d'une page, validée par la même règle
(`surfaces.override_problems`) et résolue par la même (`resolve_shortcuts`, `WamaKeys.remap`).

Gardé comme tout réglage de compte (`user_settings`, sous l'app `common`), en UN réglage pour
toutes les briques (chaque page le lit : une seule lecture). Seul ce que l'utilisateur a POSÉ est
écrit ; rétablir une brique retire son entrée, elle reprend les défauts du jour.
"""
from wama.common.utils.user_settings import (clear_user_app_settings, get_user_app_setting,
                                             save_user_app_settings)

#: Où le réglage est gardé : `UserAppSetting(app='common', name='keys')`, `{brique: {action: [touches]}}`.
SETTINGS_APP = 'common'
SETTING = 'keys'


def remappable_bricks() -> list:
    """Les briques dont une touche peut se régler : celles qui NOMMENT leurs actions."""
    from wama.common.surfaces import BRICKS, load_all
    load_all()
    return [key for key, brick in BRICKS.items() if any(s.names for s in brick.shortcuts)]


def user_keymap(user) -> dict:
    """`{brique: {action: [touches]}}` de ce que `user` a réglé — {} pour un visiteur. Une
    entrée devenue inapplicable (une brique retirée, une action qu'elle ne nomme plus) est
    ignorée, jamais servie : le clavier commun ne reçoit que ce que la brique sait lire."""
    if not (user is not None and getattr(user, 'is_authenticated', False)):
        return {}
    stored = get_user_app_setting(user, SETTINGS_APP, SETTING)
    if not isinstance(stored, dict) or not stored:
        return {}
    from wama.common.surfaces import override_problems
    known = set(remappable_bricks())
    found = {}
    for brick, table in stored.items():
        if brick not in known or not isinstance(table, dict):
            continue
        kept = {name: keys for name, keys in table.items()
                if not override_problems(brick, {name: keys})}
        if kept and not override_problems(brick, kept):
            found[brick] = kept
    return found


def account_conflicts(account_keys) -> dict:
    """Les conflits que le réglage d'un compte CRÉE : `{brique: {touche: [phrase]}}` — une touche
    que deux briques d'une même page prennent (`surfaces.key_conflicts`), cherchée sur chaque
    surface déclarée et sur les briques de page (toutes présentes sur une page d'app). Les deux
    briques sont nommées : corriger l'une ou l'autre lève le conflit. {} sans réglage — les
    pages déclarées n'ont aucun conflit (tenu par `BrickShortcutsTest`)."""
    if not account_keys:
        return {}
    from types import SimpleNamespace

    from wama.common.app_registry import app_identity
    from wama.common.surfaces import BRICKS, SURFACES, key_conflicts, load_all
    load_all()
    pages = [("les pages d'application",
              [SimpleNamespace(brick=key, options={}) for key, b in BRICKS.items() if b.is_page])]
    pages += [(f"{app_identity(s.app)['label']} · {s.label}", s.slots) for s in SURFACES.values()]
    found = {}
    for where, slots in pages:
        for key, first, second in key_conflicts(slots, account_keys):
            for mine, other in ((first, second), (second, first)):
                said = f"aussi prise par « {BRICKS[other].name} » sur {where}"
                phrases = found.setdefault(mine, {}).setdefault(key, [])
                if said not in phrases:
                    phrases.append(said)
    return found


def key_rows(brick: str, account_keys=None, conflicts=None) -> list:
    """Les raccourcis de `brick` tels que ce compte les lit, une ligne par raccourci, une entrée
    par touche : `[{action, where, keys: [{key, label, name, conflict}]}]` — `name` vide pour une
    touche que rien ne surcharge (Échap, une touche tapée dans un champ) ; `conflict` dit avec
    quelle brique et sur quelle page la touche est en conflit (`account_conflicts`), '' sinon.
    Ce que la page des briques rend, et ce que l'enregistrement d'une touche lui renvoie."""
    from wama.common.surfaces import BRICKS, key_label, resolve_shortcuts
    clashing = (conflicts or {}).get(brick, {})
    rows = []
    for shortcut in resolve_shortcuts(BRICKS[brick].shortcuts, (account_keys or {}).get(brick)):
        names = list(shortcut.names) + [''] * (len(shortcut.keys) - len(shortcut.names))
        rows.append({'action': shortcut.action, 'where': shortcut.to_dict()['where'],
                     'keys': [{'key': key, 'label': key_label(key), 'name': name,
                               'conflict': ' ; '.join(clashing.get(key, []))}
                              for key, name in zip(shortcut.keys, names)]})
    return rows


def key_settings(user) -> dict:
    """Ce que la page des briques donne à son module (`wama-key-settings.js`) : par brique
    réglable, ses lignes (conflits dits) et ce que le compte a posé."""
    account_keys = user_keymap(user)
    conflicts = account_conflicts(account_keys)
    return {key: {'rows': key_rows(key, account_keys, conflicts),
                  'keys': account_keys.get(key, {})} for key in remappable_bricks()}


def save_user_keys(user, brick: str, override) -> list:
    """Garde les touches que `user` donne aux actions de `brick` (`{action: [touches]}`, la
    surcharge ENTIÈRE de la brique ; vide : la rétablir). Rend ce qui la rend inapplicable —
    [] quand elle est gardée."""
    from wama.common.surfaces import override_problems
    if brick not in remappable_bricks():
        return [f"la brique {brick} ne nomme aucune action"]
    problems = override_problems(brick, override) if override else []
    if problems:
        return problems
    stored = get_user_app_setting(user, SETTINGS_APP, SETTING)
    tables = dict(stored) if isinstance(stored, dict) else {}
    tables.pop(brick, None)
    if override:
        tables[brick] = {name: list(keys) for name, keys in override.items()}
    if tables:
        save_user_app_settings(user, SETTINGS_APP, {SETTING: tables})
    else:
        clear_user_app_settings(user, SETTINGS_APP, [SETTING])
    return []
