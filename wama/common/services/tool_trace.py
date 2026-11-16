"""
La TRACE des outils de l'assistant devenue une MESURE — `WAMA_HARNESS §9`, chantier 3 (écart 6).

POURQUOI (2026-11-16, demande de Fabien : « améliorer l'auto-diagnostic de WAMA […] voir là où ça
bloque, là où ce n'est pas correct […] avoir un suivi de tout ça, notamment les capacités de dev de
l'assistant »). Chaque tour persiste ses étapes d'outil (`ConversationTurn.tool_steps`) depuis
septembre ; rien n'en faisait une mesure. Le relevé du jour, sur les fils réels : 473 appels depuis
le 2026-09-28, 60 en échec — dont `dev_search_code` 4 sur 7, `dev_db_query` 3 sur 3,
`dev_run_role` 11 sur 42 —, et personne ne le savait.

TROIS PIÈCES, UNE PAR RÔLE :
  • `step` — LE constructeur d'une étape, pour chacun de ses écrivains (la boucle, les relances de
    fin de tâche, les familles suivies) : le verdict (`ok`) et, quand l'appel a été chronométré,
    sa durée (`seconds`). Le contrat du chantier : l'échec se lit dans un CHAMP.
  • `result_error` — LA règle d'échec, celle du contrat des outils (une erreur est
    `{'error': …}` ; `execute_tool` et le relais de développement ne lèvent jamais). Le moteur la
    lisait déjà pour dire les refus (`assistant_engine._refusals_notice`) : il la lit ici.
  • `usage` — le lecteur : par outil, appels, échecs, durée médiane, dernière date, surfaces, et
    les erreurs les plus fréquentes. Lu par `manage.py tool_usage` (donc par l'opération
    d'exploitation du même nom, que l'assistant lance), et par la page `/apps/`.

Une étape écrite AVANT le 2026-11-16 n'a pas de champ `ok` : `step_ok` lui applique la même règle,
la seule — ce n'est pas une réinterprétation outil par outil. Elle n'a pas de durée : la médiane
ne compte que les étapes chronométrées, et le dit (`timed`).

FRONTIÈRE (celle du chantier) : la trace s'arrête à l'assistant. Généraliser à toutes les apps est
`RunOutcome` au sens large, une autre décision.
"""
from __future__ import annotations

import statistics
import time
from collections import Counter
from datetime import timedelta

#: Longueur gardée d'un message d'erreur dans l'agrégat : assez pour reconnaître le motif, pas
#: assez pour emporter un document cité en entier.
ERROR_CHARS = 160
#: Messages d'erreur gardés par outil, les plus fréquents d'abord.
ERRORS_KEPT = 3

#: Les familles d'un outil, dans l'ordre où la page les montre — la clé est celle que rend
#: `family`, le libellé celui qu'affichent la commande et la page.
FAMILIES = {
    'development': 'Développement',
    'delegation': 'Délégation',
    'unknown': 'Inconnu',
    'transverse': 'Transverse',
}


def result_error(result) -> str:
    """L'erreur que porte le résultat d'un outil, '' s'il a abouti — LA règle (contrat des outils :
    une erreur est `{'error': …}`)."""
    if isinstance(result, dict) and result.get('error'):
        return str(result['error'])
    return ''


def step(tool: str, args, result, *, started: float | None = None, **extra) -> dict:
    """Une étape d'outil telle que la trace la garde : `{tool, args, result, ok[, seconds]}` et ce
    que l'écrivain y ajoute (`automatic`, `sub_agents`…). `started` : l'instant `time.monotonic()`
    pris avant l'appel — sans lui, aucune durée n'est inventée."""
    out = {'tool': tool, 'args': args, 'result': result, 'ok': not result_error(result)}
    if started is not None:
        out['seconds'] = round(time.monotonic() - started, 3)
    out.update(extra)
    return out


def step_ok(entry: dict) -> bool:
    """L'étape a-t-elle abouti ? Son champ `ok` ; pour une étape écrite avant lui, la même règle."""
    if 'ok' in entry:
        return bool(entry['ok'])
    return not result_error(entry.get('result'))


