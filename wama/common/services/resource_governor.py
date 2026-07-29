"""
Gouvernance des ressources WAMA (GPU / CPU / RAM) — POINT D'ENTRÉE UNIQUE.

POURQUOI CE MODULE EXISTE
=========================
Les mécanismes de ressources étaient dispersés et donc invisibles : plafond
allocateur CUDA posé sur UN chemin de chargement, registre d'unloaders VRAM
local à un process, sérialisation GPU implicite dans un flag CLI de `start_wama`.
Résultat concret le 29/07/2026 : une génération imager a débordé de 24 Go à
38,1 Go, la VM WSL2 a paniqué 4 fois, et le service TTS — qui détient de la VRAM
dans un process séparé — n'était vu par aucun de ces mécanismes.

Toute logique d'allocation de ressource passe DÉSORMAIS par ici. Si tu cherches
« où limiter/réserver/prioriser », c'est ce fichier, et nulle part ailleurs.

CE QU'IL COUVRE (état au 2026-07-29)
====================================
  1. `configure_cuda_process()`  — garde niveau PROCESS : plafonne l'allocateur
     CUDA. À appeler une fois par process susceptible de toucher le GPU.
  2. Registre VRAM PARTAGÉ (Redis) — `reserve_vram` / `release_vram` /
     `reserved_gb`, visible de TOUS les process (worker GPU, service TTS,
     workers web), contrairement au registre d'unloaders qui reste local.
  3. `PRIORITIES` — table DÉCLARATIVE des priorités par app.

CE QU'IL NE COUVRE PAS ENCORE (cf. ROADMAP §Warm-loading VRAM)
==============================================================
  - Admission CPU/RAM sur la file `default` (rien aujourd'hui : `--autoscale=4,1`
    sans conscience mémoire).
  - Équité entre utilisateurs : la file est FIFO strict, un batch de 50 items
    d'un utilisateur affame les autres.
  - Câblage effectif des priorités dans le routage Celery.
Ces trois points s'ajoutent ICI, pas dans les apps.

POURQUOI PAS RAY / SLURM / TRITON
=================================
Analysé le 29/07/2026 : la sérialisation GPU existe déjà (worker `gpu` en
`--pool=solo --prefetch-multiplier=1`, une tâche à la fois toutes apps et tous
utilisateurs confondus). Le manque n'est pas un ordonnanceur, c'est que ce
verrou est invisible, non priorisable et percé (le service TTS lui échappe).
Empiler un second runtime pour récupérer de la sémantique que Celery+Redis
expriment déjà coûterait plus qu'il ne rapporte. Ray redevient le bon choix au
passage multi-GPU / multi-nœuds (serveur R760xa) — d'où l'intérêt de tout
centraliser ici : la bascule se fera dans ce fichier, pas dans les 11 apps.
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 1. Garde niveau PROCESS — plafond de l'allocateur CUDA
# ---------------------------------------------------------------------------

# Fraction du total physique au-delà de laquelle l'allocateur CUDA doit ÉCHOUER.
ALLOCATOR_CAP_FRACTION = float(os.environ.get("WAMA_CUDA_CAP_FRACTION", "0.95"))

_cuda_configured = False


def configure_cuda_process() -> bool:
    """
    Plafonne l'allocateur CUDA de CE process à `ALLOCATOR_CAP_FRACTION` de la
    VRAM physique. Idempotent, silencieux si CUDA est absent.

    CRITIQUE sous WSL2/WDDM : sans ce plafond, une allocation qui dépasse la
    VRAM physique n'échoue PAS — le pilote la fait déborder en RAM hôte et
    pagine à travers la frontière GPU-PV. Cette pagination sature
    `dxgkio_make_resident` (ENOMEM en rafale) et finit par faire paniquer le
    noyau invité : la VM WSL entière est réinitialisée, pas seulement le worker.

    Vécu 29/07/2026 : imager #42 (qwen-image-2), transformer déplacé jusqu'à
    38,1 Go sur une carte de 24 Go → 4 min 14 de pagination → kernel panic.

    ⚠ NIVEAU PROCESS, PAS NIVEAU CHEMIN DE CHARGEMENT. C'était le défaut de la
    première version (posée dans `MemoryManager.apply_memory_strategy`) : elle
    ne couvrait que la voie diffusers de l'imager, alors que transcriber,
    reader, describer, avatarizer et le service TTS font `.to('cuda')` en
    direct et pouvaient encore tuer la VM.
    """
    global _cuda_configured
    if _cuda_configured:
        return False
    try:
        import torch

        if not torch.cuda.is_available():
            return False
        torch.cuda.set_per_process_memory_fraction(ALLOCATOR_CAP_FRACTION)
        total_gb = torch.cuda.get_device_properties(0).total_memory / (1024 ** 3)
        logger.info(
            f"[ResourceGovernor] pid={os.getpid()} allocateur CUDA plafonné à "
            f"{ALLOCATOR_CAP_FRACTION:.0%} de {total_gb:.1f} GB "
            f"(= {total_gb * ALLOCATOR_CAP_FRACTION:.1f} GB) — anti-débordement WDDM"
        )
        _cuda_configured = True
        return True
    except Exception as exc:
        logger.warning(f"[ResourceGovernor] plafond CUDA non appliqué : {exc}")
        return False


def total_vram_gb() -> float:
    """VRAM physique de la carte, 0.0 si pas de GPU."""
    try:
        import torch

        if not torch.cuda.is_available():
            return 0.0
        return torch.cuda.get_device_properties(0).total_memory / (1024 ** 3)
    except Exception:
        return 0.0


# ---------------------------------------------------------------------------
# 2. Registre VRAM PARTAGÉ (Redis) — visible de tous les process
# ---------------------------------------------------------------------------

_LEDGER_KEY = "wama:vram:reservations"

# Une réservation expire seule : si un process meurt sans libérer (kernel panic,
# kill -9), sa ligne ne doit pas bloquer le GPU pour toujours. À rafraîchir par
# les traitements longs via `reserve_vram()` (le même owner écrase sa ligne).
RESERVATION_TTL_S = 3600


def _redis():
    """Connexion Redis via le broker Celery déjà configuré (aucune conf en plus)."""
    try:
        from django.conf import settings
        import redis

        url = getattr(settings, "CELERY_BROKER_URL", None) or "redis://localhost:6379/0"
        return redis.Redis.from_url(url, socket_timeout=2, socket_connect_timeout=2)
    except Exception as exc:
        logger.debug(f"[ResourceGovernor] Redis indisponible : {exc}")
        return None


def _now() -> float:
    import time

    return time.time()


def reserve_vram(owner: str, gb: float) -> bool:
    """
    Déclare que `owner` détient `gb` de VRAM. Écrase la ligne existante du même
    owner (donc sert aussi de rafraîchissement de TTL).

    `owner` doit être STABLE et identifier le détenteur réel, pas la tâche :
    p. ex. "tts-service", f"celery-gpu:{pid}", "imager:qwen-image-2".
    """
    client = _redis()
    if client is None:
        return False
    try:
        client.hset(_LEDGER_KEY, owner, f"{gb:.3f}:{_now():.0f}")
        client.expire(_LEDGER_KEY, RESERVATION_TTL_S * 2)
        return True
    except Exception as exc:
        logger.debug(f"[ResourceGovernor] reserve_vram({owner}) : {exc}")
        return False


def release_vram(owner: str) -> bool:
    """Libère la réservation de `owner`. Sans effet s'il n'en avait pas."""
    client = _redis()
    if client is None:
        return False
    try:
        client.hdel(_LEDGER_KEY, owner)
        return True
    except Exception as exc:
        logger.debug(f"[ResourceGovernor] release_vram({owner}) : {exc}")
        return False


def reservations(exclude: str | None = None) -> dict[str, float]:
    """
    Réservations VIVANTES (Go par owner). Les lignes plus vieilles que
    `RESERVATION_TTL_S` sont ignorées ET purgées : elles viennent d'un process
    mort sans libérer.
    """
    client = _redis()
    if client is None:
        return {}
    try:
        raw = client.hgetall(_LEDGER_KEY) or {}
    except Exception:
        return {}

    alive, stale, now = {}, [], _now()
    for key, value in raw.items():
        owner = key.decode() if isinstance(key, bytes) else str(key)
        text = value.decode() if isinstance(value, bytes) else str(value)
        try:
            gb_text, stamp_text = text.split(":", 1)
            gb, stamp = float(gb_text), float(stamp_text)
        except ValueError:
            stale.append(owner)
            continue
        if now - stamp > RESERVATION_TTL_S:
            stale.append(owner)
            continue
        if owner != exclude:
            alive[owner] = gb

    if stale:
        try:
            client.hdel(_LEDGER_KEY, *stale)
            logger.info(f"[ResourceGovernor] réservations périmées purgées : {stale}")
        except Exception:
            pass
    return alive


def reserved_gb(exclude: str | None = None) -> float:
    """Total réservé par les AUTRES détenteurs (tous process confondus)."""
    return sum(reservations(exclude=exclude).values())


def effective_free_gb(exclude: str | None = None) -> float:
    """
    VRAM réellement disponible = ce que le pilote annonce libre, MOINS ce que
    d'autres process ont réservé sans l'avoir encore alloué.

    C'est la mesure qui manquait : `torch.cuda.mem_get_info()` ne voit que le
    présent et ignore qu'un autre process s'apprête à prendre 18 Go.
    """
    try:
        import torch

        if not torch.cuda.is_available():
            return 0.0
        driver_free_gb = torch.cuda.mem_get_info()[0] / (1024 ** 3)
    except Exception:
        return 0.0
    return max(0.0, driver_free_gb - reserved_gb(exclude=exclude))


# ---------------------------------------------------------------------------
# 3. Priorités — DÉCLARATIF, pas codé en dur dans les apps
# ---------------------------------------------------------------------------

# ⚠⚠ PIÈGE — DANS LE TRANSPORT REDIS, LA PRIORITÉ EST INVERSÉE : **0 = LE PLUS
# PRIORITAIRE**. C'est l'inverse d'AMQP/RabbitMQ (où 9 est le plus prioritaire).
# Kombu implémente la priorité Redis en créant une liste par palier et consomme
# la PREMIÈRE liste non vide — donc le palier 0 d'abord. Écrire `cam_analyzer: 9`
# en croyant le rendre prioritaire produit EXACTEMENT L'INVERSE.
#
# Pour rendre l'erreur impossible, on ne manipule pas de nombres ici : on déclare
# des PALIERS NOMMÉS, et la conversion vers la convention du transport est faite
# à un seul endroit (`celery_priority_for`).

# Valeurs de palier du transport (doivent correspondre à `priority_steps` côté
# broker, cf. `CELERY_BROKER_TRANSPORT_OPTIONS`). Ordre = du + prioritaire au -.
TIER_VALUES = {
    "lab": 0,        # recherche — passe devant tout
    "haute": 3,
    "normale": 6,
    "basse": 9,
}

PRIORITY_STEPS = tuple(sorted(TIER_VALUES.values()))

# Décision Fabien (29/07/2026) : **WAMA-Lab prioritaire** — les traitements de
# recherche passent devant la production média.
APP_TIERS = {
    "cam_analyzer": "lab",
    "face_analyzer": "lab",
    "transcriber": "haute",
    "describer": "normale",
    "anonymizer": "normale",
    "enhancer": "normale",
    "synthesizer": "normale",
    "reader": "normale",
    "composer": "basse",
    "avatarizer": "basse",
    "imager": "basse",
    # Pseudo-app : campagne de tests nocturnes (`common.run_nightly_tests`).
    # Charge des modèles, donc file GPU, mais ne doit JAMAIS passer devant un
    # traitement demandé par un utilisateur.
    "_nightly_tests": "basse",
}

DEFAULT_TIER = "normale"


def tier_for(app_label: str) -> str:
    """Palier déclaré d'une app (nom lisible)."""
    return APP_TIERS.get(app_label, DEFAULT_TIER)


def celery_priority_for(app_label: str) -> int:
    """
    Valeur `priority` à passer à Celery pour cette app, dans la convention du
    transport Redis (**0 = le plus prioritaire**). Seule fonction qui connaît
    cette inversion — ne pas la ré-implémenter ailleurs.
    """
    return TIER_VALUES[tier_for(app_label)]


def task_routes() -> dict:
    """
    Complète les routes Celery avec la priorité de chaque app.

    Consommé par `settings.CELERY_TASK_ROUTES` : la file reste déclarée dans les
    settings (c'est une donnée de déploiement), la priorité vient d'ici (c'est
    une décision d'ordonnancement).

    ⚠ LA PRIORITÉ RÉORDONNE LA FILE, ELLE NE PRÉEMPTE PAS. Le worker `gpu` est en
    `--pool=solo` : une tâche imager déjà EN COURS n'est pas interrompue par
    l'arrivée d'une tâche lab — celle-ci passera devant les tâches en ATTENTE.
    La préemption supposerait de tuer un traitement en cours ; hors sujet ici.
    """
    return {app: {"priority": celery_priority_for(app)} for app in APP_TIERS}
