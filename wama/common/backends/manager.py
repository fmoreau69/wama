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
# que le POSITIVEMENT inlançable — un moteur déclaré qu'aucun inventaire ne sert, et depuis le
# 2026-09-29 (décision Fabien) un modèle SANS moteur que NULLE app ne porte : aucune route
# d'exécution, ce n'est plus une absence d'information. Un modèle porteur d'un `backend_ref`
# d'app, un candidat, un distant n'ont toujours pas de verdict sans moteur (cf. `backend_missing`).
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
    _CONTRACT_VERDICT_CACHE.clear()


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


def backend_for_engine(engine: str, model_id: str = '', entries=None, task: str = ''):
    """Classe de backend qui pilote `engine` (et sert `model_id` si le moteur est partagé).

    None a plusieurs causes, qui ne se valent pas — `known_engines()` et `engine_backends()`
    les distinguent : moteur inconnu ; moteur HORS PROCESSUS déclaré par un inventaire à la
    main (`audio-cpp`, `ollama` — ils ne sont pas du code Python qu'on charge) ; plusieurs
    backends candidats sans `SUPPORTED_MODELS` pour trancher ; module illisible.
    """
    from wama.common.services.backend_inventory import resolve_backend
    classe = resolve_backend(engine, model_id, entries, task=task)
    # ⚠ GARDE : `engine_backends()` peut rendre un PORTEUR qui n'est pas un backend — le
    # porteur du démon Ollama en est un. Une première version rendait cet objet, qui n'a ni
    # `load` ni `process` : l'appelant aurait cru tenir un backend. On ne rend QUE le contrat.
    if classe is not None and isinstance(classe, type) and issubclass(classe, BaseModelBackend):
        return classe
    return None


def backend_for_model(model, entries=None):
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
    # La TÂCHE voyage (2026-09-29) : un moteur partagé entre tâches ne suffit pas à choisir —
    # cf. `backend_inventory.TASK_CONTRACTS`.
    task = (getattr(model, 'capabilities', None) or {}).get('task') or ''
    return backend_for_engine(engine, cle.rsplit(':', 1)[-1] if cle else '', entries, task=task)


def backend_for_key(model_key: str, entries=None):
    """La MÊME porte que `backend_for_model`, adressée par la CLÉ de catalogue (`<source>:<id>`).

    Pourquoi elle existe (1ᵉʳ adoptant, 2026-09-07 — composer, puis enhancer) : une app ne tient
    pas la LIGNE du catalogue, elle tient l'IDENTIFIANT du modèle choisi (sa colonne `model` /
    `ai_model`). Sans cette entrée, chaque app recopierait les mêmes trois lignes de recherche
    — c'est ce que le dépôt interdit. Elle DÉLÈGUE, elle ne décide rien : aucun second chemin.

    ⚠ Recherche ORM TARDIVE : ce module est importé par des backends SANS Django. Une base
    absente ou une ligne manquante rendent None — l'appelant dit alors POURQUOI il s'arrête,
    il ne devine pas un backend « par défaut » (c'est la règle de `resolve_backend`).

    `entries` (même sens sur les trois portes) : le vivier déjà lu
    (`backend_inventory.resolvable_entries()`), pour un appelant qui résout EN SÉRIE. Sans lui,
    chaque appel relit l'inventaire — 48 fois pour les 48 modèles de l'anonymizer à chaque
    extraction de manifeste (mesuré le 2026-09-14).
    """
    if not model_key:
        return None
    try:
        from wama.model_manager.models import AIModel
        ligne = AIModel.objects.filter(model_key=model_key).first()
    except Exception as e:                       # hors Django, base absente : pas de verdict
        logger.warning('[backends] catalogue illisible pour %s : %s', model_key, e)
        return None
    return backend_for_model(ligne, entries) if ligne is not None else None


