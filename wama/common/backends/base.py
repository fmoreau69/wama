"""
Contrat de backend de modèle COMMUN à WAMA — extrait de l'app de référence (Transcriber).

But : un fonctionnement générique et **non bloquant pour de nouveaux modèles**. Un nouveau backend =
une sous-classe qui déclare ses dépendances et implémente le cycle de vie ; **aucune modif du cœur**.

⚠️ Cet en-tête a longtemps dit « CONTRAT SEUL, aucune app n'est encore migrée dessus » et renvoyait
à `BACKEND_CARTOGRAPHY.md` — **les deux sont faux depuis 2026-07** (corrigé le 13/08). Huit apps en
dérivent (anonymizer, avatarizer, composer, enhancer, imager, reader, transcriber, et depuis le
14/08 le synthesizer — dont les backends sont chargés par le service TTS, un process séparé : le
registre Redis du gouverneur étant cross-process, la comptabilité reste juste). La cartographie
est consolidée dans `WAMA_APP_GENERATION_ROUTE.md` (l'ancien fichier est archivé sous `docs/archive/`).

Ce module est aussi **l'alimentation de la route de suivi des modèles** : `__init_subclass__`
enveloppe `load`/`unload`/`process` à N'IMPORTE QUELLE profondeur d'héritage, et c'est par là que
le gouverneur (`common/services/resource_governor.py`) apprend qui occupe la VRAM
(`reserve_vram` / `release_reservation` / `mark_used`). Le registre `_LIVE_BACKENDS` ci-dessous
en est le pendant côté ACTION : il enregistre l'unloader de l'app à la première résidence réelle.
Sans ce module, le gouverneur ne verrait rien — voir `WAMA_MECANISMES.md` (Contrat de backend).

Le COMMUN est le **cycle de vie** (is_available / load / is_loaded / unload), pas le verbe métier :
les apps exposent `transcribe()/generate()/enhance()/...` en déléguant à `process(**kwargs)`.

Jonction prospection/installation : `missing_packages()` indique les libs à installer pour qu'un
modèle puisse tourner → consommé par le model_installer (proposer/poser les paquets) et par les tests
nocturnes (`is_available()==False` → scénario skippé, pas en échec).
"""
from __future__ import annotations

import functools
import importlib.util
import logging
import os
import weakref
from abc import ABC, abstractmethod
from typing import List, Optional

logger = logging.getLogger(__name__)


_WRAPPED = "_wama_governor_wrapped"

#: Attribut d'instance mémorisant la clé d'owner RÉELLEMENT publiée au registre VRAM.
#: Indispensable depuis que la clé porte le modèle : au déchargement le backend a déjà
#: oublié son modèle courant, la clé ne serait donc plus reconstituable.
_GOV_KEY = "_wama_governor_owner"

#: Attribut d'instance mémorisant les Go RÉELLEMENT publiés — sans lui, un rafraîchissement
#: de TTL (`refresh_live_reservations`) devrait re-mesurer, ce qui n'a pas de sens hors du
#: chargement (la mesure est un delta autour de `load()`).
_GOV_GB = "_wama_governor_gb"

# En dessous, la mesure est jugée non concluante (chargement paresseux) et l'on
# retombe sur `recommended_vram_gb`.
_MEASURE_FLOOR_GB = 0.1


# ── Registre des backends RÉSIDENTS (source du reclaim VRAM cross-app) ───────────
#
# Le gouverneur tient une COMPTABILITÉ (qui détient combien) ; il ne sait pas *décharger*.
# Le reclaim, lui, a besoin de l'objet vivant. Ce registre est ce chaînon : alimenté par
# l'enveloppe `load` (donc à n'importe quelle profondeur d'héritage, cf. classe intermédiaire),
# purgé par l'enveloppe `unload`, et en WeakSet pour ne jamais maintenir un modèle en vie.
#
# ⚠ Il rend l'unloader d'une app AUTOMATIQUE : plus rien à déclarer app par app tant que ses
# backends dérivent de BaseModelBackend. Une app hors contrat (modèle en variable de module)
# doit encore appeler `register_vram_unloader` dans son `apps.py::ready()`.
_LIVE_BACKENDS: "dict[str, weakref.WeakSet]" = {}


def _app_of(instance) -> str:
    """App propriétaire d'un backend, déduite de son module (`wama.<app>.…`)."""
    parts = type(instance).__module__.split('.')
    return parts[1] if len(parts) > 1 and parts[0] == 'wama' else parts[0]


