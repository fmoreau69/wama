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
  • le BAC À SABLE (`app_sandbox` : create, substitute, revert, remove, list) — l'app d'origine
    n'est jamais modifiée ;
  • le HARNAIS `app_regen_check`, SANS `--force` : sa garde (refus sur dev/main) reste entière ;
  • le RECHARGEMENT de gunicorn, qu'exigent create/remove/revert.

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
import logging
import os
import re
import shlex
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

from django.conf import settings

logger = logging.getLogger(__name__)

#: Rôles lançables et arguments ADMIS pour chacun. Nom = option CLI sans `--`, tirets en
#: soulignés ; `bool` = option sans valeur.
ROLES = {
    'librarian':  {'script': 'run_librarian.py',
                   'args': {'dist': str, 'repo': str}},
    'model':      {'script': 'run_model_manifest.py',
                   'args': {'catalog': str, 'hf': str, 'force': bool}},
    # `seed_candidate` / `candidate` (2026-09-29) : les deux options qui branchent le scout et
    # l'integrator sur la ROUTE D'INSTALLATION (candidat `proposed:` → bouton « Installer »)
    # existent en CLI depuis le 19/09 ; la surface dev ne les admettait pas, et l'assistant ne
    # pouvait donc produire que des fichiers d'`outputs/` qui se périment.
    'scout':      {'script': 'run_scout.py',
                   'args': {'hf': str, 'dry_run': bool, 'seed_candidate': bool}},
    'integrator': {'script': 'run_integrator.py',
                   'args': {'manifest': str, 'candidate': str, 'besoin': str, 'dry_run': bool}},
    'codegen':    {'script': 'run_codegen.py',
                   'args': {'app': str, 'task': str, 'truth': str}},
    # Marche B2 (2026-09-29) : écrit le BACKEND d'un modèle installé ; sa proposition se valide
    # au model manager, qui seul l'écrit dans wama/common/backends/.
    'backend':    {'script': 'run_backend.py',
                   'args': {'catalog': str, 'dry_run': bool, 'no_smoke': bool}},
    # Tâche de DÉVELOPPEMENT (2026-10-15, décision de Fabien : levée progressive de la règle
    # « wama-dev-ai ne touche pas au code ») — l'autre voie, à côté de la génération et de
    # l'intégration. Lecture seule, ou édits PROPOSÉS ; `--apply` n'est volontairement pas admis.
    'task':       {'script': 'run_task.py',
                   'args': {'task': str, 'files': str, 'write': bool}},
    # Brouillon du manifeste `app` d'une app NOUVELLE (2026-10-15, même décision) : le maillon de
    # la route « dépôt → app » qu'aucun rôle ne produisait (ROUTE §10.5). L'app naît ensuite par
    # `dev_sandbox(action="create", manifest=…)`, dans le bac à sable.
    'app':        {'script': 'run_app_manifest.py',
                   'args': {'key': str, 'need': str, 'like': str, 'requires': str,
                            'dry_run': bool}},
    # La chaîne « dépôt → app » en UNE tâche : librarian → app → naissance au bac à sable. Les fins
    # de tâche sont annoncées, elles ne relancent pas l'assistant — rôle par rôle, la route
    # attendait un « continue » humain à chaque marche.
    'repo_app':   {'script': 'run_repo_app.py',
                   'args': {'repo': str, 'key': str, 'need': str, 'like': str,
                            'no_sandbox': bool}},
}
SANDBOX_ACTIONS = ('create', 'substitute', 'revert', 'remove', 'list')

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


#: Longueur maximale d'une valeur passée en option de ligne de commande à un rôle.
MAX_VALUE_CHARS = 500


def _clean(value, name: str) -> str:
    # Le refus dit POURQUOI (2026-10-12, fil Discord #43) : « valeur refusée : 'Permettre à
    # l'API assistant de lire le contenu texte des sor' » ne disait ni la longueur ni la règle,
    # et le modèle a dû deviner en raccourcissant au hasard.
    text = str(value)
    if not text:
        reason = "valeur vide"
    elif len(text) > MAX_VALUE_CHARS:
        reason = f"{len(text)} caractères, {MAX_VALUE_CHARS} au plus"
    elif _UNSAFE_CHARS.search(text):
        reason = "saut de ligne ou caractère de contrôle — une seule ligne"
    elif text.startswith('-'):
        reason = "commence par « - » (lu comme une option)"
    else:
        return text
    raise DevToolError(f"valeur refusée pour « {name} » ({reason}) : {text[:60]!r}…")


