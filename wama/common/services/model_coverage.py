"""
Couverture multi-modèles : quelle COMBINAISON de modèles couvre un ensemble de classes.

POURQUOI CETTE BRIQUE EXISTE. `model_manager.select_model()` choisit **un** modèle. Certaines
tâches en exigent **plusieurs** : flouter « visage + plaque + voiture » demande un modèle
spécialisé visage, un spécialisé plaque et un COCO générique — aucun ne couvre les trois.
C'est un problème de RECOUVREMENT, que `select_model()` ne peut structurellement pas résoudre.

Cette logique existait, enfouie dans `anonymizer/utils/model_selector.py` (1 139 lignes), mêlée à
une découverte disque parallèle au catalogue. En la prenant pour un simple doublon de
`select_model()`, on l'aurait supprimée avec le reste — et perdu une capacité réelle. Elle est
ici pour être RÉUTILISÉE : cam_analyzer (plusieurs types d'objets), face_analyzer, une future
détection open-vocab en ont le même besoin.

CE QUI RESTE À L'APP, ET QUI NE DOIT PAS ENTRER ICI : la POLITIQUE. « Précision 100 → préférer
la segmentation et les gros modèles » est une décision de l'anonymizer ; elle se DÉCLARE en
paramètres (`preferer_segmentation`, `taille_preferee`), elle ne se code pas dans la brique.
Sinon on remplace une route parallèle par une brique truffée de `if app == …`.

SOURCE UNIQUE : le catalogue `AIModel` et ses `capabilities['classes']` — renseignées pour 46
des 48 modèles vision (mesuré le 2026-08-04). Aucun scan disque : c'est précisément la
découverte parallèle qu'on élimine.
"""
from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)


def normaliser_classe(nom: str) -> str:
    """
    'License_Plate' → 'license plate' · 'FACE' → 'face'.

    Les vocabulaires de classes viennent de fichiers de poids hétérogènes (YOLO, ONNX, COCO) :
    séparateurs et casse varient d'un modèle à l'autre. Comparer les libellés bruts fait rater
    des correspondances évidentes.
    """
    return re.sub(r'[_\-]+', ' ', (nom or '').strip().lower())


def _classes_du_modele(m) -> set:
    return {normaliser_classe(c) for c in ((m.capabilities or {}).get('classes') or []) if c}


# Un même objet se nomme différemment d'un jeu de poids à l'autre : 'plate' ici, 'license_plate'
# là. Normaliser les séparateurs ne suffit pas — ce sont des mots distincts. Cette table vient de
# `anonymizer/utils/model_selector.py::CLASS_ALIASES`, où elle rendait déjà ce service ; elle
# monte ici pour que TOUT appelant de la couverture en bénéficie. Écrite en forme NORMALISÉE
# (espaces, minuscules), sinon la comparaison la manque.
_ALIAS_CLASSES = (
    {'plate', 'license plate', 'licenseplate', 'number plate'},
    {'face', 'faces'},
)


def formes_equivalentes(nom: str) -> set:
    """
    Toutes les écritures normalisées équivalentes à `nom` (lui-même si aucun alias connu).

    PUBLIQUE parce que l'appariement ne s'arrête pas à la sélection : `couvrir_classes` rend les
    classes dans le vocabulaire de L'APPELANT (`plate`), alors que le modèle retenu peut les
    nommer autrement (`license_plate` chez morsetechlab). Le moteur qui exécute ensuite doit
    donc refaire la correspondance — sans elle il ne trouve aucun index de classe et **ignore
    le modèle en silence** (constaté le 2026-08-13 en testant le pipeline multi-modèles).
    """
    n = normaliser_classe(nom)
    for groupe in _ALIAS_CLASSES:
        if n in groupe:
            return set(groupe)
    return {n}


#: Nom historique conservé pour les appels internes de ce module.
_formes = formes_equivalentes


def _couvertes(m, voulues: set) -> set:
    """Sous-ensemble de `voulues` (libellés de l'APPELANT) que `m` sait détecter, alias compris."""
    dispo = _classes_du_modele(m)
    return {v for v in voulues if _formes(v) & dispo}


