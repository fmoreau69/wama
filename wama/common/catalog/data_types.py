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
    # ── LE type « portion de temps bornée » — universel, tous domaines ────────────────────────
    # Renommé depuis `SECTIONS`/'sections' le 2026-08-20 : « section » est connoté routier, or
    # WAMA Data doit rester universel. « segment » l'est (audio, vidéo, texte, séries), et surtout
    # il est DÉJÀ le vocabulaire de WAMA — le Transcriber manipule des segments (début, fin, texte,
    # locuteur) et sa page de correction les édite. Une transcription EST donc une collection de
    # segments au sens de ce type : le même outillage (segmenter, calculer par segment, exporter
    # par segment) s'applique sans traduction. Ce n'est pas un choix de nom, c'est une unification.
    #
    # ⚠ `segment` est le MODÈLE, jamais le mot montré à l'utilisateur (arbitrage Fabien, 2026-08-22).
    # L'UI parle de **situation** et d'**état** — deux présentations métier du même type technique :
    #   • « situation » : fenêtre porteuse de sens, ancrée sur un événement ;
    #   • « état »      : plage de valeur constante d'un signal catégoriel (run-length) ;
    #   • « section »   : portion de parcours — un cas d'usage de plus, côté conduite.
    # Un seul type, plusieurs producteurs, plusieurs libellés. C'est la règle métadonnée-driven
    # habituelle : le vocabulaire métier vit dans la déclaration, pas dans le type.
    # ⚠ Corollaire (note PROJECT_STATUS du 2026-08-05, vérifiée le 22/08) : ne JAMAIS nommer un
    # modèle Django `Segment` — « segment » est déjà pris par l'anonymizer au sens SPATIAL (tâche
    # YOLO de segmentation d'image), sens sans rapport avec celui-ci. L'avertissement miroir vit
    # sur la clé `task` de `common/utils/model_capabilities.py` (2026-08-28) : les deux
    # vocabulaires ne se comparent jamais par égalité de nom — un port parle en DataType, un
    # modèle en task, la traduction se DÉCLARE dans le binding.
    # Aucune valeur n'était persistée : renommage sans migration.
    SEGMENTS = 'segments'        # portions de temps bornées (start, end[, type, id, …attributs])
    ROAD_MAP = 'road_map'        # polylignes routières de référence (geometry, id[, type])
    DETECTIONS = 'detections'    # objets détectés par frame (frame, bbox, class, track_id…)
    DEPTH_MAP = 'depth_map'      # raster HxW de profondeur métrique (mètres) — non tabulaire


# Relation « est-un » : type → ses super-types directs. Un geo_track EST une timeseries
# qui EST une table → un port attendant `table` accepte un `geo_track`.
_SUPERTYPES = {
    DataType.GEO_TRACK: [DataType.TIMESERIES],
    DataType.TIMESERIES: [DataType.TABLE],
    DataType.SIGNAL: [DataType.TIMESERIES],
    DataType.EVENTS: [DataType.TABLE],
    DataType.SEGMENTS: [DataType.TABLE],
    DataType.DETECTIONS: [DataType.TABLE],
    DataType.COLUMN: [],
    DataType.SCALAR: [],
    DataType.ROAD_MAP: [],
    DataType.DEPTH_MAP: [],   # raster : pas un sous-type de table
    DataType.TABLE: [],
}

# Champs canoniques attendus par type (informatif — aide la validation/UI).
CANONICAL_FIELDS = {
    DataType.GEO_TRACK: ['time', 'lat', 'lon'],
    DataType.TIMESERIES: ['time'],
    DataType.SIGNAL: ['time', 'value'],
    DataType.EVENTS: ['time'],
    DataType.SEGMENTS: ['start', 'end'],
    DataType.ROAD_MAP: ['geometry', 'id'],
}


#: Valeurs de type ANCIENNES pouvant subsister en base. `UserFunction.inputs`/`.outputs` sont des
#: `JSONField` contenant des `PortSpec` sérialisés : un `data_type` y est donc PERSISTÉ, et une
#: ligne créée avant le 2026-08-20 peut porter `'sections'`.
#:
#: Pourquoi une normalisation à la lecture plutôt qu'une migration de données : les migrations
#: numérotées ne sont PAS versionnées (`.gitignore:13` → `**/migrations/0*.py`). Une migration
#: corrigerait cette base-ci et n'arriverait jamais sur une autre installation — le correctif doit
#: donc vivre dans le CODE. Ce n'est pas une juxtaposition de deux noms vivants (interdite) : c'est
#: la lecture d'une donnée héritée, ramenée au vocabulaire courant à l'entrée.
LEGACY_TYPE_ALIASES = {
    'sections': DataType.SEGMENTS,   # renommé le 2026-08-20 (« section » était connoté routier)
}


def normalize_type(data_type):
    """Ramène une valeur éventuellement héritée au vocabulaire courant. Idempotent."""
    return LEGACY_TYPE_ALIASES.get(data_type, data_type)


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
    ssi `expected` est `produced` ou l'un de ses super-types (sous-typage).

    Les deux valeurs passent par `normalize_type` : c'est le POINT DE PASSAGE UNIQUE de
    l'appariement de ports, donc le seul endroit où brancher la lecture des valeurs héritées
    (un `PortSpec` venant d'un `UserFunction` en base peut porter un ancien nom).
    """
    return normalize_type(expected) in ancestors(normalize_type(produced))


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
