"""Vocabulaire des NATURES d'assets de la médiathèque — module PUR (importable sans Django).

Construction A′ (décision Fabien, 2026-09-13 — `MEDIA_STORAGE_TIERING.md §9`) : une nature
d'asset se DÉCLARE ici, en une entrée ; tout le reste en DÉRIVE — `ASSET_TYPES`,
`ALLOWED_EXTENSIONS`, `ASSET_TYPE_CATEGORY`, `TYPE_GROUPS` (models.py), les icônes et les
formats admis de la page médiathèque, `candidate_asset_types`, le schéma d'attributs du
formulaire. Ajouter les objets 3D pour Unreal, une musique avec son tempo, une voix avec sa
langue : **une entrée, zéro migration, zéro colonne**.

Le précédent que ce module copie est `AIModel.capabilities` + `CANONICAL_CAPABILITIES`
(`common/utils/model_capabilities.py`) : un champ JSON `attributes` sur `SystemAsset` et
`UserAsset`, un vocabulaire déclaré en code, des helpers de lecture, une normalisation à la
sauvegarde, un audit. Ni colonnes par nature (A), ni table par nature (B), ni `tags` en texte —
les trois voies écartées et POURQUOI sont consignées au §9.1 ; ne pas les rouvrir.

Frontière avec `common/app_registry.py` : lui porte les CATÉGORIES média (`MEDIA_CATEGORIES`,
les extensions par catégorie, `category_of_path`) — *le domicile des vocabulaires média*. Ici
vivent les TYPES FINS de la médiathèque, qui se RATTACHENT à une catégorie (plusieurs natures →
une catégorie ; `voice`/`audio_music`/`audio_sfx` → `audio`). Un domaine, un fichier.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Tuple

from wama.common.app_registry import MEDIA_CATEGORIES


@dataclass(frozen=True)
class Attr:
    """Un attribut déclaré d'une nature : son TYPE (pour la coercition), sa description (doc
    vivante — même rôle que les valeurs de `CANONICAL_CAPABILITIES`) et, s'il en a un, son
    vocabulaire de valeurs. `choices` vide = valeur libre."""
    kind: str                      # 'str' | 'int' | 'float' | 'bool' | 'list'
    description: str
    choices: Tuple[str, ...] = ()


@dataclass(frozen=True)
class Nature:
    """Ce qu'une nature d'asset DÉCLARE. Tout consommateur en dérive, aucun ne la recopie."""
    label: str
    category: str                  # ∈ MEDIA_CATEGORIES — vérifié à l'import
    extensions: Tuple[str, ...]    # politique d'acceptation (sans point, minuscules)
    icon: str = 'fa-file'          # Font Awesome, page médiathèque
    pivot: str = ''                # format d'interéchange privilégié ('' = aucun)
    attributes: Dict[str, Attr] = field(default_factory=dict)
    #: Lien INTER-MONDES facultatif : le `DataType` (monde Data) qu'un port studio attendrait
    #: pour cette nature. Déclaré, jamais deviné (`ROADMAP §17ter`, trou 3).
    data_type: str = ''


_AGES = ('child', 'adult', 'elderly')
_GENDERS = ('male', 'female')

#: LE vocabulaire. L'ordre est celui des onglets de la médiathèque (et de `ASSET_TYPES`).
ASSET_NATURES: Dict[str, Nature] = {
    'voice': Nature(
        label='Voix', category='audio', icon='fa-microphone', pivot='wav',
        extensions=('wav', 'mp3', 'flac', 'ogg', 'm4a'),  # wama:redondance-ok — politique d'acceptation médiathèque par nature
        attributes={
            'language': Attr('str', "code ISO 639-1 de la langue parlée ('fr', 'en'…)"),
            'age':      Attr('str', "tranche d'âge de la voix", _AGES),
            'gender':   Attr('str', 'genre de la voix', _GENDERS),
            'variant':  Attr('int', 'numéro de variante parmi les voix de même (langue, âge, genre) ; 1 par défaut'),
        },
    ),
    'audio_music': Nature(
        label='Musique', category='audio', icon='fa-music',
        extensions=('mp3', 'wav', 'flac', 'ogg', 'm4a', 'aac'),  # wama:redondance-ok — politique d'acceptation médiathèque par nature
        attributes={
            'bpm': Attr('int', 'tempo en battements par minute'),
            'key': Attr('str', "tonalité ('C', 'Am'…)"),
        },
    ),
    'audio_sfx': Nature(
        label='Bruitage', category='audio', icon='fa-volume-up',
        extensions=('mp3', 'wav', 'ogg', 'flac', 'aiff'),  # wama:redondance-ok — politique d'acceptation médiathèque par nature
    ),
    'image': Nature(
        label='Image', category='image', icon='fa-image',
        extensions=('jpg', 'jpeg', 'png', 'gif', 'webp', 'bmp'),
    ),
    'video': Nature(
        label='Vidéo', category='video', icon='fa-film',
        extensions=('mp4', 'webm', 'mov', 'avi', 'mkv'),  # wama:redondance-ok — politique d'acceptation médiathèque par nature
    ),
    'document': Nature(
        label='Document', category='document', icon='fa-file-alt',
        extensions=('pdf', 'txt', 'docx', 'md', 'csv'),
    ),
    'avatar': Nature(
        label='Avatar', category='image', icon='fa-user-circle',
        extensions=('jpg', 'jpeg', 'png', 'webp'),
    ),
    # Chaîne objets 3D (ROADMAP §17ter) — pivot GLB. Extensions ⊂ `app_registry.OBJECT3D_EXTENSIONS`
    # (`.usd`/`.dae` non admis à l'ingest, assumé). `data_type` : le port studio n'existe pas
    # encore (mesuré 13/09) — la nature le DÉCLARE, le monde Data le créera sous ce nom.
    'object3d': Nature(
        label='Objet 3D', category='3d', icon='fa-cube', pivot='glb',
        extensions=('glb', 'gltf', 'obj', 'fbx', 'stl', 'ply', 'usdz'),
        attributes={
            'format':     Attr('str', "format natif du fichier ('glb', 'fbx'…) — le pivot est glb"),
            'rigged':     Attr('bool', 'squelette d\'animation présent'),
            'units':      Attr('str', 'unité des coordonnées', ('m', 'cm', 'mm')),
            'scale':      Attr('float', "facteur d'échelle vers l'unité déclarée ; 1.0 = déjà à l'échelle"),
            'polygons':   Attr('int', 'nombre de faces (indicatif)'),
            'animations': Attr('list', "noms des animations embarquées"),
        },
        data_type='object_3d',
    ),
}

for _k, _n in ASSET_NATURES.items():
    if _n.category not in MEDIA_CATEGORIES:
        raise ValueError(f"nature {_k!r} : catégorie {_n.category!r} hors de MEDIA_CATEGORIES")
del _k, _n


#: Quelle nature quand un appelant ne dit qu'une CATÉGORIE (`'audio'`, `'image'`…) — c'est le
#: cas des puits du studio (`asset_type` d'un nœud « Sortie ») et de tout mode d'app qui parle
#: en catégories (`accept='audio'`). Déclaré, pas déduit de l'ordre du dict : `voice` est la
#: première nature audio, et une musique convertie n'est pas une voix. Mesuré 13/09 : le
#: nocturne du studio écrivait `asset_type='audio'` tel quel — d'où une ligne hors vocabulaire.
CATEGORY_DEFAULT: Dict[str, str] = {
    'audio': 'audio_music', 'image': 'image', 'video': 'video',
    'document': 'document', '3d': 'object3d',
}
for _c, _t in CATEGORY_DEFAULT.items():
    if _t not in ASSET_NATURES or ASSET_NATURES[_t].category != _c:
        raise ValueError(f"CATEGORY_DEFAULT[{_c!r}] = {_t!r} n'est pas une nature de cette catégorie")
del _c, _t


def resolve_asset_type(value: str, filename: str = '') -> str:
    """La NATURE que désigne `value` : une nature telle quelle ; une catégorie → sa nature par
    défaut (ou, si `filename` est donné, la première nature de la catégorie qui ADMET cette
    extension, le défaut en tête) ; sinon `ValueError` qui cite le vocabulaire — jamais un
    alias écrit en base."""
    v = (value or '').strip()
    if v in ASSET_NATURES:
        return v
    if v in CATEGORY_DEFAULT:
        defaut = CATEGORY_DEFAULT[v]
        ext = filename.rsplit('.', 1)[-1].lower() if '.' in (filename or '') else ''
        if ext:
            for k in [defaut] + [k for k in ASSET_NATURES if k != defaut]:
                n = ASSET_NATURES[k]
                if n.category == v and ext in n.extensions:
                    return k
        return defaut
    raise ValueError(f"asset_type {v!r} : ni une nature ({', '.join(ASSET_NATURES)}) "
                     f"ni une catégorie ({', '.join(CATEGORY_DEFAULT)})")


# ── Lecture (dérivée — les consommateurs passent par ici) ────────────────────────────────
def nature_of(asset_type: str) -> Nature:
    """La nature d'un `asset_type`, ou `KeyError` : une valeur hors vocabulaire n'est pas un
    asset (cas vécu : `'audio'` — une CATÉGORIE écrite à la place d'un type, §9.2)."""
    return ASSET_NATURES[asset_type]


def attribute_schema(asset_type: str) -> Dict[str, Dict[str, Any]]:
    """Le schéma d'attributs d'une nature, sérialisable — c'est ce depuis quoi un formulaire
    se REND (même geste que `param_schema` → `WamaParams` pour les réglages d'app)."""
    return {k: {'kind': a.kind, 'description': a.description, 'choices': list(a.choices)}
            for k, a in nature_of(asset_type).attributes.items()}


def is_canonical_attribute(asset_type: str, key: str) -> bool:
    """Audit : `key` est-il déclaré pour cette nature ? (jumeau d'`is_canonical_key`)."""
    return key in ASSET_NATURES.get(asset_type, Nature('', 'image', ())).attributes


def natures_as_json() -> Dict[str, Dict[str, Any]]:
    """La déclaration entière, sérialisable pour la page médiathèque : icône, formats admis,
    libellé, catégorie, schéma. Le JS n'a plus AUCUNE table à recopier."""
    return {k: {'label': n.label, 'category': n.category, 'icon': n.icon, 'pivot': n.pivot,
                'extensions': list(n.extensions), 'attributes': attribute_schema(k)}
            for k, n in ASSET_NATURES.items()}


# ── Normalisation à la SAUVEGARDE (jumeau de `normalize_capabilities`) ────────────────────
_COERCE = {
    'str':   lambda v: str(v).strip(),
    'int':   lambda v: int(v),
    'float': lambda v: float(v),
    'bool':  lambda v: v if isinstance(v, bool) else str(v).strip().lower() in ('1', 'true', 'yes', 'oui'),
    'list':  lambda v: list(v) if isinstance(v, (list, tuple)) else [s.strip() for s in str(v).split(',') if s.strip()],
}


def normalize_attributes(asset_type: str, attrs: Dict[str, Any] | None) -> Dict[str, Any]:
    """Rend un NOUVEAU dict, coercé sur la déclaration de la nature.

    - `asset_type` hors vocabulaire → `ValueError` (on refuse d'écrire un alias) ;
    - clé déclarée : valeur coercée au `kind` (`'1'` → `1`), et si un vocabulaire de valeurs est
      déclaré, une valeur hors vocabulaire est REFUSÉE (`ValueError`) — une nature qui déclare
      ses valeurs ne tolère pas leurs variantes, sinon aucun filtre ne les retrouve ;
    - clé inconnue : CONSERVÉE telle quelle (jamais de perte silencieuse — même règle que
      `normalize_capabilities`) ;
    - valeur `None` ou `''` : la clé est retirée (absent = non renseigné, pas « vide »).
    """
    nature = nature_of(asset_type)          # KeyError → on le dit en ValueError, avec le mot juste
    out: Dict[str, Any] = {}
    for key, value in (attrs or {}).items():
        if value is None or value == '':
            continue
        spec = nature.attributes.get(key)
        if spec is None:
            out[key] = value
            continue
        try:
            value = _COERCE[spec.kind](value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{asset_type}.{key} : {value!r} n'est pas un {spec.kind}") from exc
        if spec.choices and value not in spec.choices:
            raise ValueError(f"{asset_type}.{key} : {value!r} ∉ {spec.choices}")
        out[key] = value
    return out


# ── UNE porte de compatibilité (jumeau serveur de `WamaInputMatch.accepts(caps, el)`) ─────
COMPATIBLE, WARNING, INCOMPATIBLE = 'compatible', 'warning', 'incompatible'


@dataclass(frozen=True)
class AssetSpec:
    """Ce qu'un CONSOMMATEUR déclare accepter — un nœud studio, un moteur, un slot d'app.

    `category` / `asset_types` : le premier filtre (existe déjà partout sous forme de catégorie).
    `require` : attributs EXIGÉS (valeur, ou tuple de valeurs admises) → sinon INCOMPATIBLE.
    `prefer`  : attributs SOUHAITÉS → sinon WARNING (compatible, avec avertissement).
    Trois états, jamais « caché » : c'est la règle des filtres voix/langue
    (`INPUT_MODEL_MATCHING §6.7`), appliquée à toute nature."""
    category: str = ''
    asset_types: Tuple[str, ...] = ()
    require: Dict[str, Any] = field(default_factory=dict)
    prefer: Dict[str, Any] = field(default_factory=dict)


def _matches(expected: Any, actual: Any) -> bool:
    if isinstance(expected, (tuple, list, set, frozenset)):
        return actual in expected
    return actual == expected


def asset_accepts(spec: AssetSpec, asset_type: str, attributes: Dict[str, Any] | None) -> Tuple[str, str]:
    """Rend `(état, raison)` — la raison NOMME ce qui manque, pour être affichée telle quelle."""
    nature = ASSET_NATURES.get(asset_type)
    if nature is None:
        return INCOMPATIBLE, f"type d'asset inconnu : {asset_type}"
    if spec.asset_types and asset_type not in spec.asset_types:
        return INCOMPATIBLE, f"attend {', '.join(spec.asset_types)}, reçoit {asset_type}"
    if spec.category and nature.category != spec.category:
        return INCOMPATIBLE, f"attend un média {spec.category}, reçoit {nature.category}"
    attrs = attributes or {}
    for key, expected in spec.require.items():
        if key not in attrs:
            return INCOMPATIBLE, f"{key} non renseigné"
        if not _matches(expected, attrs[key]):
            return INCOMPATIBLE, f"{key} = {attrs[key]!r}, attendu {expected!r}"
    for key, expected in spec.prefer.items():
        if key not in attrs or not _matches(expected, attrs[key]):
            return WARNING, f"{key} : {attrs.get(key, 'non renseigné')!r}, préféré {expected!r}"
    return COMPATIBLE, ''
