"""Ce qu'un processus Python dit à la surveillance des services (`scripts/worker_watchdog.sh`), et ce
qu'il lit de leur état.

Des drapeaux, dans `logs/`, le même canal que la pause de la surveillance
(`logs/worker_watchdog.pause`) : un fichier se lit depuis bash sans lancer Django et sans Redis.

  • `service_wanted.<service>` : un appelant a trouvé le service éteint. C'est ce qui relance un
    service À LA DEMANDE : sans demande, un service arrêté pour libérer la carte le reste ;
  • `service_stopped.<service>` : l'arrêt est VOULU (le gouverneur a demandé la carte). Sa relance ne
    compte pas dans le budget, qui sert à repérer ce qui meurt à répétition ;
  • `service_held.<service>` : un administrateur l'a arrêté. La surveillance l'arrête et le laisse
    arrêté, demande ou pas, jusqu'à un « Lancer » ou au prochain démarrage de WAMA ;
  • `service_launch.<service>` : un administrateur veut le lancer ou le relancer.

`<service>` : la clé du service au registre des sources (`external_sources.SOURCES`).

Le serveur web ne lance ni ne tue aucun processus : il dépose l'ordre, la surveillance l'exécute
avec les fonctions et l'environnement du démarrage (`scripts/wama_services.sh`). Sans surveillance
vivante, un ordre ne serait jamais exécuté : il est refusé, et la page le dit.

LES AUTRES PROCESSUS DE WAMA (2026-11-11, demande de Fabien : « relancer depuis WAMA tout ce qui
est relançable ») — sur le même canal, réservés à un administrateur :
  • un WORKER Celery (`WAMA_CELERY_WORKERS`) : `service_launch.<worker>` → la surveillance lui
    demande un arrêt À CHAUD (il finit sa tâche en cours) puis le relance, hors budget et sans
    rapport. `worker_seen.<worker>` : le signe de vie qu'elle pose quand elle le trouve en marche ;
  • le SERVEUR WEB (`web`) : `service_launch.web` → rechargement à chaud de gunicorn (`HUP` au
    maître) — ses workers relisent le code, le port reste ouvert ;
  • TOUT WAMA (`wama`) : `wama_restart` → la surveillance lance le script de démarrage DÉTACHÉ
    (`WAMA_START_SCRIPT`), qui l'arrête elle-même en route.
Ce qui exige les droits root (PostgreSQL, Apache, WSL, la machine) n'est PAS relançable d'ici : le
mot de passe système ne transite jamais par WAMA. Le geste qui COUPE (tout WAMA, un worker en pleine
tâche) demande le mot de passe WAMA de l'administrateur (`needs_password`, vérifié par la vue).
"""
import os
import re
import time
from pathlib import Path
from urllib.parse import urlparse

#: Une surveillance muette depuis ce délai est tenue pour absente. Un passage peut durer : une
#: relance attend jusqu'à une minute, le rapport d'une mort lance Django.
WATCHDOG_SILENCE_S = 300

#: (connexion, lecture) de la sonde `/health`, relevée à chaque tour du poller de la page.
_HEALTH_TIMEOUT = (0.5, 1.5)

#: État d'un service → (libellé, tonalité du badge).
_STATES = {
    'ok': ('En marche', 'success'),
    'loading': ('Chargement', 'warning'),
    'busy': ('Occupé', 'info'),
    'stopping': ('Arrêt en cours', 'warning'),
    'restarting': ('Relance demandée', 'warning'),
    'starting': ('Démarrage demandé', 'warning'),
    'held': ('Arrêté à la main', 'secondary'),
    'on_demand': ('À la demande', 'secondary'),
    'down': ('Arrêté', 'danger'),
}

_WATCHDOG_REFUSALS = {
    'paused': "La surveillance est en pause (logs/worker_watchdog.pause) : aucun ordre n'est exécuté.",
    'absent': "La surveillance ne tourne pas : aucun ordre ne serait exécuté. Relancez WAMA.",
}


def _logs() -> Path:
    from django.conf import settings
    return Path(settings.BASE_DIR) / 'logs'


def _flag(kind: str, service: str) -> Path:
    return _logs() / f'service_{kind}.{service}'


def _raise_flag(kind: str, service: str) -> None:
    try:
        _flag(kind, service).touch()
    except OSError:
        pass                        # le drapeau n'est qu'une demande : l'appelant a son repli


def ask_for_service(service: str) -> None:
    """Le service est éteint et quelqu'un en a besoin : la surveillance le relancera."""
    _raise_flag('wanted', service)


def note_stopped_on_purpose(service: str) -> None:
    """Le service s'arrête parce qu'on le lui demande, pas parce qu'il est tombé."""
    _raise_flag('stopped', service)


def _script_list(name: str) -> list:
    """Une liste que déclare `scripts/wama_services.sh` (`NOM="a b c"`) : sa seule déclaration. Une
    liste VIDE (`NOM=""`) en est une (`WAMA_SERVICE_ENVIRONMENTS` en mono-venv)."""
    from django.conf import settings
    script = Path(settings.BASE_DIR) / 'scripts' / 'wama_services.sh'
    return re.search(rf'^{name}="([^"]*)"', script.read_text(encoding='utf-8'), re.M).group(1).split()


