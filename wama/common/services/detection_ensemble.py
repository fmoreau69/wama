"""Détection par un ENSEMBLE de modèles — l'union de leurs documents `detections` (2026-10-10).

POURQUOI. Anonymiser, c'est ne rien rater : une plaque oubliée suffit à casser l'anonymisation.
Le banc des plaques en caméra embarquée l'a mesuré — aucun détecteur seul ne dépasse 60 % de
rappel, mais leurs erreurs diffèrent (EgoBlur 59,5 %, RT-DETR 40 %, leur union 64,6 %). Jusqu'ici
l'union n'était possible qu'entre modèles ultralytics, dans `Anonymize` ; un détecteur d'une autre
famille (`transformers`, TorchScript) ne pouvait pas y entrer.

COMMENT. Les modèles ultralytics passent ENSEMBLE par `Anonymize` (une passe chacun, suivi et
pistes compris — rien ne change pour eux) ; chaque autre modèle passe par SON backend, résolu
par la porte commune (`backend_instance_for_key` : moteur déclaré au catalogue ↔ `ENGINE`), et
rend son propre document ; `detections.merge` les réunit. L'interpolation des trous, faite au
floutage, relie les détections par leur position : un détecteur sans suivi en profite aussi.

Consommateurs : l'anonymizer (process « Détection ») et le banc de rappel
(`model_manager/services/bench.py`), qui mesure chaque modèle par le MÊME chemin que celui qui
servira — un banc qui appellerait YOLO à sa façon mesurerait autre chose que ce qui floute.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

#: Moteur des modèles que `Anonymize` charge lui-même (`YOLO(chemin)`).
ULTRALYTICS = 'ultralytics'


def engine_of(model_key: str) -> str:
    """Le moteur DÉCLARÉ au catalogue — la lecture commune (`backends.manager.engine_of`)."""
    from wama.common.backends.manager import engine_of as declared_engine
    return declared_engine(model_key)


def _scaled(progress, rank: int, count: int):
    """La progression d'UNE passe ramenée à sa part de l'ensemble (sinon la barre repartirait
    de zéro à chaque détecteur)."""
    if progress is None:
        return None
    return lambda done, total: progress(rank * max(total, 1) + done, count * max(total, 1))


class DetectorSet:
    """Les détecteurs d'un ensemble, CHARGÉS UNE FOIS puis appliqués média par média
    (2026-10-10) : un banc de 3 226 images ne recharge pas ses modèles 3 226 fois.

    `models` : descripteurs `{'model_key', 'path', 'name', 'classes', 'engine'?}` (forme de la
    couverture de classes) ; `engine` absent se lit au catalogue, et un modèle sans moteur
    déclaré est réputé ultralytics (les poids YOLO historiques)."""

    def __init__(self, models, *, user=None, source_dir=None, destination_dir=None):
        from wama.common.backends.anonymize import Anonymize
        from wama.common.backends.manager import backend_instance_for_key
        models = [dict(m) for m in models or []]
        for m in models:
            m.setdefault('engine', engine_of(m.get('model_key')) or ULTRALYTICS)
        yolo = [m for m in models if m['engine'] == ULTRALYTICS]
        self.engine = None
        if yolo:
            self.engine = Anonymize(source_dir=source_dir, destination_dir=destination_dir)
            with_path = [m for m in yolo if m.get('path')]
            # Aucun chemin désigné : le modèle par défaut d'`Anonymize`, comme avant l'ensemble.
            self.engine.load_model(**({'models': with_path} if with_path else {}))
        self.others = [(m, backend_instance_for_key(m['model_key'], user))
                       for m in models if m['engine'] != ULTRALYTICS]

    @property
    def passes(self) -> int:
        return (1 if self.engine else 0) + len(self.others)

    def detect(self, **kwargs) -> dict:
        """Le document `detections` de l'ensemble sur `kwargs['media_path']`. `kwargs` : ceux du
        process de détection (`classes2blur`, `detection_threshold`, `on_frame`, `progress`…),
        transmis à chaque détecteur — avec, pour un détecteur hors ultralytics, SES classes à
        la place de la demande."""
        from wama.common.utils import detections as dets
        progress = kwargs.pop('progress', None)
        docs, rank = [], 0
        if self.engine:
            docs.append(self.engine.detect(**kwargs, progress=_scaled(progress, rank, self.passes)))
            rank += 1
        for m, detector in self.others:
            wanted = m.get('classes') or kwargs.get('classes2blur')
            logger.debug("[ensemble] %s (%s) : %s", m['model_key'], m['engine'], wanted)
            # Un détecteur qui lit une description reçoit la part que le routeur lui CONFIE
            # (`prompt` du descripteur, `route_concepts`) ; sans elle, la description de la card.
            own = {'prompt': m['prompt']} if m.get('prompt') is not None else {}
            docs.append(detector.detect(**{**kwargs, 'classes2blur': wanted, **own},
                                        progress=_scaled(progress, rank, self.passes)))
            rank += 1
        doc = dets.merge(docs)
        logger.debug("[ensemble] %d détecteur(s), %d détection(s)", self.passes, dets.count(doc))
        return doc


def route_concepts(concepts, *, cover, open_model_key: str = '') -> dict:
    """Le ROUTEUR de concepts (2026-11-24, `ROADMAP §17quater` A.2, décision de Fabien : « ce sont
    les mécanismes qui choisissent les modèles selon la description et le curseur ») : chaque
    concept d'une description va au détecteur DÉDIÉ qui le couvre — la couverture de l'appelant,
    rappel mesuré et curseur compris —, et ce qu'aucun ne couvre au modèle qui LIT une description
    (`open_model_key` : SAM3, LocateAnything), qui ne reçoit que cette part (`prompt`). Tous passent
    ensuite par le MÊME ensemble (`DetectorSet`) : un document, une sélection.

    `cover(concepts)` est la couverture de l'APP (ses arbitrages déclarés : tâches admises,
    spécialisation, ensemble par classe) ; elle rend `{'models': [descripteurs avec leurs
    'classes'], 'unsupported_classes': [...]}`, la forme de `model_coverage.couvrir_classes` telle
    que l'anonymizer la sert (`needs_parallel_detection`).

    Rend `{'models': [descripteurs], 'plan': [{'concept', 'by': [clés]}], 'unrouted': [...]}` —
    le plan dit, concept par concept, QUI le cherche (ce que l'interface montre de « ce que le
    système a compris ») ; `unrouted` : ce que personne ne cherchera (aucun modèle à description
    disponible), à DIRE.

    Un concept peut porter des ATTRIBUTS (2026-11-25, `ROADMAP §17quater` B : « red car »,
    `detection_attributes.read_concept`) : la couverture juge le concept NU (`car`, que YOLO
    connaît) ; un détecteur dédié cherche la classe, et le pas du plan garde ses attributs
    (`attrs`) — la qualification les mesure, la sélection les suit (`detections.within_request`).
    Le modèle qui lit une description reçoit la phrase ENTIÈRE et l'entend lui-même : son pas
    n'a pas d'`attrs`, il n'y a rien à mesurer après lui."""
    from wama.common.services.model_coverage import formes_equivalentes
    from wama.common.utils.detection_attributes import read_concept
    phrases, read, wanted = [], {}, []
    for phrase in concepts or ():
        if phrase and phrase not in phrases:
            phrases.append(phrase)
            read[phrase] = read_concept(phrase)
            if read[phrase][0] not in wanted:
                wanted.append(read[phrase][0])
    if not wanted:
        return {'models': [], 'plan': [], 'unrouted': []}
    covered = cover(wanted) or {}
    models = [dict(m) for m in covered.get('models') or []]
    # Couvert = un modèle RETENU le déclare (alias compris) — lu sur les modèles eux-mêmes, pas sur
    # une liste rendue à côté : un concept que rien ne déclare n'est jamais tenu pour cherché.
    claimed = set()
    for m in models:
        for name in m.get('classes') or []:
            claimed |= formes_equivalentes(name)
    left = [c for c in wanted if not (formes_equivalentes(c) & claimed)]
    # Le modèle à description reçoit les PHRASES de ce qu'il cherche, attributs compris.
    open_part = [p for p in phrases if read[p][0] in left]
    if open_part and open_model_key:
        models.append({'model_key': open_model_key, 'path': None, 'name': open_model_key,
                       'classes': None, 'prompt': ', '.join(open_part)})
    plan = []
    for phrase in phrases:
        concept, attrs = read[phrase]
        if concept in left:
            plan.append({'concept': phrase, 'by': [open_model_key] if open_model_key else []})
            continue
        forms = formes_equivalentes(concept)
        by = [m.get('model_key') or m.get('name') for m in models
              if any(formes_equivalentes(c) & forms for c in m.get('classes') or [])]
        plan.append({'concept': concept, 'by': by, **({'attrs': attrs} if attrs else {})})
    return {'models': models, 'plan': plan,
            'unrouted': [] if open_model_key else open_part}


def detect_with_models(models, *, user=None, source_dir=None, destination_dir=None,
                       **kwargs) -> dict:
    """Le document `detections` de l'ENSEMBLE `models` sur UN média — `DetectorSet` à usage
    unique (le process « Détection » d'une card)."""
    return DetectorSet(models, user=user, source_dir=source_dir,
                       destination_dir=destination_dir).detect(**kwargs)
