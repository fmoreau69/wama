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

CE QU'IL COUVRE (état au 2026-09-14)
====================================
  1. `configure_cuda_process()`  — garde niveau PROCESS : plafonne l'allocateur
     CUDA. À appeler une fois par process susceptible de toucher le GPU.
  2. Registre VRAM PARTAGÉ (Redis) — `reserve_vram` / `release_reservation` /
     `unseen_reserved_gb` / `effective_free_gb`, visible de TOUS les process (worker
     GPU, service TTS, workers web), contrairement au registre d'unloaders qui reste
     local. Une ligne est une ANNONCE ou une empreinte DÉJÀ ALLOUÉE : chaque sonde ne
     retranche que ce qu'elle ne voit pas encore (cf. `unseen_reserved_gb`).
  3. `APP_TIERS` / `celery_priority_for` — priorités DÉCLARATIVES par app, câblées
     dans `CELERY_TASK_ROUTES` depuis le 2026-07-29.

CE QU'IL NE COUVRE PAS ENCORE (cf. ROADMAP §Gouvernance des ressources)
======================================================================
  - Admission CPU/RAM sur la file `default` (rien aujourd'hui : `--autoscale=4,1`
    sans conscience mémoire).
  - Équité entre utilisateurs : la file est FIFO strict, un batch de 50 items
    d'un utilisateur affame les autres.
  - Déchargement INTER-process : le reclaim (`MemoryManager.release_vram`) reste
    local au process qui l'appelle ; seul Ollama se décharge à distance.
Ces points s'ajoutent ICI, pas dans les apps.

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

#: Empreintes DÉJÀ ALLOUÉES par l'allocateur torch d'un process : owner → pid (2026-09-14).
#: Hash SÉPARÉ, même raison que `_USED_KEY`. Sans lui, le registre ne distinguait pas une
#: ANNONCE (posée avant d'allouer) d'une empreinte MESURÉE après chargement — et les sondes
#: qui voient déjà cette dernière la retranchaient une seconde fois (cf. `unseen_reserved_gb`).
_ALLOC_KEY = "wama:vram:allocated"

#: Horodatage du PREMIER dépôt d'une ligne — son chargement : owner → ts (2026-09-14). Le
#: battement réécrit l'horodatage de la ligne (TTL) ; sans ce hash, un modèle chargé et jamais
#: utilisé paraissait « actif » à chaque battement, et le nettoyeur ne le voyait jamais inactif.
_LOADED_KEY = "wama:vram:loaded_at"

#: Ce qui vit et meurt avec une ligne de réservation.
_SIDE_KEYS = (_USED_KEY, _ALLOC_KEY, _LOADED_KEY)

# Une réservation expire seule : si un process meurt sans libérer (kernel panic,
# kill -9), sa ligne ne doit pas bloquer le GPU pour toujours. Un détenteur VIVANT la
# rafraîchit (`RESERVATION_HEARTBEAT_S`) : le TTL ne sanctionne que le process mort.
RESERVATION_TTL_S = 3600

#: Période de rafraîchissement d'une ligne tenue par un process vivant — strictement sous le
#: TTL. Utilisée par le battement des résidents (`base.start_reservation_heartbeat`) et par
#: `vram_reservation` pour les blocs plus longs que le TTL (audio.cpp : `1800 + 30 × durée` s).
RESERVATION_HEARTBEAT_S = 600


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


