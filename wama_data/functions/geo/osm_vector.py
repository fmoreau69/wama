"""Données VECTORIELLES OpenStreetMap (Overpass) — sémantique d'intersection et réseau mondial.

Module JUMEAU de `ign_vector`, et la question « pourquoi deux » a une réponse nette : ils ne
publient pas la même chose.

  • **BD TOPO** est autoritative sur la GÉOMÉTRIE (tronçons au décimètre, largeur de chaussée,
    hauteurs de bâtiments) — et le reste, IGN excepté, ne la vaut pas. Elle ne dit RIEN de la
    règle de priorité qui s'applique à un carrefour.
  • **OSM** est faible là où BD TOPO est forte, et seule à porter la **sémantique de contrôle** :
    `highway=stop`, `give_way`, `traffic_signals`, `crossing`, `junction=roundabout`, ainsi que
    `maxspeed`, `lanes`, `oneway`.

Or c'est exactement ce que `cam_analyzer` APPREND aujourd'hui du trafic observé
(`intersection_branches.learn_branches`) ou détecte visuellement (`world_markings` : lignes
d'arrêt, passages piétons) — **sans aucune vérité terrain pour s'y comparer**. La règle du
domaine posée le 2026-07-28 (« ce qu'un référentiel publie en vecteur ne se détecte pas
visuellement ») s'applique donc ici comme ailleurs, mais sur d'autres objets que l'IGN.

Second usage, incident : `road_map_frame` alimente le port `road_map` **hors de France**, là
où `ign_vector` n'a rien à dire.

⚠ **Les axes ne se posent PAS comme chez l'IGN.** Overpass attend son bbox en
`(sud, ouest, nord, est)` = (lat_min, lon_min, lat_max, lon_max) et rend ses géométries en
`lat`/`lon` NOMMÉS — donc, contrairement à `ign_vector.road_map_frame`, il n'y a **aucune
inversion à faire ici**, et en ajouter une par symétrie serait le bug. L'ordre inverse du WFS
IGN est documenté en tête de `ign_vector` : les deux pièges existent, ils sont opposés.
"""
import logging

logger = logging.getLogger(__name__)

_OVERPASS = "https://overpass-api.de/api/interpreter"

#: Nœuds qui portent une RÈGLE de circulation. `crossing` est inclus parce qu'il est le
#: pendant vectoriel exact du `crossing` que SAM3 segmente sur l'ortho (amer du recalage 2b).
CONTROL_NODES = ('traffic_signals', 'stop', 'give_way', 'crossing', 'mini_roundabout')

_M_PER_DEG_LAT = 111_320.0

# Cache mémoire par (requête, bbox arrondi) — même politique qu'`ign_vector` : une session
# rejoue les mêmes carrefours, et OSM demande qu'on ménage son instance publique.
_CACHE: dict = {}
_CACHE_MAX = 64


def _bbox_around(lat: float, lon: float, radius_m: float):
    """Carré de ±radius_m, en ordre **Overpass** : (sud, ouest, nord, est)."""
    import math
    dlat = radius_m / _M_PER_DEG_LAT
    dlon = radius_m / (_M_PER_DEG_LAT * max(math.cos(math.radians(lat)), 1e-6))
    return (lat - dlat, lon - dlon, lat + dlat, lon + dlon)


def _overpass(corps: str, lat: float, lon: float, radius_m: float, timeout_s: int = 60):
    """Exécute une requête Overpass QL et rend la liste d'`elements` ([] si échec réseau).

    `corps` contient `{bbox}`, substitué par le bbox en ordre Overpass. Comme
    `ign_vector._wfs_features`, cette fonction n'est JAMAIS bloquante : une panne réseau
    rend une liste vide et un avertissement, jamais une exception qui casse la chaîne.
    """
    import requests
    from wama.common.utils.http_proxy import outbound_proxies

    s, o, n, e = _bbox_around(lat, lon, radius_m)
    bbox = f"{s},{o},{n},{e}"
    key = (corps, tuple(round(v, 5) for v in (s, o, n, e)))
    if key in _CACHE:
        return _CACHE[key]

    query = f"[out:json][timeout:{timeout_s}];\n" + corps.format(bbox=bbox) + "\nout geom;"
    try:
        r = requests.post(_OVERPASS, data={'data': query}, timeout=timeout_s + 10,
                          proxies=outbound_proxies('WAMA_OUTBOUND_PROXY'))
        r.raise_for_status()
        elements = r.json().get('elements', []) or []
    except Exception as exc:  # réseau/proxy/quota Overpass — jamais bloquant
        logger.warning("[osm_vector] Overpass indisponible (%s)", exc)
        return []

    if len(_CACHE) >= _CACHE_MAX:
        _CACHE.clear()
    _CACHE[key] = elements
    return elements


