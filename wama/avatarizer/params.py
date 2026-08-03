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
    # STANDALONE-ONLY (2026-07-15) : l'audio vient d'AMONT (synthesizer, ou fichier),
    # PAS d'un TTS interne. Le TTS relève du synthesizer ; en pipeline studio, c'est la
    # composition synthesizer -> avatarizer. Donc AUCUN paramètre TTS ici (source unique).
    # Le couple de modes rapide/qualité est MORT (2026-08-03, décision route F2 enfin
    # appliquée à l'UI) : la « qualité » n'a jamais été qu'un alias du toggle CodeFormer —
    # le backend ne lit QUE use_enhancer. quality_mode survit en champ DÉRIVÉ (ETA/data).
    include=["use_enhancer", "bbox_shift"],
    overrides={
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
