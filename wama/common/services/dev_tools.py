"""
Outils de DÉVELOPPEMENT de WAMA — la surface du serveur MCP « wama-dev » (ROADMAP §8d Phase 3,
étape 3).

⚠ CE MODULE N'EST JAMAIS CHARGÉ DANS LE PROCESS DE PRODUCTION. ROADMAP §16 : « outils dev/admin
dans un serveur MCP séparé/process distinct, JAMAIS chargés dans le process prod (défense en
profondeur > simple scope de jeton) ». Seul `run_mcp_server --surface dev` l'importe ; il n'est
ni dans `TOOL_REGISTRY` ni importé par `tool_api`. `tests_mcp_dev_tools` le garde.

CE QU'IL OUVRE (décision Fabien du 2026-09-15 : « rôles + bac à sable ») :
  • les RÔLES wama-dev-ai (librarian, model, scout, integrator, codegen) — ils écrivent une
    PROPOSITION dans `wama-dev-ai/outputs/` (PENDING_HUMAN_VALIDATION) et n'appliquent rien ;
  • le BAC À SABLE (`app_sandbox` : create, substitute, revert, drop, list) — l'app d'origine
    n'est jamais modifiée ;
  • le HARNAIS `app_regen_check`, SANS `--force` : sa garde (refus sur dev/main) reste entière ;
  • le RECHARGEMENT de gunicorn, qu'exigent create/drop/revert.

CE QU'IL NE FAIT PAS : appliquer une proposition (write_back, écriture dans `wama/`), commiter,
installer une librairie. La règle écrite en tête des outils de plan de `tool_api` vaut ici :
l'agent propose, l'humain valide.

TÂCHES LONGUES : un rôle ou une création de jumelle dure des minutes, bien au-delà du délai d'un
appel d'outil. Chaque lancement devient une TÂCHE détachée — journal et code de retour écrits
sous `logs/dev_jobs/` —, l'outil rend son identifiant et `dev_job_status` la suit. Les fichiers
survivent au redémarrage du serveur.

ARGUMENTS : chaque rôle déclare ceux qu'il admet ; tout autre est REFUSÉ, jamais transmis. Une
valeur qui commence par `-` (elle serait lue comme une option) ou contient un caractère de
contrôle est refusée. La commande est une liste d'arguments, jamais une chaîne interprétée.

DROITS : développeurs et administrateurs (`accounts.permissions.is_developer`), vérifiés à
CHAQUE appel — la liste des outils n'est qu'un confort.
"""
from __future__ import annotations

import inspect
import json
import os
import re
import shlex
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

from django.conf import settings

#: Rôles lançables et arguments ADMIS pour chacun. Nom = option CLI sans `--`, tirets en
#: soulignés ; `bool` = option sans valeur.
ROLES = {
    'librarian':  {'script': 'run_librarian.py',
                   'args': {'dist': str, 'repo': str}},
    'model':      {'script': 'run_model_manifest.py',
                   'args': {'catalog': str, 'hf': str, 'force': bool}},
    'scout':      {'script': 'run_scout.py',
                   'args': {'hf': str, 'dry_run': bool}},
    'integrator': {'script': 'run_integrator.py',
                   'args': {'manifest': str, 'besoin': str, 'dry_run': bool}},
    'codegen':    {'script': 'run_codegen.py',
                   'args': {'app': str, 'task': str, 'truth': str}},
}
SANDBOX_ACTIONS = ('create', 'substitute', 'revert', 'drop', 'list')

_UNSAFE_CHARS = re.compile(r'[\x00-\x1f]')
_JOB_ID = re.compile(r'^\d{8}-\d{6}-[0-9a-f]{6}$')
_OUTPUT_LINE = re.compile(r'(wama-dev-ai/outputs/[^\s\'"]+\.json)')
LOG_TAIL_CHARS = 6000


class DevToolError(ValueError):
    """Refus LISIBLE — rendu comme `{'error': …}`, jamais comme une trace."""


def base_dir() -> Path:
    return Path(settings.BASE_DIR)


def jobs_dir() -> Path:
    path = base_dir() / 'logs' / 'dev_jobs'
    path.mkdir(parents=True, exist_ok=True)
    return path


def outputs_dir() -> Path:
    return base_dir() / 'wama-dev-ai' / 'outputs'


def _clean(value, name: str) -> str:
    text = str(value)
    if not text or len(text) > 500 or _UNSAFE_CHARS.search(text) or text.startswith('-'):
        raise DevToolError(f"valeur refusée pour « {name} » : {text[:60]!r}")
    return text


# ── Construction des commandes — une LISTE d'arguments, jamais une chaîne ───────────────────