def reserve_vram(owner: str, gb: float, *, allocated: bool = False,
                 expires_in_s: float | None = None) -> bool:
    """
    Déclare que `owner` détient `gb` de VRAM. Écrase la ligne existante du même
    owner (donc sert aussi de rafraîchissement de TTL).

    `owner` doit être STABLE et identifier le détenteur réel, pas la tâche. Formes publiées :
    `<module>.<Classe>:<pid>#<clé>` (contrat de backend), `composer.audiocpp:<pid>`
    (sous-processus), `ollama-host#ollama:<nom>` (`ollama_host_owner`).

    `allocated=True` : l'empreinte est DÉJÀ prise par l'allocateur torch de CE process (mesure
    de `_wrap_load`). Les sondes qui la voient déjà ne la retranchent plus
    (`unseen_reserved_gb`). Par défaut une ligne est une ANNONCE — et republier en annonce
    retire le marqueur.

    `expires_in_s` : durée de vie plus courte que `RESERVATION_TTL_S`, pour une résidence
    bornée connue d'avance (rappel mémoire : Ollama garde l'embedder 5 min). Posée en
    ANTIDATANT l'horodatage de la ligne : le format `"<go>:<ts>"` reste lisible des process
    restés sur l'ancien code, qui la purgent au même instant.
    """
    client = _redis()
    if client is None:
        return False
    try:
        now = _now()
        stamp = now
        if expires_in_s is not None:
            stamp = now - (RESERVATION_TTL_S - max(0.0, min(float(expires_in_s),
                                                              float(RESERVATION_TTL_S))))
        client.hset(_LEDGER_KEY, owner, f"{gb:.3f}:{stamp:.0f}")
        client.hsetnx(_LOADED_KEY, owner, f"{now:.0f}")
        if allocated:
            client.hset(_ALLOC_KEY, owner, str(os.getpid()))
        else:
            client.hdel(_ALLOC_KEY, owner)
        for key in (_LEDGER_KEY, _ALLOC_KEY, _LOADED_KEY):
            client.expire(key, RESERVATION_TTL_S * 2)
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
        # Registre d'abord, annexes ensuite : entre les deux, une ligne absente ne compte pour
        # rien. L'usage et le chargement partent avec elle (2026-09-14) : un modèle rechargé
        # plus tard par le même détenteur n'hérite plus de l'inactivité de sa vie antérieure.
        client.hdel(_LEDGER_KEY, owner)
        for key in _SIDE_KEYS:
            client.hdel(key, owner)
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

    La ligne est RAFRAÎCHIE toutes les `RESERVATION_HEARTBEAT_S` tant que le bloc dure
    (2026-09-14). Cette docstring disait « appelants bornés à 10 et 30 min » : audio.cpp,
    arrivé depuis, attend jusqu'à `1800 + 30 × durée` s — sa réservation expirait en pleine
    génération. Le TTL ne protège plus que du process MORT, qui n'a plus de battement.

        with vram_reservation(f"avatarizer.musetalk:{os.getpid()}", 8.0):
            subprocess.run([...], timeout=600)
    """
    import threading

    stop = threading.Event()

    def _beat():
        while not stop.wait(RESERVATION_HEARTBEAT_S):
            reserve_vram(owner, gb)

    reserve_vram(owner, gb)
    battement = threading.Thread(target=_beat, daemon=True, name=f"vram-reservation:{owner}")
    battement.start()
    try:
        yield
    finally:
        # Arrêter le battement AVANT de libérer : sinon une republication tardive recréerait
        # une ligne fantôme pour une heure. Le délai couvre un appel Redis bloqué (2 s × 2).
        stop.set()
        battement.join(timeout=10)
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
            for key in _SIDE_KEYS:           # usage, marqueur alloué, chargement : suivent leur ligne
                client.hdel(key, *stale)
            logger.info(f"[ResourceGovernor] réservations périmées purgées : {stale}")
        except Exception:
            pass
    return alive


def reserved_gb(exclude: str | None = None) -> float:
    """Total BRUT réservé, tous détenteurs et process confondus (sauf `exclude`).

    ⚠ Ne pas le retrancher d'une sonde : il contient aussi les empreintes que la sonde voit déjà.
    Pour « combien retrancher », c'est `unseen_reserved_gb(probe)` (2026-09-14)."""
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
        for cle in model_keys_of(owner):
            # Somme : le même modèle peut être résident dans PLUSIEURS process
            # (deux workers GPU), et chacun en occupe sa propre empreinte.
            par_modele[cle] = par_modele.get(cle, 0.0) + gb
    return par_modele


#: Préfixe d'un suffixe d'owner qui porte le NOM LOCAL du modèle (celui que le backend
#: connaît), et non sa clé catalogue — résolu à la LECTURE (2026-09-14).
OWNER_LOCAL_NAME_PREFIX = '@'


def model_keys_of(owner: str) -> list[str]:
    """Clés catalogue du modèle porté par une clé d'owner — [] s'il n'en porte pas, ou si le
    nom ne se résout pas.

    Deux formes de suffixe :
    - une clé catalogue (`ollama-host#ollama:gemma3:4b`, `memory-embed#ollama:bge-m3:latest`) ;
    - `@<nom local>`, publié par le contrat de backend : le process qui charge (service TTS
      compris, SANS ORM) ne sait que sa classe et le nom qu'il sert ; la clé se résout ici, dans
      un process Django (`backends.manager.catalog_keys_for_owner`). Jusqu'au 2026-09-14 la
      source se déduisait du chemin du module : `common:<id>` pour 101 modèles, 0 juste.
    Un nom qui désigne plusieurs clés (Whisper, servi pour describer ET transcriber) les rend
    toutes.
    """
    if OWNER_MODEL_SEP not in owner:
        return []
    suffixe = owner.split(OWNER_MODEL_SEP, 1)[1].strip()
    if not suffixe:
        return []
    if not suffixe.startswith(OWNER_LOCAL_NAME_PREFIX):
        return [suffixe]
    try:
        from wama.common.backends.manager import catalog_keys_for_owner
        return list(catalog_keys_for_owner(owner))
    except Exception:
        return []


def model_key_of(owner: str) -> str | None:
    """Première clé de `model_keys_of` — pour un appelant qui n'en attend qu'une."""
    cles = model_keys_of(owner)
    return cles[0] if cles else None


#: Détenteur des lignes de résidence de l'OLLAMA HÔTE (service séparé, lu par `/api/ps`).
OLLAMA_HOST_OWNER_PREFIX = f"ollama-host{OWNER_MODEL_SEP}"


def ollama_host_owner(name: str) -> str:
    """Clé d'owner de la résidence du modèle Ollama `name`.

    La convention ne s'écrit qu'ICI (2026-09-14) : la synchro du catalogue la pose, et les
    deux voies qui déchargent Ollama (`MemoryManager.unload_model`, olmOCR) la retirent —
    elles l'ignoraient jusque-là, laissant une ligne fantôme jusqu'à la synchro suivante.
    """
    return f"{OLLAMA_HOST_OWNER_PREFIX}ollama:{name}"


def _allocated_by() -> dict[str, int]:
    """owner → pid dont l'allocateur torch tient DÉJÀ l'empreinte (cf. `_ALLOC_KEY`)."""
    client = _redis()
    if client is None:
        return {}
    try:
        raw = client.hgetall(_ALLOC_KEY) or {}
    except Exception:
        return {}
    out: dict[str, int] = {}
    for k, v in raw.items():
        try:
            out[k.decode() if isinstance(k, bytes) else str(k)] = int(
                v.decode() if isinstance(v, bytes) else v)
        except (TypeError, ValueError):
            continue
    return out