def unload_app_backends(app: str) -> bool:
    """Décharge les backends résidents de `app`. True si quelque chose a été libéré."""
    freed = False
    for instance in list(_LIVE_BACKENDS.get(app) or ()):
        try:
            if not getattr(instance, 'is_loaded', True):
                continue
            instance.unload()
            freed = True
        except Exception:
            logger.warning("Déchargement de %s échoué", type(instance).__name__, exc_info=True)
    return freed


def refresh_live_reservations() -> int:
    """Rafraîchit le TTL de la ligne de registre de chaque backend résident de CE process.

    Une réservation expire après `RESERVATION_TTL_S` (1 h) pour qu'un process mort ne gèle
    pas le GPU — garde-fou légitime, mais qui rendrait INVISIBLE un modèle résident à demeure
    dans un process vivant (cas nommé : Kokoro dans le service TTS, chaud en permanence pour
    la vocalisation temps réel). Un process qui héberge des résidents longue durée appelle
    ceci périodiquement (période < TTL) ; les Go re-publiés sont ceux MESURÉS au chargement
    (`_GOV_GB`), pas une re-mesure. Retourne le nombre de lignes rafraîchies.
    """
    refreshed = 0
    for bucket in _LIVE_BACKENDS.values():
        for instance in list(bucket):
            owner = getattr(instance, _GOV_KEY, None)
            gb = getattr(instance, _GOV_GB, None)
            if not owner or not gb:
                continue
            try:
                from wama.common.services.resource_governor import reserve_vram
                reserve_vram(owner, float(gb))
                refreshed += 1
            except Exception:
                logger.debug("Rafraîchissement de %s ignoré", owner, exc_info=True)
    return refreshed


def _track_live(instance) -> None:
    app = _app_of(instance)
    bucket = _LIVE_BACKENDS.get(app)
    if bucket is None:
        bucket = _LIVE_BACKENDS[app] = weakref.WeakSet()
        # Enregistrement à la PREMIÈRE résidence réelle, pas à l'import : le registre
        # ne contient donc que des apps ayant effectivement chargé un modèle.
        try:
            from wama.model_manager.services.memory_manager import register_vram_unloader
            register_vram_unloader(app, functools.partial(unload_app_backends, app))
        except Exception:
            logger.debug("Enregistrement de l'unloader %s ignoré", app, exc_info=True)
    bucket.add(instance)


def _untrack_live(instance) -> None:
    bucket = _LIVE_BACKENDS.get(_app_of(instance))
    if bucket is not None:
        bucket.discard(instance)


def _wrap_load(func):
    """Déclare l'empreinte VRAM au gouverneur après un chargement réussi."""
    if getattr(func, _WRAPPED, False):
        return func

    @functools.wraps(func)
    def wrapper(self, *args, **kwargs):
        before = _vram_snapshot()
        result = func(self, *args, **kwargs)
        try:
            if result is not False:
                gb = _measured_vram_gb(before) if before is not None else None
                # Une mesure NULLE n'est pas une preuve d'absence d'empreinte :
                # chargement paresseux, poids déplacés vers le GPU plus tard, ou
                # mémoire prise hors de l'allocateur PyTorch. On retombe alors sur
                # la valeur déclarée — qui vaut None pour un backend purement CPU,
                # auquel cas on ne réserve rien, ce qui est correct.
                if gb is None or gb < _MEASURE_FLOOR_GB:
                    gb = self.recommended_vram_gb
                if gb:
                    from wama.common.services.resource_governor import (
                        release_reservation, reserve_vram,
                    )
                    owner = _governor_owner(self)
                    # La clé porte désormais le modèle : un backend qui BASCULE de modèle
                    # sans décharger (diffusers, cogvideox…) publierait deux lignes pour un
                    # seul détenteur, dont une fantôme jusqu'à expiration du TTL. On rend
                    # donc la précédente. D'où la mémorisation de la clé PUBLIÉE : au
                    # déchargement, `_current_model` est déjà remis à None et la clé ne
                    # serait plus reconstituable.
                    prev = getattr(self, _GOV_KEY, None)
                    if prev and prev != owner:
                        release_reservation(prev)
                    reserve_vram(owner, float(gb))
                    try:
                        setattr(self, _GOV_KEY, owner)
                        setattr(self, _GOV_GB, float(gb))
                    except Exception:
                        pass
        except Exception:
            logger.debug("Déclaration VRAM au gouverneur ignorée", exc_info=True)
        _track_live(self)
        return result

    setattr(wrapper, _WRAPPED, True)
    return wrapper


