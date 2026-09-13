"""
Source COMMUNE des options de voix (TTS) — centralise ce qui était rendu en optgroups par app.

`get_voice_groups(user)` renvoie la structure groupée attendue par WamaParams (optgroups) :
    [ {"group": "<libellé>", "options": [(valeur, libellé), …]}, … ]

5 groupes (ordre reproduisant l'existant Synthesizer) :
  1. Voix par défaut            → default
  2. Voix de référence intégrées → voice_reference_groups() : les `SystemAsset(voice)` de la
                                   médiathèque, groupés par (langue, âge) depuis `attributes`
                                   (depuis le 2026-09-13 — avant : un scan de dossier, et un
                                   repli statique « héritage » quand le dossier était vide)
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

def get_voice_groups(user) -> list[dict]:
    """Groupes de voix (optgroups) pour l'utilisateur, format WamaParams option_groups."""
    groups: list[dict] = [
        {"group": "Voix par défaut", "options": [("default", "Voix par défaut")]},
    ]

    # 2. Voix de référence de la médiathèque. Une médiathèque VIDE donne zéro groupe — plus de
    # repli « héritage » (il offrait des ids plats dont les fichiers n'existaient pas forcément).
    try:
        from wama.common.tts.voice_refs import voice_reference_groups
        refs = voice_reference_groups() or []
    except Exception:
        refs = []
    # `attributes` (par valeur d'option) : ce que l'option PORTE au-delà de sa valeur — ici la
    # langue de la voix, rendue en `data-language` par WamaParams ; les filtres la croisent
    # avec les langues du moteur. Les options restent des paires : `voice_display_options` et
    # tous les lecteurs `for v, l in options` n'ont rien à apprendre.
    for grp in refs:
        voices = grp.get("voices", [])
        groups.append({
            "group": grp.get("group", ""),
            "options": [(v["id"], v["label"]) for v in voices],
            "attributes": {v["id"]: {"language": v["language"]} for v in voices if v.get("language")},
        })

    # 3. Mes voix (clonage) — UserAsset type='voice' ; sa langue si l'utilisateur l'a renseignée.
    try:
        from wama.media_library.models import UserAsset
        customs = list(UserAsset.objects.filter(user=user, asset_type="voice")
                       .values("id", "name", "attributes"))
        groups.append({
            "group": "Mes voix (clonage)",
            "options": [(f"ua_{c['id']}", c["name"]) for c in customs],
            "attributes": {f"ua_{c['id']}": {"language": (c["attributes"] or {}).get("language")}
                           for c in customs if (c["attributes"] or {}).get("language")},
        })
    except Exception:
        pass

    # 4. Bark presets.
    groups.append({"group": "Bark (presets)", "options": list(BARK_PRESETS)})
    return groups


def voice_display_options(user) -> list[tuple[str, str]]:
    """[(valeur, libellé)] de TOUT ce qu'une donnée de voix peut porter — pour AFFICHER.

    Distinct de `get_voice_groups` (l'inventaire PROPOSÉ au select) et plus large que lui :
    les valeurs héritées `cv_<id>` (ancien modèle `CustomVoice`, remplacé par les UserAsset
    `ua_<id>`) ne sont plus offertes pour un nouveau travail, mais des lignes RÉELLES les
    portent encore — et une card doit dire « Voix Fab », pas `cv_1` (constat Fabien,
    card 65, 2026-09-01). Même partage que R43 : *on cesse de proposer une option morte,
    on ne rend pas illisible la donnée qui la porte.*

    Import du modèle synthesizer PARESSEUX et tolérant — même précédent que
    `voice_reference_groups` plus haut : ce module centralise la connaissance des voix, il est
    le seul du substrat autorisé à la chercher là où elle vit.
    """
    plates: list[tuple[str, str]] = []
    for g in get_voice_groups(user):
        plates += [(str(v), l) for v, l in (g.get("options") or [])]
    try:
        from wama.synthesizer.models import CustomVoice
        plates += [(f"cv_{c.pk}", c.name)
                   for c in CustomVoice.objects.filter(user=user)]
    except Exception:
        pass
    return plates
