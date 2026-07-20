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
]


def enabled(session, key):
    return _is_enabled(FEATURES, getattr(session, 'config', None), key)


def effective(session):
    return resolve(FEATURES, getattr(session, 'config', None))


def catalog(session):
    return _describe(FEATURES, getattr(session, 'config', None))


def clean_overrides(raw):
    return sanitize_overrides(FEATURES, raw)
