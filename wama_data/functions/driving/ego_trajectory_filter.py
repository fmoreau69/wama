"""Filtrage de la trajectoire EGO (véhicule porteur) — position, vitesse et cap lissés.

Pourquoi ce module existe (2026-09-05, inventaire `CAM_ANALYZER_CHAINE §INVENTAIRE D.1`) : la
pose du véhicule porteur n'était filtrée NULLE PART. Le Kalman+RTS ne servait que les objets
suivis ; la navette roulait sur GPS brut interpolé linéairement, avec un cap = bearing entre
deux fixes bruts — désigné par `§[2]` comme LA source d'erreur angulaire dominante de la chaîne
(±10-25° à basse vitesse, 8 m × 15° ≈ 2 m d'arc sur les objets). Or la pose ego contamine
TOUTES les détections d'une frame : c'est le levier de correction le plus en amont qui existe.

Ce que ça fait
--------------
1. lat/lon → repère local plan (ENU, origine = 1er point) ;
2. Kalman vitesse-constante + lisseur RTS (`kinematics.rts_smoother`) → position ET vitesse
   lissées, SANS retard de phase (le passage arrière voit le futur) ;
3. retour en lat/lon ;
4. **cap dérivé de la VITESSE LISSÉE** (`atan2(v_est, v_nord)`), tenu au dernier connu quand la
   vitesse passe sous `heading_min_speed_mps` — c'est la généralisation du « tenu si déplacement
   < 0,30 m » du cap brut, mais appliquée à une vitesse débruitée plutôt qu'à un déplacement
   entre deux fixes bruités.

5. **accélération COMMANDÉE** (optionnel, `accel_long`) : quand l'accéléromètre est disponible,
   le modèle cesse de supposer « accélération inconnue ±`sigma_a` » et suppose « accélération
   mesurée ±`sigma_a_commanded` ». MESURÉ le 2026-09-10 (§D.4 ⑤) : le résidu vaut 0,20 m/s²
   contre 0,8 — **4× plus fin**. Deux passes (la 1ʳᵉ donne le cap qui projette l'accélération
   longitudinale en ENU) ; le rapport chiffre ce que la commande DÉPLACE.

Ce que ça ne fait PAS (assumé, mesurable)
-----------------------------------------
* Pas de cap à l'arrêt : sans gyroscope, aucune source ne le donne. ⚠ **Et l'accéléromètre
  n'y supplée PAS** : la relation non-holonome `ω = ay/v` tient pourtant à l'échelle 1
  (mesuré : `c = −1,004`, §D.4 ⑥), mais elle divise par `v` — or le cap n'est mauvais QUE
  lorsque `v` est petit, et à 0,5 m/s un virage à 10°/s passe 3× SOUS le bruit de l'axe.
  Testé sur 61 segments : tenir le cap erre de 4,8° en médiane, l'intégrer de 65,5°. C'est la
  case que `geometry.ego_rotation` (rotation par flux de points) est destinée à remplir.
* La commande n'est PAS atteignable depuis le Studio : `accel_long` est un CALLABLE (une série
  échantillonnée à une autre cadence), pas un scalaire — un `ParamSpec` ne peut pas le porter.
  Le jour où l'accélération arrivera comme un second PORT d'entrée typé, ce sera la bonne
  forme ; en attendant, seul l'appelant applicatif (`cam_analyzer.ego_pose`) la fournit.

Enricher : mêmes lignes en sortie, colonnes AJOUTÉES (`lat_f`, `lon_f`, `speed_f_kmh`,
`heading_f`, `heading_f_held`), colonnes brutes intactes — l'A/B se lit ligne à ligne.
Deux étages (patron `geometry/placement_metrics`) : `filter_gps_points` (noyau, listes de dicts,
sans pandas) et `filter_ego_track` (wrapper TypedFrame, ce que le catalogue appelle).
"""
from __future__ import annotations

import math
from bisect import bisect_left

from ..kinematics.rts_smoother import kalman_rts_cv

M_LAT = 111_320.0