def unseen_reserved_gb(probe: str = 'driver', exclude: str | None = None) -> float:
    """
    VRAM réservée que la SONDE `probe` ne voit pas encore — la seule part à lui retrancher.

    Une ligne du registre est soit une ANNONCE (sous-processus, juge de prospection, embedder :
    posée AVANT d'allouer), soit une empreinte DÉJÀ ALLOUÉE (`_wrap_load` publie APRÈS la mesure).
    Retrancher la seconde d'une sonde qui la voit déjà la compte deux fois : c'est le défaut
    mesuré le 2026-09-14 — `effective_free_gb`, `MemoryManager._free_vram_gb` et
    `get_free_vram_gb` retranchaient tout le registre, résidents compris.

    - `probe='driver'` — `torch.cuda.mem_get_info`, toute la machine : voit toute empreinte
      allouée, on ne retranche que les annonces ;
    - `probe='process'` — total − `memory_allocated` de CE process : ne voit que ce que ce
      process a alloué, on retranche tout sauf les empreintes allouées ici même.

    ⚠ Seule une empreinte MESURÉE par l'allocateur torch est marquée allouée. Valeurs déclarées
    (CTranslate2, onnxruntime), Ollama hôte et sous-processus restent des annonces : les compter
    deux fois est prudent, les oublier ne l'est pas. En particulier, que `mem_get_info` sous
    WSL2 voie les allocations de l'hôte Windows (Ollama) n'est PAS mesuré — d'où ce choix.
    """
    if probe not in ('driver', 'process'):
        raise ValueError(f"sonde inconnue : {probe!r} (attendu 'driver' ou 'process')")
    # Marqueurs lus AVANT les lignes : une ligne publiée entre les deux lectures est comptée
    # comme annonce (prudent), jamais l'inverse.
    alloues = _allocated_by()
    pid = os.getpid()
    total = 0.0
    for owner, gb in reservations(exclude=exclude).items():
        detenteur = alloues.get(owner)
        if detenteur is None or (probe == 'process' and detenteur != pid):
            total += gb
    return total


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


#: Empreintes MESURÉES au chargement, en attente d'être rendues au catalogue : owner → "go:ts"
#: (2026-09-14). Hash SÉPARÉ et HORS `_SIDE_KEYS` : une mesure SURVIT à la libération de sa
#: réservation — un modèle peut être déchargé bien avant le passage de
#: `model_manager.persist_measured_vram` (toutes les 10 min).
_MEASURED_KEY = "wama:vram:measured"
MEASURED_TTL_S = 24 * 3600


def record_measured_vram(owner: str, gb: float) -> bool:
    """Consigne une empreinte MESURÉE par l'allocateur torch au chargement de `owner`.

    Appelé par `_wrap_load` seulement pour une mesure FRAÎCHE et concluante — jamais pour une
    valeur déclarée. La clé catalogue se résout plus tard, à la persistance (process Django) :
    le service TTS, qui mesure aussi, n'a pas d'ORM.
    """
    client = _redis()
    if client is None:
        return False
    try:
        client.hset(_MEASURED_KEY, owner, f"{gb:.3f}:{_now():.0f}")
        client.expire(_MEASURED_KEY, MEASURED_TTL_S)
        return True
    except Exception as exc:
        logger.debug(f"[ResourceGovernor] record_measured_vram({owner}) : {exc}")
        return False


def measured_vram() -> dict[str, tuple[float, float]]:
    """Mesures en attente de persistance : owner → (Go, horodatage). Lignes illisibles ignorées."""
    client = _redis()
    if client is None:
        return {}
    try:
        raw = client.hgetall(_MEASURED_KEY) or {}
    except Exception:
        return {}
    out: dict[str, tuple[float, float]] = {}
    for k, v in raw.items():
        owner = k.decode() if isinstance(k, bytes) else str(k)
        text = v.decode() if isinstance(v, bytes) else str(v)
        try:
            gb_text, stamp_text = text.split(":", 1)
            out[owner] = (float(gb_text), float(stamp_text))
        except ValueError:
            continue
    return out


def forget_measured_vram(rendues: dict) -> int:
    """Oublie les mesures RENDUES au catalogue — `rendues` : owner → horodatage lu.

    Une ligne dont l'horodatage a changé entre la lecture et l'oubli (nouveau chargement mesuré
    entre-temps) est GARDÉE : elle sera rendue au passage suivant au lieu d'être perdue.
    """
    client = _redis()
    if client is None or not rendues:
        return 0
    oubliees = 0
    for owner, stamp in rendues.items():
        try:
            cur = client.hget(_MEASURED_KEY, owner)
            if cur is None:
                continue
            text = cur.decode() if isinstance(cur, bytes) else str(cur)
            if float(text.split(":", 1)[1]) == float(stamp):
                oubliees += client.hdel(_MEASURED_KEY, owner)
        except Exception:
            continue
    return oubliees


