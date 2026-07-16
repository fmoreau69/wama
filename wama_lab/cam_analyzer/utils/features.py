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
