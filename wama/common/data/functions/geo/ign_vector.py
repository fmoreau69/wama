"""Données VECTORIELLES IGN (BD TOPO V3) — bâtiments et réseau routier.

**Règle posée 2026-07-28** : ce que l'IGN publie en vecteur ne doit PAS être détecté
visuellement. Les emprises de bâtiments et les tronçons de route viennent d'ici —
autoritatifs, exacts, avec leurs attributs (hauteur, altitudes sol/toit) — tandis que les
marquages au sol, absents de toute base vectorielle, restent du ressort de la détection
(SAM3 / détecteur open-vocab, cf. ROADMAP §17).

Premier consommateur : cam_analyzer (recalage GPS, étape 2b). Rien ici n'est spécifique à
cette app — d'où la place en `common/` (reclassé 2026-07-29).

Deux usages :
  1. `sky_mask()` — masquage satellite par les bâtiments (urban canyon). C'est ce qui permet
     d'EXPLIQUER un biais GPS latéral (ex. façades à l'est) au lieu de le constater, et donc
     de pondérer/corriger le recalage plutôt que d'appliquer un offset aveugle.
  2. `fetch_roads()` — géométrie de route autoritative pour le map-matching.

Axes : le WFS IGN attend le bbox en **lon,lat** (vérifié 2026-07-28 ; l'ordre lat,lon renvoie
0 entité sans erreur — piège silencieux). Les géométries reviennent en lon,lat[,altitude].
"""
import logging
import math

logger = logging.getLogger(__name__)

_WFS = "https://data.geopf.fr/wfs/ows"
LAYER_BUILDINGS = "BDTOPO_V3:batiment"
LAYER_ROADS = "BDTOPO_V3:troncon_de_route"

# Cache mémoire par (couche, bbox arrondi) — une session rejoue souvent les mêmes zones.
# Volontairement pas de cache disque : la BD TOPO évolue, et le coût réseau reste faible.
_CACHE: dict = {}
_CACHE_MAX = 64


def _bbox_around(lat: float, lon: float, radius_m: float):
    """Carré géographique de ±radius_m autour de (lat, lon), en (lon_min, lat_min, lon_max, lat_max)."""
    dlat = radius_m / 111_320.0
    dlon = radius_m / (111_320.0 * max(math.cos(math.radians(lat)), 1e-6))
    return (lon - dlon, lat - dlat, lon + dlon, lat + dlat)


def _wfs_features(typename: str, lat: float, lon: float, radius_m: float, count: int = 1000):
    """Interroge le WFS IGN et retourne la liste de features GeoJSON ([] si échec réseau)."""
    import requests
    from wama.common.utils.http_proxy import outbound_proxies

    bbox = _bbox_around(lat, lon, radius_m)
    key = (typename, tuple(round(v, 5) for v in bbox))
    if key in _CACHE:
        return _CACHE[key]

    params = {
        "SERVICE": "WFS", "VERSION": "2.0.0", "REQUEST": "GetFeature",
        "TYPENAMES": typename, "SRSNAME": "EPSG:4326",
        "BBOX": f"{bbox[0]},{bbox[1]},{bbox[2]},{bbox[3]},EPSG:4326",
        "COUNT": str(count), "OUTPUTFORMAT": "application/json",
    }
    try:
        r = requests.get(_WFS, params=params, timeout=60,
                         proxies=outbound_proxies('CAM_ANALYZER_ORTHO_PROXY'))
        r.raise_for_status()
        feats = r.json().get("features", []) or []
    except Exception as exc:  # réseau/proxy/JSON — jamais bloquant pour la chaîne
        logger.warning("[ign_vector] %s indisponible (%s)", typename, exc)
        return []

    if len(_CACHE) >= _CACHE_MAX:
        _CACHE.clear()
    _CACHE[key] = feats
    return feats


def _rings(geom):
    """Anneaux extérieurs d'un (Multi)Polygon, en listes de (lon, lat)."""
    if not geom:
        return []
    t, c = geom.get("type"), geom.get("coordinates") or []
    polys = c if t == "MultiPolygon" else ([c] if t == "Polygon" else [])
    out = []
    for poly in polys:
        if poly:
            # poly[0] = anneau extérieur ; coords éventuellement 3D (lon, lat, alt).
            out.append([(pt[0], pt[1]) for pt in poly[0] if len(pt) >= 2])
    return out