def route_for_nature(package: str, nature: str, routes: dict = None):
    """La porte par NATURE d'entrée : le callable que les `ROUTES` d'une app déclarent pour
    `nature`, au contrat commun des routes (« fichier » ou « texte », marche B1).

    L'AUTRE moitié du routage, et pas un second chemin vers un backend : les trois portes
    ci-dessus vont du MODÈLE au backend (le catalogue) ; celle-ci suit la décision de routage
    de l'APP (`backends/__init__.ROUTES`, « la frontière », 8c556100) — une nature mène à une
    fonction de l'app, qui résout elle-même son modèle par les portes du catalogue.

    `package` : le paquet de l'app appelante (`__package__`) — l'import est RELATIF À LUI, ce
    qui laisse une jumelle du bac à sable résoudre SES copies de `backends/` sans citer un nom
    d'app. `routes` : la table quand l'appelant la tient déjà (corps généré, depuis le
    manifeste) ; sinon celle du paquet `backends` de l'app.

    Une nature sans route LÈVE (`ValueError`) : la tâche échoue en le disant, elle ne tombe
    jamais sur une route « par défaut ». Né le 2026-10-05 : la résolution était recopiée trois
    fois (enhancer, describer, corps émis par `tasks_gen`) et le converter, qui déclare ses
    ROUTES, les contournait par un `if/elif` écrit à la main."""
    from importlib import import_module
    if routes is None:
        routes = getattr(import_module('.backends', package), 'ROUTES', None) or {}
    path = routes.get((nature or '').strip())
    if not path:
        raise ValueError(f"Nature d'entrée non supportée : {nature!r} (aucune route déclarée)")
    module, name = path.rsplit('.', 1)
    return getattr(import_module('.' + module, package), name)


# ── Clé CATALOGUE d'un modèle résident, résolue À LA LECTURE (2026-09-14) ───────────────
#
# Le contrat de backend publie au registre VRAM `<module>.<Classe>:<pid>#@<nom local>` : le
# process qui charge ne connaît que sa classe et le nom qu'il sert — et le service TTS n'a pas
# d'ORM. La clé se reconstitue ICI, par la moitié inverse du lien que `backend_for_model` suit
# dans l'autre sens : parmi les modèles du catalogue que cette classe exécute, celui que ce nom
# désigne. Avant, la source se DÉDUISAIT du chemin du module (`base._app_of`) — juste tant que
# les backends vivaient dans les apps, faux pour les 101 modèles résolus depuis leur
# déménagement sous `common/backends/` (8c556100 ; mesuré le 2026-09-14 : 0 clé juste).
CATALOG_INDEX_TTL_S = 60.0
_CATALOG_INDEX: dict = {}


def invalidate_catalog_index() -> None:
    """Le prochain `catalog_keys_for_owner` relit le catalogue (après une synchro, un test)."""
    _CATALOG_INDEX.clear()


def _catalog_index() -> dict:
    """{`module.Classe`: [(clé, hf_id)]} — mémoïsé une minute : le catalogue ne bouge qu'à la
    synchro, et les lecteurs de résidence (sélecteur, model_manager) l'interrogent souvent."""
    import time
    now = time.monotonic()
    hit = _CATALOG_INDEX.get('index')
    if hit is not None and now - hit[0] < CATALOG_INDEX_TTL_S:
        return hit[1]
    from wama.model_manager.models import AIModel
    from wama.common.services.backend_inventory import resolvable_entries
    entries = resolvable_entries()
    index: dict = {}
    for ligne in AIModel.objects.only('model_key', 'hf_id', 'composition'):
        classe = backend_for_model(ligne, entries)
        if classe is not None:
            index.setdefault(f"{classe.__module__}.{classe.__name__}", []).append(
                (ligne.model_key, ligne.hf_id or ''))
    _CATALOG_INDEX['index'] = (now, index)
    return index


def prime_catalog_index() -> int:
    """Remplit l'index du catalogue (et, par lui, importe les modules de backends) — rend le
    nombre de classes indexées. Porte PUBLIQUE du préchauffage de l'assistant
    (`assistant_engine.warm_up`) : le premier tirage « auto » d'un processus payait ~5 s ici."""
    return len(_catalog_index())


