"""
Taxonomie des TYPES DE DONNÉE de WAMA Data (pendant de `MEDIA_CATEGORIES` côté média).

Déclarée UNE fois, centralement, pour que sources et fonctions parlent la même langue.
Le sous-typage (`geo_track ⊂ timeseries ⊂ table`) pilote la compatibilité des ports lors
du chaînage. Voir `WAMA_DATA_FUNCTION_CARDS.md` §3.
"""
from __future__ import annotations


class DataType:
    """Constantes de type de donnée (valeurs stables, utilisées dans les PortSpec)."""
    GEO_TRACK = 'geo_track'      # trajectoire géolocalisée temporelle (time, lat, lon[, heading, speed])
    TIMESERIES = 'timeseries'    # time + N colonnes numériques
    SIGNAL = 'signal'            # canal unique échantillonné (time, value[, fs])
    EVENTS = 'events'            # occurrences datées discrètes (time[, duration, type, value])
    TABLE = 'table'              # lignes × colonnes (tabulaire générique)
    COLUMN = 'column'            # une colonne isolée (applicable colonne-à-colonne)
    SCALAR = 'scalar'            # valeur unique / indicateur agrégé
    SECTIONS = 'sections'        # intervalles typés (start, end[, type, id])
    ROAD_MAP = 'road_map'        # polylignes routières de référence (geometry, id[, type])
    DETECTIONS = 'detections'    # objets détectés par frame (frame, bbox, class, track_id…)


# Relation « est-un » : type → ses super-types directs. Un geo_track EST une timeseries
# qui EST une table → un port attendant `table` accepte un `geo_track`.
_SUPERTYPES = {
    DataType.GEO_TRACK: [DataType.TIMESERIES],
    DataType.TIMESERIES: [DataType.TABLE],
    DataType.SIGNAL: [DataType.TIMESERIES],
    DataType.EVENTS: [DataType.TABLE],
    DataType.SECTIONS: [DataType.TABLE],
    DataType.DETECTIONS: [DataType.TABLE],
    DataType.COLUMN: [],
    DataType.SCALAR: [],
    DataType.ROAD_MAP: [],
    DataType.TABLE: [],
}

# Champs canoniques attendus par type (informatif — aide la validation/UI).
CANONICAL_FIELDS = {
    DataType.GEO_TRACK: ['time', 'lat', 'lon'],
    DataType.TIMESERIES: ['time'],
    DataType.SIGNAL: ['time', 'value'],
    DataType.EVENTS: ['time'],
    DataType.SECTIONS: ['start', 'end'],
    DataType.ROAD_MAP: ['geometry', 'id'],
}


def ancestors(data_type):
    """Ensemble des super-types (transitif), y compris le type lui-même."""
    seen, stack = set(), [data_type]
    while stack:
        t = stack.pop()
        if t in seen:
            continue
        seen.add(t)
        stack.extend(_SUPERTYPES.get(t, []))
    return seen


def is_compatible(produced, expected):
    """Une sortie de type `produced` peut alimenter une entrée attendant `expected`
    ssi `expected` est `produced` ou l'un de ses super-types (sous-typage)."""
    return expected in ancestors(produced)


class TypedFrame:
    """Une donnée typée = un `pandas.DataFrame` + son `data_type` + méta optionnelles.
    C'est l'objet qui circule entre les fonctions (représentation runtime de WAMA Data).
    Volontairement minimal : `.df` (les données), `.data_type`, `.meta`, `.fields`."""

    __slots__ = ('df', 'data_type', 'meta')

    def __init__(self, df, data_type, meta=None):
        self.df = df
        self.data_type = data_type
        self.meta = dict(meta or {})

    @property
    def fields(self):
        """Colonnes disponibles (pour la satisfaction des `required_fields`)."""
        try:
            return list(self.df.columns)
        except Exception:
            return []

    def has_fields(self, names):
        cols = set(self.fields)
        return all(n in cols for n in names)

    def __repr__(self):
        n = len(self.df) if self.df is not None else 0
        return f'<TypedFrame {self.data_type} rows={n} fields={self.fields}>'