#: Défauts PROVISOIRES pour une navette urbaine sur GPS ~1-3 Hz de bon fix (HDOP < 1) :
#: accélération de processus modérée (une navette n'excède guère 1 m/s²), bruit de mesure
#: de l'ordre de 2 m. À réétalonner sur `placement_spread` (règle : la métrique conclut).
DEFAULT_SIGMA_A = 0.8
DEFAULT_SIGMA_M = 2.0
#: Dispersion de processus quand l'accélération est COMMANDÉE (accéléromètre en entrée).
#: MESURÉ le 2026-09-10 sur la session P97 (`CAM_ANALYZER_CHAINE §D.4 ⑤`) : le résidu
#: `dv/dt − (k·ax·g + b)` contre la vitesse Doppler vaut **0,202 m/s²**, soit 4× plus fin que
#: `DEFAULT_SIGMA_A`. ⚠ C'est une **BORNE HAUTE** — le résidu inclut le bruit du Doppler qui
#: sert de référence, donc la vraie dispersion de l'accéléromètre lui est inférieure. 0,25
#: arrondit dans le sens PRUDENT (un σ trop petit ferait diverger le filtre en croyant la
#: commande plus qu'elle ne vaut ; trop grand, il perd du gain sans rien casser).
DEFAULT_SIGMA_A_COMMANDED = 0.25
#: En dessous, la direction de la vitesse lissée n'est plus significative → cap tenu.
#: MESURÉ (2026-09-05, trace synthétique 1 Hz, arrêt franc) : la vitesse filtrée résiduelle à
#: l'ARRÊT vaut ~0,17 m/s médiane / 0,50 max pour ±1 m de bruit GPS, ~0,33 / 1,01 pour ±2 m.
#: Un seuil à 0,5 m/s était donc sur le fil ; 1,0 m/s (3,6 km/h) tient à ±1 m et couvre
#: l'essentiel à ±2 m. Sous 3,6 km/h la navette manœuvre ou est arrêtée : c'est précisément le
#: régime où le cap brut vaut ±10-25° — tenir le cap y est le bon choix, et la vraie source
#: pour ce régime est la rotation visuelle (`geometry.ego_rotation`), pas le GPS.
DEFAULT_HEADING_MIN_SPEED_MPS = 1.0


def _bearing_from_velocity(ve: float, vn: float) -> float:
    """Cap (deg, 0 = nord, sens horaire) depuis une vitesse (est, nord)."""
    return math.degrees(math.atan2(ve, vn)) % 360.0


def _angle_diff(a: float, b: float) -> float:
    return (a - b + 180.0) % 360.0 - 180.0


