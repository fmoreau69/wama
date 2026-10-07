"""
Schéma de paramètres Avatarizer — pour l'inspecteur contextuel du volet (compose-panel).

Comme Synthesizer : on GARDE les champs compose existants (id=/radios) et on câble l'inspecteur
contextuel dessus via WamaInspector.initFromSchema (panel read/apply dom_id-aware). dom_id du contexte
panel = id du champ (ou name du groupe radio). voice_preset hérite des voix centralisées
(options_source='voices' — utile si on rend la modale en WamaParams plus tard ; le compose garde ses
optgroups server-rendered pour l'instant). cardSettings (côté JS) lit les data-* du bouton ⚙ de la card.
"""
from wama.common.utils.auto_model import intent_param
from wama.common.utils.param_schema import derive_from_model, schema_to_dicts
from wama.avatarizer.models import AvatarJob
from wama.avatarizer.utils.model_config import ANIMATION_SPEC

PANEL = ("panel",)
PANEL_ITEM = ("panel", "item")   # P1 : la MODALE est générée par WamaParams (IDs legacy via dom_id)
PANEL_ITEM_BATCH = ("panel", "item", "batch")   # + modale de LOT (context='batch' → batch_update)

PARAMS = derive_from_model(
    AvatarJob,
    # PIPELINE DÉRIVÉ (2026-08-28, fin du standalone-only du 2026-07-15) : l'entrée peut
    # être un TEXTE — l'app enchaîne alors TTS (brique commune service_client + voix du
    # synthesizer) puis animation. Le mode n'est pas un réglage : il se DÉRIVE des entrées
    # (MODES_QUEUE_UX §2bis, précédent imager). Les champs TTS ne s'affichent que sur un
    # job porteur de texte (`show_if='text_content'` — un job standalone n'en a jamais).
    # Le couple de modes rapide/qualité est MORT (2026-08-03, décision route F2 enfin
    # appliquée à l'UI) : la « qualité » n'a jamais été qu'un alias du toggle CodeFormer —
    # le backend ne lit QUE use_enhancer. quality_mode survit en champ DÉRIVÉ (ETA/data).
    # ⚠ ORDRE : `tts_model` reste le PREMIER select `catalog` — `auto_model.catalog_field`
    # rend le premier, et le tirage du moteur TTS du worker (`app_id='avatarizer'`) lit SON
    # domaine. `animation_model` vient après, et son tirage passe un `spec` explicite.
    include=["text_content", "tts_model", "quality_intent", "language", "voice_preset",
             "animation_model", "use_enhancer", "bbox_shift"],
    overrides={
        # MODÈLE D'ANIMATION (2026-10-03) : les modèles `lip-sync` de l'avatarizer, au
        # catalogue — MuseTalk (photo), TalkingHead (avatar 3D riggé), et tout modèle qui s'y
        # ajoutera, sans retoucher ce schéma. « auto » = le modèle se tire d'après l'avatar
        # fourni (comportement d'avant, resté le défaut).
        # `options_auto="silent"` : PAS de prévision sous le select. Le tirage dépend de
        # l'avatar de CHAQUE élément, que la prévision ne connaît pas — elle annoncerait le
        # modèle le plus léger (TalkingHead) à quelqu'un qui a posé une photo. *La prévision
        # doit dire la vérité ou se taire* ; l'aide ci-dessous dit la règle à sa place.
        "animation_model": dict(
            type="select", label="Modèle d'animation", icon="fa-film", chip=True,
            help_source="avatarizer",
            help_fallback={"auto": "Choisi d'après l'avatar fourni : une photo est animée par "
                                   "MuseTalk, un avatar 3D (.glb) par TalkingHead."},
            # Domaine par TÂCHE, déclaré UNE fois (`model_config.ANIMATION_SPEC`, que le tirage
            # du worker lit aussi) ; valeurs = clés de catalogue (route F4b ⑤, 2026-10-07).
            options_source="catalog",
            options_query=ANIMATION_SPEC,
            options_auto="silent",
            dom_id={"panel": "animation_model", "item": "settingsAnimationModel",
                    "batch": "batchSettingsAnimationModel"},
            contexts=PANEL_ITEM_BATCH,
            # Ce que chaque réglage PÉRIME (`Param.stales`, 2026-10-05) : `ProcessSpec.watched`
            # s'en dérive (function_specs.py n'y garde que les champs hors schéma).
            stales=("animate",)),
        "text_content": dict(type="textarea", label="Texte à dire", icon="fa-quote-left",
                             show_if="text_content",   # auto-porté : vide (standalone) = masqué
                             dom_id={"item": "settingsTextContent"}, contexts=("item",),
                             help="La relance régénère la voix depuis ce texte.",
                             stales=("speak",)),
        # Options tirées du CATALOGUE (route F4b ②, 2026-09-01) — OBLIGATOIRE ici, pas
        # optionnel : `AvatarJob.tts_model` a perdu son `choices=` dans le même geste, donc
        # `derive_from_model` ne peut plus fournir la moindre option. Sans cette déclaration
        # le select de la modale serait VIDE — et un select vide ne lève pas, il ne propose
        # rien. La requête est la même que celle du synthesizer, par CAPACITÉ : c'est le
        # même parc, et l'avatarizer n'en possède aucun moteur.
        "tts_model":    dict(type="select", label="Modèle TTS", icon="fa-microchip", chip=True,
                             show_if="text_content", help_source="synthesizer",
                             options_source="catalog",
                             options_query={"task": "text-to-speech"},
                             # « auto » + prévision (brique commune auto_model, 2026-09-02)
                             # — le lancement résout dans workers.py.
                             options_auto=True,
                             dom_id={"item": "settingsTtsModel"}, contexts=("item",),
                             stales=("speak",)),
        # Curseur de qualité du tirage « auto » — mêmes conditions de visibilité que le
        # select sur lequel il pèse (job porteur de texte ET modèle « auto »).
        "quality_intent": intent_param(
            dom_id={"item": "settingsQualityIntent"}, contexts=("item",),
            show_if={"field": "tts_model", "equals": "auto"}, stales=("speak",),
        ),
        "language":     dict(type="select", label="Langue", icon="fa-language",
                             show_if="text_content",
                             dom_id={"item": "settingsLanguage"}, contexts=("item",),
                             stales=("speak",)),
        "voice_preset": dict(type="select", label="Voix", icon="fa-user", chip=True,
                             show_if="text_content", options_source="voices",
                             dom_id={"item": "settingsVoicePreset"}, contexts=("item",),
                             stales=("speak",)),
        "use_enhancer": dict(type="toggle", label="Amélioration CodeFormer", chip=True,
                             icon="fa-wand-magic-sparkles",
                             help="Restauration faciale haute qualité — légèrement plus lent. "
                                  "Photo animée seulement : sans effet sur un avatar 3D.",
                             dom_id={"panel": "use_enhancer", "item": "settingsUseEnhancer"},
                             contexts=PANEL_ITEM_BATCH, stales=("enhance",)),
        "bbox_shift":   dict(type="range", label="Bbox shift", icon="fa-arrows-up-down", chip=True,
                             dom_id={"panel": "bbox_shift", "item": "settingsBboxShift"},
                             min=-10, max=10, step=1, contexts=PANEL_ITEM_BATCH,
                             help="Décalage vertical de la zone bouche (px). 0 = auto. "
                                  "Photo animée seulement : sans effet sur un avatar 3D.",
                             stales=("animate",)),
    },
)

PARAMS_JSON = schema_to_dicts(PARAMS)
