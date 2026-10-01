"""Correction d'une trajectoire géoréférencée par offsets ANCRÉS.

Générique : des offsets mesurés en quelques points de repère (ancres) sont décomposés,
interpolés le long du temps et appliqués à une trace lat/lon. Aucune dépendance à une app.

Premier consommateur : cam_analyzer, étape 2b — l'offset caméra→ortho mesuré aux
intersections (`ortho_markings.py`) devient une correction de trajectoire, derrière une
bascule ⚑. Reclassé de `cam_analyzer/utils/ortho_apply.py` vers `common/` le 2026-07-29.

Décomposition (décision Fabien 2026-07-28)
-----------------------------------------
L'offset mesuré mêle deux biais de natures différentes, que leur signature spatiale sépare :

* la **médiane globale** = biais de PROJECTION CAMÉRA — systématique, constant sur la session
  (erreur d'étalonnage résiduelle de l'étape 2a) ;
* l'**écart d'une intersection à cette médiane** = biais GPS LOCAL — il varie avec
  l'environnement (canyon urbain, façades d'un seul côté), donc il ne peut pas être caméra.

Seule la part locale corrige la trajectoire GPS. La part globale relève de la projection et
n'est pas appliquée ici (elle serait à reporter sur l'étalonnage caméra).

Pondération par le masquage satellite
-------------------------------------
Un écart local mesuré là où le ciel est DÉGAGÉ est plus probablement du bruit d'appariement
qu'un vrai biais GPS. On rétracte donc la correction vers zéro proportionnellement à
l'ouverture du ciel (`ign_vector.sky_mask`) : pleine application en canyon profond, correction
atténuée en zone dégagée. C'est ce qui évite d'injecter du bruit en rase campagne.

Signe (dérivation — une inversion ici serait silencieuse)
--------------------------------------------------------
Si la position véhicule supposée vaut `vraie + ε`, toute détection projetée depuis elle atterrit
en `vrai_passage + ε`. L'offset mesuré vaut `de = ortho(vrai) − caméra(projeté) = −ε`.
Donc `ε = −offset`, et la position corrigée est `supposée − ε = supposée + offset`.
**On AJOUTE l'offset aux coordonnées GPS.**
"""
import logging
import math

logger = logging.getLogger(__name__)

M_LAT = 111_320.0

# Ouverture de ciel (élévation moyenne bouchée, degrés) au-delà de laquelle on applique la
# correction locale à 100 %. Valeur PROVISOIRE : Lyon centre mesuré à 9,5° (2026-07-28),
# rase campagne à 0°. À réétalonner sur données réelles ENA_CASA.
FULL_TRUST_MASK_DEG = 12.0


def decompose(rec):
    """Sépare biais caméra (global) et biais GPS local (écart par intersection).

    `rec` = sortie de `match_recalage` : {'per_window': {wi: {de_m, dn_m, n}}, 'global': {...}}.
    Retourne {'camera': {'de_m', 'dn_m'}, 'gps_local': {wi: {'de_m', 'dn_m', 'n'}}}.
    """
    g = (rec or {}).get('global') or {}
    gde, gdn = float(g.get('de_m') or 0.0), float(g.get('dn_m') or 0.0)
    local = {}
    for wi, w in ((rec or {}).get('per_window') or {}).items():
        local[wi] = {
            'de_m': round(float(w.get('de_m') or 0.0) - gde, 3),
            'dn_m': round(float(w.get('dn_m') or 0.0) - gdn, 3),
            'n': int(w.get('n') or 0),
        }
    return {'camera': {'de_m': round(gde, 3), 'dn_m': round(gdn, 3)}, 'gps_local': local}


#: Portée temporelle d'une ancre PAR PASSAGE (s) : la correction s'éteint linéairement au-delà.
#: L'erreur GPS varie d'un passage à l'autre (mesuré ENA_CASA : ≈ 1 m sur trois passages, 5 à 7 m sur
#: un quatrième) — tenir une ancre jusqu'à la suivante, plusieurs minutes plus loin, propagerait une
#: erreur locale sur des kilomètres. Valeur PROVISOIRE (≈ une traversée d'intersection et ses abords).
PASS_REACH_S = 60.0