def fetch_buildings(lat: float, lon: float, radius_m: float = 300.0):
    """Bâtiments BD TOPO autour d'un point.

    Retourne [{'rings': [[(lon, lat), …]], 'hauteur': m|None, 'alt_sol': m|None,
               'alt_toit': m|None, 'etages': int|None}].
    Rayon 300 m par défaut : un immeuble de 25 m à 300 m masque encore ~5° d'élévation,
    ce qui reste dans la plage des satellites bas responsables du multitrajet.
    """
    out = []
    for f in _wfs_features(LAYER_BUILDINGS, lat, lon, radius_m):
        p = f.get("properties") or {}
        rings = _rings(f.get("geometry"))
        if not rings:
            continue
        out.append({
            "rings": rings,
            "hauteur": p.get("hauteur"),
            "alt_sol": p.get("altitude_minimale_sol"),
            "alt_toit": p.get("altitude_maximale_toit"),
            "etages": p.get("nombre_d_etages"),
        })
    return out


def fetch_roads(lat: float, lon: float, radius_m: float = 300.0):
    """Tronçons de route BD TOPO autour d'un point.

    Retourne [{'coords': [(lon, lat), …], 'nature': str|None, 'nom': str|None,
               'sens': str|None, 'largeur': m|None}].
    """
    out = []
    for f in _wfs_features(LAYER_ROADS, lat, lon, radius_m):
        p = f.get("properties") or {}
        geom = f.get("geometry") or {}
        t, c = geom.get("type"), geom.get("coordinates") or []
        lines = c if t == "MultiLineString" else ([c] if t == "LineString" else [])
        for line in lines:
            coords = [(pt[0], pt[1]) for pt in line if len(pt) >= 2]
            if len(coords) >= 2:
                out.append({
                    "coords": coords,
                    "nature": p.get("nature"),
                    "nom": p.get("nom_1_gauche") or p.get("nom_collaborateur"),
                    "sens": p.get("sens_de_circulation"),
                    "largeur": p.get("largeur_de_chaussee"),
                })
    return out


def sky_mask(lat: float, lon: float, buildings, n_azimuth: int = 72,
             receiver_alt: float = None, receiver_height_m: float = 1.5):
    """Masque d'élévation par azimut : jusqu'à quelle hauteur le ciel est bouché.

    Retourne une liste de `n_azimuth` angles d'élévation en degrés (index 0 = Nord,
    sens horaire, pas = 360/n_azimuth). 0.0 = horizon dégagé.

    Modèle : pour chaque sommet d'emprise, élévation = atan(hauteur_utile / distance).
    `receiver_alt` (altitude NGF du récepteur) permet d'utiliser `alt_toit` — sinon on
    retombe sur `hauteur` en supposant le terrain localement plat, hypothèse raisonnable
    en milieu urbain sur quelques centaines de mètres.
    """
    step = 360.0 / n_azimuth
    mask = [0.0] * n_azimuth
    coslat = max(math.cos(math.radians(lat)), 1e-6)

    for b in buildings:
        h = b.get("hauteur")
        if receiver_alt is not None and b.get("alt_toit") is not None:
            h = b["alt_toit"] - receiver_alt
        if not h or h <= 0:
            continue
        h = h - receiver_height_m
        if h <= 0:
            continue

        for ring in b["rings"]:
            for (plon, plat) in ring:
                de = (plon - lon) * 111_320.0 * coslat      # Est, mètres
                dn = (plat - lat) * 111_320.0                # Nord, mètres
                d = math.hypot(de, dn)
                if d < 1.0:      # récepteur dans l'emprise : ignoré (cas dégénéré)
                    continue
                elev = math.degrees(math.atan2(h, d))
                az = math.degrees(math.atan2(de, dn)) % 360.0
                i = int(az / step) % n_azimuth
                if elev > mask[i]:
                    mask[i] = elev

    return [round(v, 1) for v in mask]


def sky_mask_at(lat: float, lon: float, radius_m: float = 300.0, n_azimuth: int = 72):
    """Masque satellite en un point : récupère les bâtiments puis calcule le masque.

    Retourne {'mask': [élévations par azimut], **mask_summary}. `mask` vide si BD TOPO est
    injoignable — un appelant NE DOIT PAS confondre ce cas avec un ciel dégagé (cf.
    `ortho_apply.build_anchors`, où l'absence de mesure vaut « ne pas atténuer »).
    """
    blds = fetch_buildings(lat, lon, radius_m)
    if not blds:
        return {"mask": [], "available": False}
    m = sky_mask(lat, lon, blds, n_azimuth)
    return {"mask": m, "available": True, **mask_summary(m)}


