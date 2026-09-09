"""
Manager de backends COMMUN — extrait du pattern Transcriber/Imager.

Registre générique réutilisable : enregistre des classes `BaseModelBackend`, instancie en
singleton (keep_loaded), expose disponibilité/infos, décharge. Sélection auto par priorité.

⚠️ ADDITIF : aucune app n'est forcée de l'adopter. Une app crée son manager et enregistre ses
backends ; ça remplace le boilerplate des managers par-app (transcriber/imager) quand on voudra,
sans toucher aux apps non migrées (ex. Anonymizer, dont Cam Analyzer réutilise les modèles).

La sélection VRAM-aware au niveau CATALOGUE reste à `model_manager.services.model_selector.select_model`
(granularité variante de modèle) ; ici on gère le cycle de vie des backends (granularité moteur).
"""
from __future__ import annotations

import logging
from typing import Dict, List, Optional, Type

from .base import BaseModelBackend

logger = logging.getLogger(__name__)


# ── Inventaire des MOTEURS d'exécution — grisage AUTOMATIQUE (décision Fabien 02/09) ────
#
# Le pending « griser les moteurs sans backend » (31/08) est tranché : PAS de grisage à la
# main — un système qui VÉRIFIE. Chaque producteur enregistre l'inventaire des moteurs
# qu'il sait exécuter (`apps.py:ready()` — le registre ne connaît JAMAIS ses producteurs,
# règle AGENTS.md) ; `backend_missing()` rend un verdict à la demande. Comme l'inventaire
# est RELU à chaque appel, un backend qui apparaît RÉ-AUTORISE tout seul — rien à dégriser.
#
# Verdict PERMISSIF par construction (même doctrine que `matches_inputs`) : on ne condamne
# que le POSITIVEMENT inlançable — un moteur déclaré qu'aucun inventaire ne sert. Un modèle
# sans moteur déclaré, ou porteur d'un `backend_ref` d'app, n'a pas de verdict : l'exclure
# sur une absence d'information viderait des lots entiers (imager/composer déclaratifs).
#
# Consommateurs : `select_model` (un tirage AUTO inlançable est toujours faux → exclu) et
# `get_registry_models` (le select AFFICHE, grisé AVEC la raison — lister n'est pas
# pouvoir choisir, jamais d'exclusion de liste : INPUT_MODEL_MATCHING §2).
_ENGINE_INVENTORIES: List = []


def register_engine_inventory(fn) -> None:
    """Enregistre un inventaire de moteurs. Le callable rend soit un MAPPING
    {moteur: classe de backend} — forme préférée, elle seule permet de remonter au
    contrat du backend (`PIP_PACKAGES`, `missing_packages`) —, soit un simple itérable
    de noms (forme tolérée : aucune classe, le moteur est réputé exécutable)."""
    _ENGINE_INVENTORIES.append(fn)


def engine_backends() -> dict:
    """{moteur: classe de backend} pour tous les inventaires qui exposent leurs classes.

    Rend les moteurs ENREGISTRÉS (installés ou non) : c'est la question « qui sait
    exécuter ce moteur ? », distincte de « peut-il tourner maintenant ? »
    (`known_engines`). C'est cette carte qui permet à un manifeste de MODÈLE de
    remonter à la LIBRAIRIE que son moteur exige (`requires`, 2026-09-03).
    """
    carte = {}
    for fn in _ENGINE_INVENTORIES:
        try:
            res = fn()
            if isinstance(res, dict):
                carte.update(res)
        except Exception as e:   # un inventaire cassé ne condamne pas les autres
            logger.debug("[engines] inventaire %r illisible : %s", fn, e)
    return carte