def decompose_passes(passes):
    """Sépare biais caméra et erreur GPS à partir d'écarts LE LONG DE LA MARCHE mesurés passage par
    passage (même décision que `decompose`, du 2026-07-28 : séparer les deux biais par leur
    SIGNATURE — ici l'orientation plutôt que le lieu).

    Un biais de projection caméra est constant dans le repère du VÉHICULE (il suit le cap) ; une
    erreur GPS est GÉOGRAPHIQUE et propre à chaque passage. Le biais caméra est donc la médiane des
    écarts le long de la marche ; le reste de chaque passage, rapporté à son cap, est l'erreur GPS.
    Séparable seulement si la navette passe dans des sens OPPOSÉS (deux caps à plus de 90°) — sinon
    les deux biais se projettent sur le même axe : rien n'est attribué au GPS.

    `passes` : [{'key', 'ts', 'heading_deg', 'along_m', 'n'}]. Retourne
    {'camera': {'along_m', 'separable', 'n_passes'}, 'gps_local': {key: {'de_m', 'dn_m', 'n', 'ts',
    'along_m'}}} — `de_m/dn_m` s'AJOUTENT à la trace (dérivation du signe : en-tête du module).
    """
    ps = [p for p in (passes or []) if p.get('along_m') is not None and p.get('heading_deg') is not None]
    if not ps:
        return {'camera': {'along_m': 0.0, 'separable': False, 'n_passes': 0}, 'gps_local': {}}
    vals = sorted(float(p['along_m']) for p in ps)
    mid = len(vals) // 2
    bias = vals[mid] if len(vals) % 2 else (vals[mid - 1] + vals[mid]) / 2.0
    hs = [math.radians(float(p['heading_deg'])) for p in ps]
    separable = any(math.cos(a - b) < 0 for i, a in enumerate(hs) for b in hs[i + 1:])
    local = {}
    if separable:
        for p, h in zip(ps, hs):
            r = float(p['along_m']) - bias
            local[str(p['key'])] = {'de_m': round(r * math.sin(h), 3), 'dn_m': round(r * math.cos(h), 3),
                                    'n': int(p.get('n') or 0), 'ts': float(p['ts']),
                                    'along_m': round(r, 3)}
    return {'camera': {'along_m': round(bias, 3), 'separable': separable, 'n_passes': len(ps)},
            'gps_local': local}


def _landmark_time(w):
    """Instant représentatif d'un repère : `ts` direct, sinon milieu de `t_enter`/`t_exit`.

    Les deux formes sont acceptées pour que la fonction serve aussi bien un repère
    ponctuel qu'une fenêtre de traversée (cas des intersections cam_analyzer).
    """
    if w.get('ts') is not None:
        return float(w['ts'])
    te, tx = w.get('t_enter'), w.get('t_exit')
    if te is None and tx is None:
        return None
    if te is None:
        return float(tx)
    if tx is None:
        return float(te)
    return (float(te) + float(tx)) / 2.0


def build_anchors(landmarks, decomposed, mask_by_key=None, reach_s=None):
    """Points d'ancrage temporels de la correction GPS.

    `landmarks` : liste de repères indexée par les clés de `decomposed['gps_local']`.
    Chaque repère porte `ts`, ou `t_enter`/`t_exit`.
    `mask_by_key` : {clé: mean_deg} issu de `geo.ign_vector` (masquage satellite).
    Absent → aucune rétraction (alpha = 1), comportement neutre.
    Un écart qui porte son propre `ts` (mesure PAR PASSAGE, en temps GPS) l'emporte sur l'instant
    du repère — les bornes des fenêtres cam_analyzer sont en temps VIDÉO, pas celui de la trace.
    `reach_s` : portée de chaque ancre (cf. `offset_at`) ; None → interpolation historique.

    Retourne [{'ts', 'de_m', 'dn_m', 'n', 'alpha'(, 'reach_s')}] trié par temps.
    """
    wins = landmarks or []
    mask_by_window = mask_by_key
    anchors = []
    for wi, off in (decomposed.get('gps_local') or {}).items():
        try:
            w = wins[int(wi)]
        except (ValueError, IndexError, TypeError):
            logger.warning("[trajectory_offset] repère %r hors de la liste — ignoré", wi)
            continue
        ts = off['ts'] if off.get('ts') is not None else _landmark_time(w)
        if ts is None:
            continue

        # Masque ABSENT ≠ ciel dégagé : BD TOPO peut être injoignable. Dans ce cas on ne
        # rétracte pas (alpha=1) — sinon une panne réseau annulerait toute la correction
        # en silence. Seule une valeur réellement mesurée peut atténuer.
        alpha = 1.0
        if mask_by_window is not None and wi in mask_by_window:
            mean_deg = float(mask_by_window[wi] or 0.0)
            alpha = max(0.0, min(1.0, mean_deg / FULL_TRUST_MASK_DEG))

        anchor = {
            'ts': float(ts),
            'de_m': off['de_m'] * alpha,
            'dn_m': off['dn_m'] * alpha,
            'n': off['n'],
            'alpha': round(alpha, 3),
        }
        if reach_s is not None:
            anchor['reach_s'] = float(reach_s)
        anchors.append(anchor)
    anchors.sort(key=lambda a: a['ts'])
    return anchors


