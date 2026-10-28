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
  3. Mes voix (clonage)         → UserAsset(asset_type='voice') dont je suis propriétaire (ua_<id>) ;
                                  TOUJOURS émis, même vide (la page du synthesizer y insère la
                                  voix qu'on vient de cloner)
  3bis. Voix partagées          → celles qu'on m'a partagées, libellées avec leur propriétaire
                                  (depuis le 2026-09-21 — avant, le sélecteur ne montrait QUE les
                                  miennes ; décision de Fabien : « une voix partagée doit être
                                  accessible en fonction des droits de chacun »). Le groupe
                                  n'apparaît pas s'il est vide
  4. Voix propres des moteurs   → un groupe par jeu de modèles du catalogue qui les déclarent
                                  (`capabilities.voices`, 2026-10-28 : Bark, Kokoro, Phonon) ;
                                  chaque option porte les modèles qui la disent (`attributes.models`
                                  → `data-models`)

Le FILTRAGE par modèle (cacher un enregistrement `ua_`/`sa_` si supports_cloning=false, une voix de
moteur sous un modèle qui ne la nomme pas, restreindre les langues) est centralisé côté client par
WamaModelCaps (`voiceFits`, lit AIModel.capabilities) — pas dupliqué ici ; le tirage « auto » reçoit
la même contrainte côté serveur (`voice_refs.voice_draw_constraint`).

Consommé : par les vues (passage JSON au template) et par l'endpoint commun de voix → WamaParams
résout `options_source='voices'` depuis ces groupes. Lève le verrou d'uniformisation du Synthesizer
(les voix n'étaient pas centralisées, seul le filtrage l'était).
"""
from __future__ import annotations

import json

def get_voice_groups(user) -> list[dict]:
    """Groupes de voix (optgroups) pour l'utilisateur, format WamaParams option_groups."""
    # `key` : l'identité STABLE du groupe — le libellé n'est qu'un texte affiché. WamaParams la
    # rend en `data-group-key` sur l'`<optgroup>` (22/09), et c'est par elle qu'un JS d'app
    # retrouve un groupe : la page du synthesizer insère dans « Mes voix » la voix qu'on vient de
    # cloner. Les lecteurs de `group`/`options`/`attributes` n'ont rien à apprendre.
    groups: list[dict] = [
        {"key": "default", "group": "Voix par défaut", "options": [("default", "Voix par défaut")]},
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
            "key": "reference",
            "group": grp.get("group", ""),
            "options": [(v["id"], v["label"]) for v in voices],
            "attributes": {v["id"]: {"language": v["language"]} for v in voices if v.get("language")},
        })

    # 3. Les voix de clonage que l'utilisateur a le DROIT d'employer — les siennes ET celles qui
    # lui sont partagées (Fabien, 2026-09-21). DEUX groupes et non un seul : une voix est une
    # personne, savoir de QUI elle est n'est pas un détail d'affichage. Le lecteur de droits est
    # commun aux deux surfaces (`common/tts/voice_refs.readable_voice_assets`) — le sélecteur ne
    # propose donc jamais ce que la résolution refuserait.
    try:
        from wama.common.tts.voice_refs import readable_voice_assets
        rows = list(readable_voice_assets(user)
                    .values("id", "name", "attributes", "user_id", "user__username"))
        mine = [c for c in rows if c["user_id"] == getattr(user, "id", None)]
        shared = [c for c in rows if c["user_id"] != getattr(user, "id", None)]
        for key, label, batch, with_owner in (("mine", "Mes voix (clonage)", mine, False),
                                              ("shared", "Voix partagées", shared, True)):
            # « Mes voix » est TOUJOURS émis, même vide — la page du synthesizer y insère la voix
            # qu'on vient de cloner ; absent, son JS le recréerait sous un autre libellé et à une
            # autre place. Seul le groupe des voix PARTAGÉES se tait quand il est vide.
            if key == "shared" and not batch:
                continue
            groups.append({
                "key": key,
                "group": label,
                "options": [(f"ua_{c['id']}",
                             f"{c['name']} — {c['user__username']}" if with_owner else c["name"])
                            for c in batch],
                "attributes": {f"ua_{c['id']}": {"language": (c["attributes"] or {}).get("language")}
                               for c in batch if (c["attributes"] or {}).get("language")},
            })
    except Exception:
        pass

    # 4. Les voix PROPRES des moteurs (2026-10-28) : posées par `apply_engine_flags` depuis la
    # classe du moteur (Bark, Kokoro, Phonon). Chaque option porte les modèles qui la disent
    # (`data-models`) : le filtre commun ne la montre que sous eux (`WamaModelCaps.voiceFits`). Les
    # préréglages Bark étaient ici une copie de `constants.VOICE_PRESET_CHOICES`, offerte sous TOUT
    # moteur.
    groups.extend(engine_voice_groups(user))
    return groups