# ── Construction des commandes — une LISTE d'arguments, jamais une chaîne ───────────────────

def role_command(role: str, args=None, provider: str = '', model: str = '') -> list:
    spec = ROLES.get(role)
    if spec is None:
        raise DevToolError(f"rôle inconnu : {role!r} (connus : {', '.join(sorted(ROLES))})")
    # Vécu le 2026-10-15 : `args="repo=…, key=…"` (une CHAÎNE) rendait une erreur Python brute
    # (« 'str' object has no attribute 'items' ») — le modèle s'est corrigé seul, au jugé.
    if args is not None and not isinstance(args, dict):
        raise DevToolError(f"`args` doit être un OBJET {{nom: valeur}} — ex. "
                           f"{{\"{next(iter(spec['args']))}\": \"…\"}} —, pas une chaîne")
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


def role_model(user, provider: str = '', model: str = '') -> dict:
    """Le modèle d'un rôle, TIRÉ pour le compte qui le lance : `{'key', 'provider', 'model',
    'note'}` — `provider`/`model` sont ce que le rôle reçoit en `--provider`/`--model`.

    POURQUOI ICI (2026-10-13). Le rôle est un process détaché : il ne connaît pas le compte, et
    son propre tirage (`role_utils.resolve_model`) se faisait donc SANS lui — local seulement, le
    profil cloud et les clés de l'utilisateur ignorés ; un `provider` distant prenait le modèle
    par défaut du fournisseur, hors niveau développement. La surface, elle, connaît le compte :
    elle tire avec la brique commune (`development_models.development_model`, au-dessus du
    sélecteur `select_model`) et passe le modèle RÉSOLU. Un seul tirage : le modèle que la fiche
    annonce est celui qui répond.

    `provider` borne le tirage à ce fournisseur ; `model` est un choix, respecté s'il a le niveau,
    REMPLACÉ sinon — `note` le dit, pour que l'assistant ne raconte pas le modèle demandé."""
    from wama.common.services.development_models import development_model, development_refusal
    from wama.common.utils.model_keys import catalog_key, split_key

    requested = catalog_key(_clean(model, 'model'), provider or 'ollama') if model else None
    key = development_model(user, requested, source=provider)
    if not key:
        raise DevToolError(development_refusal(user, source=provider))
    source, model_id = split_key(key)
    note = ''
    if requested and key != requested:
        note = f"{requested} n'a pas le niveau développement : remplacé par {key}"
    return {'key': key, 'provider': source, 'model': model_id, 'note': note}


def sandbox_manifest(path: str) -> str:
    """Le manifeste d'où une app naît DE ZÉRO — un brouillon du corpus (`manifests/app_drafts/`)
    ou une sortie du rôle `app` (`wama-dev-ai/outputs/app_*.manifest.json`), rien d'autre : la
    surface ne fait pas naître une app d'un fichier quelconque du disque."""
    from wama.common.manifests.codegen.pipeline_decl import DRAFTS_DIR
    rel = _clean(path, 'manifest').replace('\\', '/').removeprefix('./')
    full = (base_dir() / rel).resolve()
    drafts = (base_dir() / DRAFTS_DIR).resolve()
    allowed = (full.parent == drafts and full.suffix == '.json') or (
        full.parent == outputs_dir().resolve() and full.name.startswith('app_')
        and full.name.endswith('.manifest.json'))
    if not allowed or not full.is_file():
        raise DevToolError(f"manifeste refusé : {rel!r} — un brouillon de manifests/app_drafts/ "
                           "ou une sortie du rôle app (wama-dev-ai/outputs/app_*.manifest.json)")
    return full.relative_to(base_dir()).as_posix()


def sandbox_command(action: str, app: str = '', target: str = '', owner: str = '',
                    manifest: str = '') -> list:
    if action not in SANDBOX_ACTIONS:
        raise DevToolError(f"action inconnue : {action!r} (connues : {', '.join(SANDBOX_ACTIONS)})")
    argv = [sys.executable, str(base_dir() / 'manage.py'), 'app_sandbox', action]
    if action == 'create' and manifest:
        argv += ['--from-manifest', sandbox_manifest(manifest)]
        if owner:
            argv += ['--owner', _clean(owner, 'owner')]
        return argv
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
        argv += ['--owner', _clean(owner, 'owner')]
    return argv