def mask_summary(mask):
    """Résumé lisible d'un masque : ouverture moyenne et secteur le plus bouché.

    Retourne {'mean_deg', 'max_deg', 'max_azimuth_deg', 'blocked_ratio'} —
    `blocked_ratio` = part des azimuts bouchés au-delà de 15° (seuil usuel des
    satellites bas, principaux contributeurs du multitrajet en canyon urbain).
    """
    if not mask:
        return {"mean_deg": 0.0, "max_deg": 0.0, "max_azimuth_deg": 0.0, "blocked_ratio": 0.0}
    n = len(mask)
    imax = max(range(n), key=lambda i: mask[i])
    return {
        "mean_deg": round(sum(mask) / n, 1),
        "max_deg": round(mask[imax], 1),
        "max_azimuth_deg": round(imax * 360.0 / n, 1),
        "blocked_ratio": round(sum(1 for v in mask if v > 15.0) / n, 2),
    }


# ── Manifestes ────────────────────────────────────────────────────────────────────────
# Ce sont des fonctions SOURCE (aucun port d'entrée : elles sont paramétrées par un point,
# pas alimentées par une donnée amont). `FunctionCategory` n'a pas de valeur `SOURCE` :
# TRANSFORM est le moins faux — écart signalé plutôt que masqué.
from wama.common.data.function_catalog import (  # noqa: E402
    FunctionCategory, FunctionSpec, ParamSpec, PortSpec, register)
from wama.common.data.data_types import DataType  # noqa: E402

_LOC_PARAMS = [
    ParamSpec('lat', 'float', None, -90.0, 90.0, unit='°', description='Latitude WGS84.'),
    ParamSpec('lon', 'float', None, -180.0, 180.0, unit='°', description='Longitude WGS84.'),
    ParamSpec('radius_m', 'float', 300.0, 10.0, 2000.0, unit='m',
              description="Rayon autour du point. 300 m : un immeuble de 25 m y masque "
                          "encore ~5° d'élévation, plage des satellites bas."),
]

SPEC_BUILDINGS = register(FunctionSpec(
    key='ign_buildings',
    name='Bâtiments IGN (BD TOPO)',
    description="Emprises de bâtiments avec hauteur, altitudes sol/toit et nombre d'étages, "
                "depuis le WFS IGN. Autoritatif : à préférer systématiquement à une "
                "détection visuelle de bâtiments.",
    category=FunctionCategory.TRANSFORM,
    tags=['geo', 'ign', 'reference', 'network', 'france'],
    inputs=[],
    outputs=[PortSpec('buildings', DataType.TABLE,
                      produced_fields=['rings', 'hauteur', 'alt_sol', 'alt_toit', 'etages'],
                      cardinality='many',
                      description='Emprises (anneaux lon/lat) et attributs de hauteur.')],
    params=_LOC_PARAMS,
    cost={'network': True},
    projects=['ENA'],
    fn=fetch_buildings,
))

SPEC_ROADS = register(FunctionSpec(
    key='ign_roads',
    name='Réseau routier IGN (BD TOPO)',
    description="Tronçons de route (axes) avec nature, sens de circulation et largeur de "
                "chaussée, depuis le WFS IGN. Référentiel de map-matching.",
    category=FunctionCategory.TRANSFORM,
    tags=['geo', 'ign', 'reference', 'network', 'france'],
    inputs=[],
    outputs=[PortSpec('road_map', DataType.ROAD_MAP,
                      produced_fields=['coords', 'nature', 'nom', 'sens', 'largeur'],
                      cardinality='many',
                      description='Polylignes routières lon/lat + attributs.')],
    params=_LOC_PARAMS,
    cost={'network': True},
    projects=['ENA'],
    fn=fetch_roads,
))

SPEC_SKY_MASK = register(FunctionSpec(
    key='sky_mask',
    name='Masquage satellite (canyon urbain)',
    description="Élévation bouchée par les bâtiments, par azimut. Explique un biais GPS "
                "latéral (multitrajet en canyon urbain) au lieu de le constater : sert à "
                "pondérer une correction de trajectoire. `available=False` = référentiel "
                "injoignable — à ne PAS confondre avec un ciel dégagé.",
    category=FunctionCategory.INDICATOR,
    tags=['geo', 'gnss', 'ign', 'network', 'france'],
    inputs=[],
    outputs=[PortSpec('sky_mask', DataType.TABLE,
                      produced_fields=['mask', 'available', 'mean_deg', 'max_deg',
                                       'max_azimuth_deg', 'blocked_ratio'],
                      description="Masque par azimut + résumé (0 = horizon dégagé).")],
    params=_LOC_PARAMS + [
        ParamSpec('n_azimuth', 'int', 72, 8, 360,
                  description="Nombre de secteurs d'azimut (72 = pas de 5°)."),
    ],
    cost={'network': True},
    projects=['ENA'],
    fn=sky_mask_at,
))
