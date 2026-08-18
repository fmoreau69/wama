"""
Rotation et cloisonnement des journaux WAMA — brique COMMUNE.

PRINCIPE (posé 2026-07-29, après l'incident de la boucle de crash WSL2)
======================================================================
On ne VIDE jamais un journal au démarrage : on le DÉCALE.

Le réflexe « `> fichier.log` à chaque relance » (utilisé jusqu'ici pour
`tts-service.log`) est exactement ce qu'il ne faut pas faire quand on débogue un
crash : au redémarrage qui suit l'incident, la trace qui aurait expliqué le crash
est écrasée, et il faut REPRODUIRE le bug pour l'étudier. Le 29/07/2026, c'est
précisément `celery-gpu.log` — conservé parce que Celery écrit en append — qui a
permis d'identifier la tâche imager #42 responsable de 4 kernel panics WSL2.

Le décalage réconcilie les deux besoins qui semblaient s'opposer :
  - chaque run démarre sur un fichier PROPRE et lisible ;
  - le run PRÉCÉDENT reste intégralement disponible (`.log.1`), et les `keep`
    derniers avec lui.

⚠ ORDONNANCEMENT — la rotation doit avoir lieu SERVICES ARRÊTÉS, avant de les
relancer. Sous Linux, renommer un fichier ouvert ne détache pas le descripteur :
un process encore vivant continuerait d'écrire dans l'inode renommé (`.log.1`),
et le nouveau `.log` resterait vide. D'où l'appel unique en tête des scripts de
démarrage (`manage.py rotate_logs`), et JAMAIS depuis un `AppConfig.ready()` —
qui s'exécute dans chacun des ~7 process (4 gunicorn + 2 celery + beat) et
ferait donc tourner la rotation 7 fois, détruisant l'historique.
"""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# Nombre de runs conservés en plus du run courant → `.log` + `.log.1` … `.log.9`.
#
# Porté de 3 à 9 le 2026-08-07 : la machine hôte enchaînait 3 coupures d'alimentation
# dans la journée, et la fenêtre de 3 runs a été CHASSÉE avant qu'on ait pu identifier
# la tâche GPU qui tournait lors du crash du 04/08 à 02:38 (VRAM 0,78 → 8,3 Go, aucune
# trace survivante). Un post-mortem a besoin de remonter plusieurs redémarrages, pas un.
DEFAULT_KEEP = 9

# Journaux RÉÉCRITS À CHAQUE RUN par un service — les seuls à tourner par défaut.
#
# Volontairement une liste EXPLICITE et non un `*.log` : le répertoire contient
# aussi des journaux d'archive à tirage unique (`download_*.log` d'installations
# de modèles, `poc_*`, audits ponctuels…). Les balayer avec le même filet les
# ferait sortir de la fenêtre `keep` au bout de 3 redémarrages et DISPARAÎTRE,
# alors qu'ils ne sont réécrits par personne. Un nouveau service qui journalise
# s'ajoute ici.
RUNTIME_LOGS = (
    "celery-beat.log",
    "celery-default.log",
    "celery-gpu.log",
    "gunicorn-access.log",
    "gunicorn-error.log",
    "model-sync.log",
    "tts-service.log",
    "wama.log",           # journal applicatif global (loggers `wama.*`, common/apps.py)
)

# PAS dans la liste : `wama-console.log` tourne DÉJÀ tout seul, par taille
# (`console_utils.py` : RotatingFileHandler maxBytes=5 Mo, backupCount=3) — et avec
# le MÊME nommage `.1/.2/.3`. L'ajouter ici ferait travailler deux mécanismes sur
# les mêmes fichiers. Antériorité respectée : c'est la rotation par taille qui gère.

# Handlers déjà posés par `attach_dedicated_log` (idempotence multi-process).
_ATTACHED: set[str] = set()

_MARKER = "_wama_dedicated"


def get_log_dir() -> Path:
    """Répertoire des journaux (`<BASE_DIR>/logs` sauf réglage explicite)."""
    from django.conf import settings

    configured = getattr(settings, "LOG_DIR", None)
    if configured:
        return Path(configured)
    return Path(settings.BASE_DIR) / "logs"


