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
    vocabulaire de valeurs. `choices` vide = valeur libre.

    `label` et `labels` sont ce qu'on AFFICHE : le nom du champ, et le nom de chaque valeur
    (`'fr'` → `Français`). Ils vivent ICI, avec la déclaration, et nulle part ailleurs — c'est
    le même partage que `choices` : *une nature qui déclare ses valeurs déclare comment on les
    lit*. Jusqu'au 2026-09-27 ces tables vivaient dans la brique TTS (`tts/voice_refs.py`), qui
    était donc seule à savoir dire « Français — Adulte — Homme » ; la médiathèque, qui STOCKE
    ces attributs, ne les affichait pas du tout.
    """
    kind: str                      # 'str' | 'int' | 'float' | 'bool' | 'list'
    description: str
    choices: Tuple[str, ...] = ()
    label: str = ''                # libellé du CHAMP ('' → la clé telle quelle)
    labels: Dict[str, str] = field(default_factory=dict)   # libellé de chaque VALEUR


@dataclass(frozen=True)
class Nature:
    """Ce qu'une nature d'asset DÉCLARE. Tout consommateur en dérive, aucun ne la recopie."""
    label: str
    category: str                  # ∈ MEDIA_CATEGORIES — vérifié à l'import
    extensions: Tuple[str, ...]    # politique d'acceptation (sans point, minuscules)
    icon: str = 'fa-file'          # Font Awesome, page médiathèque
    pivot: str = ''                # format d'interéchange privilégié ('' = aucun)
    #: Formats ADMIS À L'AJOUT à condition d'être CONVERTIS vers le `pivot` (2026-09-30). Le
    #: fichier stocké reste toujours dans `extensions` : ce qui entre en webm (l'enregistrement
    #: au micro d'un navigateur) est rangé en wav. Le `pivot` était déclaré depuis A′ sans aucun
    #: consommateur ; sans lui, « Enregistrer ma voix » était refusé depuis février.
    to_pivot: Tuple[str, ...] = ()
    #: La nature s'AJOUTE aussi par le micro (2026-09-30) : la card d'ajout de la médiathèque —
    #: page ET fenêtre commune — montre alors « Enregistrer ». L'enregistrement (webm) entre par
    #: `to_pivot`. Déclaré par nature, jamais déduit de la catégorie : une musique ne s'enregistre
    #: pas au micro de l'ordinateur, une voix de clonage si.
    recordable: bool = False
    #: Ce que la nature porte d'une PERSONNE, dit en clair (« la voix d'une personne ») — ou vide.
    #: Non vide, PARTAGER un tel asset au-delà du privé demande le consentement de celui qui
    #: partage (décision de Fabien, 2026-09-30 : « il faut juste le prévenir et lui faire valider
    #: le consentement ; sinon il annule ; il peut retirer le partage à tout moment »). Le service
    #: de partage commun le lit par `UserAsset.share_consent_subject()`, jamais par nature.
    personal: str = ''
    attributes: Dict[str, Attr] = field(default_factory=dict)
    #: Lien INTER-MONDES facultatif : le `DataType` (monde Data) qu'un port studio attendrait
    #: pour cette nature. Déclaré, jamais deviné (`ROADMAP §17ter`, trou 3).
    data_type: str = ''


_AGES = ('child', 'adult', 'elderly')
_GENDERS = ('male', 'female')

#: Les libellés des valeurs de la nature `voice`. ⚠ DOMICILE UNIQUE depuis le 2026-09-27 :
#: `common/tts/voice_refs.py` les lit d'ici (ses `_LANG_CODE_TO_LABEL`/`_AGE_TO_LABEL`/
#: `_GENDER_TO_LABEL` en étaient la souche) et la page médiathèque les reçoit par
#: `natures_as_json()`. Ajouter une langue = une ligne, et les deux surfaces suivent.
_LANGUAGE_LABELS: Dict[str, str] = {
    'fr': 'Français', 'en': 'English', 'es': 'Español',
    'de': 'Deutsch', 'it': 'Italiano', 'pt': 'Português',
    'ja': '日本語', 'zh': '中文', 'ko': '한국어',
    'nl': 'Nederlands', 'pl': 'Polski', 'ru': 'Русский',
}
_AGE_LABELS: Dict[str, str] = {'child': 'Enfant', 'adult': 'Adulte', 'elderly': 'Senior'}
_GENDER_LABELS: Dict[str, str] = {'male': 'Homme', 'female': 'Femme'}

#: Les TROIS natures audio acceptent les MÊMES fichiers (2026-09-19, question de Fabien :
#: « pourquoi un bruitage ne peut-il pas être un .aac ? »). Les listes divergeaient par
#: héritage d'un littéral (aac pour la musique seule, aiff pour le bruitage seul), pas par
#: décision : un rôle audio se choisit ou se déclare (`result_role`), il ne se déduit pas de
#: l'extension — et la conversion universelle du converter rend tout format joignable.
AUDIO_EXTENSIONS = ('wav', 'mp3', 'flac', 'ogg', 'm4a', 'aac', 'aiff')

#: Ce qu'une nature PARLÉE (voix, parole) admet en le convertissant vers son pivot `wav` :
#: l'enregistrement d'un navigateur (`MediaRecorder` → webm/opus) et les formats de dictaphone.
SPEECH_TO_PIVOT = ('webm', 'weba', 'opus', 'mka', 'wma', 'amr')

#: LE vocabulaire. L'ordre est celui des onglets de la médiathèque (et de `ASSET_TYPES`).
ASSET_NATURES: Dict[str, Nature] = {
    'voice': Nature(
        label='Voix', category='audio', icon='fa-microphone', pivot='wav',
        extensions=AUDIO_EXTENSIONS, to_pivot=SPEECH_TO_PIVOT, recordable=True,
        personal="la voix d'une personne",
        attributes={
            'language': Attr('str', "code ISO 639-1 de la langue parlée ('fr', 'en'…)",
                             label='Langue', labels=_LANGUAGE_LABELS),
            'age':      Attr('str', "tranche d'âge de la voix", _AGES,
                             label='Âge', labels=_AGE_LABELS),
            'gender':   Attr('str', 'genre de la voix', _GENDERS,
                             label='Genre', labels=_GENDER_LABELS),
            'variant':  Attr('int', 'numéro de variante parmi les voix de même (langue, âge, genre) ; 1 par défaut',
                             label='Variante'),
        },
    ),
    # PAROLE ENREGISTRÉE (2026-09-28) — une réunion, un entretien : ce qu'on TRANSCRIT, et en
    # particulier les jeux d'ÉVALUATION des moteurs ASR (SUMM-RE, `WAMA_QUALITE §9bis`). Pas une
    # `voice` : celle-ci est une voix de CLONAGE du synthétiseur, et une réunion de 21 min rangée
    # là remonterait dans ses menus de voix (`voice_reference_groups` interroge `voice`).
    'speech': Nature(
        label='Parole enregistrée', category='audio', icon='fa-comments', pivot='wav',
        extensions=AUDIO_EXTENSIONS, to_pivot=SPEECH_TO_PIVOT, recordable=True,
        personal='la parole de personnes enregistrées',
        attributes={
            'language': Attr('str', "code ISO 639-1 de la langue parlée ('fr', 'en'…) — la plus "
                                    "parlée si l'enregistrement en mêle plusieurs",
                             label='Langue', labels=_LANGUAGE_LABELS),
            # Un enregistrement peut CHANGER de langue (2026-09-29, jeux FLEURS-CS) : toutes ses
            # langues, la plus parlée d'abord, séparées par des virgules.
            'languages': Attr('str', "toutes les langues parlées ('fr,en'…)", label='Langues'),
            'speakers': Attr('int', 'nombre de locuteurs', label='Locuteurs'),
            'corpus':   Attr('str', "corpus d'origine (clé de son manifeste `dataset`)", label='Corpus'),
            # Liste OUVERTE : chaque corpus nomme ses partitions (`example`, `validation`…).
            'split':    Attr('str', 'partition du corpus (test, dev, train…)', label='Partition'),
            'recording': Attr('str', "identifiant de l'enregistrement dans son corpus",
                              label='Enregistrement'),
        },
    ),
    'audio_music': Nature(
        label='Musique', category='audio', icon='fa-music',
        extensions=AUDIO_EXTENSIONS,
        attributes={
            'bpm': Attr('int', 'tempo en battements par minute'),
            'key': Attr('str', "tonalité ('C', 'Am'…)"),
        },
    ),
    'audio_sfx': Nature(
        label='Bruitage', category='audio', icon='fa-volume-up',
        extensions=AUDIO_EXTENSIONS,
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
        # `srt`/`vtt` (2026-09-28) : une transcription horodatée — les RÉFÉRENCES des jeux
        # d'évaluation ASR, que le transcriber lit déjà (`transcript_documents`).
        extensions=('pdf', 'txt', 'docx', 'md', 'csv', 'srt', 'vtt'),
    ),
    'avatar': Nature(
        label='Avatar', category='image', icon='fa-user-circle',
        extensions=('jpg', 'jpeg', 'png', 'webp'),
    ),
    # Chaîne objets 3D (ROADMAP §17ter) — pivot GLB. Extensions ⊂ `app_registry.OBJECT3D_EXTENSIONS`
    # (`.usd`/`.dae` non admis à l'ingest, assumé). ⚠ Cette nature a porté `data_type='object_3d'`
    # du 13/09 au 17/09 : le monde Data avait créé un type sous ce nom pour que le port studio
    # ait une sortie. Retiré (décision de Fabien) — un objet 3D est un fichier MÉDIA, il n'a pas
    # de jumeau côté données ; le port nomme la nature.
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
            # Visage animable (2026-09-30) — MESURÉS dans le fichier par `media_probe` (noms des
            # formes, `extras.targetNames`), jamais saisis : un avatar parlant est un objet 3D qui
            # porte ces attributs, pas une nature à part (décision de Fabien). Présents seulement
            # si le jeu est COMPLET — un jeu partiel ne fait pas bouger la bouche.
            'face_rig':   Attr('str', "formes du visage : 'arkit' = les 52 blendshapes ARKit "
                                      "(expressions, clignements, regard)", ('arkit',),
                               label='Visage', labels={'arkit': 'ARKit (52 formes)'}),
            'visemes':    Attr('str', "formes de la bouche qui parle : 'oculus' = les 15 visèmes Oculus",
                               ('oculus',), label='Visèmes', labels={'oculus': 'Oculus (15)'}),
        },
        # ⚠ PAS de `data_type` (retiré le 2026-09-17) : un objet 3D est un fichier MÉDIA, sa
        # nature est `3d`. Le champ reste pour les natures qui portent VRAIMENT une donnée du
        # monde Data (un `.csv` rangé en médiathèque → `table`), jamais pour créer un jumeau.
    ),
}

for _k, _n in ASSET_NATURES.items():
    if _n.category not in MEDIA_CATEGORIES:
        raise ValueError(f"nature {_k!r} : catégorie {_n.category!r} hors de MEDIA_CATEGORIES")
    if _n.to_pivot and _n.pivot not in _n.extensions:
        # Convertir « vers le pivot » n'a de sens que si le pivot est lui-même un format stocké.
        raise ValueError(f"nature {_k!r} : `to_pivot` déclaré sans pivot admis ({_n.pivot!r})")
    if _n.recordable and 'webm' not in _n.to_pivot:
        # Un navigateur enregistre en webm : une nature enregistrable doit savoir le convertir.
        raise ValueError(f"nature {_k!r} : `recordable` sans `webm` dans `to_pivot`")
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
    return {k: {'kind': a.kind, 'description': a.description, 'choices': list(a.choices),
                'label': a.label or k, 'labels': dict(a.labels)}
            for k, a in nature_of(asset_type).attributes.items()}


def is_canonical_attribute(asset_type: str, key: str) -> bool:
    """Audit : `key` est-il déclaré pour cette nature ? (jumeau d'`is_canonical_key`)."""
    return key in ASSET_NATURES.get(asset_type, Nature('', 'image', ())).attributes


def natures_as_json() -> Dict[str, Dict[str, Any]]:
    """La déclaration entière, sérialisable pour la page médiathèque : icône, formats admis,
    libellé, catégorie, schéma. Le JS n'a plus AUCUNE table à recopier."""
    # `extensions` = ce que le geste d'AJOUT admet : les formats stockés tels quels, puis ceux
    # que le service convertit vers le pivot (`to_pivot`). Le JS n'a pas à connaître la nuance.
    return {k: {'label': n.label, 'category': n.category, 'icon': n.icon, 'pivot': n.pivot,
                'extensions': list(n.extensions) + [e for e in n.to_pivot if e not in n.extensions],
                'recordable': n.recordable,
                'attributes': attribute_schema(k)}
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
