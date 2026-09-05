"""
Registre des bascules cam_analyzer — comparer AVEC/SANS chaque amélioration.

Mécanisme générique : `wama/common/utils/feature_flags.py`. Surcharges stockées dans
`AnalysisSession.config['features']` (endpoint `set_features`, panneau ⚑ Modes de la
vue de dessus). Un flag absent de la config retombe sur son défaut.

Règle : toute amélioration COMPARABLE du positionnement/cap/distances passe par une
bascule déclarée ici (jamais de if ad hoc dispersé) — voir CAM_ANALYZER_CHANGELOG.md.
"""
from wama.common.utils.feature_flags import (Feature, resolve, is_enabled as _is_enabled,
                                             describe as _describe, sanitize_overrides)

FEATURES = [
    Feature('fov_dist_correction', 'Correction FOV distances',
            "Corrige les distances annotées avec un ancien FOV V supposé "
            "(caméras latérales : ×3,6 trop courtes). OFF = distances brutes stockées.",
            default=True, scope='live'),
    Feature('mount_lever_arm', 'Bras de levier caméras',
            "Positions de montage réelles des caméras (antenne GPS à l'arrière, caméra "
            "avant +4,5 m). OFF = toutes les caméras supposées à l'antenne.",
            default=True, scope='live'),
    Feature('heading_ratio', 'Cap par ratio de bbox',
            "Cap des lents/stationnés estimé par le ratio largeur/hauteur de bbox, fondu "
            "avec la trajectoire selon la vitesse. OFF = trajectoire seule (cap figé à "
            "l'arrêt).",
            default=True, scope='live'),
    Feature('antenna_lever', "Levier d'antenne GPS",
            "Le point GPS est l'ANTENNE (coin arrière droit sur le rig ENA), pas le centre "
            "du véhicule : tout le repère est ramené au centre arrière via le levier déclaré "
            "(config gps_antenna). Corrige un biais systématique ~1 m vers la droite.",
            default=True, scope='compute'),
    Feature('artifact_filter', 'Filtre reflets/artefacts',
            "Masque les détections collées à l'image (reflets de vitrage : bbox immobile "
            "pendant que la navette avance). Le marquage/exclusion du tracking s'applique "
            "au prochain calcul des indicateurs ; le masquage à l'affichage est immédiat.",
            default=True, scope='live'),
    Feature('anchor_heading', 'Cap serveur des stationnés',
            "Cap des véhicules garés = consensus axial du ratio de bbox sur TOUTE la vie "
            "du track (calculé par le tracking 360°), au lieu de l'estimation frame par "
            "frame au rendu.",
            default=True, scope='live'),
    Feature('auto_ground_calib', 'Calibration sol auto (pitch)',
            "Position des objets par PROJECTION SOL (angle caméra estimé automatiquement "
            "depuis le mouvement + véhicules stationnés) au lieu du pinhole (hauteur de "
            "bbox). Étape 2a : corrige l'angle (gain ×5 mesuré) ; l'échelle absolue viendra "
            "des marquages ortho. Recalcule la calib au tracking si absente.",
            default=False, scope='compute'),
    Feature('ortho_correction', 'Recalage GPS par marquages ortho',
            "Applique à la trajectoire l'offset mesuré à l'étape 2b (passages piétons de "
            "l'orthophoto IGN vs caméra) — l'ÉCHELLE/POSITION absolue que 2a ne peut pas "
            "donner. La médiane globale est tenue pour un biais de PROJECTION caméra et "
            "n'est PAS appliquée ; seul l'écart LOCAL par intersection corrige le GPS, "
            "interpolé entre intersections et atténué là où le ciel est dégagé (hauteurs "
            "BD TOPO). OFF = trajectoire brute, l'offset restant mesuré et rapporté.",
            default=False, scope='compute'),
    Feature('shuttle_filter', 'Filtre de trajectoire navette (Kalman+RTS)',
            "Position et cap de la NAVETTE lissés par Kalman vitesse-constante + lisseur RTS "
            "(sans retard de phase) ; cap dérivé de la vitesse lissée, tenu à l'arrêt. Appliqué "
            "au point d'ingestion UNIQUE de la trace, côté serveur ET affichage : tout le "
            "positionnement (tracking 360°, ancres, TTC/PET, calibration sol) en hérite. OFF = "
            "GPS brut, cap = bearing entre fixes (±10-25° à basse vitesse — la source d'erreur "
            "angulaire dominante, §[2]). Premier levier qui touche la pose navette (inventaire "
            "2026-09-05 : aucun avant lui). Rapport A/B chiffré en console au recalcul.",
            default=False, scope='compute'),
    Feature('world_markings', 'Marquages SAM3 en monde',
            "Les stop_line/passages piétons segmentés par SAM3 sont projetés au sol et "
            "agrégés multi-passages : bornes réelles d'intersection sur la mini-map, et "
            "axe de la branche croisante même sans trafic observé.",
            default=True, scope='compute'),
    Feature('sam3_interp', 'Interpolation des marquages SAM3',
            "Les marquages (passages piétons…) ne sont segmentés qu'aux keyframes "
            "(sam3_fps du profil) : l'affichage interpole entre deux keyframes "
            "(translation+échelle) pour un rendu continu, avec fondu aux extrémités.",
            default=True, scope='live'),
    Feature('learned_branches', 'Branches apprises du trafic',
            "Les voies croisantes aux intersections sont apprises des trajectoires monde "
            "des véhicules suivis (côté, azimut, étendue et largeur observés) au lieu "
            "d'une bande perpendiculaire symétrique aveugle.",
            default=True, scope='compute'),
    Feature('heading_cluster', 'Prior de cluster (cap des garés)',
            "Les garés voisins (< 15 m) partagent souvent leur axe (rangée, épi) : mélange "
            "axial pondéré du cap individuel avec celui des voisins.",
            default=True, scope='compute'),
    Feature('track_speed_unified', 'Vitesse/distance unifiées par track',
            "Une seule vitesse/distance monde par véhicule (tracker 360°) servie à toutes "
            "les vues, au lieu de valeurs indépendantes par caméra. (Pas encore implémenté "
            "— déclaré pour le chantier d'unification.)",
            default=False, scope='compute'),
    Feature('depth_estimation', 'Profondeur monoculaire (1ère passe)',
            "Profondeur métrique par image (Apple Depth Pro, Apache-2.0). Chaîne en 3 ÉTAGES "
            "DÉCOUPLÉS (« analyse d'abord, calculs ensuite ») : ÉTAGE 1 ANALYSE = la passe `depth` du "
            "volet (session-wide, 4 caméras) infère et STOCKE la donnée brute (cartes → DepthFrame, "
            "profondeur de contact `depth_distance_m`) — indépendante de ce flag ; ÉTAGE 2 CALCULS "
            "(CPU, re-jouable) relit la db → plan de sol (RANSAC sur zone roulable) et cross-check "
            "distance. CE FLAG = ÉTAGE 3 : quand ON, la projection CONSOMME le plan profondeur au "
            "lieu de la recherche homographique (tranché sur `placement_spread`) ; l'overlay de "
            "profondeur viendra plus tard (la carte est déjà stockée pour l'alimenter). NON fumé au "
            "GPU (interdit sous WSL2 ; test côté runtime) ; signe du pitch validé (CPU). 1ère passe : "
            "si le gain est insuffisant, on itère. Voir CAM_ANALYZER_CHAINE_TRAITEMENT.md §[E].",
            default=False, scope='compute'),
]


def enabled(session, key):
    return _is_enabled(FEATURES, getattr(session, 'config', None), key)


def effective(session):
    return resolve(FEATURES, getattr(session, 'config', None))


def catalog(session):
    return _describe(FEATURES, getattr(session, 'config', None))


def clean_overrides(raw):
    return sanitize_overrides(FEATURES, raw)