#: Verdict d'IMPORTABILITÉ par classe de backend : {classe: (instant, exécutable)}.
#: Mémoïsé à court terme (2026-09-05) — `missing_packages()` interroge `importlib.find_spec`
#: pour chaque paquet de chaque backend, soit **400 `find_spec` et 2 904 `stat` sur `/mnt/d`
#: par appel** (profilé). `get_registry_models` appelait `backend_missing` PAR MODÈLE (×8),
#: et la page synthesizer trois fois `get_registry_models` : ~24 inventaires disque par
#: rendu, **4,5 s** pour `/synthesizer/` contre 0,6 s pour `/transcriber/` — c'est ce qui
#: faisait tomber le geste nocturne `synthesizer.import` (mesure pendant le rechargement).
#: La doctrine du 03/09 tient : les INVENTAIRES sont relus à chaque appel (un backend
#: ENREGISTRÉ ré-autorise seul, `tests_auto_model` le tient) ; seul le `stat` du disque n'est
#: pas refait dans la minute. Un pip install n'est pas un événement de la seconde — et
#: `invalidate_engine_cache()` existe pour l'installeur qui veut un verdict immédiat.
_EXECUTABLE_CACHE: dict = {}
ENGINE_CACHE_TTL_S = 60.0


def invalidate_engine_cache() -> None:
    """À appeler après une installation de librairie : le prochain `known_engines()`
    re-mesure l'importabilité de chaque backend."""
    _EXECUTABLE_CACHE.clear()


def _executable(cls) -> bool:
    import time
    now = time.monotonic()
    hit = _EXECUTABLE_CACHE.get(cls)
    if hit is not None and now - hit[0] < ENGINE_CACHE_TTL_S:
        return hit[1]
    ok = not getattr(cls, 'missing_packages', lambda: [])()
    _EXECUTABLE_CACHE[cls] = (now, ok)
    return ok


def known_engines() -> set:
    """Moteurs réellement EXÉCUTABLES — inventaires relus à CHAQUE appel (ré-autorisation
    auto) ; le verdict d'importabilité par classe est mémoïsé une minute (cf. ci-dessus).

    ⚠ La politique « exécutable » (backend enregistré ET runtime importable) vit ICI
    depuis le 2026-09-03, plus chez chaque producteur : elle y était recopiée, donc
    vouée à diverger — et un producteur qui filtrait lui-même privait le commun de la
    carte des classes (cf. `engine_backends`). Un inventaire sans classe reste réputé
    exécutable : on ne condamne pas ce qu'on ne sait pas mesurer (même permissivité
    que `backend_missing`).
    """
    moteurs = set()
    for fn in _ENGINE_INVENTORIES:
        try:
            res = fn()
            if isinstance(res, dict):
                moteurs.update(k for k, c in res.items() if _executable(c))
            else:
                moteurs.update(res)
        except Exception as e:
            logger.debug("[engines] inventaire %r illisible : %s", fn, e)
    return moteurs


# ── RÉSOLUTION PAR DÉCLARATION (2026-09-06, étape 1 du plan Fabien) ──────────────────────
#
# Une app ne doit plus jamais importer un backend PAR SON CHEMIN. Elle demande « le backend
# qui pilote ce moteur », ou mieux « le backend qui sait exécuter ce modèle », et le registre
# résout. C'est ce qui rend l'EMPLACEMENT PHYSIQUE indifférent — préalable au déplacement des
# backends vers le substrat transversal : tant qu'on importe par chemin, tout déplacement
# casse des imports ; une fois qu'on résout par déclaration, le déplacement ne casse rien.
#
# Deux dépendances inter-apps existent déjà et sont exactement la pathologie visée :
#   • `common/utils/whisper_utils` importe `transcriber.backends.manager` ;
#   • `wama_lab/cam_analyzer` importe `anonymizer.backends.sam3_processor` — une app du monde
#     LAB qui dépend d'une app du monde MÉDIAS.
#
# ⚠ La résolution IMPORTE réellement le module du backend : c'est une exécution, pas une
# lecture. Elle est donc CIBLÉE (un module) et TARDIVE (à la demande) — jamais un balayage.
# Le registre, lui, reste statique. *Lire une déclaration ne doit rien exécuter ; exécuter
# est une décision de l'appelant.*