def regen_check_command(app: str) -> list:
    """`--force` n'est JAMAIS ajouté : la garde du harnais (refus sur dev/main) reste entière."""
    return [sys.executable, str(base_dir() / 'manage.py'), 'app_regen_check',
            _clean(app, 'app'), '--json']


# ── Tâches détachées ─────────────────────────────────────────────────────────────────────────

#: Ce que le résultat d'un lancement dit au modèle (2026-10-12, fil Discord #43) : l'assistant
#: suivait la tâche DANS son tour — cinq `dev_job_status` d'affilée, six minutes pendant
#: lesquelles il ne répondait à rien. La fin arrive désormais d'elle-même (`notify_finished_jobs`).
JOB_STARTED_NOTICE = ("Tâche lancée en ARRIÈRE-PLAN. Ne la suis pas dans ce tour : réponds "
                      "maintenant à l'utilisateur. Sa fin sera annoncée dans ce fil et dans les "
                      "notifications de WAMA ; dev_job_status ne sert que si l'utilisateur "
                      "demande où elle en est.")


def start_job(user, tool: str, argv: list, env: dict = None, shown: list = None) -> dict:
    """Lance `argv` détaché ; le journal et le code de retour sont écrits à côté de la fiche.

    `env` : l'environnement du process (sinon celui du serveur) — un SECRET y passe (jeton
    personnel de Claude Code), jamais dans `argv`, qui est écrit dans la fiche et le script.
    `shown` : la commande telle que la fiche la montre (par défaut `argv` sans l'exécutable)."""
    job_id = datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S-') + uuid.uuid4().hex[:6]
    directory = jobs_dir()
    log, rc = directory / f'{job_id}.log', directory / f'{job_id}.rc'
    script = f"{shlex.join(argv)} > {shlex.quote(str(log))} 2>&1; echo $? > {shlex.quote(str(rc))}"
    proc = subprocess.Popen(['bash', '-c', script], cwd=str(base_dir()), env=env,
                            start_new_session=True, stdin=subprocess.DEVNULL,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    meta = {'id': job_id, 'tool': tool, 'command': shown if shown is not None else argv[1:],
            'user': getattr(user, 'username', ''), 'pid': proc.pid,
            'started_at': datetime.now(timezone.utc).isoformat(timespec='seconds')}
    (directory / f'{job_id}.json').write_text(json.dumps(meta, ensure_ascii=False, indent=1),
                                              encoding='utf-8')
    return {'job_id': job_id, 'status': 'running', 'tool': tool, 'next_step': JOB_STARTED_NOTICE}


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
        if str(state.get('tool', '')).startswith(CLAUDE_CODE_TOOL) and state['status'] != 'running':
            # Le journal d'une tâche Claude Code EST sa réponse JSON : on la lit comme l'appel
            # synchrone (`claude_code.read_output`), pas comme une fin de journal brute.
            from wama.common.services.claude_code import read_output
            answer = read_output(text)
            state['response'] = (answer.get('texte') or answer.get('error') or '')[:LOG_TAIL_CHARS]
            state['model'] = answer.get('modele', '')
            state['cost_usd'] = answer.get('cout_usd')
    return state


# ── La FIN d'une tâche, annoncée — plus jamais suivie dans un tour (2026-10-12) ────────────────

#: Une fin plus ancienne n'est plus annoncée (serveur arrêté longtemps) : elle reste lisible par
#: `dev_list_jobs`, mais une notification de la veille surprendrait plus qu'elle n'aiderait.
NOTIFY_MAX_AGE_S = 6 * 3600
#: Intervalle du veilleur (s) — celui de la relève des canaux (`gateway.core.FOLLOW_UP_INTERVAL_S`).
WATCH_INTERVAL_S = 15


def _job_summary(state: dict) -> str:
    """Le corps de la notification : la réponse (Claude Code), les propositions écrites (rôles),
    sinon la fin du journal — de quoi décider sans rouvrir la tâche."""
    if state.get('response'):
        return state['response'][:1500]
    lines = []
    if state.get('outputs'):
        lines.append("Propositions écrites (en attente de validation) : "
                     + ', '.join(state['outputs']))
    if state['status'] != 'done' or not lines:
        tail = [line for line in (state.get('log_tail') or '').splitlines()
                if line.strip() and 'Warning' not in line and 'warn(' not in line][-6:]
        if tail:
            lines.append('\n'.join(tail))
    return '\n'.join(lines)[:1500]


def notify_finished_jobs() -> int:
    """Annonce, une fois, chaque tâche de développement TERMINÉE : une notification DANS WAMA
    (cloche du web) que la passerelle relaie dans le fil d'où la tâche a été demandée — le chemin
    des tâches d'app (`notify_job_end` → `gateway.core.collect_job_follow_ups`), sans en écrire un
    second. Marque la fiche (`notified`) ; rend le nombre de notifications créées."""
    import time

    from django.contrib.auth import get_user_model

    from wama.common.utils.notifications import DEV_JOB_APP, DEV_JOB_TYPE, notify_in_app

    created = 0
    for meta_path in jobs_dir().glob('*.json'):
        try:
            meta = json.loads(meta_path.read_text(encoding='utf-8'))
            rc_path = meta_path.with_suffix('.rc')
            if meta.get('notified') or not rc_path.exists():
                continue
            meta['notified'] = True
            if time.time() - rc_path.stat().st_mtime <= NOTIFY_MAX_AGE_S:
                user = get_user_model().objects.filter(username=meta.get('user', '')).first()
                if user is not None:
                    state = job_state(meta['id'])
                    success = state['status'] == 'done'
                    title = (f"Tâche de développement « {meta.get('tool', '')} » "
                             f"{'terminée' if success else 'en échec'}")
                    created += notify_in_app([user], 'job_done' if success else 'job_failed',
                                             title, body=_job_summary(state),
                                             app=DEV_JOB_APP, object_type=DEV_JOB_TYPE,
                                             object_id=meta['id'])
            meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding='utf-8')
        except Exception:
            logger.exception("[dev_tools] fin de tâche non annoncée : %s", meta_path.name)
    return created


