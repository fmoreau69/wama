"""
Schéma de paramètres Composer — inspecteur contextuel du volet (compose-panel).

Params éditables per-item : `model` (le type music/sfx en est dérivé) + `duration`, et **format/qualité
de fichier via la BRIQUE COMMUNE** (output_format_params_for_app : domaine audio + early-binding déduits
d'APP_CATALOG). On garde les champs compose existants (id=) ; câblage via initFromSchema (panel dom_id-aware).
cardSettings générique lit les data-model/data-duration de la racine de card.
"""
from wama.common.utils.auto_model import intent_param
from wama.common.utils.param_schema import Param, schema_to_dicts
from wama.common.utils.output_formats import output_format_params_for_app
from wama.composer.utils.model_choice import AUTO_MUSIC, AUTO_SFX, TASKS

PANEL = ("panel",)
PANEL_ITEM = ("panel", "item")
# Batch = ce que la modale de lot POSTE (model/duration/format/qualité) — le prompt reste
# per-item. Modale batch DÉDIÉE (contrat reader, 17/08) rendue de ce schéma.
PANEL_ITEM_BATCH = ("panel", "item", "batch")

PARAMS = [
    # Ordre = ordre de DÉCLARATION (WamaParams déroule la liste). Le PROMPT ouvre la modale
    # (décision Fabien 18/08 : l'intention d'abord, les réglages ensuite) — contexts item
    # seulement, donc l'ordre du VOLET (Modèle → Durée → Format → Qualité) est inchangé.
    Param(name="prompt", type="textarea", label="Prompt", icon="fa-pen",
          dom_id={"item": "settingsPrompt"}, contexts=("item",)),
    # Route F4b (2026-10-01) : les options viennent du CATALOGUE, bornées par la TÂCHE — jamais par
    # la source : un modèle installé depuis le model manager (YuE2, prospecté) entre sans une ligne
    # de code. Valeurs = CLÉS ENTIÈRES (migration des lignes : `utils/model_choice.normalize`).
    # Groupes par tâche (Musique / Ambiances) et un « auto » PAR GROUPE (`auto:<tâche>`) — la
    # décision « pas de 2 modes : grouper côté serveur + un auto par groupe » ; le type
    # musique/bruitage se DÉRIVE du modèle choisi (décision 2026-07-02, pas de switch de type).
    Param(name="model", type="select", label="Modèle", icon="fa-music", chip=True,
          help_source="composer",
          help_fallback={
              AUTO_MUSIC: "Choix automatique : le meilleur modèle MUSIQUE tenant dans la VRAM libre au lancement.",
              AUTO_SFX: "Choix automatique : le meilleur modèle AMBIANCE / BRUITAGE tenant dans la VRAM libre au lancement.",
          },
          dom_id={"panel": "modelSelect", "item": "settingsModel", "batch": "batchSettingsModel"},
          contexts=PANEL_ITEM_BATCH,
          options_source="catalog",
          options_query={"task": ",".join(TASKS)},
          options_group="task", options_auto="group",
          # Les modèles proposés SONT ceux du composer : leurs entrées ouvrent les ports de la card
          # (la partition de YuE2, 2026-10-01) — `app_registry.app_input_ports`.
          options_ports=True,
          default=AUTO_MUSIC),
    # Curseur rapide/qualité commun (chantier C, 2026-09-20) : visible sur les « auto », lu au
    # LANCEMENT par le tirage (`resolve_auto_model` → `item=gen`). Rendu par le renderer commun
    # (volet : même hôte que le modèle ; modale/lot : lu génériquement par WamaParams.read).
    Param(name="quality_intent", dom_id={"panel": "qualityIntent", "item": "settingsQualityIntent",
                                          "batch": "batchSettingsQualityIntent"},
          contexts=PANEL_ITEM_BATCH,
          **intent_param(show_if={"field": "model", "in": [AUTO_MUSIC, AUTO_SFX]})),
    # `default=210` (3:30, la durée d'une chanson — Fabien, 2026-10-04 ; c'était 10 s) : celui du
    # bouton « Réinitialiser » et d'un profil neuf. Sans défaut, un curseur rendu sans valeur se
    # posait au MILIEU de l'échelle (305 s) avec un libellé vide — vu au navigateur le 2026-10-03.
    # Un modèle qui produit moins (MusicGen : 30 s) le BORNE par `cap_from`.
    # `display_format` : « 3:30 » partout où la valeur se lit (curseur, bornes, chip).
    # `default_from` : un audio de travail déposé (cover) PROPOSE sa propre durée.
    Param(name="duration", type="range", label="Durée", icon="fa-clock", min=10, max=600, step=5,
          default=210, unit="s", display_format="duration", chip=True,
          default_from={"port": "work_audio", "property": "duration"},
          dom_id={"panel": "durationSlider", "item": "settingsDuration",
                  "batch": "batchSettingsDuration"},
          contexts=PANEL_ITEM_BATCH,
          # Le curseur S'ARRÊTE à ce que le modèle choisi sait produire (MusicGen 30 s, Music 3
          # 300 s) : avant, 10 min étaient proposées et la tâche réduisait en silence au
          # lancement. Capacité du catalogue, la même que `clamp_duration` lit ; « auto » ou
          # modèle sans plafond déclaré → curseur du schéma, intact.
          cap_from={"field": "model", "capability": "max_duration_s"}),
]

# Format + qualité de sortie depuis la brique commune (audio, early-binding auto via le catalogue).
PARAMS += output_format_params_for_app(
    "composer",
    contexts=PANEL_ITEM_BATCH,
    dom_id_format={"panel": "output_format", "item": "settingsOutputFormat",
                   "batch": "batchSettingsOutputFormat"},
    dom_id_quality={"panel": "output_quality", "item": "settingsOutputQuality",
                    "batch": "batchSettingsOutputQuality"},
)

PARAMS_JSON = schema_to_dicts(PARAMS)
