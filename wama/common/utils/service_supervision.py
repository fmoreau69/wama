"""Ce qu'un processus Python dit à la surveillance des services (`scripts/worker_watchdog.sh`).

Deux drapeaux, dans `logs/`, le même canal que la pause de la surveillance
(`logs/worker_watchdog.pause`) : un fichier se lit depuis bash sans lancer Django et sans Redis.

  • `service_wanted.<service>` : un appelant a trouvé le service éteint. C'est ce qui relance un
    service À LA DEMANDE : sans demande, un service arrêté pour libérer la carte le reste ;
  • `service_stopped.<service>` : l'arrêt est VOULU (le gouverneur a demandé la carte). Sa relance ne
    compte pas dans le budget, qui sert à repérer ce qui meurt à répétition.

`<service>` : la clé du service au registre des sources (`external_sources.SOURCES`).
"""
from pathlib import Path


def _flag(kind: str, service: str) -> Path:
    from django.conf import settings
    return Path(settings.BASE_DIR) / 'logs' / f'service_{kind}.{service}'


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