def rotate_file(path, keep: int = DEFAULT_KEEP) -> bool:
    """
    Décale `X.log` → `X.log.1` → … → `X.log.<keep>`, la plus ancienne étant
    supprimée. Renvoie True si une rotation a eu lieu.

    Un fichier absent ou VIDE n'est pas tourné : sans ça, une suite de
    redémarrages rapprochés (le cas d'une boucle de crash, justement) chasserait
    l'historique utile en le remplaçant par des fichiers vides.
    """
    path = Path(path)
    try:
        if not path.exists() or path.stat().st_size == 0:
            return False

        oldest = Path(f"{path}.{keep}")
        if oldest.exists():
            oldest.unlink()

        for index in range(keep - 1, 0, -1):
            source = Path(f"{path}.{index}")
            if source.exists():
                source.rename(f"{path}.{index + 1}")

        path.rename(f"{path}.1")
        return True
    except OSError as exc:
        logger.warning(f"[log_rotation] Rotation de {path} impossible : {exc}")
        return False


def resolve_targets(log_dir=None, names=None, pattern: str = None) -> list[Path]:
    """
    Journaux candidats à la rotation. Par défaut `RUNTIME_LOGS` ; `pattern`
    ('*.log') élargit explicitement à tout le répertoire — à n'utiliser qu'en
    connaissance de cause (cf. l'avertissement sur RUNTIME_LOGS).
    """
    directory = Path(log_dir) if log_dir else get_log_dir()
    if not directory.is_dir():
        return []
    if pattern:
        return [p for p in sorted(directory.glob(pattern)) if p.is_file()]
    return [directory / name for name in (names or RUNTIME_LOGS)]


def rotate_startup_logs(log_dir=None, keep: int = DEFAULT_KEEP,
                        names=None, pattern: str = None) -> list[str]:
    """
    Tourne les journaux de service. À appeler UNE fois par démarrage de WAMA,
    services arrêtés. Renvoie les noms effectivement tournés.
    """
    rotated = []
    for entry in resolve_targets(log_dir=log_dir, names=names, pattern=pattern):
        if rotate_file(entry, keep=keep):
            rotated.append(entry.name)
    return rotated


def attach_dedicated_log(
    logger_name: str,
    filename: str,
    *,
    level: int = logging.INFO,
    log_dir=None,
    propagate: bool = False,
    fmt: str = "%(asctime)s [%(levelname)s] %(message)s",
) -> bool:
    """
    Cloisonne un logger BAVARD dans son propre fichier.

    `propagate=False` est le point important : la sortie cesse de remonter au
    logger racine, donc de polluer le journal du worker qui l'héberge. Motivation
    d'origine : `[ModelSync]` représentait 71 % de `celery-default.log`
    (138 328 lignes sur 194 328) et noyait les traces de tâches réelles.

    Idempotent : appelé depuis un `AppConfig.ready()`, il s'exécute dans chaque
    process ; le fichier est ouvert en APPEND (jamais tronqué) et le handler
    n'est posé qu'une fois par process. La remise à zéro est le travail de
    `rotate_startup_logs`, au démarrage, une seule fois.

    ANTÉRIORITÉ : `console_utils.py` applique déjà ce motif (logger dédié +
    `propagate=False` + fichier propre) pour la console WAMA, mais de façon
    intégrée à ce canal (push Redis + RotatingFileHandler par taille). Cette
    fonction est la version GÉNÉRIQUE, applicable à n'importe quel logger déjà
    existant sans toucher à ses sites d'appel. Un journal borné en TAILLE pendant
    un run reste l'affaire de `console_utils` : `RotatingFileHandler` n'est pas
    sûr en rollover multi-process (7 process ici), on ne le généralise pas.
    """
    if logger_name in _ATTACHED:
        return False

    try:
        directory = Path(log_dir) if log_dir else get_log_dir()
        directory.mkdir(parents=True, exist_ok=True)

        target = logging.getLogger(logger_name)
        if any(getattr(h, _MARKER, False) for h in target.handlers):
            _ATTACHED.add(logger_name)
            return False

        handler = logging.FileHandler(directory / filename, mode="a", encoding="utf-8")
        handler.setLevel(level)
        handler.setFormatter(logging.Formatter(fmt))
        setattr(handler, _MARKER, True)

        target.addHandler(handler)
        target.setLevel(level)
        target.propagate = propagate

        _ATTACHED.add(logger_name)
        return True
    except Exception as exc:
        # Un journal cloisonné qui échoue ne doit JAMAIS empêcher l'app de démarrer :
        # on retombe sur le comportement d'avant (les lignes repartent vers la racine).
        logger.warning(f"[log_rotation] Journal dédié '{filename}' non attaché : {exc}")
        return False