def _wrap_unload(func):
    """Libère la réservation VRAM au gouverneur après un déchargement."""
    if getattr(func, _WRAPPED, False):
        return func

    @functools.wraps(func)
    def wrapper(self, *args, **kwargs):
        result = func(self, *args, **kwargs)
        try:
            # `release_reservation` et NON `release_vram` : ici on rend la LIGNE DE REGISTRE du
            # gouverneur, on ne décharge rien du GPU (le déchargement vient de se produire
            # juste au-dessus, dans `func`). L'ancien nom était l'homonyme de
            # `MemoryManager.release_vram()`, qui lui vide réellement la VRAM.
            from wama.common.services.resource_governor import release_reservation
            # La clé PUBLIÉE, pas une clé recalculée : `func` vient de décharger et a
            # remis `_current_model` à None, donc `_governor_owner(self)` ne rendrait
            # plus la même chaîne et la ligne resterait au registre jusqu'au TTL.
            release_reservation(getattr(self, _GOV_KEY, None) or _governor_owner(self))
            try:
                setattr(self, _GOV_KEY, None)
                setattr(self, _GOV_GB, None)
            except Exception:
                pass
        except Exception:
            logger.debug("Libération de la réservation au gouverneur ignorée", exc_info=True)
        _untrack_live(self)
        return result

    setattr(wrapper, _WRAPPED, True)
    return wrapper


def _wrap_process(func):
    """Horodate l'USAGE du modèle au gouverneur, à chaque traitement."""
    if getattr(func, _WRAPPED, False):
        return func

    @functools.wraps(func)
    def wrapper(self, *args, **kwargs):
        # AVANT l'appel : un traitement long (génération vidéo) ne doit pas paraître
        # inactif pendant toute son exécution. Et si `func` lève, le modèle a quand
        # même servi — l'horodatage reste juste.
        try:
            owner = getattr(self, _GOV_KEY, None)
            if owner:
                from wama.common.services.resource_governor import mark_used
                mark_used(owner)
        except Exception:
            logger.debug("Horodatage d'usage ignoré", exc_info=True)
        return func(self, *args, **kwargs)

    setattr(wrapper, _WRAPPED, True)
    return wrapper


#: Sépare l'identité du DÉTENTEUR (backend + process) de celle du MODÈLE dans la clé
#: d'owner. `#` et non `:` : les clés de catalogue en contiennent déjà
#: (`anonymizer:yolo:yolo11n.pt`), un découpage sur `:` serait ambigu.
GOVERNOR_MODEL_SEP = '#'


def _backend_model_key(instance, model=None) -> Optional[str]:
    """Clé CATALOGUE du modèle porté par ce backend, ou None s'il ne l'expose pas.

    `AIModel.model_key` vaut `<source>:<model_id>` et les backends nomment leur
    modèle courant `_current_model` (= le `model_id`) — convention déjà lue par
    `model_registry._discover_imager_models`. La clé se reconstitue donc exactement,
    sans table de correspondance à tenir.
    """
    name = model
    if name is None:
        for attr in ('_current_model', 'current_model', 'model_name'):
            name = getattr(instance, attr, None)
            if name:
                break
    if not name:
        return None
    return f"{_app_of(instance)}:{name}"


def _governor_owner(instance, model=None) -> str:
    """Identité de ce backend, dans CE process, pour le registre VRAM partagé.

    Porte le MODÈLE quand le backend l'expose. Sans lui le registre ne sait dire que
    « tel backend détient 8 Go dans tel process » : impossible d'en déduire QUEL modèle
    est résident, donc impossible pour `select_model(prefer_loaded=True)` d'éviter un
    déchargement/rechargement. La docstring de `reserve_vram` donnait déjà
    « imager:qwen-image-2 » en exemple d'owner — l'intention précédait l'implémentation.
    """
    base = f"{type(instance).__module__}.{type(instance).__name__}:{os.getpid()}"
    key = _backend_model_key(instance, model)
    return f"{base}{GOVERNOR_MODEL_SEP}{key}" if key else base


def _measured_vram_gb(before_bytes) -> Optional[float]:
    """Empreinte VRAM réellement prise depuis `before_bytes`, ou None hors CUDA."""
    try:
        import torch

        if not torch.cuda.is_available():
            return None
        return max(0.0, (torch.cuda.memory_allocated() - before_bytes) / (1024 ** 3))
    except Exception:
        return None


def _vram_snapshot() -> Optional[int]:
    try:
        import torch

        return torch.cuda.memory_allocated() if torch.cuda.is_available() else None
    except Exception:
        return None