def declared_services() -> list:
    """Les services que la surveillance connaît : la liste du script qui les lance, seule déclaration."""
    return _script_list('WAMA_SERVICES')


def declared_environments() -> dict:
    """Les ENVIRONNEMENTS d'exécution `{nom: dossier du venv}`, dans l'ordre déclaré — le premier est
    celui de référence (`WAMA_ENVIRONMENTS` du script, sa seule déclaration ; multi-venv, 2026-11-11).
    Le dossier est absolu, sous la racine du dépôt."""
    from django.conf import settings
    return {name: Path(settings.BASE_DIR) / folder
            for name, _, folder in (pair.partition(':') for pair in _script_list('WAMA_ENVIRONMENTS'))}


def reference_environment() -> str:
    """L'environnement de référence : celui des workers, du serveur web et des services sans autre."""
    return next(iter(declared_environments()))


def service_environment(service: str) -> str:
    """L'environnement dans lequel la surveillance lance `service` (`WAMA_SERVICE_ENVIRONMENTS`), celui
    de référence s'il n'en déclare pas — la règle de `wama_service_environment`, côté Python."""
    pairs = dict(pair.partition(':')[::2] for pair in _script_list('WAMA_SERVICE_ENVIRONMENTS'))
    return pairs.get(service) or reference_environment()


def environment_python(environment: str) -> Path:
    """Le Python d'un environnement déclaré (`<venv>/bin/python`). KeyError pour un nom inconnu."""
    return declared_environments()[environment] / 'bin' / 'python'


def services_at_start() -> list:
    """Ceux qui démarrent avec WAMA : la section des scripts `start_wama`, héritée de leur environnement."""
    return os.environ.get('WAMA_SERVICES_AT_START', '').split()


def watchdog_state() -> str:
    """`running`, `paused` ou `absent`, d'après le signe de vie que la surveillance écrit à chaque passage."""
    try:
        silence = time.time() - (_logs() / 'worker_watchdog.alive').stat().st_mtime
    except OSError:
        return 'absent'
    if silence > WATCHDOG_SILENCE_S:
        return 'absent'
    return 'paused' if (_logs() / 'worker_watchdog.pause').exists() else 'running'


def _health(service: str):
    """Ce que le service dit de lui : `ok`, `loading`, `stopping` ; `busy` s'il tient son port sans
    répondre à temps (un service en plein calcul) ; None s'il n'écoute pas."""
    import requests

    from wama.common.external_sources import base_url, proxies_for
    try:
        response = requests.get(f'{base_url(service)}/health', proxies=proxies_for(service),
                                timeout=_HEALTH_TIMEOUT)
    except requests.ConnectionError:
        return None
    except requests.RequestException:
        return 'busy'
    if response.status_code != 200:
        return 'busy'
    status = response.json().get('status')
    return status if status in _STATES else 'ok'


def _resolve_state(health, *, held: bool, launch: bool, wanted: bool, at_start: bool) -> str:
    if health:
        if held:
            return 'stopping'
        return 'restarting' if launch else health
    if launch or (wanted and not held):
        return 'starting'
    if held:
        return 'held'
    return 'down' if at_start else 'on_demand'


def _actions(state: str) -> list:
    if state in ('ok', 'loading', 'busy'):
        return ['stop', 'restart']
    return ['start'] if state in ('held', 'on_demand', 'down') else []


def _describe(service: str, at_start: list) -> dict:
    from wama.common.external_sources import by_key
    source = by_key()[service]
    state = _resolve_state(_health(service), held=_flag('held', service).exists(),
                           launch=_flag('launch', service).exists(),
                           wanted=_flag('wanted', service).exists(), at_start=service in at_start)
    label, tone = _STATES[state]
    return {'key': service, 'label': source.label, 'usage': source.usage, 'when_off': source.when_off,
            'port': urlparse(source.base).port, 'state': state, 'state_label': label, 'tone': tone,
            'at_start': service in at_start, 'actions': _actions(state)}


def services_overview() -> dict:
    """L'état de chaque service, et de la surveillance qui exécute les ordres."""
    at_start = services_at_start()
    watchdog = watchdog_state()
    return {'watchdog': watchdog, 'watchdog_message': _WATCHDOG_REFUSALS.get(watchdog, ''),
            'services': [_describe(service, at_start) for service in declared_services()],
            'processes': processes_overview()}


#: Une reconfirmation du mot de passe vaut pour les gestes suivants de la même session, ce temps-là.
REAUTH_WINDOW_S = 300

#: Le serveur web et WAMA entier : deux clés de plus, à côté des services et des workers.
WEB, WAMA = 'web', 'wama'

#: Ce que redit l'ordre à l'administrateur, et ce qu'il coupe (la confirmation de la page).
_PROCESS_TEXTS = {
    WEB: ('Serveur web (gunicorn)', "Rechargement à chaud : ses processus relisent le code, les "
                                    "pages restent servies."),
    WAMA: ('WAMA entier', "Relance complète par le script de démarrage : toutes les pages se coupent "
                          "environ deux minutes, les traitements en cours sont interrompus."),
}