def match_local_name(rows, name: str) -> list:
    """Clés, parmi les lignes `(clé, hf_id)` d'une classe, que désigne le nom local `name`.

    La première règle qui trouve l'emporte :
      1. égalité avec la clé, l'identifiant (après la source), le dernier segment ou le `hf_id`
         (`yolov8n.pt` → `anonymizer:yolo:yolov8n.pt` ; `Qwen/Qwen3-ASR-1.7B`) ;
      2. dernier composant du `hf_id` égal au nom, ou finissant par `-<nom>` (Whisper :
         `large-v3` → `openai/whisper-large-v3`, `base` → `openai/whisper-base`) ;
      3. la classe n'exécute qu'UN modèle du catalogue → c'est lui (Kokoro-onnx, Audio8…).
    Sinon [] : entre plusieurs modèles, on ne devine pas. Un nom qui en désigne plusieurs les
    rend tous (mêmes poids servis sous deux clés).
    """
    name = (name or '').strip()
    if not name or not rows:
        return []
    exact = [cle for cle, hf in rows
             if name in (cle, cle.split(':', 1)[-1], cle.rsplit(':', 1)[-1], hf)]
    if exact:
        return exact
    base = name.rstrip('/').rsplit('/', 1)[-1]
    par_hf = [cle for cle, hf in rows if hf and (
        hf.rsplit('/', 1)[-1] == base or hf.rsplit('/', 1)[-1].endswith(f'-{base}'))]
    if par_hf:
        return par_hf
    return [rows[0][0]] if len(rows) == 1 else []


def catalog_keys_for_owner(owner: str) -> list:
    """Clés catalogue désignées par une clé d'owner du registre VRAM — [] si rien ne se résout.

    Un suffixe qui n'est pas un nom local (`ollama-host#ollama:gemma3:4b`) EST déjà une clé.
    """
    from wama.common.services.resource_governor import OWNER_LOCAL_NAME_PREFIX, OWNER_MODEL_SEP
    if not owner or OWNER_MODEL_SEP not in owner:
        return []
    detenteur, suffixe = owner.split(OWNER_MODEL_SEP, 1)
    suffixe = suffixe.strip()
    if not suffixe:
        return []
    if not suffixe.startswith(OWNER_LOCAL_NAME_PREFIX):
        return [suffixe]
    classe = detenteur.rsplit(':', 1)[0]            # `<module>.<Classe>:<pid>`
    try:
        rows = _catalog_index().get(classe, [])
    except Exception as e:                          # hors Django, base absente : pas de verdict
        logger.debug('[backends] catalogue illisible pour %s : %s', owner, e)
        return []
    return match_local_name(rows, suffixe[len(OWNER_LOCAL_NAME_PREFIX):])


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
    if engine:
        if engine not in known_engines():
            return f"moteur « {engine} » sans backend installé"
        return _unserved_by_task_contract(model, engine)
    # ⚠⚠ AUCUN MOTEUR DÉCLARÉ — la permissivité est LEVÉE pour le seul cas sans route (décision
    # de Fabien, 2026-09-29). Elle se justifiait le 05/09 : 159 modèles sur 174 ne déclaraient
    # pas de moteur, les condamner aurait grisé des listes entières. Remesuré le 29/09 : 2 lignes
    # sur tout le catalogue hors candidats (109 installés, 11 non téléchargés et 24 distants en
    # déclarent tous un) — et ce sont exactement les deux inexécutables, deux lignes du balayage
    # générique qu'aucune app ne porte (Supra2-IMG-ONNX, Minimax-h3). La première était PROPOSÉE
    # au select texte→image par la route F4b et pouvait gagner le tirage, puis échouer au
    # lancement. *Une permissivité justifiée par un compte se remesure quand le compte change.*
    #
    # Le critère est la SOURCE, pas `backend_ref` (qui n'atteste qu'une appartenance — cf. plus
    # haut) : seule une ligne du BALAYAGE GÉNÉRIQUE (`GENERIC_SCAN_SOURCES`) n'a, sans moteur,
    # aucune route. Une ligne d'app est routée par le gestionnaire de son app ; une ligne Ollama
    # a son moteur par nature ; un candidat n'est pas proposé à l'exécution ; un distant est
    # exécuté par son fournisseur.
    if (getattr(model, 'source', '') not in GENERIC_SCAN_SOURCES
            or getattr(model, 'is_proposed', False)
            or getattr(model, 'execution', '') == 'cloud'):
        return None
    return "aucun moteur déclaré et aucune app ne le porte — aucune route d'exécution"