def family(tool: str) -> str:
    """La famille d'un outil : `development` (surface de développement, `dev_*`), `delegation`
    (le verbe de la boucle qui lance des sous-agents), `unknown` (un nom qu'aucun registre ne
    déclare — inventé par le modèle, ou un outil retiré), sinon l'app qui GARDE l'outil
    (`tool_api.app_id_for_tool`), ou `transverse`."""
    from wama.common.services import mcp_client
    from wama.common.services.assistant_engine import DELEGATE_TOOL
    from wama.tool_api import TOOL_REGISTRY, app_id_for_tool
    if mcp_client.is_dev_tool(tool):
        return 'development'
    if tool == DELEGATE_TOOL:
        return 'delegation'
    if tool not in TOOL_REGISTRY:
        return 'unknown'
    return app_id_for_tool(tool) or 'transverse'


def _walk(steps, depth: int = 0):
    """Les étapes d'un tour, celles de ses sous-agents comprises : `(étape, profondeur)`."""
    for entry in steps or ():
        if not isinstance(entry, dict) or not entry.get('tool'):
            continue
        yield entry, depth
        for agent in entry.get('sub_agents') or ():
            yield from _walk((agent or {}).get('steps'), depth + 1)


def callable_tools() -> set:
    """Les outils que l'assistant peut appeler : le registre, la surface de développement, et le
    verbe de délégation de la boucle."""
    from wama.common.services.assistant_engine import DELEGATE_TOOL
    from wama.common.services.dev_tools import DEV_TOOLS
    from wama.tool_api import TOOL_REGISTRY
    return set(TOOL_REGISTRY) | set(DEV_TOOLS) | {DELEGATE_TOOL}


def usage(days: int | None = None) -> dict:
    """Ce que les fils persistés disent des outils, sur les `days` derniers jours (tout, sinon).

    `{'since', 'turns', 'calls', 'failures', 'tools': [ligne…], 'families': {famille: {calls,
    failures, tools}}, 'never_called': [noms]}` — une ligne par outil appelé, les plus en échec
    d'abord : `{tool, family, calls, failures, automatic, sub_agent, timed, median_seconds, last,
    surfaces, errors: [(message, n)]}`. Lecture seule ; aucune donnée d'utilisateur n'en sort hors
    des messages d'erreur, que seul le relevé détaillé (`manage.py tool_usage`) affiche."""
    from django.utils import timezone

    from wama.common.models import ConversationTurn

    turns = ConversationTurn.objects.filter(role='assistant').exclude(tool_steps=[])
    if days:
        turns = turns.filter(created_at__gte=timezone.now() - timedelta(days=int(days)))
    rows, first, count = {}, None, 0
    for created, surface, steps in turns.values_list(
            'created_at', 'conversation__surface', 'tool_steps').iterator():
        count += 1
        first = created if first is None or created < first else first
        for entry, depth in _walk(steps):
            name = str(entry['tool'])
            row = rows.get(name)
            if row is None:
                row = rows[name] = {'tool': name, 'calls': 0, 'failures': 0, 'automatic': 0,
                                    'sub_agent': 0, 'seconds': [], 'last': None,
                                    'surfaces': Counter(), 'errors': Counter()}
            row['calls'] += 1
            row['automatic'] += bool(entry.get('automatic'))
            row['sub_agent'] += depth > 0
            row['surfaces'][surface] += 1
            row['last'] = created if row['last'] is None or created > row['last'] else row['last']
            if isinstance(entry.get('seconds'), (int, float)):
                row['seconds'].append(entry['seconds'])
            if not step_ok(entry):
                row['failures'] += 1
                row['errors'][result_error(entry.get('result'))[:ERROR_CHARS] or '?'] += 1

    tools, families = [], {}
    for row in rows.values():
        seconds = row.pop('seconds')
        row.update(family=family(row['tool']), timed=len(seconds),
                   median_seconds=round(statistics.median(seconds), 2) if seconds else None,
                   last=row['last'].date().isoformat(), surfaces=dict(row['surfaces']),
                   errors=row['errors'].most_common(ERRORS_KEPT))
        tools.append(row)
        total = families.setdefault(row['family'], {'calls': 0, 'failures': 0, 'tools': 0})
        total['calls'] += row['calls']
        total['failures'] += row['failures']
        total['tools'] += 1
    tools.sort(key=lambda r: (-r['failures'], -r['calls'], r['tool']))
    return {'since': first.date().isoformat() if first else None, 'days': days, 'turns': count,
            'calls': sum(r['calls'] for r in tools), 'failures': sum(r['failures'] for r in tools),
            'tools': tools, 'families': families,
            'never_called': sorted(callable_tools() - set(rows))}
