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


def declared_services() -> list:
    """Les services que la surveillance connaît : la liste du script qui les lance, seule déclaration."""
    from django.conf import settings
    script = Path(settings.BASE_DIR) / 'scripts' / 'wama_services.sh'
    return re.search(r'^WAMA_SERVICES="([^"]+)"', script.read_text(encoding='utf-8'), re.M).group(1).split()


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
            'services': [_describe(service, at_start) for service in declared_services()]}


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