def engine_voice_groups(user) -> list[dict]:
    """Les groupes de voix propres aux moteurs — un par JEU de modèles qui disent les mêmes voix.

    Chaque option porte les modèles qui la NOMMENT (`attributes.models`, clés séparées par une
    espace → `data-models`) : la compatibilité se lit au catalogue, sans liste à tenir. Deux
    moteurs qui déclarent les mêmes voix (Kokoro 82M et sa version ONNX, `voices.kokoro_voices`)
    partagent donc UN groupe — sous « auto », où toutes les voix restent offertes, deux groupes
    identiques auraient mis deux fois la même valeur dans le select."""
    try:
        from wama.model_manager.models import AIModel
        rows = (AIModel.objects.catalogue_visible_to(user)
                .filter(capabilities__has_key="voices").order_by("name")
                .values_list("model_key", "name", "capabilities"))
    except Exception:
        return []
    names, voices = {}, {}
    for key, name, caps in rows:
        for v in ((caps or {}).get("voices") or []):
            if isinstance(v, dict) and v.get("value"):
                names[key] = name
                entry = voices.setdefault(v["value"], {"voice": v, "models": []})
                entry["models"].append(key)
    by_models: dict[tuple, list] = {}
    for value, entry in voices.items():
        by_models.setdefault(tuple(entry["models"]), []).append(entry["voice"])
    return [{
        "key": "engine:" + " ".join(models),
        "group": "Voix de " + " · ".join(names[k] for k in models),
        "options": [(v["value"], v.get("label") or v["value"]) for v in group],
        "attributes": {v["value"]: {"models": " ".join(models),
                                    **({"language": v["language"]} if v.get("language") else {})}
                       for v in group},
    } for models, group in by_models.items()]


def voice_groups_json(user) -> str:
    """Les mêmes groupes, prêts à injecter dans un gabarit (`{{ voice_groups_json|safe }}`).

    Une page qui GÉNÈRE son champ de voix (WamaParams + `options_source='voices'`) passe ces
    groupes en `optionsResolver` : le champ est peuplé dès le premier rendu, sans attendre
    l'aller-retour vers `/common/api/voices/` — l'endpoint reste la source qui RECHARGE.
    Repli `[]` : un gabarit ne doit jamais recevoir un JSON invalide, il perdrait TOUT son
    script (l'avatarizer s'en protégeait déjà par `|default:"[]"` côté gabarit).
    """
    try:
        return json.dumps(get_voice_groups(user))
    except Exception:
        return "[]"


def voice_display_options(user) -> list[tuple[str, str]]:
    """[(valeur, libellé)] de TOUT ce qu'une donnée de voix peut porter — pour AFFICHER.

    Distinct de `get_voice_groups` (l'inventaire PROPOSÉ au select) : ce sont les mêmes valeurs
    aplaties. Il ajoutait les valeurs héritées `cv_<id>` (ancien modèle `CustomVoice`) pour
    qu'une card dise « Voix Fab » et pas `cv_1` (constat Fabien, card 65, 2026-09-01) ; le
    préfixe est RETIRÉ le 2026-09-30, sa seule ligne convertie en `ua_` (migration
    synthesizer 0028) — la card le lit donc désormais par son groupe « Mes voix ».
    """
    plates: list[tuple[str, str]] = []
    for g in get_voice_groups(user):
        plates += [(str(v), l) for v, l in (g.get("options") or [])]
    return plates