def _unserved_by_task_contract(model, engine: str) -> Optional[str]:
    """Raison si le moteur existe mais qu'AUCUN backend du contrat LIANT de la tâche ne sert CE
    modèle, sinon None (2026-09-30).

    « Le moteur est exécutable » ne disait pas « ce modèle l'est » : FrWhisper, LinTO et Kyutai
    STT, installés « poids seulement », déclarent `transformers` — moteur bien servi, par
    Qwen3-ASR. Le select les proposait donc comme lançables, et le lancement échouait ou les
    confiait au mauvais backend. Limité aux contrats LIANTS (`TASK_CONTRACTS`) et aux moteurs
    que le VIVIER de backends connaît : c'est là, et seulement là, que la résolution sait dire
    non ; ailleurs le verdict reste permissif, comme avant."""
    import time
    from wama.common.services.backend_inventory import TASK_CONTRACTS, resolve_entry
    task = (getattr(model, 'capabilities', None) or {}).get('task') or ''
    contract = TASK_CONTRACTS.get(task)
    if not contract or not contract[2]:
        return None
    key = getattr(model, 'model_key', '') or ''
    model_id = key.rsplit(':', 1)[-1] if key else ''
    memo_key, now = (engine, model_id, task), time.monotonic()
    hit = _CONTRACT_VERDICT_CACHE.get(memo_key)
    if hit is not None and now - hit[0] < ENGINE_CACHE_TTL_S:
        return hit[1]
    entries = _CONTRACT_VERDICT_CACHE.get('entries')
    if entries is None or now - entries[0] >= ENGINE_CACHE_TTL_S:
        from wama.common.services.backend_inventory import resolvable_entries
        entries = _CONTRACT_VERDICT_CACHE['entries'] = (now, resolvable_entries())
    # Un moteur servi HORS du vivier (inventaire de noms : `audio-cpp`, `ollama`, le service TTS)
    # n'a pas de backend à résoudre : la résolution ne sait rien en dire, on ne condamne pas.
    if not any(e.engine == engine for e in entries[1]):
        verdict = None
    elif resolve_entry(engine, model_id, entries[1], task=task) is not None:
        verdict = None
    else:
        verdict = f"moteur « {engine} » : aucun backend de {task} ne sert ce modèle"
    _CONTRACT_VERDICT_CACHE[memo_key] = (now, verdict)
    return verdict


#: Verdicts par contrat et vivier qui les fonde, mémorisés une minute comme `_EXECUTABLE_CACHE` :
#: une liste d'options demande le verdict de CHACUN de ses modèles, et relire le vivier coûtait
#: ~0,4 s par modèle sur `/mnt/d` (mesuré le 2026-09-30).
_CONTRACT_VERDICT_CACHE: dict = {}


#: Sources des lignes créées par le BALAYAGE GÉNÉRIQUE d'un snapshot (`model_registry`,
#: « catalogué ≠ utilisable ») : aucune app ne les déclare, seul un moteur DÉCLARÉ les rend
#: exécutables. Les autres sources sont des apps (leur gestionnaire route) ou des plateformes
#: qui exécutent elles-mêmes (Ollama, fournisseurs distants).
GENERIC_SCAN_SOURCES = ('huggingface', 'custom')


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