def declared_workers() -> list:
    """Les processus Celery que la surveillance connaît : la liste du script qui les lance."""
    return _script_list('WAMA_CELERY_WORKERS')


def _worker_busy(worker: str) -> bool:
    """Le worker exécute-t-il une tâche ? Sans réponse, on le tient pour OCCUPÉ : un worker gpu en
    pool solo ne répond pas pendant une tâche (`worker_watchdog.sh`, en-tête) — et c'est le cas qui
    coupe. `beat` n'exécute rien. La lecture de la flotte est celle de la réconciliation
    (`process_control.collect_worker_snapshot`), avec la même règle : une absence de réponse ne
    prouve rien."""
    if worker == 'beat':
        return False
    import socket

    from wama.common.utils.process_control import collect_worker_snapshot
    snapshot = collect_worker_snapshot(timeout=1.0)
    node = f'{worker}@{socket.gethostname()}'
    if not snapshot or node not in snapshot['workers']:
        return True
    return snapshot.get('busy', {}).get(node, 0) > 0


def needs_password(key: str, action: str) -> bool:
    """Le geste COUPE-t-il un travail en cours ? Alors l'administrateur redonne son mot de passe
    WAMA (recommandation retenue par Fabien, 2026-11-11) : relancer tout WAMA, ou un worker en pleine
    tâche. Recharger le serveur web, lancer ou arrêter un service : la confirmation habituelle."""
    if key == WAMA:
        return True
    return key in declared_workers() and action == 'restart' and _worker_busy(key)


def _worker_state(worker: str) -> str:
    # L'ordre déposé, puis l'arrêt à chaud que la surveillance a engagé (`service_stopped`).
    if _flag('launch', worker).exists() or _flag('stopped', worker).exists():
        return 'restarting'
    try:
        seen = time.time() - (_logs() / f'worker_seen.{worker}').stat().st_mtime
    except OSError:
        return 'down'
    return 'ok' if seen <= WATCHDOG_SILENCE_S else 'down'


def processes_overview() -> list:
    """Les workers, le serveur web et WAMA entier — ce que la page offre de relancer."""
    rows = []
    for worker in declared_workers():
        state = _worker_state(worker)
        label, tone = _STATES[state]
        rows.append({'key': worker, 'label': f'Worker {worker}', 'kind': 'worker', 'state': state,
                     'state_label': label, 'tone': tone,
                     'actions': ['restart'] if state in ('ok', 'down') else []})
    for key in (WEB, WAMA):
        label, when = _PROCESS_TEXTS[key]
        restarting = (_logs() / 'wama_restart').exists() if key == WAMA else _flag('launch', key).exists()
        state = 'restarting' if restarting else 'ok'
        rows.append({'key': key, 'label': label, 'kind': key, 'when_off': when, 'state': state,
                     'state_label': _STATES[state][0], 'tone': _STATES[state][1],
                     'actions': [] if restarting else ['restart']})
    return rows


def control_process(key: str, action: str) -> tuple:
    """Dépose l'ordre de relancer un worker, le serveur web ou WAMA entier → (accepté ?, message).
    Seul `restart` existe : arrêter un worker laisserait sa file sans consommateur."""
    if action != 'restart':
        return False, f"Action inconnue : {action}."
    if key not in declared_workers() and key not in (WEB, WAMA):
        return False, f"Processus inconnu : {key}."
    watchdog = watchdog_state()
    if watchdog != 'running':
        return False, _WATCHDOG_REFUSALS[watchdog]
    try:
        if key == WAMA:
            (_logs() / 'wama_restart').touch()
            return True, ("Relance de WAMA demandée : la page va se couper environ deux minutes, "
                          "puis revenir.")
        _flag('launch', key).touch()
    except OSError as exc:
        return False, f"{key} : ordre non déposé ({exc})."
    if key == WEB:
        return True, "Rechargement du serveur web demandé : les pages restent servies."
    return True, f"Worker {key} : relance demandée — il finit sa tâche en cours avant de redémarrer."


def control_service(service: str, action: str) -> tuple:
    """Dépose l'ordre `start`, `stop` ou `restart` → (accepté ?, message à montrer)."""
    from wama.common.external_sources import by_key
    if service not in declared_services():
        return False, f"Service inconnu : {service}."
    if action not in ('start', 'stop', 'restart'):
        return False, f"Action inconnue : {action}."
    watchdog = watchdog_state()
    if watchdog != 'running':
        return False, _WATCHDOG_REFUSALS[watchdog]
    name = by_key()[service].label
    held, launch = _flag('held', service), _flag('launch', service)
    try:
        if action == 'stop':
            launch.unlink(missing_ok=True)
            held.touch()
            return True, f"{name} : arrêt demandé."
        held.unlink(missing_ok=True)
        if action == 'start' and _health(service):
            return True, f"{name} est déjà en marche."
        launch.touch()
    except OSError as exc:
        return False, f"{name} : ordre non déposé ({exc})."
    return True, f"{name} : {'relance' if action == 'restart' else 'démarrage'} demandé."