def backend_for_engine(engine: str, model_id: str = ''):
    """Classe de backend qui pilote `engine` (et sert `model_id` si le moteur est partagé).

    None a plusieurs causes, qui ne se valent pas — `known_engines()` et `engine_backends()`
    les distinguent : moteur inconnu ; moteur HORS PROCESSUS déclaré par un inventaire à la
    main (`audio-cpp`, `ollama` — ils ne sont pas du code Python qu'on charge) ; plusieurs
    backends candidats sans `SUPPORTED_MODELS` pour trancher ; module illisible.
    """
    from wama.common.services.backend_inventory import resolve_backend
    classe = resolve_backend(engine, model_id)
    # ⚠ GARDE : `engine_backends()` peut rendre un PORTEUR qui n'est pas un backend — le
    # porteur du démon Ollama en est un. Une première version rendait cet objet, qui n'a ni
    # `load` ni `process` : l'appelant aurait cru tenir un backend. On ne rend QUE le contrat.
    if classe is not None and isinstance(classe, type) and issubclass(classe, BaseModelBackend):
        return classe
    return None


def backend_for_model(model):
    """Classe de backend qui sait exécuter `model`, ou None.

    C'est le point d'entrée que les apps doivent employer : elles connaissent leur MODÈLE
    (catalogue), pas le module qui l'exécute. Le chemin passe par la déclaration
    `composition.runtime.engine` — la moitié modèle du lien — et rejoint la moitié backend
    (`BaseModelBackend.ENGINE`), départagée par `SUPPORTED_MODELS` quand le moteur est partagé.

    ⚠ Ne consulte PAS `backend_ref` : il porte un nom d'app, donc une appartenance, jamais
    une exécutabilité (cf. `backend_missing`, dont le court-circuit a été retiré le 05/09).
    """
    composition = getattr(model, 'composition', None) or {}
    engine = (composition.get('runtime') or {}).get('engine') or ''
    # `model_key` vaut `<source>:<model_id>` — et parfois `<source>:<famille>:<id>` (yolo).
    # C'est le DERNIER segment qui porte l'identifiant qu'un `SUPPORTED_MODELS` déclarerait.
    cle = getattr(model, 'model_key', '') or ''
    return backend_for_engine(engine, cle.rsplit(':', 1)[-1] if cle else '')


def backend_for_key(model_key: str):
    """La MÊME porte que `backend_for_model`, adressée par la CLÉ de catalogue (`<source>:<id>`).

    Pourquoi elle existe (1ᵉʳ adoptant, 2026-09-07 — composer, puis enhancer) : une app ne tient
    pas la LIGNE du catalogue, elle tient l'IDENTIFIANT du modèle choisi (sa colonne `model` /
    `ai_model`). Sans cette entrée, chaque app recopierait les mêmes trois lignes de recherche
    — c'est ce que le dépôt interdit. Elle DÉLÈGUE, elle ne décide rien : aucun second chemin.

    ⚠ Recherche ORM TARDIVE : ce module est importé par des backends SANS Django. Une base
    absente ou une ligne manquante rendent None — l'appelant dit alors POURQUOI il s'arrête,
    il ne devine pas un backend « par défaut » (c'est la règle de `resolve_backend`).
    """
    if not model_key:
        return None
    try:
        from wama.model_manager.models import AIModel
        ligne = AIModel.objects.filter(model_key=model_key).first()
    except Exception as e:                       # hors Django, base absente : pas de verdict
        logger.warning('[backends] catalogue illisible pour %s : %s', model_key, e)
        return None
    return backend_for_model(ligne) if ligne is not None else None