def filter_gps_points(points, *, sigma_a: float = DEFAULT_SIGMA_A,
                      sigma_m: float = DEFAULT_SIGMA_M,
                      heading_min_speed_mps: float = DEFAULT_HEADING_MIN_SPEED_MPS,
                      time_field: str = 'ts', accel_long=None,
                      sigma_a_commanded: float = DEFAULT_SIGMA_A_COMMANDED):
    """NOYAU — liste de dicts {ts, lat, lon[, heading, speed_kmh]} → même liste enrichie.

    Rend (points_enrichis, rapport). Chaque point reçoit `lat_f`, `lon_f`, `speed_f_kmh`,
    `heading_f`, `heading_f_held`. Le rapport chiffre l'A/B : déplacement RMS brut→filtré (m),
    écart de cap médian |brut − filtré| (deg) sur les points où les deux existent, part des
    caps tenus. Points sans lat/lon ou sans temps : recopiés tels quels, sans champs `_f`.

    `accel_long` (optionnel) : `callable(t) -> a` en m/s², accélération LONGITUDINALE mesurée
    (accéléromètre, axe avant). Fournie, le filtre passe du modèle « accélération inconnue
    ±`sigma_a` » au modèle « accélération mesurée ±`sigma_a_commanded` ». **DEUX PASSES** : la
    1ʳᵉ (non commandée) donne le cap, qui sert à projeter l'accélération longitudinale en ENU
    pour la 2ᵉ — un accéléromètre mesure dans le repère du VÉHICULE, le filtre travaille dans
    celui du TERRAIN, et rien d'autre ne donne la rotation entre les deux. Là où le cap est
    tenu (vitesse trop faible), c'est le dernier cap connu qui sert : à ce régime la navette
    démarre ou s'arrête dans l'axe de sa voie, l'hypothèse est explicite et bornée.
    """
    usable = [(i, p) for i, p in enumerate(points)
              if p.get('lat') is not None and p.get('lon') is not None
              and p.get(time_field) is not None]
    out = [dict(p) for p in points]
    if len(usable) < 3:
        return out, {'n': len(usable), 'filtered': False,
                     'reason': 'moins de 3 points géolocalisés'}

    lat0, lon0 = float(usable[0][1]['lat']), float(usable[0][1]['lon'])
    m_lon = M_LAT * max(math.cos(math.radians(lat0)), 1e-6)

    series = [(float(p[time_field]),
               (float(p['lon']) - lon0) * m_lon,
               (float(p['lat']) - lat0) * M_LAT) for _, p in usable]

    def _lisse(sig_a, command):
        sm = kalman_rts_cv(series, sigma_a=sig_a, sigma_m=sigma_m, command=command)
        # Le lisseur moyenne les doublons de temps : on relit par timestamp arrondi.
        return {round(t, 4): (e, n, ve, vn) for t, e, n, ve, vn in sm}

    by_t = _lisse(sigma_a, None)
    by_t_libre, commande = None, None

    if accel_long is not None:
        # Cap de la 1ʳᵉ passe, tenu au dernier connu sous le seuil — même règle qu'en sortie.
        t_cap, cap_rad = [], []
        dernier = None
        for t, _e, _n in series:
            st = by_t.get(round(t, 4))
            if st is not None and math.hypot(st[2], st[3]) >= heading_min_speed_mps:
                dernier = math.atan2(st[2], st[3])
            t_cap.append(t)
            cap_rad.append(dernier)

        def _commande(t):
            a = accel_long(t)
            if a is None:
                return (None, None)
            k = bisect_left(t_cap, t)
            if k >= len(cap_rad):
                k = len(cap_rad) - 1
            h = cap_rad[k]
            if h is None:
                return (None, None)          # aucun cap encore connu : on ne commande pas
            return (a * math.sin(h), a * math.cos(h))

        by_t_libre = by_t
        by_t = _lisse(sigma_a_commanded, _commande)
        commande = True

    last_heading = None
    disp2, dheads, held = [], [], 0
    for i, p in usable:
        st = by_t.get(round(float(p[time_field]), 4))
        if st is None:
            continue
        e, n, ve, vn = st
        lat_f = lat0 + n / M_LAT
        lon_f = lon0 + e / m_lon
        speed = math.hypot(ve, vn)
        if speed >= heading_min_speed_mps:
            last_heading = _bearing_from_velocity(ve, vn)
            is_held = False
        else:
            is_held = True
            held += 1
        q = out[i]
        q['lat_f'] = round(lat_f, 7)
        q['lon_f'] = round(lon_f, 7)
        q['speed_f_kmh'] = round(speed * 3.6, 2)
        q['heading_f'] = round(last_heading, 1) if last_heading is not None else None
        q['heading_f_held'] = is_held
        de = (float(p['lon']) - lon_f) * m_lon
        dn = (float(p['lat']) - lat_f) * M_LAT
        disp2.append(de * de + dn * dn)
        h_raw = p.get('heading')
        if h_raw is not None and last_heading is not None:
            dheads.append(abs(_angle_diff(float(h_raw), last_heading)))

    dheads.sort()
    report = {
        'n': len(disp2),
        'filtered': True,
        'sigma_a': sigma_a_commanded if commande else sigma_a,
        'sigma_m': sigma_m,
        'heading_min_speed_mps': heading_min_speed_mps,
        'displacement_rms_m': round(math.sqrt(sum(disp2) / len(disp2)), 3) if disp2 else None,
        'heading_delta_median_deg': (round(dheads[len(dheads) // 2], 1) if dheads else None),
        'heading_held_ratio': round(held / len(disp2), 3) if disp2 else None,
    }
    if commande:
        # A/B INTERNE : ce que la commande DÉPLACE par rapport à la même trace non commandée.
        # Un écart nul dirait que la commande n'arrive pas (garde contre le câblage muet) ;
        # un écart énorme dirait qu'elle tire le filtre au lieu de l'aider.
        ecarts, dv = [], []
        for t, _e, _n in series:
            k = round(t, 4)
            a, b = by_t.get(k), by_t_libre.get(k)
            if a is None or b is None:
                continue
            ecarts.append(math.hypot(a[0] - b[0], a[1] - b[1]))
            dv.append(abs(math.hypot(a[2], a[3]) - math.hypot(b[2], b[3])))
        ecarts.sort()
        dv.sort()
        report['commanded'] = True
        report['sigma_a_libre'] = sigma_a
        report['command_shift_median_m'] = round(ecarts[len(ecarts) // 2], 3) if ecarts else None
        report['command_shift_p95_m'] = (round(ecarts[int(0.95 * (len(ecarts) - 1))], 3)
                                         if ecarts else None)
        report['command_speed_delta_median_kmh'] = (round(dv[len(dv) // 2] * 3.6, 3)
                                                    if dv else None)
    return out, report


def filter_ego_track(track: 'TypedFrame', *, sigma_a: float = DEFAULT_SIGMA_A,
                     sigma_m: float = DEFAULT_SIGMA_M,
                     heading_min_speed_mps: float = DEFAULT_HEADING_MIN_SPEED_MPS,
                     time_field: str = 'time') -> 'TypedFrame':
    """Wrapper FunctionSpec : `TypedFrame` geo_track → `TypedFrame` geo_track enrichi.

    `time_field` : `time` (canonique WAMA Data) ou `ts` (cam_analyzer) — les deux existent
    dans le dépôt, le port ne tranche pas à la place du producteur.
    """
    import pandas as pd
    from wama.common.catalog.data_types import TypedFrame, DataType

    df = track.df
    tf = time_field if time_field in df.columns else ('ts' if 'ts' in df.columns else 'time')
    pts = df.to_dict('records')
    enriched, report = filter_gps_points(pts, sigma_a=sigma_a, sigma_m=sigma_m,
                                         heading_min_speed_mps=heading_min_speed_mps,
                                         time_field=tf)
    out = pd.DataFrame(enriched, index=df.index)
    return TypedFrame(out, DataType.GEO_TRACK, meta={**(track.meta or {}), 'ego_filter': report})


# ── Manifeste ─────────────────────────────────────────────────────────────────────────
from wama.common.catalog.function_catalog import (  # noqa: E402
    FunctionCategory, FunctionSpec, ParamSpec, PortSpec, register)
from wama.common.catalog.data_types import DataType  # noqa: E402

SPEC = register(FunctionSpec(
    key='ego_track_filter',
    name='Filtre de trajectoire ego (Kalman + RTS)',
    description="Lisse la position et la vitesse du véhicule porteur par Kalman vitesse-"
                "constante + lisseur RTS (sans retard de phase), et dérive le cap de la vitesse "
                "lissée — tenu sous un seuil de vitesse. Colonnes ajoutées, brutes conservées : "
                "l'A/B se lit ligne à ligne. Premier levier de correction qui touche la pose ego, "
                "dont toute détection hérite.",
    category=FunctionCategory.ENRICHER,
    tags=['geo', 'timeseries', 'ego-motion', 'gnss', 'ab-metric'],
    inputs=[PortSpec('track', DataType.GEO_TRACK, required_fields=['lat', 'lon'],
                     description='Trace GPS du véhicule porteur (heading optionnel, sert au rapport).')],
    # Facette estimateur (⑤b) : ce port ESTIME le cap ego depuis le GPS seul. σ = 3° est
    # la valeur MESURÉE sur trace synthétique (`tests_ego_trajectory_filter` : < 1/3 des 8°
    # du cap brut) — PROVISOIRE sur données réelles, à réétalonner comme σa/σm. Cap tenu
    # (`heading_f_held`) = pas une mesure : la fusion l'écarte. `derived_from=['gps']` dit
    # à `fuse_estimates` que cette sortie ne se fusionne JAMAIS avec le cap brut GPS (même
    # source) — seulement avec une source indépendante (`geometry.ego_rotation`, image).
    outputs=[PortSpec('track', DataType.GEO_TRACK,
                      produced_fields=['lat_f', 'lon_f', 'speed_f_kmh', 'heading_f', 'heading_f_held'],
                      description='Même trace, enrichie ; rapport A/B dans meta.ego_filter.',
                      estimates='heading', estimate_field='heading_f',
                      uncertainty={'model': 'held', 'field': 'heading_f_held', 'sigma': 3.0},
                      derived_from=['gps'])],
    params=[
        ParamSpec('sigma_a', 'float', DEFAULT_SIGMA_A, 0.05, 10.0, unit='m/s²',
                  description="Accélération de processus (agilité du véhicule)."),
        ParamSpec('sigma_m', 'float', DEFAULT_SIGMA_M, 0.1, 20.0, unit='m',
                  description="Bruit de mesure GPS (≈ HDOP × précision nominale)."),
        ParamSpec('heading_min_speed_mps', 'float', DEFAULT_HEADING_MIN_SPEED_MPS, 0.0, 5.0,
                  unit='m/s', description="Sous cette vitesse lissée, le cap est tenu."),
    ],
    cost={'cpu_bound': True},
    fn=filter_ego_track,
))
