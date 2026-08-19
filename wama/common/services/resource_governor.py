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
from contextlib import contextmanager

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

#: Dernier USAGE par owner. Hash SÉPARÉ et non un 3ᵉ champ de la ligne de réservation :
#: `_reservations_raw` parse `"<go>:<horodatage>"` et traiterait un champ supplémentaire
#: comme une ligne illisible — donc périmée, donc PURGÉE. Une réservation vivante aurait
#: été effacée par un process resté sur l'ancien format.
_USED_KEY = "wama:vram:last_used"

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


def release_reservation(owner: str) -> bool:
    """
    Libère la RÉSERVATION de `owner` dans le registre Redis. Sans effet s'il n'en avait pas.

    ⚠ NE TOUCHE PAS AU GPU — c'est de la comptabilité, pas un déchargement. Le vrai
    déchargement est `model_manager.services.memory_manager.MemoryManager.release_vram()`.

    Renommée le 2026-08-04 : les deux fonctions s'appelaient `release_vram` avec des sémantiques
    OPPOSÉES (l'une écrit une ligne de registre, l'autre vide la VRAM). Un appel confondu ne
    libérait rien, ou déchargeait tout — et rien dans le nom ne permettait de s'en apercevoir.
    """
    client = _redis()
    if client is None:
        return False
    try:
        client.hdel(_LEDGER_KEY, owner)
        return True
    except Exception as exc:
        logger.debug(f"[ResourceGovernor] release_reservation({owner}) : {exc}")
        return False


#: Alias RÉTROCOMPATIBLE, à retirer une fois les appelants hors-dépôt (le cas échéant) migrés.
#: Conservé parce qu'un `release_vram` absent échouerait à l'import — donc au démarrage — alors
#: que le renommage vise justement à éviter les accidents.
release_vram = release_reservation


@contextmanager
def vram_reservation(owner: str, gb: float):
    """
    Réserve `gb` pour la DURÉE d'un bloc, puis libère — y compris si le bloc lève.

    Destiné aux consommateurs de VRAM qui ne sont PAS des `BaseModelBackend` résidents :
    typiquement un **sous-processus** (MuseTalk, CodeFormer) ou un **service séparé** (TTS).
    Leur empreinte est invisible du process appelant — sans déclaration, le gouverneur croit
    la VRAM libre et laisse démarrer une autre tâche GPU par-dessus. C'est exactement le
    scénario qui a produit les kernel panics du 29/07.

    ⚠️ Une réservation expire après `RESERVATION_TTL_S` (1 h) — garde-fou pour qu'un process
    mort ne gèle pas le registre. Ne pas envelopper un bloc plus long sans rafraîchissement
    (les appelants actuels sont bornés par un `timeout` de 10 et 30 min).

        with vram_reservation(f"avatarizer.musetalk:{os.getpid()}", 8.0):
            subprocess.run([...], timeout=600)
    """
    reserve_vram(owner, gb)
    try:
        yield
    finally:
        release_reservation(owner)


def reservations(exclude: str | None = None) -> dict[str, float]:
    """
    Réservations VIVANTES (Go par owner). Les lignes plus vieilles que
    `RESERVATION_TTL_S` sont ignorées ET purgées : elles viennent d'un process
    mort sans libérer.
    """
    return {owner: gb for owner, (gb, _) in _reservations_raw(exclude=exclude).items()}


