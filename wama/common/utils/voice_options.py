"""
Source COMMUNE des options de voix (TTS) — centralise ce qui était rendu en optgroups par app.

`get_voice_groups(user)` renvoie la structure groupée attendue par WamaParams (optgroups) :
    [ {"group": "<libellé>", "options": [(valeur, libellé), …]}, … ]

5 groupes (ordre reproduisant l'existant Synthesizer) :
  1. Voix par défaut            → default
  2. Voix de référence intégrées → scan_voice_refs() (dynamique) ; sinon « héritage » statique
  3. Mes voix (clonage)         → UserAsset(asset_type='voice') de l'utilisateur (ua_<id>)
  4. Bark (presets)             → constantes BARK_PRESETS

Le FILTRAGE par modèle (cacher le clonage ua_/cv_ si supports_cloning=false, restreindre les langues)
est déjà centralisé côté client par WamaModelCaps (lit AIModel.capabilities) — pas dupliqué ici.

Consommé : par les vues (passage JSON au template) et par l'endpoint commun de voix → WamaParams
résout `options_source='voices'` depuis ces groupes. Lève le verrou d'uniformisation du Synthesizer
(les voix n'étaient pas centralisées, seul le filtrage l'était).
"""
from __future__ import annotations

# Presets Bark statiques (indépendants de l'utilisateur).
BARK_PRESETS = [
    ("bark_v2_en_0", "Bark EN Speaker 0"), ("bark_v2_en_1", "Bark EN Speaker 1"),
    ("bark_v2_en_2", "Bark EN Speaker 2"), ("bark_v2_en_3", "Bark EN Speaker 3"),
    ("bark_v2_en_4", "Bark EN Speaker 4"), ("bark_v2_en_5", "Bark EN Speaker 5"),
    ("bark_v2_fr_0", "Bark FR Speaker 0"), ("bark_v2_fr_1", "Bark FR Speaker 1"),
    ("bark_v2_es_0", "Bark ES Speaker 0"), ("bark_v2_de_0", "Bark DE Speaker 0"),
]

# Repli « héritage » si scan_voice_refs() ne renvoie rien (voix non téléchargées).
_HERITAGE = [
    ("male_1", "Voix masculine 1"), ("male_2", "Voix masculine 2"),
    ("female_1", "Voix féminine 1"), ("female_2", "Voix féminine 2"),
]


def get_voice_groups(user) -> list[dict]:
    """Groupes de voix (optgroups) pour l'utilisateur, format WamaParams option_groups."""
    groups: list[dict] = [
        {"group": "Voix par défaut", "options": [("default", "Voix par défaut")]},
    ]

    # 2. Voix de référence intégrées (dynamique) ou repli héritage.
    try:
        from wama.synthesizer.utils.voice_utils import scan_voice_refs
        refs = scan_voice_refs() or []
    except Exception:
        refs = []
    if refs:
        for grp in refs:
            groups.append({
                "group": grp.get("group", ""),
                "options": [(v["id"], v["label"]) for v in grp.get("voices", [])],
            })
    else:
        groups.append({"group": "Voix intégrées (héritage)", "options": list(_HERITAGE)})

    # 3. Mes voix (clonage) — UserAsset type='voice'.
    try:
        from wama.media_library.models import UserAsset
        customs = UserAsset.objects.filter(user=user, asset_type="voice").values("id", "name")
        groups.append({
            "group": "Mes voix (clonage)",
            "options": [(f"ua_{c['id']}", c["name"]) for c in customs],
        })
    except Exception:
        pass

    # 4. Bark presets.
    groups.append({"group": "Bark (presets)", "options": list(BARK_PRESETS)})
    return groups