def classes_couvertes(m, voulues) -> set:
    """Accès PUBLIC à l'appariement d'alias : sous-ensemble de `voulues` (vocabulaire de
    l'APPELANT) que le modèle `m` (AIModel) sait détecter. Exposé le 2026-08-17 pour la meta
    UI de l'anonymizer (WamaModelCaps : griser les classes hors modèle) — l'appariement ne se
    réimplémente JAMAIS côté consommateur (leçon couvrir_classes)."""
    return _couvertes(m, set(voulues))


#: La taille se lit sur un TOKEN, jamais sur une lettre perdue dans le nom (`'n' in nom` est
#: vrai pour presque tout nom — mesuré le 2026-08-04, le critère devenait inerte et « Rapide »
#: retenait un modèle `l`). Deux conventions coexistent au catalogue, toutes deux issues des
#: tailles ultralytics :
_MOTIFS_TAILLE = (
    r'yolo\D*\d+([nsmlx])(?![a-z0-9])',   # yolo11l-seg.pt, yolov9s-face.pt, face_yolov8m-seg
    # `…-v1m.onnx` — convention des finetunes publiés hors nommage YOLO (morsetechlab).
    # Sans ce motif, les 5 modèles de plaques rendaient '' : la taille demandée était donc
    # SANS EFFET sur eux, et le départage retombait sur la VRAM — c'est-à-dire le plus gros
    # (v1x, 227 Mo) quelle que soit la précision demandée (constaté le 2026-08-12).
    r'v\d+([nsmlx])(?![a-z0-9])',
)


def _taille_du_nom(nom: str) -> str:
    """'yolo11l-seg.pt' → 'l' · 'license-plate-finetune-v1m.onnx' → 'm'. '' si indéterminable."""
    minuscule = (nom or '').lower()
    for motif in _MOTIFS_TAILLE:
        trouve = re.search(motif, minuscule)
        if trouve:
            return trouve.group(1)
    return ''


#: Stratégies de recouvrement. Ce n'est PAS un réglage cosmétique : les deux optimisent des
#: choses opposées, et le bon choix dépend du métier de l'appelant.
#:
#:   'couverture'    — le moins de modèles possible (recouvrement glouton). Chaque modèle en
#:                     moins est une passe de détection en moins : c'est le bon objectif quand
#:                     le coût domine.
#:   'specialisation'— le modèle le plus SPÉCIALISÉ par classe, quitte à en charger plusieurs.
#:                     Tant qu'aucune qualité n'est MESURÉE, le nombre de classes déclarées est
#:                     le seul proxy honnête de spécialisation : un détecteur de visages entraîné
#:                     sur des visages bat en pratique un modèle 2-en-1 (constaté par Fabien, et
#:                     mesuré le 2026-08-12 — sur une foule, le détecteur dédié trouve 307
#:                     visages là où le modèle « visages+plaques » en trouve 4).
#:                     ⚠ Proxy, pas vérité : à remplacer par la qualité mesurée dès qu'elle existe.
STRATEGIES = ('couverture', 'specialisation')