def fetch_control_nodes(lat: float, lon: float, radius_m: float = 300.0):
    """Nœuds de contrôle OSM autour d'un point.

    Retourne [{'osm_id', 'lat', 'lon', 'control', 'tags'}] où `control` ∈ CONTROL_NODES
    ∪ {'level_crossing'}.
    """
    motif = "|".join(CONTROL_NODES)
    corps = ('(\n'
             f'  node["highway"~"^({motif})$"]({{bbox}});\n'
             '  node["railway"="level_crossing"]({bbox});\n'
             ');')
    out = []
    for el in _overpass(corps, lat, lon, radius_m):
        if el.get('type') != 'node':
            continue
        tags = el.get('tags') or {}
        control = tags.get('highway') or tags.get('railway')
        if not control:
            continue
        out.append({
            'osm_id': el.get('id'),
            'lat': el.get('lat'),
            'lon': el.get('lon'),
            'control': control,
            'tags': tags,
        })
    return out


def fetch_roads(lat: float, lon: float, radius_m: float = 300.0):
    """Voies carrossables OSM autour d'un point.

    Retourne [{'osm_id', 'coords': [(lat, lon), …], 'highway', 'nom', 'oneway',
               'lanes', 'maxspeed', 'junction'}].

    ⚠ `coords` est en **(lat, lon)** — l'ordre attendu par `gps_map_match`. C'est l'ordre
    NATIF d'Overpass ; la clé homonyme d'`ign_vector.fetch_roads` est en (lon, lat).
    Deux clés du même nom, deux conventions : elles ne se recopient pas d'un module à l'autre.
    """
    corps = ('(\n'
             '  way["highway"]["highway"!~"^(footway|path|steps|cycleway|pedestrian|track)$"]'
             '({bbox});\n'
             ');')
    out = []
    for el in _overpass(corps, lat, lon, radius_m):
        if el.get('type') != 'way':
            continue
        tags = el.get('tags') or {}
        coords = [(p['lat'], p['lon']) for p in (el.get('geometry') or [])
                  if p.get('lat') is not None and p.get('lon') is not None]
        if len(coords) < 2:
            continue
        out.append({
            'osm_id': el.get('id'),
            'coords': coords,
            'highway': tags.get('highway'),
            'nom': tags.get('name'),
            'oneway': tags.get('oneway'),
            'lanes': tags.get('lanes'),
            'maxspeed': tags.get('maxspeed'),
            'junction': tags.get('junction'),
        })
    return out


def road_map_frame(lat: float, lon: float, radius_m: float = 300.0):
    """Voies OSM → `TypedFrame` ROAD_MAP consommable par `gps_map_match`.

    Même port, même forme que `ign_vector.road_map_frame` — mais **aucune inversion d'axes**
    (voir l'en-tête du module). Utile hors de France, ou pour disposer d'un second
    référentiel quand on veut comparer les recalages.
    """
    import pandas as pd
    from wama.common.catalog.data_types import TypedFrame, DataType

    rows = []
    for i, r in enumerate(fetch_roads(lat, lon, radius_m)):
        rows.append({
            'id': r.get('nom') or f"osm_way_{r.get('osm_id') or i}",
            'type': r.get('highway'),
            'geometry': list(r['coords']),      # DÉJÀ en (lat, lon)
            'nom': r.get('nom'),
            'sens': r.get('oneway'),
            'lanes': r.get('lanes'),
            'maxspeed': r.get('maxspeed'),
        })
    return TypedFrame(pd.DataFrame(rows, columns=[
        'id', 'type', 'geometry', 'nom', 'sens', 'lanes', 'maxspeed']), DataType.ROAD_MAP,
        meta={'source': 'osm:overpass', 'center': (lat, lon), 'radius_m': radius_m})