def backend_missing(model) -> Optional[str]:
    """Raison si `model` est POSITIVEMENT sans backend, sinon None.

    `model` : AIModel (ou tout porteur de `composition`/`backend_ref`).
    """
    # ⚠ Un court-circuit `if model.backend_ref: return None` vivait ICI jusqu'au 2026-09-05.
    # Il partait d'une idée juste — « l'app qui déclare un backend l'assume » — mais
    # `backend_ref` porte un nom d'APP, pas de backend : il attestait donc une APPARTENANCE,
    # jamais une EXÉCUTABILITÉ. Résultat : tout modèle rattaché à une app était réputé
    # exécutable, y compris quand son moteur n'existait nulle part. Il masquait exactement ce
    # que cette fonction existe pour dire.
    #
    # RETIRÉ après avoir MESURÉ son effet réel : sur 174 modèles, un SEUL change de verdict
    # (`ResembleAI/chatterbox` → moteur `chatterbox-tts`, qu'aucun backend ne pilote —
    # vérifié : `wama/synthesizer/backends/` n'en contient pas). Le nouveau verdict est JUSTE.
    # Les 159 modèles qui ne déclarent pas de moteur restent non condamnés : on ne condamne
    # pas ce qu'on ne sait pas mesurer.
    #
    # Le CHAMP `backend_ref` survit à son court-circuit : il sert encore la PROVENANCE du lien
    # au registre des backends (`lien='backend_ref'`). Son retrait complet reste un chantier —
    # il suppose que les 95 modèles qui le portent déclarent leur moteur (14 aujourd'hui).
    composition = getattr(model, 'composition', None) or {}
    engine = (composition.get('runtime') or {}).get('engine') or ''
    if not engine or engine in known_engines():
        return None
    return f"moteur « {engine} » sans backend installé"


class BackendManager:
    """Registre + cycle de vie de backends `BaseModelBackend` (singletons keep_loaded)."""

    def __init__(self, name: str = "backend", priority: Optional[List[str]] = None):
        self.name = name
        self.priority = list(priority or [])
        self._backends: Dict[str, Type[BaseModelBackend]] = {}
        self._instances: Dict[str, BaseModelBackend] = {}

    # ── Enregistrement ───────────────────────────────────────────────────────
    def register(self, key: str, backend_cls: Type[BaseModelBackend]) -> None:
        self._backends[key] = backend_cls

    def register_many(self, mapping: Dict[str, Type[BaseModelBackend]]) -> None:
        for k, c in mapping.items():
            self.register(k, c)

    def keys(self) -> List[str]:
        return list(self._backends)

    # ── Disponibilité / infos ────────────────────────────────────────────────
    def available(self) -> Dict[str, bool]:
        """{clé: is_available()} — quels backends peuvent réellement tourner."""
        out = {}
        for k, c in self._backends.items():
            try:
                out[k] = bool(c.is_available())
            except Exception as e:  # is_available d'un backend ne doit jamais casser le manager
                logger.debug("[%s] is_available(%s) a levé: %s", self.name, k, e)
                out[k] = False
        return out

    def info(self) -> Dict[str, dict]:
        out = {}
        for k, c in self._backends.items():
            try:
                avail = bool(c.is_available())
                missing = c.missing_packages()
            except Exception:
                avail, missing = False, []
            out[k] = {
                'available': avail,
                'missing_packages': missing,
                'description': getattr(c, 'description', ''),
                'recommended_vram_gb': getattr(c, 'recommended_vram_gb', None),
                'loaded': k in self._instances,
            }
        return out

    # ── Récupération / sélection ─────────────────────────────────────────────
    def _auto_select(self) -> Optional[str]:
        avail = self.available()
        for k in self.priority:               # priorité explicite d'abord
            if avail.get(k):
                return k
        for k, ok in avail.items():            # sinon premier dispo
            if ok:
                return k
        return None

    def get_backend(self, key: Optional[str] = None) -> Optional[BaseModelBackend]:
        """
        Retourne l'INSTANCE (singleton keep_loaded) du backend `key`. Si key=None, auto-sélection
        par priorité parmi les disponibles. None si rien ne correspond / n'est disponible.
        """
        if key is None:
            key = self._auto_select()
        if key is None:
            return None
        cls = self._backends.get(key)
        if cls is None:
            logger.warning("[%s] backend inconnu: %s", self.name, key)
            return None
        if key not in self._instances:
            self._instances[key] = cls()
        return self._instances[key]

    # ── Cycle de vie ─────────────────────────────────────────────────────────
    def unload(self, key: str) -> None:
        inst = self._instances.pop(key, None)
        if inst is not None:
            try:
                inst.unload()
            except Exception as e:
                logger.warning("[%s] unload(%s) a levé: %s", self.name, key, e)

    def unload_all(self) -> None:
        for k in list(self._instances):
            self.unload(k)
