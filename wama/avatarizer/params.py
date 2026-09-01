"""
Schéma de paramètres Avatarizer — pour l'inspecteur contextuel du volet (compose-panel).

Comme Synthesizer : on GARDE les champs compose existants (id=/radios) et on câble l'inspecteur
contextuel dessus via WamaInspector.initFromSchema (panel read/apply dom_id-aware). dom_id du contexte
panel = id du champ (ou name du groupe radio). voice_preset hérite des voix centralisées
(options_source='voices' — utile si on rend la modale en WamaParams plus tard ; le compose garde ses
optgroups server-rendered pour l'instant). cardSettings (côté JS) lit les data-* du bouton ⚙ de la card.
"""
from wama.common.utils.param_schema import derive_from_model, schema_to_dicts
from wama.avatarizer.models import AvatarJob

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
    include=["text_content", "tts_model", "language", "voice_preset",
             "use_enhancer", "bbox_shift"],
    overrides={
        "text_content": dict(type="textarea", label="Texte à dire", icon="fa-quote-left",
                             show_if="text_content",   # auto-porté : vide (standalone) = masqué
                             dom_id={"item": "settingsTextContent"}, contexts=("item",),
                             help="La relance régénère la voix depuis ce texte."),
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
                             dom_id={"item": "settingsTtsModel"}, contexts=("item",)),
        "language":     dict(type="select", label="Langue", icon="fa-language",
                             show_if="text_content",
                             dom_id={"item": "settingsLanguage"}, contexts=("item",)),
        "voice_preset": dict(type="select", label="Voix", icon="fa-user", chip=True,
                             show_if="text_content", options_source="voices",
                             dom_id={"item": "settingsVoicePreset"}, contexts=("item",)),
        "use_enhancer": dict(type="toggle", label="Amélioration CodeFormer", chip=True,
                             icon="fa-wand-magic-sparkles",
                             help="Restauration faciale haute qualité — légèrement plus lent.",
                             dom_id={"panel": "use_enhancer", "item": "settingsUseEnhancer"},
                             contexts=PANEL_ITEM_BATCH),
        "bbox_shift":   dict(type="range", label="Bbox shift", icon="fa-arrows-up-down", chip=True,
                             dom_id={"panel": "bbox_shift", "item": "settingsBboxShift"},
                             min=-9, max=9, step=1, contexts=PANEL_ITEM_BATCH,
                             help="Décalage vertical de la zone bouche (px). 0 = auto."),
    },
)

PARAMS_JSON = schema_to_dicts(PARAMS)