def role_command(role: str, args=None, provider: str = '', model: str = '') -> list:
    spec = ROLES.get(role)
    if spec is None:
        raise DevToolError(f"rôle inconnu : {role!r} (connus : {', '.join(sorted(ROLES))})")
    argv = [sys.executable, str(base_dir() / 'wama-dev-ai' / spec['script'])]
    for name, value in (args or {}).items():
        kind = spec['args'].get(name)
        if kind is None:
            raise DevToolError(f"argument « {name} » non admis pour le rôle {role} "
                               f"(admis : {', '.join(sorted(spec['args']))})")
        option = '--' + name.replace('_', '-')
        if kind is bool:
            if value in (True, 'true', 'True', '1', 1):
                argv.append(option)
            continue
        argv += [option, _clean(value, name)]
    if provider:
        argv += ['--provider', _clean(provider, 'provider')]
    if model:
        argv += ['--model', _clean(model, 'model')]
    return argv


def sandbox_command(action: str, app: str = '', target: str = '', owner: str = '') -> list:
    if action not in SANDBOX_ACTIONS:
        raise DevToolError(f"action inconnue : {action!r} (connues : {', '.join(SANDBOX_ACTIONS)})")
    argv = [sys.executable, str(base_dir() / 'manage.py'), 'app_sandbox', action]
    if action != 'list':
        if not app:
            raise DevToolError(f"« {action} » exige `app` (app source pour create, "
                               f"label de jumelle sinon)")
        argv.append(_clean(app, 'app'))
    if action in ('substitute', 'revert'):
        if not target:
            raise DevToolError(f"« {action} » exige `target` (apps, urls, models, params, "
                               f"tasks, views, templates)")
        argv.append(_clean(target, 'target'))
    if action == 'create' and owner:
        argv += ['--proprietaire', _clean(owner, 'owner')]
    return argv


def regen_check_command(app: str) -> list:
    """`--force` n'est JAMAIS ajouté : la garde du harnais (refus sur dev/main) reste entière."""
    return [sys.executable, str(base_dir() / 'manage.py'), 'app_regen_check',
            _clean(app, 'app'), '--json']


# ── Tâches détachées ─────────────────────────────────────────────────────────────────────────