def _reservations_raw(exclude: str | None = None) -> dict[str, tuple[float, float]]:
    """Réservations vivantes AVEC leur horodatage : owner → (Go, posé_le).

    Le timestamp sert de repli d'inactivité pour un modèle chargé mais jamais
    utilisé (`idle_models`) — `reservations()` n'expose que les Go pour ne pas
    changer son contrat.
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
            alive[owner] = (gb, stamp)

    if stale:
        try:
            client.hdel(_LEDGER_KEY, *stale)
            client.hdel(_USED_KEY, *stale)   # l'horodatage d'usage suit sa réservation
            logger.info(f"[ResourceGovernor] réservations périmées purgées : {stale}")
        except Exception:
            pass
    return alive


def reserved_gb(exclude: str | None = None) -> float:
    """Total réservé par les AUTRES détenteurs (tous process confondus)."""
    return sum(reservations(exclude=exclude).values())


#: Sépare détenteur et modèle dans la clé d'owner (cf. `common.backends.base`).
#: `#` et non `:` : les clés de catalogue en contiennent (`anonymizer:yolo:yolo11n.pt`).
OWNER_MODEL_SEP = '#'


def resident_models() -> dict[str, float]:
    """
    Modèles actuellement RÉSIDENTS en VRAM — `AIModel.model_key` → Go — tous process
    confondus (workers Celery, service TTS, web).

    C'est la réponse à une question à laquelle `AIModel.is_loaded` ne pouvait pas
    répondre : un booléen en base n'est écrit par personne (aucun `is_loaded=True` dans
    le dépôt) et surtout un modèle vit dans le process qui l'a chargé — un singleton
    Python n'est jamais visible d'un autre process. Le registre partagé, lui, l'est,
    et ses lignes expirent seules si un worker meurt sans libérer.

    Les détenteurs qui ne déclarent pas de modèle (sous-processus MuseTalk/CodeFormer
    via `vram_reservation`) sont ignorés : ils occupent de la VRAM sans qu'un modèle du
    catalogue soit résident — c'est `reserved_gb()` qui les compte, pas cette fonction.
    """
    par_modele: dict[str, float] = {}
    for owner, gb in reservations().items():
        cle = model_key_of(owner)
        if cle:
            # Somme : le même modèle peut être résident dans PLUSIEURS process
            # (deux workers GPU), et chacun en occupe sa propre empreinte.
            par_modele[cle] = par_modele.get(cle, 0.0) + gb
    return par_modele


def model_key_of(owner: str) -> str | None:
    """Clé catalogue portée par une clé d'owner, ou None si elle n'en porte pas."""
    if OWNER_MODEL_SEP not in owner:
        return None
    return owner.split(OWNER_MODEL_SEP, 1)[1].strip() or None


def mark_used(owner: str) -> bool:
    """Horodate le dernier USAGE de `owner` (appelé à chaque `process()` d'un backend).

    Sans ce signal, « inactif » ne peut pas se distinguer de « chargé » : c'est ce qui
    manquait à `WAMAMemoryTracker`, dont le champ `last_used` existait mais que personne
    n'alimentait (aucun appel à `register_model` dans le dépôt).
    """
    client = _redis()
    if client is None:
        return False
    try:
        client.hset(_USED_KEY, owner, f"{_now():.0f}")
        client.expire(_USED_KEY, RESERVATION_TTL_S * 2)
        return True
    except Exception as exc:
        logger.debug(f"[ResourceGovernor] mark_used({owner}) : {exc}")
        return False


def idle_models(idle_threshold_s: int = 300) -> list[dict]:
    """
    Modèles RÉSIDENTS inactifs depuis plus de `idle_threshold_s`, tous process confondus.

    Un modèle chargé mais jamais utilisé compte son inactivité depuis son CHARGEMENT :
    sans ce repli il paraîtrait éternellement actif, alors que c'est le cas le plus
    typique d'occupation inutile (préchargement suivi d'aucune demande).
    """
    client = _redis()
    usages: dict[str, float] = {}
    if client is not None:
        try:
            for k, v in (client.hgetall(_USED_KEY) or {}).items():
                owner = k.decode() if isinstance(k, bytes) else str(k)
                try:
                    usages[owner] = float(v.decode() if isinstance(v, bytes) else v)
                except (TypeError, ValueError):
                    continue
        except Exception:
            pass

    now, out = _now(), []
    for owner, (gb, pose_le) in _reservations_raw().items():
        cle = model_key_of(owner)
        if not cle:
            continue                      # détenteur sans modèle (sous-processus)
        dernier = usages.get(owner, pose_le)
        inactif = now - dernier
        if inactif >= idle_threshold_s:
            out.append({
                'model_key': cle,
                'owner': owner,
                'vram_gb': round(gb, 2),
                'idle_seconds': int(inactif),
                'idle_minutes': round(inactif / 60, 1),
                'jamais_utilise': owner not in usages,
            })
    return sorted(out, key=lambda d: -d['idle_seconds'])


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
    # Pseudo-app : passe d'évaluation LLM des candidats de prospection
    # (`model_manager.assess_proposed`). La charge tourne dans l'OLLAMA HÔTE (même GPU
    # physique) : file gpu --pool=solo pour la SÉRIALISER derrière les traitements, palier
    # le plus bas. Leçon du 2026-08-19 : enchaînée hors gouverneur, elle a fait tomber
    # l'hôte (pattern « Ollama hôte enchaîné », instabilité sous l'OS).
    "_prospect_assess": "basse",
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