def offset_at(anchors, ts):
    """Offset (de_m, dn_m) au temps `ts`, par interpolation linéaire entre ancres.

    Hors des bornes : maintien de la valeur extrême (jamais d'extrapolation — elle
    diverge et corromprait le début/fin de trace).
    """
    if not anchors:
        return 0.0, 0.0
    # Ancres À PORTÉE (`reach_s`, mesure par passage) : chacune pèse 1 en son instant et s'éteint
    # linéairement à ±reach_s ; les ancres qui se recouvrent se mélangent au prorata de leur poids ×
    # fiabilité, et l'ensemble est atténué par le plus fort de ces poids — loin de toute ancre, aucune
    # correction (et jamais d'extrapolation).
    if all(a.get('reach_s') for a in anchors):
        num_e = num_n = tot = 0.0
        fade = 0.0
        for a in anchors:
            w = max(0.0, 1.0 - abs(ts - a['ts']) / float(a['reach_s']))
            if w <= 0:
                continue
            k = w * max(int(a.get('n') or 0), 1)
            num_e += k * a['de_m']
            num_n += k * a['dn_m']
            tot += k
            fade = max(fade, w)
        if tot <= 0:
            return 0.0, 0.0
        return fade * num_e / tot, fade * num_n / tot
    if len(anchors) == 1 or ts <= anchors[0]['ts']:
        return anchors[0]['de_m'], anchors[0]['dn_m']
    if ts >= anchors[-1]['ts']:
        return anchors[-1]['de_m'], anchors[-1]['dn_m']

    for a, b in zip(anchors, anchors[1:]):
        if a['ts'] <= ts <= b['ts']:
            span = b['ts'] - a['ts']
            if span <= 0:
                return a['de_m'], a['dn_m']
            # Interpolation pondérée par la fiabilité (nombre d'appariements) : une ancre
            # mesurée sur 12 passages pèse plus qu'une mesurée sur 2.
            u = (ts - a['ts']) / span
            wa, wb = a['n'] * (1.0 - u), b['n'] * u
            tot = wa + wb
            if tot <= 0:
                return (a['de_m'] * (1 - u) + b['de_m'] * u,
                        a['dn_m'] * (1 - u) + b['dn_m'] * u)
            return ((a['de_m'] * wa + b['de_m'] * wb) / tot,
                    (a['dn_m'] * wa + b['dn_m'] * wb) / tot)
    return 0.0, 0.0


def correct_track(gps_track, anchors):
    """Trace GPS corrigée (nouvelle liste ; l'originale n'est jamais modifiée).

    Chaque point reçoit `lat`/`lon` corrigés et conserve l'original sous
    `lat_raw`/`lon_raw`, plus `corr_de_m`/`corr_dn_m` pour la traçabilité.
    """
    if not anchors:
        return list(gps_track or [])

    out = []
    for p in (gps_track or []):
        q = dict(p)
        # `time` est le champ canonique d'un `geo_track` ; `ts` est accepté en REPLI pour les
        # traces héritées (et parce que les ancres, elles, portent bien `ts` — cf. le SPEC).
        # Lire les deux ici est une tolérance de LECTURE, pas un second vocabulaire : la
        # déclaration, elle, n'exige que `time`.
        ts, lat, lon = (p.get('time', p.get('ts')), p.get('lat'), p.get('lon'))
        if ts is None or lat is None or lon is None:
            out.append(q)
            continue
        de, dn = offset_at(anchors, float(ts))
        m_lon = M_LAT * max(math.cos(math.radians(float(lat))), 1e-6)
        q['lat_raw'], q['lon_raw'] = lat, lon
        q['lat'] = float(lat) + dn / M_LAT          # + offset (cf. dérivation du signe)
        q['lon'] = float(lon) + de / m_lon
        q['corr_de_m'], q['corr_dn_m'] = round(de, 3), round(dn, 3)
        out.append(q)
    return out


def correction_report(anchors, corrected_track=None):
    """Résumé chiffré de la correction, pour la console et l'A/B objectif."""
    if not anchors:
        return {'n_anchors': 0, 'max_shift_m': 0.0, 'mean_shift_m': 0.0}
    shifts = [math.hypot(a['de_m'], a['dn_m']) for a in anchors]
    rep = {
        'n_anchors': len(anchors),
        'max_shift_m': round(max(shifts), 2),
        'mean_shift_m': round(sum(shifts) / len(shifts), 2),
        'mean_alpha': round(sum(a['alpha'] for a in anchors) / len(anchors), 3),
    }
    if corrected_track:
        moved = [p for p in corrected_track if p.get('corr_de_m') is not None]
        rep['n_points_corrected'] = len(moved)
    return rep