def start_job(user, tool: str, argv: list) -> dict:
    """Lance `argv` détaché ; le journal et le code de retour sont écrits à côté de la fiche."""
    job_id = datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S-') + uuid.uuid4().hex[:6]
    directory = jobs_dir()
    log, rc = directory / f'{job_id}.log', directory / f'{job_id}.rc'
    script = f"{shlex.join(argv)} > {shlex.quote(str(log))} 2>&1; echo $? > {shlex.quote(str(rc))}"
    proc = subprocess.Popen(['bash', '-c', script], cwd=str(base_dir()),
                            start_new_session=True, stdin=subprocess.DEVNULL,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    meta = {'id': job_id, 'tool': tool, 'command': argv[1:],
            'user': getattr(user, 'username', ''), 'pid': proc.pid,
            'started_at': datetime.now(timezone.utc).isoformat(timespec='seconds')}
    (directory / f'{job_id}.json').write_text(json.dumps(meta, ensure_ascii=False, indent=1),
                                              encoding='utf-8')
    return {'job_id': job_id, 'status': 'running', 'tool': tool,
            'follow': "dev_job_status(job_id) — la tâche peut durer plusieurs minutes"}


def _pid_alive(pid) -> bool:
    try:
        os.kill(int(pid), 0)
        return True
    except (OSError, ValueError, TypeError):
        return False


def job_state(job_id: str, with_log: bool = True) -> dict:
    if not _JOB_ID.match(job_id or ''):
        raise DevToolError(f"identifiant de tâche invalide : {job_id!r}")
    directory = jobs_dir()
    meta_path = directory / f'{job_id}.json'
    if not meta_path.exists():
        raise DevToolError(f"tâche inconnue : {job_id}")
    state = json.loads(meta_path.read_text(encoding='utf-8'))
    rc_path, log_path = directory / f'{job_id}.rc', directory / f'{job_id}.log'
    if rc_path.exists():
        code = rc_path.read_text(encoding='utf-8').strip()
        state['status'] = 'done' if code == '0' else 'failed'
        state['returncode'] = int(code) if code.lstrip('-').isdigit() else code
    else:
        # Sans code de retour : vivant = en cours ; mort = interrompu (serveur ou machine arrêtés).
        state['status'] = 'running' if _pid_alive(state.get('pid')) else 'interrupted'
    if with_log and log_path.exists():
        text = log_path.read_text(encoding='utf-8', errors='replace')
        state['log_tail'] = text[-LOG_TAIL_CHARS:]
        state['outputs'] = sorted(set(_OUTPUT_LINE.findall(text)))
    return state


# ── Les outils ───────────────────────────────────────────────────────────────────────────────

def dev_run_role(user, role: str, args: dict = None, provider: str = '', model: str = '') -> dict:
    """Lance un rôle wama-dev-ai en tâche de fond ; il écrit une PROPOSITION en attente de validation, n'applique rien.

    role : librarian (args dist | repo), model (catalog | hf, force), scout (hf, dry_run),
    integrator (manifest, besoin, dry_run), codegen (app, task, truth). provider : ollama (local,
    charge le GPU) ou un fournisseur distant comme albert. model : modèle précis (sinon défaut du
    rôle). Rend job_id — suivre avec dev_job_status, lire la proposition avec dev_read_output.
    """
    return start_job(user, f'role:{role}', role_command(role, args, provider, model))


def dev_sandbox(user, action: str, app: str = '', target: str = '') -> dict:
    """Bac à sable d'apps en tâche de fond : create, substitute, revert, drop, list — l'app d'origine n'est jamais modifiée.

    create app=<app source> : jumelle <app>_NN dont le demandeur est le créateur. substitute /
    revert app=<jumelle> target=<apps|urls|models|params|tasks|views|templates>. drop
    app=<jumelle>. Après create, revert ou drop : dev_reload_web pour servir le changement.
    """
    owner = getattr(user, 'username', '') if action == 'create' else ''
    return start_job(user, f'sandbox:{action}', sandbox_command(action, app, target, owner))


def dev_regen_check(user, app: str) -> dict:
    """Harnais de régénération d'une app (app_regen_check) en tâche de fond — refusé sur dev/main par sa propre garde."""
    return start_job(user, 'regen_check', regen_check_command(app))


def dev_reload_web(user) -> dict:
    """Recharge gunicorn (signal HUP, rechargement gracieux) — nécessaire après la création, la restauration ou le retrait d'une jumelle."""
    # Motif `[g]unicorn` : un motif littéral se retrouverait dans la ligne de commande de ce
    # `pkill` lui-même, qui se signalerait (piège mesuré le 2026-09-15).
    res = subprocess.run(['pkill', '-HUP', '-f', '[g]unicorn wama.wsgi'],
                         capture_output=True, text=True)
    if res.returncode == 0:
        return {'reloaded': True}
    return {'error': "gunicorn introuvable — aucun rechargement (serveur arrêté ?)"}


def dev_job_status(user, job_id: str) -> dict:
    """État d'une tâche de développement : en cours, terminée, échouée ou interrompue ; fin du journal et propositions écrites."""
    return job_state(job_id)


def dev_list_jobs(user, limit: int = 20) -> dict:
    """Dernières tâches de développement lancées (tous développeurs), la plus récente d'abord."""
    fiches = sorted(jobs_dir().glob('*.json'), reverse=True)[:max(1, min(int(limit or 20), 100))]
    return {'jobs': [job_state(p.stem, with_log=False) for p in fiches]}


def dev_read_output(user, path: str) -> dict:
    """Lit une proposition écrite par un rôle (fichier JSON de wama-dev-ai/outputs/) — lecture seule."""
    root = outputs_dir().resolve()
    candidate = (base_dir() / path).resolve() if '/' in path else (root / path).resolve()
    if root not in candidate.parents or candidate.suffix != '.json' or not candidate.is_file():
        raise DevToolError(f"proposition introuvable dans wama-dev-ai/outputs/ : {path!r}")
    return {'path': str(candidate.relative_to(base_dir())),
            'content': json.loads(candidate.read_text(encoding='utf-8'))}


DEV_TOOLS = {fn.__name__: fn for fn in (dev_run_role, dev_sandbox, dev_regen_check, dev_reload_web,
                                         dev_job_status, dev_list_jobs, dev_read_output)}


# ── L'interface qu'attend `mcp_server` : lister, appeler ────────────────────────────────────

def tools_for(user) -> list:
    """Outils de développement visibles par `user` — aucun pour un non-développeur."""
    import mcp.types as types
    from wama.accounts.permissions import is_developer
    from wama.tool_api import input_schema_for

    if not is_developer(user):
        return []
    return [types.Tool(name=name, description=inspect.getdoc(fn) or '',
                       inputSchema=input_schema_for(fn))
            for name, fn in sorted(DEV_TOOLS.items())]


def call(user, name: str, arguments) -> dict:
    """Un appel d'outil de développement — droits vérifiés ICI, à chaque appel."""
    from wama.accounts.permissions import is_developer

    if not is_developer(user):
        return {'error': 'forbidden',
                'detail': "Outils de développement réservés aux développeurs et administrateurs."}
    fn = DEV_TOOLS.get(name)
    if fn is None:
        return {'error': f"Outil inconnu : {name!r}. Disponibles : {', '.join(sorted(DEV_TOOLS))}"}
    params = inspect.signature(fn).parameters
    clean = {k: v for k, v in dict(arguments or {}).items() if k in params and k != 'user'}
    try:
        return fn(user, **clean)
    except DevToolError as e:
        return {'error': str(e)}
    except TypeError as e:
        return {'error': f"Mauvais arguments pour {name!r} : {e}"}
