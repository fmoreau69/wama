"""
Registre de COUVERTURE d'analyse — étape 1 du design « analyse incrémentale »
(CAM_ANALYZER_CHAINE_TRAITEMENT.md §Chantier complétion, 2026-07-18).

Vérité : `session.config['analyzed_ranges'] = {position: [[t0, t1], ...]}` — les plages
de TEMPS VIDÉO (secondes) réellement analysées par caméra, tenues par l'analyse
(ajout en fin de passe caméra, remise à zéro au wipe force_rerun). Vérité de
secours : la présence de `DetectionFrame` en base (`rebuild_from_db`, pour les
sessions antérieures au registre).

Consommateurs à venir : complétion batch (scope demandé − couverture = tranches à
analyser), mode « analyse au fil de la lecture » (même calcul, priorisé au playhead).
"""
import logging

from wama.common.utils.intervals import merge_intervals, subtract_intervals

logger = logging.getLogger(__name__)

# Fusionne les plages quasi-contiguës (< 2 frames à 12 fps) — évite la poussière.
_MERGE_TOL_S = 0.2


def get_coverage(session):
    """{position: [[t0, t1], ...]} — plages analysées (copie, fusionnées)."""
    raw = ((getattr(session, 'config', None) or {}).get('analyzed_ranges') or {})
    return {pos: merge_intervals(rs, tol=_MERGE_TOL_S) for pos, rs in raw.items()}


def add_coverage(session, position, ranges):
    """Ajoute des plages analysées pour une caméra (union avec l'existant) et persiste."""
    if not ranges:
        return
    cfg = session.config or {}
    ar = cfg.setdefault('analyzed_ranges', {})
    merged = merge_intervals(list(ar.get(position) or []) + [list(r) for r in ranges],
                             tol=_MERGE_TOL_S)
    ar[position] = [[round(a, 2), round(b, 2)] for a, b in merged]
    session.config = cfg
    session.save(update_fields=['config'])


def reset_coverage(session, position=None):
    """Vide le registre (une caméra, ou toutes si None) — à appeler au wipe des détections."""
    cfg = session.config or {}
    ar = cfg.get('analyzed_ranges') or {}
    if position is None:
        cfg['analyzed_ranges'] = {}
    elif position in ar:
        ar.pop(position)
    session.config = cfg
    session.save(update_fields=['config'])


def missing_ranges(session, position, scope, min_len=0.5):
    """`scope` (plages de temps vidéo requises) − couverture = tranches À analyser."""
    covered = get_coverage(session).get(position) or []
    return subtract_intervals(scope, covered, min_len=min_len)


def rebuild_from_db(session, gap_tol_s=0.5):
    """Reconstruit le registre depuis les DetectionFrame existantes (sessions
    antérieures au registre). Un trou > gap_tol_s dans les timestamps ouvre une
    nouvelle plage. Écrase le registre existant. Retourne {position: n_plages}."""
    from ..models import DetectionFrame
    cfg = session.config or {}
    ar = {}
    for cam in session.cameras.all():
        ts = list(DetectionFrame.objects.filter(camera=cam)
                  .order_by('timestamp').values_list('timestamp', flat=True))
        if not ts:
            continue
        half = gap_tol_s / 2.0
        ranges = [[ts[0] - half, ts[0] + half]]
        for t in ts[1:]:
            if t - ranges[-1][1] <= gap_tol_s:
                ranges[-1][1] = t + half
            else:
                ranges.append([t - half, t + half])
        ar[cam.position] = [[round(max(0.0, a), 2), round(b, 2)] for a, b in ranges]
    cfg['analyzed_ranges'] = ar
    session.config = cfg
    session.save(update_fields=['config'])
    return {pos: len(rs) for pos, rs in ar.items()}