def idle_models(idle_threshold_s: int = 300) -> list[dict]:
    """
    Modèles RÉSIDENTS inactifs depuis plus de `idle_threshold_s`, tous process confondus.

    Un modèle chargé mais jamais utilisé compte son inactivité depuis son CHARGEMENT :
    sans ce repli il paraîtrait éternellement actif, alors que c'est le cas le plus
    typique d'occupation inutile (préchargement suivi d'aucune demande).
    """
    client = _redis()
    usages: dict[str, float] = {}
    charges: dict[str, float] = {}
    if client is not None:
        for cible, key in ((usages, _USED_KEY), (charges, _LOADED_KEY)):
            try:
                for k, v in (client.hgetall(key) or {}).items():
                    owner = k.decode() if isinstance(k, bytes) else str(k)
                    try:
                        cible[owner] = float(v.decode() if isinstance(v, bytes) else v)
                    except (TypeError, ValueError):
                        continue
            except Exception:
                pass

    now, out = _now(), []
    for owner, (gb, pose_le) in _reservations_raw().items():
        cles = model_keys_of(owner)
        if not cles:
            continue                      # détenteur sans modèle (sous-processus) ou non résolu
        # Dernier usage, sinon le CHARGEMENT — et non l'horodatage de la ligne, que le battement
        # réécrit toutes les 10 min (2026-09-14). La ligne ne sert plus de repli qu'aux lignes
        # posées par un process resté sur l'ancien code, sans `_LOADED_KEY`.
        dernier = usages.get(owner) or charges.get(owner) or pose_le
        inactif = now - dernier
        if inactif >= idle_threshold_s:
            for cle in cles:              # un même poids servi sous deux clés : une ligne chacune
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
    VRAM réellement disponible = ce que le pilote annonce libre, MOINS ce que des
    process ont ANNONCÉ sans l'avoir encore alloué (`unseen_reserved_gb('driver')`).

    C'est la mesure qui manquait : `torch.cuda.mem_get_info()` ne voit que le
    présent et ignore qu'un autre process s'apprête à prendre 18 Go.

    ⚠ Corrigé le 2026-09-14 : on retranchait TOUTES les réservations, y compris les modèles
    résidents dont le pilote a déjà ôté l'empreinte de son libre — chaque résident comptait
    deux fois (la docstring disait déjà « sans l'avoir encore alloué », le code non).
    """
    try:
        import torch

        if not torch.cuda.is_available():
            return 0.0
        driver_free_gb = torch.cuda.mem_get_info()[0] / (1024 ** 3)
    except Exception:
        return 0.0
    return max(0.0, driver_free_gb - unseen_reserved_gb('driver', exclude=exclude))


# ---------------------------------------------------------------------------
# 2 bis. Mode « dépannage GPU » (WAMA_GPU_SAFE_MODE) — réduction de la superposition
# de charges sur le GPU partagé hôte/WSL, le temps de diagnostiquer les crashs hôte
# (INFRA_WSL_VS_WINDOWS §crashs). Interrupteur de CONDITIONS : OFF = comportement
# nominal à l'octet. Le gouverneur est le DOMICILE de cette politique — les
# consommateurs (pipeline de prompts, backends sous-processus) l'interrogent ici.
# ---------------------------------------------------------------------------

def gpu_safe_mode() -> bool:
    """Vrai si le mode dépannage GPU est actif (settings/env `WAMA_GPU_SAFE_MODE`)."""
    from django.conf import settings
    return bool(getattr(settings, 'WAMA_GPU_SAFE_MODE', False))


def pipeline_keep_alive() -> str | None:
    """
    `keep_alive` à passer aux appels Ollama de la pipeline de prompts : '0' en mode
    dépannage (le modèle LLM est déchargé sitôt la réponse rendue, au lieu de rester
    résident ~5 min pendant que la génération GPU monte en charge), None sinon
    (= défaut Ollama, comportement nominal).
    """
    return '0' if gpu_safe_mode() else None


def wait_for_free_vram(needed_gb: float, *, timeout_s: float = 180.0,
                       poll_s: float = 5.0, exclude: str | None = None,
                       console=None) -> tuple[bool, float]:
    """
    Attend que `effective_free_gb()` atteigne `needed_gb`, puis rend (True, mesure).
    À l'épuisement du délai : (False, dernière mesure) — au CALLER de refuser EN LE
    DISANT (jamais un défaut silencieux). Ne décharge rien : l'attente laisse les
    résidences expirer d'elles-mêmes (keep_alive Ollama, TTL des réservations).
    """
    import time
    fin = time.monotonic() + max(0.0, timeout_s)
    libre = effective_free_gb(exclude=exclude)
    while libre < needed_gb:
        if time.monotonic() >= fin:
            return False, libre
        msg = (f"[ResourceGovernor] VRAM mesurée {libre:.1f} Go < {needed_gb:.1f} Go requis "
               f"— attente (mode dépannage GPU)")
        logger.info(msg)
        if console:
            try:
                console(msg)
            except Exception:
                pass
        time.sleep(poll_s)
        libre = effective_free_gb(exclude=exclude)
    return True, libre


# ---------------------------------------------------------------------------
# 2 ter. TENANTS, TÂCHES EN COURS et DEMANDES DE LIBÉRATION — chantier B1 (2026-09-20)
# ---------------------------------------------------------------------------
# Décisions de Fabien (16/09, reformulées le 20/09 — `ROADMAP §Gouvernance`, bloc B1/B2/B3) :
# une tâche qui ne tient pas dans la VRAM libre ATTEND (illimité) que les résidences se
# libèrent d'elles-mêmes ; libérer TOUTE la carte n'intervient que sur ACCORD EXPLICITE de
# l'utilisateur ; un service (TTS, worker, retranscription live à venir) se DÉCLARE au
# gouverneur — nom, occupé ?, décharger, recharger — rien n'est câblé en dur ; le gouverneur
# décide, tous les chemins passent par lui.
#
# Ce que le registre ne savait pas dire avant ce bloc, mesuré le 20/09 : les TÂCHES en cours
# (lues jusque-là dans les statuts `RUNNING` des tables d'app, invisibles d'ici) ; « occupé »
# (un verrou du service TTS n'était visible que de lui) ; et surtout le DÉCHARGEMENT restait
# LOCAL au process (`base.unload_live_backends`, `MemoryManager.release_vram`) — « canal de
# requête inter-process : conçu, non implémenté » (ROADMAP :546). Le canal est ci-dessous : une
# DEMANDE écrite dans Redis, servie par chaque tenant dans son propre process, acquittée ; la
# vérité finale reste la sonde (`effective_free_gb`), jamais le nombre d'acquittements.
#
# Formats : hashs NEUFS, valeurs JSON (la contrainte `"<go>:<ts>"` ne vaut que pour la ligne
# de réservation, lue par des process restés sur l'ancien code).

_TASKS_KEY = "wama:vram:tasks"          # jeton → {app, item, gb, tenant, ts, ttl}
_BUSY_KEY = "wama:vram:busy"            # tenant → ts du dernier « occupé » déclaré
_REQUESTS_KEY = "wama:vram:requests"    # id → {gb, requester, reason, ts}
_ACKS_KEY = "wama:vram:acks"            # id → {tenant: {freed, busy, ts}}
_GRANTS_KEY = "wama:vram:grants"        # "app:item" → ts de l'accord explicite de l'utilisateur

#: Un tenant est « occupé » s'il l'a dit, ou si l'un de ses résidents a servi, depuis moins de
#: cette fenêtre (proposition du 20/09 : un modèle temps réel qui parle est occupé tant qu'il
#: parle ; passée la minute, il ne l'est plus).
BUSY_WINDOW_S = 60
#: Une demande de libération non close meurt seule (requérant mort).
REQUEST_TTL_S = 15 * 60
#: Un accord explicite de l'utilisateur vaut pour l'item, un jour — pas pour toujours.
GRANT_TTL_S = 24 * 3600
#: Durée par défaut d'UN traitement (Fabien, 16/09 : 30 min, réglable) — c'est aussi le TTL de
#: la ligne « tâche en cours », qui expire donc avec le traitement au lieu d'un jour entier.
TASK_DEFAULT_MAX_S = 30 * 60


def tenant_id() -> str:
    """Identité d'un TENANT = un process (le worker gpu, le service TTS, gunicorn…). Les clés
    d'owner du contrat portent ce pid (`<Classe>:<pid>#…`) : c'est ce qui relie un résident à
    son tenant sans table."""
    return str(os.getpid())


def tenant_of_owner(owner: str) -> str | None:
    """Tenant (pid) d'une clé d'owner du contrat, None pour une ligne sans process (Ollama hôte)."""
    import re
    m = re.search(r':(\d+)(?:#|$)', owner or '')
    return m.group(1) if m else None


def fits_alone(needed_gb: float) -> bool | None:
    """`needed_gb` tiendrait-il sur la carte VIDE ? None sans GPU (on ne conclut pas d'une
    absence). C'est le premier des trois cas de Fabien (20/09) : ce qui ne tient pas même seul
    ne se sélectionne pas et ne se lance pas — aucune attente ne changera la taille de la carte."""
    total = total_vram_gb()
    if total <= 0:
        return None
    return float(needed_gb) <= total


def _hash_json(key: str) -> dict:
    client = _redis()
    if client is None:
        return {}
    import json
    try:
        raw = client.hgetall(key) or {}
    except Exception:
        return {}
    out = {}
    for k, v in raw.items():
        name = k.decode() if isinstance(k, bytes) else str(k)
        try:
            out[name] = json.loads(v.decode() if isinstance(v, bytes) else v)
        except (TypeError, ValueError):
            continue
    return out


def _hset_json(key: str, field: str, value: dict, ttl_s: float = RESERVATION_TTL_S * 2) -> bool:
    client = _redis()
    if client is None:
        return False
    import json
    try:
        client.hset(key, field, json.dumps(value))
        client.expire(key, int(ttl_s))
        return True
    except Exception as exc:
        logger.debug(f"[ResourceGovernor] {key}[{field}] : {exc}")
        return False


def _hdel(key: str, *fields) -> None:
    client = _redis()
    if client is None or not fields:
        return
    try:
        client.hdel(key, *fields)
    except Exception:
        pass


# ── Tâches en cours ─────────────────────────────────────────────────────────────────────

def task_started(app_id: str, item_id, needed_gb: float = 0.0, *,
                 max_s: float | None = None) -> str:
    """Déclare une tâche GPU EN COURS ; rend son jeton. Posé par le squelette commun autour de
    la glu (`run_item_task`) — un seul point, aucune app. La ligne expire d'elle-même à
    `max_s` (défaut `TASK_DEFAULT_MAX_S`) : un worker mort ne laisse pas une tâche fantôme."""
    token = f"{app_id}:{item_id}:{tenant_id()}"
    _hset_json(_TASKS_KEY, token, {
        'app': app_id, 'item': item_id, 'gb': round(float(needed_gb or 0.0), 3),
        'tenant': tenant_id(), 'ts': _now(),
        'ttl': float(max_s if max_s is not None else TASK_DEFAULT_MAX_S),
    })
    return token


def task_finished(token: str) -> None:
    _hdel(_TASKS_KEY, token)


def running_tasks() -> list[dict]:
    """Tâches GPU en cours, tous process confondus — lignes expirées purgées."""
    now, alive, stale = _now(), [], []
    for token, line in _hash_json(_TASKS_KEY).items():
        try:
            if now - float(line.get('ts', 0)) > float(line.get('ttl') or TASK_DEFAULT_MAX_S):
                stale.append(token)
                continue
        except (TypeError, ValueError):
            stale.append(token)
            continue
        alive.append({'token': token, **line})
    _hdel(_TASKS_KEY, *stale)
    return alive


# ── Occupé ─────────────────────────────────────────────────────────────────────────────

def mark_busy(tenant: str | None = None) -> bool:
    """Un tenant se déclare OCCUPÉ (le service TTS quand son verrou de synthèse est pris)."""
    return _hset_json(_BUSY_KEY, tenant or tenant_id(), {'ts': _now()})


def clear_busy(tenant: str | None = None) -> None:
    _hdel(_BUSY_KEY, tenant or tenant_id())


def busy_tenants(window_s: float = BUSY_WINDOW_S) -> set[str]:
    """Tenants occupés : déclarés depuis moins de `window_s`, ou dont un résident a SERVI depuis
    moins de `window_s` (`mark_used`, émis à chaque `process()` d'un backend du contrat)."""
    now, out = _now(), set()
    for tenant, line in _hash_json(_BUSY_KEY).items():
        try:
            if now - float(line.get('ts', 0)) < window_s:
                out.add(tenant)
        except (TypeError, ValueError):
            continue
    client = _redis()
    if client is not None:
        try:
            for k, v in (client.hgetall(_USED_KEY) or {}).items():
                owner = k.decode() if isinstance(k, bytes) else str(k)
                stamp = float(v.decode() if isinstance(v, bytes) else v)
                tenant = tenant_of_owner(owner)
                if tenant and now - stamp < window_s:
                    out.add(tenant)
        except Exception:
            pass
    return out


def gpu_is_busy(window_s: float = BUSY_WINDOW_S, *, exclude_tenant: str | None = None) -> bool:
    """Une tâche tourne, ou un tenant sert — hors `exclude_tenant` (le requérant lui-même)."""
    me = exclude_tenant
    if any(t.get('tenant') != me for t in running_tasks()):
        return True
    return bool(busy_tenants(window_s) - ({me} if me else set()))


# ── Accord explicite de l'utilisateur ──────────────────────────────────────────────────

def _grant_key(app_id: str, item_id) -> str:
    return f"{app_id}:{item_id}"


def grant_release(app_id: str, item_id, user_id=None) -> bool:
    """L'utilisateur ACCEPTE que toute la carte soit libérée pour CET item (bouton de la card en
    attente). Sans cet accord, le gouverneur attend ; il ne décharge jamais d'office."""
    return _hset_json(_GRANTS_KEY, _grant_key(app_id, item_id),
                      {'ts': _now(), 'user': user_id}, ttl_s=GRANT_TTL_S)


def revoke_grant(app_id: str, item_id) -> None:
    _hdel(_GRANTS_KEY, _grant_key(app_id, item_id))


def release_granted(app_id: str, item_id) -> dict | None:
    """L'accord vivant pour cet item (`{'ts', 'user'}`), ou None. C'est le squelette — qui connaît
    l'item — qui vérifie que `user` en est le propriétaire (ou un admin)."""
    line = _hash_json(_GRANTS_KEY).get(_grant_key(app_id, item_id))
    try:
        if line and _now() - float(line.get('ts', 0)) < GRANT_TTL_S:
            return line
    except (TypeError, ValueError):
        pass
    return None


# ── Demandes de libération (le canal inter-process) ────────────────────────────────────

def request_release(needed_gb: float, requester: str, reason: str = '') -> str | None:
    """Écrit une DEMANDE : « libérez ce que vous tenez, il me faut `needed_gb` ». Rend son id.
    Chaque tenant la sert dans son process (`serve_release_requests`) ; le requérant attend la
    SONDE, pas les acquittements (`obtain_vram`)."""
    import uuid
    request_id = uuid.uuid4().hex[:12]
    ok = _hset_json(_REQUESTS_KEY, request_id, {
        'gb': round(float(needed_gb), 3), 'requester': requester, 'reason': reason or '',
        'ts': _now(),
    }, ttl_s=REQUEST_TTL_S * 2)
    return request_id if ok else None


def pending_release_requests() -> dict[str, dict]:
    """Demandes vivantes (id → ligne) ; les périmées sont purgées avec leurs acquittements."""
    now, alive, stale = _now(), {}, []
    for request_id, line in _hash_json(_REQUESTS_KEY).items():
        try:
            if now - float(line.get('ts', 0)) > REQUEST_TTL_S:
                stale.append(request_id)
                continue
        except (TypeError, ValueError):
            stale.append(request_id)
            continue
        alive[request_id] = line
    if stale:
        _hdel(_REQUESTS_KEY, *stale)
        _hdel(_ACKS_KEY, *stale)
    return alive


def acknowledge_release(request_id: str, tenant: str, *, freed: int = 0,
                        busy: bool = False) -> bool:
    """Un tenant dit ce qu'il a fait pour cette demande : `freed` instances déchargées, ou
    `busy` (il sert, il ne se décharge pas — le requérant attendra)."""
    acks = _hash_json(_ACKS_KEY).get(request_id) or {}
    acks[tenant] = {'freed': int(freed), 'busy': bool(busy), 'ts': _now()}
    return _hset_json(_ACKS_KEY, request_id, acks, ttl_s=REQUEST_TTL_S * 2)


def release_acks(request_id: str) -> dict:
    return _hash_json(_ACKS_KEY).get(request_id) or {}


def close_release_request(request_id: str) -> None:
    """Le requérant a ce qu'il voulait (ou renonce) : la demande disparaît, et les tenants qui
    s'étaient déchargés POUR elle peuvent restaurer (`serve_release_requests`)."""
    _hdel(_REQUESTS_KEY, request_id)
    _hdel(_ACKS_KEY, request_id)


def obtain_vram(needed_gb: float, requester: str, *, reason: str = '',
                timeout_s: float = 120.0, poll_s: float = 2.0, console=None) -> tuple[bool, float]:
    """Demande la libération, puis ATTEND que la SONDE rende `needed_gb` (bornée : le pilote
    rend la mémoire en secondes, pas en minutes — au-delà, quelque chose ne libère pas et on le
    dit). Rend (obtenu, libre mesuré). La demande est close dans tous les cas."""
    import time
    request_id = request_release(needed_gb, requester, reason)
    if request_id is None:
        return False, effective_free_gb()
    fin = time.monotonic() + max(0.0, timeout_s)
    try:
        while True:
            libre = effective_free_gb()
            if libre >= needed_gb:
                return True, libre
            if time.monotonic() >= fin:
                acks = release_acks(request_id)
                occupes = sorted(t for t, a in acks.items() if a.get('busy'))
                msg = (f"[ResourceGovernor] {libre:.1f} Go libres après demande de libération "
                       f"({needed_gb:.1f} requis) — {len(acks)} tenant(s) ont répondu"
                       + (f", occupés : {occupes}" if occupes else ""))
                logger.info(msg)
                if console:
                    try:
                        console(msg)
                    except Exception:
                        pass
                return False, libre
            time.sleep(poll_s)
    finally:
        close_release_request(request_id)


def release_in_progress() -> bool:
    """Une libération est en cours (au moins une demande vivante). L'assistant le lit pour rester
    MUET et répondre un message d'attente (Fabien, 16/09 : il charge aussi un LLM, pas seulement
    la voix — le laisser parler pendant une libération, c'est recharger ce qu'on vient de rendre)."""
    return bool(pending_release_requests())


def holders_summary(limit: int = 4) -> str:
    """Une phrase pour l'utilisateur : QUI tient QUOI — modèles résidents (Go) et tâches en cours.
    C'est l'information qui manquait à la card « En attente de ressources » : sans elle, l'attente
    ressemble à une panne et l'utilisateur renonce (Fabien, 20/09)."""
    parts = []
    residents = sorted(resident_models().items(), key=lambda kv: -kv[1])
    if residents:
        shown = ', '.join(f"{k} ({gb:.1f} Go)" for k, gb in residents[:limit])
        extra = len(residents) - limit
        parts.append("résidents : " + shown + (f" +{extra}" if extra > 0 else ''))
    tasks = running_tasks()
    if tasks:
        parts.append("en cours : " + ', '.join(f"{t['app']} #{t['item']}" for t in tasks[:limit]))
    return ' ; '.join(parts)


# ── Durée max d'UN traitement ──────────────────────────────────────────────────────────
# Décision Fabien (16/09) : 30 min par défaut, réglable par utilisateur dans son profil ; défaut
# PAR TYPE DE TÂCHE possible (une vidéo longue dépasse 30 min légitimement). Déclaratif, à côté
# d'`APP_TIERS` — pas dans les apps. ⚠ Mesuré le 20/09 : `--pool=solo` N'HONORE AUCUNE limite
# Celery (`celery/concurrency/solo.py:29`, `'timeouts': ()`) — la garde est celle du squelette
# commun (`task_skeleton`), qui lit ce plafond ici.

#: Minutes par app (clé = app_id) ; `_default` pour les autres. Vide = tout au défaut, à dessein :
#: un défaut par type se pose quand une mesure le justifie, pas d'avance.
TASK_MAX_MINUTES = {
    '_default': 30,
}
#: Réglage utilisateur (brique `user_settings`, app `common`) : 0 / absent = le défaut de l'app.
USER_SETTING_MAX_TASK_MINUTES = 'max_task_minutes'
#: Réglage PAR MODÈLE (2026-09-24, demande de Fabien : « 30 min, un peu léger pour une vidéo —
#: un réglage depuis WAMA, depuis le model manager ») : clé d'`AIModel.extra_info`, écrite par
#: l'inspecteur du model manager (`api_model_task_limit`), à côté de `vram_measured` et `eta`.
MODEL_INFO_MAX_TASK_MINUTES = 'max_task_minutes'


def model_task_minutes(model_key: str | None) -> int:
    """Durée max déclarée pour un modèle au catalogue (minutes), 0 si aucune."""
    if not model_key:
        return 0
    try:
        from wama.model_manager.models import AIModel
        info = AIModel.objects.filter(model_key=model_key).values_list(
            'extra_info', flat=True).first() or {}
        return max(0, int(info.get(MODEL_INFO_MAX_TASK_MINUTES) or 0))
    except Exception:
        return 0


def task_time_limit_s(app_id: str, user=None, model_key: str | None = None) -> float:
    """Plafond de durée d'UN traitement, en secondes : le réglage de l'utilisateur s'il en a posé
    un, sinon celui du MODÈLE au catalogue, sinon le défaut de l'app, sinon `_default`."""
    minutes = 0
    if user is not None and getattr(user, 'pk', None):
        try:
            from wama.common.utils.user_settings import get_user_app_setting
            minutes = int(get_user_app_setting(user, 'common', USER_SETTING_MAX_TASK_MINUTES) or 0)
        except Exception:
            minutes = 0
    if minutes <= 0:
        minutes = model_task_minutes(model_key)
    if minutes <= 0:
        minutes = int(TASK_MAX_MINUTES.get(app_id) or TASK_MAX_MINUTES['_default'])
    return float(minutes * 60)


# ── Le tenant : déclaré, jamais câblé ──────────────────────────────────────────────────

class Tenant:
    """Ce qu'un process qui tient de la VRAM DÉCLARE au gouverneur : son nom, comment savoir
    s'il est occupé, comment se décharger, comment se recharger après. Le worker Celery et le
    service TTS en instancient un ; un service futur aussi — sans toucher au gouverneur.

    `unload()` rend le nombre d'instances déchargées ; `restore()` est appelé une fois la
    demande CLOSE, seulement si ce tenant s'est déchargé pour elle (le TTS recharge ses
    `keep_resident`, un worker ne recharge rien : ses modèles reviennent au prochain usage) ;
    `is_busy()` : True = « je sers, je ne me décharge pas maintenant » (le requérant attend)."""

    def __init__(self, name: str, *, unload, restore=None, is_busy=None):
        self.name = name
        self._unload = unload
        self._restore = restore
        self._is_busy = is_busy
        self.unloaded_for: set[str] = set()

    def is_busy(self) -> bool:
        try:
            return bool(self._is_busy()) if self._is_busy else False
        except Exception:
            return True                  # dans le doute, on ne décharge pas

    def unload(self) -> int:
        return int(self._unload() or 0)

    def restore(self) -> None:
        if self._restore:
            self._restore()


def serve_release_requests(tenant: Tenant) -> int:
    """UN passage : sert les demandes que ce tenant n'a pas encore acquittées, restaure après
    celles qui sont closes. Rend le nombre d'instances déchargées. Appelé en boucle par le
    thread de `start_release_listener`, et directement par les tests."""
    me = tenant_id()
    pending = pending_release_requests()
    freed_total = 0
    for request_id, line in pending.items():
        if line.get('requester') == me:
            continue                     # on ne se décharge pas pour sa propre demande
        if me in release_acks(request_id):
            continue
        if tenant.is_busy():
            acknowledge_release(request_id, me, busy=True)
            continue
        try:
            freed = tenant.unload()
        except Exception:
            logger.warning("[ResourceGovernor] %s : déchargement échoué", tenant.name, exc_info=True)
            freed = 0
        freed_total += freed
        if freed:
            tenant.unloaded_for.add(request_id)
        acknowledge_release(request_id, me, freed=freed)
    closed = [r for r in tenant.unloaded_for if r not in pending]
    if closed:
        tenant.unloaded_for.difference_update(closed)
        try:
            tenant.restore()
        except Exception:
            logger.warning("[ResourceGovernor] %s : restauration échouée", tenant.name, exc_info=True)
    return freed_total


_LISTENER = None
RELEASE_POLL_S = 3.0


def start_release_listener(tenant: Tenant, poll_s: float = RELEASE_POLL_S) -> bool:
    """Lance, une fois par process, le thread démon qui sert les demandes de libération pour
    `tenant`. Même famille que `base.start_reservation_heartbeat` (qui garde les lignes
    vivantes) — celui-ci écoute. Rend True s'il vient d'être lancé."""
    global _LISTENER
    if _LISTENER is not None and _LISTENER.is_alive():
        return False
    import threading
    import time

    def _loop():
        while True:
            time.sleep(poll_s)
            try:
                serve_release_requests(tenant)
            except Exception:
                logger.debug("[ResourceGovernor] écoute des demandes ignorée", exc_info=True)

    _LISTENER = threading.Thread(target=_loop, daemon=True, name=f"wama-vram-listener:{tenant.name}")
    _LISTENER.start()
    return True


def contract_tenant(name: str, *, restore=None, is_busy=None) -> Tenant:
    """Le tenant par défaut d'un process qui héberge des modèles : décharge par
    `MemoryManager.release_vram()` (existant) — les backends du contrat (`unload_live_backends`)
    ET les modèles hors contrat inscrits dans `_VRAM_UNLOADERS` (pipeline pyannote en variable de
    module), puis `empty_cache`. Revérification du 20/09 : la 1re version n'appelait que
    `unload_live_backends` et laissait les hors-contrat résidents — le second angle mort nommé au
    palier B1, fermé ici par la brique qui le couvrait déjà. Le worker Celery l'emploie tel quel ;
    le service TTS y ajoute son occupé (verrou) et sa restauration (ses `keep_resident`)."""
    def _unload() -> int:
        from wama.model_manager.services.memory_manager import MemoryManager
        return MemoryManager.release_vram()
    return Tenant(name, unload=_unload, restore=restore, is_busy=is_busy)


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
    # Fonctions GPU du STUDIO (`studio.gpu_tasks`, ex. image→3D §17ter) : demandées par un
    # utilisateur dans un pipeline, au palier des apps média courantes.
    "studio": "normale",
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