def control_nodes_frame(lat: float, lon: float, radius_m: float = 300.0):
    """Nœuds de contrôle → `TypedFrame` TABLE (`lat`, `lon`, `control`, `osm_id`).

    TABLE et non SEGMENTS/EVENTS : ce sont des POINTS géographiques permanents, sans
    extension temporelle. Le catalogue n'a pas de type « points » — écart signalé plutôt
    que masqué, comme l'absence de `FunctionCategory.SOURCE` l'est dans `ign_vector`.
    """
    import pandas as pd
    from wama.common.catalog.data_types import TypedFrame, DataType

    rows = [{'osm_id': n['osm_id'], 'lat': n['lat'], 'lon': n['lon'], 'control': n['control']}
            for n in fetch_control_nodes(lat, lon, radius_m)]
    return TypedFrame(pd.DataFrame(rows, columns=['osm_id', 'lat', 'lon', 'control']),
                      DataType.TABLE,
                      meta={'source': 'osm:overpass', 'center': (lat, lon), 'radius_m': radius_m})


def nearest_control(nodes, lat: float, lon: float, max_dist_m: float = 25.0):
    """Nœud de contrôle le plus proche d'un point, ou None au-delà de `max_dist_m`.

    Sert le geste qui motive ce module : confronter une ligne d'arrêt DÉTECTÉE (SAM3, en
    monde) au `highway=stop`/`give_way` DÉCLARÉ par OSM, et rendre l'écart en mètres —
    c'est-à-dire une métrique A/B chiffrée là où il n'y avait qu'un jugement visuel.
    """
    import math
    m_lon = _M_PER_DEG_LAT * math.cos(math.radians(lat))
    best, best_d = None, max_dist_m
    for n in nodes:
        if n.get('lat') is None or n.get('lon') is None:
            continue
        dx = (n['lon'] - lon) * m_lon
        dy = (n['lat'] - lat) * _M_PER_DEG_LAT
        d = math.hypot(dx, dy)
        if d < best_d:
            best, best_d = n, d
    return (best, round(best_d, 2)) if best is not None else None


# ── Manifestes ────────────────────────────────────────────────────────────────────────
# Comme dans `ign_vector` : fonctions SOURCE (paramétrées par un point, pas alimentées par
# une donnée amont) déclarées TRANSFORM faute de valeur `SOURCE` dans `FunctionCategory`.
from wama.common.catalog.function_catalog import (  # noqa: E402
    FunctionCategory, FunctionSpec, ParamSpec, PortSpec, register)
from wama.common.catalog.data_types import DataType  # noqa: E402

_LOC_PARAMS = [
    ParamSpec('lat', 'float', None, -90.0, 90.0, unit='°', description='Latitude WGS84.'),
    ParamSpec('lon', 'float', None, -180.0, 180.0, unit='°', description='Longitude WGS84.'),
    ParamSpec('radius_m', 'float', 300.0, 10.0, 2000.0, unit='m',
              description="Rayon autour du point."),
]

SPEC_CONTROL = register(FunctionSpec(
    key='osm_control_nodes',
    name="Nœuds de contrôle OSM (stop, cédez-le-passage, feux, passages piétons)",
    description="Règles de circulation aux carrefours, depuis OpenStreetMap. Seule source "
                "vectorielle de la SÉMANTIQUE d'intersection : la BD TOPO donne la géométrie "
                "des tronçons mais pas la priorité qui s'y applique. Sert de vérité terrain "
                "aux branches apprises du trafic et aux marquages détectés.",
    category=FunctionCategory.TRANSFORM,
    tags=['geo', 'osm', 'reference', 'intersection', 'ground-truth'],
    inputs=[],
    outputs=[PortSpec('control_nodes', DataType.TABLE,
                      produced_fields=['osm_id', 'lat', 'lon', 'control'],
                      cardinality='many',
                      description='Points de contrôle géolocalisés et leur nature.')],
    params=_LOC_PARAMS,
    cost={'network': True},
    fn=control_nodes_frame,
))

SPEC_ROAD_MAP = register(FunctionSpec(
    key='osm_road_map',
    name='Référentiel de map-matching OSM (mondial)',
    description="Réseau carrossable OSM à la forme du port `road_map`, avec sens unique, "
                "nombre de voies et vitesse limite. Troisième voie d'alimentation du port, "
                "après le CSV de projet et la BD TOPO : la seule qui couvre l'étranger.",
    category=FunctionCategory.TRANSFORM,
    tags=['geo', 'osm', 'reference', 'network', 'map-matching', 'worldwide'],
    inputs=[],
    outputs=[PortSpec('road_map', DataType.ROAD_MAP,
                      produced_fields=['id', 'geometry', 'type', 'nom', 'sens', 'lanes', 'maxspeed'],
                      cardinality='many',
                      description='Polylignes (lat, lon) + attributs de circulation.')],
    params=_LOC_PARAMS,
    cost={'network': True},
    fn=road_map_frame,
))