def start_job_watcher() -> None:
    """Le veilleur des fins de tâche, dans le process du serveur de développement — celui qui
    POSSÈDE les tâches (`run_mcp_server --surface dev`). Un fil démon ; une erreur n'arrête pas
    la ronde suivante."""
    import threading
    import time

    def watch():
        while True:
            try:
                notify_finished_jobs()
            except Exception:
                logger.exception("[dev_tools] ronde du veilleur en échec")
            finally:
                from django.db import connection
                connection.close()
            time.sleep(WATCH_INTERVAL_S)

    threading.Thread(target=watch, name='dev-job-watcher', daemon=True).start()


# ── Les outils ───────────────────────────────────────────────────────────────────────────────

def dev_run_role(user, role: str, args: dict = None, provider: str = '', model: str = '') -> dict:
    """Lance un rôle wama-dev-ai en tâche de fond ; il écrit une PROPOSITION en attente de validation, n'applique rien.

    role : librarian (args dist | repo), model (catalog | hf, force), scout (hf, dry_run),
    integrator (manifest, besoin, dry_run), codegen (app = id d'une app du catalogue, task = NOM
    de sa tâche Celery comme read_document_task, truth = module:fonction de référence — écrit la
    GLU de cette seule tâche ; ce n'est PAS un rôle de modification générale du code : pour cela,
    dev_claude_code avec write=true), backend (catalog, dry_run, no_smoke), task (tâche de
    DÉVELOPPEMENT par wama-dev-ai : task = la tâche en clair, files = chemins du dépôt séparés par
    des virgules, `chemin:début-fin` pour une tranche, 8 au plus ; sans write, réponse citée
    ligne par ligne ; write=true, édits PROPOSÉS et contrôlés, appliqués après validation
    humaine — jamais par toi), app (BROUILLON du manifeste d'une app NOUVELLE : key =
    underscore_case libre, need = ce qu'elle fait, like = app existante la plus proche, requires =
    briques déjà produites `library:<clé>,model:<clé>` ; sa sortie *.manifest.json fait naître
    l'app par dev_sandbox create manifest=…), repo_app (la CHAÎNE entière en une tâche : repo =
    owner/name, key, need, like — librarian, brouillon app, naissance au bac à sable et
    rechargement ; no_sandbox = s'arrêter au brouillon). Valeurs d'une ligne,
    500 caractères au plus. Intégrer un modèle INSTALLÉ : model d'abord (manifeste : moteur,
    composants), validation au model manager, PUIS backend (il exige le moteur déclaré).
    Modèle : laisser vide = tirage du niveau développement pour ton compte (local, ou souverain
    selon ton profil). provider borne ce tirage à un fournisseur (ollama = local, charge le GPU ;
    albert…) ; model est un choix précis, remplacé s'il n'a pas le niveau. Rend job_id et le
    modèle retenu — la fin de la tâche est annoncée ; dev_read_output lit la proposition.
    """
    role_command(role, args)          # les arguments d'abord : on ne tire pas pour une commande refusée
    chosen = role_model(user, provider, model)
    # Le COMPTE suit le rôle dans son process : sa clé et sa garde cloud servent l'appel.
    from wama.common.services.development_models import ROLE_USER_ENV
    env = {**os.environ, ROLE_USER_ENV: str(user.pk)}
    job = start_job(user, f'role:{role}',
                    role_command(role, args, chosen['provider'], chosen['model']), env=env)
    job['model'] = chosen['key']
    if chosen['note']:
        job['model_note'] = chosen['note']
    return job