def couvrir_classes(classes, *, source: str = '', model_type: str = 'vision',
                    budget_vram_gb: float | None = None,
                    taches_admises=(),
                    preferer_segmentation: bool = False,
                    taille_preferee: str = '',
                    strategie: str = 'couverture',
                    max_modeles: int = 4) -> dict:
    """
    Ensemble MINIMAL de modèles couvrant `classes`, par recouvrement glouton.

    À chaque tour on retient le modèle qui couvre le PLUS de classes encore non couvertes ; à
    égalité, le plus qualitatif (`quality_index`, cf. `model_manager/services/model_quality.py`).
    Glouton et non optimal : le recouvrement exact est NP-difficile, et sur des catalogues de
    quelques dizaines de modèles l'écart est négligeable devant le coût d'une recherche exacte.

    `preferer_segmentation` / `taille_preferee` sont des PRÉFÉRENCES de l'appelant, appliquées
    en départage — jamais en filtre : mieux vaut couvrir une classe avec un modèle non préféré
    que de ne pas la couvrir.

    `taches_admises` est le seul FILTRE de capacité, et il se DÉCLARE (vide = aucun filtre).
    Un classifieur annonce des classes sans savoir les localiser : `yolo11l-cls` déclare `plate`
    — l'assiette d'ImageNet — et le retenir pour flouter ne produirait aucune boîte. Ce n'est
    pas une préférence qu'on départage, c'est une incapacité. L'anonymizer déclare donc
    `('detect', 'segment')` ; une app qui veut juste étiqueter une image ne déclare rien.

    Retourne `{'modeles': [...], 'classes_non_couvertes': [...], 'couverture': 0..1}`.
    `couverture` vaut 1.0 quand tout est couvert ; les classes qu'aucun modèle installé ne sait
    détecter sont NOMMÉES plutôt que silencieusement ignorées — c'est ce qui permet à l'appelant
    de proposer une installation (cf. la prospection).
    """
    from wama.model_manager.models import AIModel

    voulues = {normaliser_classe(c) for c in (classes or []) if c}
    if not voulues:
        return {'modeles': [], 'classes_non_couvertes': [], 'couverture': 0.0}

    qs = AIModel.objects.filter(is_downloaded=True, is_available=True)
    if model_type:
        qs = qs.filter(model_type=model_type)
    if source:
        qs = qs.filter(source=source)
    if taches_admises:
        admises = set(taches_admises)
        qs = [m for m in qs if (m.capabilities or {}).get('task') in admises]
    candidats = [m for m in qs if _couvertes(m, voulues)]
    if budget_vram_gb is not None:
        # Filtre par modèle, pas sur la somme : les détections tournent séquentiellement dans
        # l'anonymizer. Un appelant qui les paralléliserait devrait borner le TOTAL lui-même.
        candidats = [m for m in candidats if (m.vram_gb or 0) <= budget_vram_gb]

    if strategie not in STRATEGIES:
        raise ValueError(f"strategie inconnue : {strategie!r} (attendu : {', '.join(STRATEGIES)})")

    # Les indices de qualité ne se comparent QUE si tout le lot en a un : l'échelle d'un
    # `quality_index` (−26,7 à 58,7) n'a rien à voir avec celle d'une VRAM (0,1 à 24 Go), et
    # les mélanger ferait gagner mécaniquement le premier modèle qualifié. Même règle que
    # `model_selector._rank_key`, pour que les deux couches classent pareil.
    tous_qualifies = bool(candidats) and all(m.quality_index is not None for m in candidats)

    def _departage(m):
        """Préférences de l'appelant, puis qualité. Jamais des filtres — seulement un ordre."""
        caps = m.capabilities or {}
        return (
            preferer_segmentation and caps.get('task') == 'segment',
            bool(taille_preferee) and _taille_du_nom(m.name) == taille_preferee,
            m.quality_index if tous_qualifies else (m.vram_gb or 0),
        )

    retenus, restantes = [], set(voulues)
    while restantes and candidats and len(retenus) < max_modeles:
        def gain(m):
            couvre = _couvertes(m, restantes)
            if strategie == 'specialisation':
                # On maximise la SPÉCIALISATION, pas le recouvrement : le modèle qui déclare le
                # MOINS de classes au total (d'où le signe négatif) l'emporte, même s'il couvre
                # moins de classes demandées — c'est le prix assumé d'une meilleure détection.
                # `min(couvre, 1)` garde la garantie de progression : un modèle qui ne couvre
                # rien reste dernier et la boucle s'arrête proprement.
                return (min(len(couvre), 1), -len(_classes_du_modele(m))) + _departage(m)
            return (len(couvre),) + _departage(m)

        meilleur = max(candidats, key=gain)
        couvertes = _couvertes(meilleur, restantes)
        if not couvertes:
            break                      # plus aucun progrès possible : on s'arrête net
        retenus.append({
            'model_key': meilleur.model_key,
            'name': meilleur.name,
            'path': meilleur.local_path or '',
            'classes': sorted(couvertes),
            'quality_index': meilleur.quality_index,
            'vram_gb': meilleur.vram_gb or 0,
        })
        restantes -= couvertes
        candidats.remove(meilleur)

    couverture = round((len(voulues) - len(restantes)) / len(voulues), 3)
    if restantes:
        logger.info("[couverture] %d/%d classes couvertes ; manquantes : %s",
                    len(voulues) - len(restantes), len(voulues), sorted(restantes))
    return {
        'modeles': retenus,
        'classes_non_couvertes': sorted(restantes),
        'couverture': couverture,
    }