class BaseModelBackend(ABC):
    """
    Backend de modèle local (chargement/déchargement + traitement).

    DÉCLARATION AUTOMATIQUE AU GOUVERNEUR DE RESSOURCES
    ===================================================
    Tout sous-classe voit ses `load()` / `unload()` enveloppés automatiquement
    (`__init_subclass__`) pour déclarer/libérer son empreinte VRAM dans le
    registre PARTAGÉ (`common/services/resource_governor.py`).

    Pourquoi ici et pas dans chaque app : c'est le seul point par lequel passent
    tous les backends, présents ET à venir. Un backend futur hérite de la
    déclaration sans que personne n'y pense — c'est ce qui évite de « perdre un
    mécanisme en route ».

    L'empreinte déclarée est **MESURÉE** (delta `torch.cuda.memory_allocated()`
    autour du chargement), et retombe sur `recommended_vram_gb` seulement si la
    mesure est impossible. La mesure prime volontairement sur le déclaratif :
    le 29/07/2026, le preset de `qwen-image` annonçait 16 Go pour une empreinte
    réelle de 38,1 Go — c'est cet écart qui a fait paniquer le noyau WSL2.

    Le câblage ne peut JAMAIS faire échouer un chargement : toute erreur du
    gouverneur est avalée (le backend garde son comportement d'origine).
    """

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        # N'envelopper QUE les méthodes définies par cette classe-ci : sans ce
        # garde, une sous-classe de sous-classe (imager : Base → ImagerBase →
        # backend concret) ré-envelopperait une méthode déjà enveloppée et
        # compterait l'empreinte deux fois.
        if "load" in cls.__dict__:
            cls.load = _wrap_load(cls.__dict__["load"])
        if "unload" in cls.__dict__:
            cls.unload = _wrap_unload(cls.__dict__["unload"])
        if "process" in cls.__dict__:
            cls.process = _wrap_process(cls.__dict__["process"])

    # ── Déclaratif (métadonnée-driven) ───────────────────────────────────────
    # Modules d'import requis pour faire tourner ce backend (ex. ['df', 'torch']).
    REQUIRED_PACKAGES: List[str] = []
    # Paquets pip à installer si un import manque (souvent = REQUIRED_PACKAGES, mais le nom pip
    # peut différer du nom d'import : ex. import 'cv2' ↔ pip 'opencv-python'). Override au besoin.
    PIP_PACKAGES: Optional[List[str]] = None
    #: Installer les paquets SANS leurs dépendances (`pip install --no-deps`, 2026-09-03).
    #: À déclarer quand un pin AMONT trop serré rétrograderait une dépendance PARTAGÉE du
    #: venv — cas mesuré : `qwen-tts==0.1.1` épingle `transformers==4.57.3` alors que WAMA
    #: tourne en 4.57.6 et que le paquet s'importe parfaitement sans rétrogradation.
    #: ⚠ Le prix est un DEVOIR : en `--no-deps`, pip ne comble plus les oublis — `PIP_PACKAGES`
    #: doit lister EXHAUSTIVEMENT ce qui manque au venv (à VÉRIFIER par un import réel).
    PIP_NO_DEPS: bool = False
    recommended_vram_gb: Optional[float] = None
    description: str = ""

    #: MOTEUR piloté par ce backend — la librairie qui exécute réellement le modèle
    #: (`faster-whisper`, `diffusers`, `coqui`, `audio-cpp`…), déclarée le 2026-09-03
    #: (recadrage Fabien : *le backend n'EST PAS le moteur, il l'APPELLE*).
    #:
    #: C'est la MOITIÉ BACKEND du lien modèle↔moteur : le modèle déclare le moteur qu'il
    #: exige (`AIModel.composition['runtime']['engine']`), le backend déclare celui qu'il
    #: sait piloter, et `known_engines()` en dérive l'inventaire des exécutables — plus
    #: aucune liste tenue à la main. Vocabulaire PARTAGÉ avec les manifestes de modèle :
    #: une valeur nouvelle ici doit être celle qu'un modèle écrirait, sinon le lien ne se
    #: refermera jamais.
    #:
    #: Vide = backend qui n'expose pas de moteur nommé (base métier abstraite, adaptateur
    #: interne). Ce n'est pas un défaut : ce qui compte est qu'aucun moteur EXIGÉ par un
    #: modèle ne reste sans exécutant — c'est ce que la page Backends signale.
    ENGINE: str = ""

    # ── Capacités déclarées par le moteur (vocabulaire commun) ───────────────
    # Vocabulaire figé par `common/utils/model_capabilities.py` (source unique) — qui annonce
    # depuis 2026-07-01 que le préfixe `supports_` est « ALIGNÉ sur les flags backend », alors
    # que le contrat commun n'en portait AUCUN. Conséquence mesurée le 2026-08-20 : DEUX chemins
    # de déclaration pour la même notion — le STT les portait au backend (`SpeechToTextBackend`,
    # recopiés par son manager), le TTS ne les portait nulle part et c'est le registre de
    # découverte qui les écrivait à la main À LA PLACE des moteurs (`supports_cloning=True
    # # XTTS = clonage`). Un moteur ne pouvait donc pas déclarer ce qu'il sait faire.
    #
    # Défauts FALSE : un backend ne promet rien tant qu'il ne l'a pas déclaré. Une sous-classe
    # qui redéclare le même flag garde exactement son comportement (override à valeur égale).
    supports_diarization: bool = False
    supports_timestamps: bool = False
    supports_hotwords: bool = False
    supports_streaming: bool = False
    supports_cloning: bool = False
    #: Borne LANGUE de `supports_timestamps` (cf. vocabulaire commun) : liste vide/None = la
    #: capacité vaut pour toutes les langues du moteur. Lire via `supports_timestamps_for()`,
    #: jamais le booléen seul — sinon la borne se perd au premier appelant qui l'ignore.
    timestamp_languages: Optional[List[str]] = None
    #: Langues que le moteur ACCEPTE sans les servir proprement — il produit un résultat, mais
    #: par un pipeline d'emprunt (cas mesuré : Kokoro rabat 8 langues sur le pipeline anglais,
    #: donc une voix anglaise lit de l'allemand). Elles ne sont PAS dans `languages` : le
    #: catalogue ne doit jamais les annoncer comme gérées. Déclarées ici pour que l'UI puisse
    #: les DISTINGUER d'un refus pur et le dire à l'utilisateur — sans quoi l'app choisit entre
    #: mentir (« supportée ») et mentir autrement (« impossible »), alors qu'un son sort.
    #: Vide/None = le moteur n'a pas de repli, ce qui est le cas général.
    fallback_languages: Optional[List[str]] = None

    # ── Disponibilité / dépendances (hook prospection) ───────────────────────
    @classmethod
    def missing_packages(cls) -> List[str]:
        """Modules requis dont l'import est introuvable (sans les importer réellement)."""
        missing = []
        for mod in cls.REQUIRED_PACKAGES:
            try:
                if importlib.util.find_spec(mod) is None:
                    missing.append(mod)
            except (ImportError, ValueError, ModuleNotFoundError):
                missing.append(mod)
        return missing

    @classmethod
    def is_available(cls) -> bool:
        """
        True si le backend peut RÉELLEMENT tourner. Défaut : aucun paquet pip manquant (find_spec).

        ⚠️ OVERRIDE par un vrai try-import quand il y a des dépendances NATIVES : `find_spec('df')`
        trouve le paquet alors qu'`import df` peut échouer (lib native `libdf` absente). Le défaut
        find_spec répond à « faut-il pip install ? » (→ missing_packages), pas à « ça importe ? ».
        Exemple d'override correct : `DeepFilterNetBackend.is_available()` fait `try: import df`.
        """
        return not cls.missing_packages()

    @classmethod
    def pip_install_spec(cls) -> List[str]:
        """Paquets pip à installer pour rendre le backend disponible (pour le model_installer)."""
        if cls.PIP_PACKAGES is not None:
            return cls.PIP_PACKAGES
        return list(cls.REQUIRED_PACKAGES)

    # ── Cycle de vie (à implémenter) ─────────────────────────────────────────
    @abstractmethod
    def load(self, model: Optional[str] = None) -> bool:
        """Charge le modèle en mémoire. Retourne True si chargé. Idempotent si déjà chargé."""

    @property
    @abstractmethod
    def is_loaded(self) -> bool:
        """True si le modèle est actuellement chargé en mémoire."""

    @abstractmethod
    def unload(self) -> None:
        """Décharge le modèle et libère la VRAM/RAM. No-op si déjà déchargé."""

    @abstractmethod
    def process(self, **kwargs):
        """Point d'entrée métier générique. Les apps exposent un alias (transcribe/generate/…)."""

    # ── Confort ──────────────────────────────────────────────────────────────
    def info(self) -> dict:
        return {
            "backend": type(self).__name__,
            "available": self.is_available(),
            "missing_packages": self.missing_packages(),
            "loaded": self.is_loaded,
            "recommended_vram_gb": self.recommended_vram_gb,
            "description": self.description,
        }