def dev_sandbox(user, action: str, app: str = '', target: str = '', manifest: str = '') -> dict:
    """Bac à sable d'apps en tâche de fond : create, substitute, revert, remove, list — l'app d'origine n'est jamais modifiée.

    create app=<app source> : jumelle <app>_NN dont le demandeur est le créateur. create
    manifest=<chemin> (sans app) : app NOUVELLE née DE ZÉRO d'un manifeste `app` — la sortie
    `*.manifest.json` du rôle app, ou un brouillon de manifests/app_drafts/ ; ses trous de glu se
    remplissent ensuite par le rôle codegen. substitute / revert app=<jumelle>
    target=<apps|urls|models|params|tasks|views|templates>. remove app=<jumelle>. Après create,
    revert ou remove : dev_reload_web pour servir le changement.
    """
    owner = getattr(user, 'username', '') if action == 'create' else ''
    return start_job(user, f'sandbox:{action}',
                     sandbox_command(action, app, target, owner, manifest))


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


#: Préfixe du nom de tâche Claude Code (`claude_code` ou `claude_code:write`).
CLAUDE_CODE_TOOL = 'claude_code'
#: Délai d'une tâche Claude Code DÉTACHÉE (s) : sans spectateur qui attend, la borne de l'appel
#: synchrone (15 min) n'a plus de raison ; elle évite seulement un process orphelin éternel.
CLAUDE_CODE_JOB_TIMEOUT_S = 3600


def dev_claude_code(user, task: str, write: bool = False, model: str = '') -> dict:
    """Confie une tâche de développement à Claude Code (abonnement du demandeur) en TÂCHE DE FOND : audit, explication, ou modification du dépôt avec write=true. Réponds aussitôt à l'utilisateur ; la réponse de Claude Code arrive dans le fil à la fin.

    task : la tâche en clair. write : autoriser la modification du dépôt (sinon lecture seule).
    model : un modèle déclaré de l'abonnement (opus, sonnet…) — vide = choix du CLI.
    """
    from wama.common.services.claude_code import (ClaudeCodeIndisponible, prepare,
                                                  subscription_allowed)

    if not subscription_allowed(user):
        return {'error': 'forbidden', 'detail': "Claude Code est réservé aux développeurs et "
                                                "administrateurs."}
    task = (task or '').strip()
    if not task:
        raise DevToolError("« task » vide : décrivez la tâche à confier à Claude Code.")
    try:
        prepared = prepare(task, ecriture=bool(write), user=user, model=model)
    except ClaudeCodeIndisponible as e:
        return {'error': str(e)}
    if 'error' in prepared:
        return {'error': prepared['error']}
    argv = ['timeout', str(CLAUDE_CODE_JOB_TIMEOUT_S), *prepared['argv']]
    # La fiche montre la tâche, pas les options du CLI ; le jeton reste dans `env`.
    shown = [f"write={bool(write)}", f"model={model or 'défaut'}", task[:300]]
    return start_job(user, CLAUDE_CODE_TOOL + (':write' if write else ''), argv,
                     env=prepared['env'], shown=shown)


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
                                         dev_claude_code, dev_job_status, dev_list_jobs,
                                         dev_read_output)}


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