# ── Manifeste ─────────────────────────────────────────────────────────────────────────
from wama.common.catalog.function_catalog import (  # noqa: E402
    FunctionCategory, FunctionSpec, ParamSpec, PortSpec, register)
from wama.common.catalog.data_types import DataType  # noqa: E402


def apply_anchored_offsets(track, anchors, **_):
    """Point d'entrée chaînable : trace + ancres → trace corrigée (voir `correct_track`)."""
    return correct_track(track, anchors)


SPEC = register(FunctionSpec(
    key='trajectory_offset',
    name='Correction de trajectoire par offsets ancrés',
    description="Applique à une trace lat/lon des offsets mesurés en quelques repères : "
                "interpolation entre ancres pondérée par la fiabilité, sans extrapolation "
                "hors bornes. Conserve l'original (`lat_raw`/`lon_raw`) et trace la "
                "correction appliquée par point.",
    category=FunctionCategory.TRANSFORM,
    tags=['geo', 'gnss', 'timeseries'],
    inputs=[
        # ⚠ `time`, PAS `ts` (corrigé le 2026-09-09) : c'est un port `geo_track`, et le champ
        # temporel canonique de ce type est `time` (`CANONICAL_FIELDS`). Avec `ts`, cette
        # fonction était la SEULE du catalogue à exiger un champ que son propre type ne porte
        # jamais — donc AUCUN producteur de `geo_track` ne pouvait l'alimenter, en silence.
        # Famille de la leçon `ign_vector`, inversée : là un port PROMETTAIT ce qu'il ne
        # servait pas ; ici il EXIGEAIT ce qui n'existe pas. Trouvé par le tri des refus de
        # chaînage — 62 fonctions passées au crible, un seul cas.
        PortSpec('track', DataType.GEO_TRACK, required_fields=['time', 'lat', 'lon'],
                 description='Trace à corriger.'),
        # ⚠ Les ANCRES gardent `ts`, et ce n'est pas une incohérence : c'est une structure
        # INTERNE produite par `build_anchors`, sur un port `table` — type SANS champs
        # canoniques, donc sans vocabulaire imposé. Et surtout elle est PERSISTÉE par
        # cam_analyzer (`results_summary`, « on ne stocke que les ANCRES ») : la renommer
        # rendrait illisibles les ancres déjà écrites. Un vocabulaire canonique s'applique
        # là où un TYPE le garantit, pas partout par uniformité de façade.
        PortSpec('anchors', DataType.TABLE, required_fields=['ts', 'de_m', 'dn_m'],
                 cardinality='many',
                 description="Offsets ancrés (sortie de `build_anchors`). Une ancre qui porte "
                             "`reach_s` (mesure par passage) s'éteint linéairement au-delà : loin "
                             "de toute ancre, aucune correction."),
    ],
    outputs=[
        PortSpec('track', DataType.GEO_TRACK,
                 produced_fields=['lat', 'lon', 'lat_raw', 'lon_raw',
                                  'corr_de_m', 'corr_dn_m'],
                 description="Trace corrigée EN PLACE : `lat`/`lon` portent la position "
                             "corrigée, et l'originale survit sous `lat_raw`/`lon_raw`. "
                             "`corr_de_m`/`corr_dn_m` disent de combien chaque point a bougé "
                             "— sans eux la correction serait invérifiable après coup. Ancres "
                             "SANS portée : hors des bornes d'ancrage, l'offset EXTRÊME est "
                             "MAINTENU (jamais extrapolé : une extrapolation diverge et "
                             "corromprait le début et la fin de trace). Ancres À PORTÉE "
                             "(`reach_s`) : loin de toute ancre l'offset vaut 0 — le point porte "
                             "alors des champs de correction nuls. Seul un point sans coordonnées "
                             "ou sans instant ressort inchangé, sans champs de correction."),
    ],
    params=[
        ParamSpec('full_trust_mask_deg', 'float', FULL_TRUST_MASK_DEG, 0.0, 45.0, unit='°',
                  description="Élévation moyenne bouchée au-delà de laquelle la correction "
                              "locale s'applique à 100 % (rétraction en ciel dégagé). "
                              "Valeur PROVISOIRE, à réétalonner sur données réelles."),
    ],
    cost={'cpu_bound': True},
    projects=['ENA'],
    fn=apply_anchored_offsets,
))
