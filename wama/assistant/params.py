"""
Schéma de paramètres de l'AI-Assistant — le MÊME mécanisme que les apps (facettes F3 / F4b).

Ce qui remplace la table de RÔLES (`_ROLE_TIER` : fast, dev, coder, architect, debug) : le geste
commun des apps — « auto » en tête du menu, le curseur Rapide ↔ Qualité, et le choix manuel d'un
modèle. Les trois COEXISTENT (recadrage de Fabien, 15/09 : « il n'y a pas à choisir, écarter ou
remplacer »). Ce que les rôles apportaient vraiment — un gabarit de modèle — est porté par le
curseur ; ce qu'ils apportaient d'autre — une posture — l'était déjà par les skills, que
l'assistant charge lui-même (`charger_competence`).

DOMAINE déclaré : `llm`. Une seule catégorie parce qu'un modèle de conversation qui accepte des
images est rangé en `llm` + `vision` — la convention d'Ollama (`ollama:gemma4:12b`), désormais
suivie aussi pour les modèles distants (`cloud_models._CHAT_MULTIMODAL`). Mesuré le 16/09 : avec
`llm,vlm`, la liste proposait `describer:blip` (légendage, `completion=False`), qui ne converse
pas. Un seul domaine, deux usages : ce que le select PROPOSE et ce que « auto » TIRE
(`auto_model.catalog_domain('assistant')`).

`options_cloud` : les modèles DISTANTS que les clés d'API de l'utilisateur ouvrent entrent au
menu, selon son niveau cloud — jamais ceux d'un autre, jamais sans autorisation.
"""
from wama.common.utils.auto_model import AUTO, intent_param
from wama.common.utils.param_schema import Param, ParamGroup, groups_to_dicts, schema_to_dicts

#: Deux SURFACES pour un schéma, comme les apps (2026-10-18, décision de Fabien) : la section
#: « Paramètres » du VOLET droit de l'accueil (`panel`) et la modale ⚙ du chat (`item`), chemin du
#: mode simplifié — volets masqués — et du mini-chat des autres pages. Un identifiant par contexte :
#: les deux peuvent être rendus sur la même page.
SURFACES = ('panel', 'item')

PARAMS = [
    Param(
        name='model', type='select', label='Modèle', icon='fa-microchip',
        default=AUTO, dom_id={'panel': 'ai-model', 'item': 'ai-model-modal'}, contexts=SURFACES,
        options_source='catalog',
        options_query={'model_type': 'llm'},
        options_auto=True, options_cloud=True, options_abilities=True,
        # Aide CONTEXTUELLE sous le sélecteur (2026-10-04) : la description du modèle choisi et
        # son ORIGINE — local, cloud souverain (Albert), cloud commercial, et à quel prix. Lue du
        # catalogue sur le domaine du select, par la brique commune `WamaModelHelp`.
        help_source='assistant',
        help_fallback={AUTO: "Choisi au lancement : le curseur, la mémoire GPU libre et ce que "
                             "votre profil autorise comme cloud."},
        help="« Automatique » choisit au lancement selon le curseur, la mémoire GPU libre et "
             "les clés d'API que vous avez enregistrées.",
    ),
    # Le curseur de l'assistant vaut AUSSI pour les tâches qu'il lance (Fabien, 22/09) : dit ici,
    # dit dans la réponse de l'assistant (`quality_level` du résultat d'outil) — explicite partout.
    Param(name='quality_intent', dom_id={'panel': 'ai-quality', 'item': 'ai-quality-modal'},
          contexts=SURFACES, **intent_param(
        help="Guide le choix automatique du modèle de l'assistant — et s'applique aux tâches que "
             "vous lui demandez de lancer (les apps dont le curseur s'appelle « qualité » "
             "le reçoivent ; l'assistant vous le confirme à chaque lancement).")),
    # L'AVATAR PARLANT est une préférence DURABLE de l'assistant (2026-09-22, demande de Fabien) :
    # jusque-là « affiché / masqué » n'était qu'un état de la page d'accueil, perdu au premier
    # changement de page. `contexts=()` : ces deux réglages ne sont rendus dans AUCUN panneau de
    # paramètres — leur surface est le bouton de l'assistant et le chevron du volet droit
    # (`wama-avatar-panel.js`) ; ils ne sont déclarés ici que pour être bornés et persistés par
    # le MÊME chemin que le modèle et le curseur (`ai_chat_settings` → `user_settings`).
    Param(name='avatar', type='toggle', label="Avatar parlant", default=True, contexts=(),
          help="Afficher l'avatar 3D de l'assistant en tête du volet droit, sur toutes les pages."),
    Param(name='avatar_collapsed', type='toggle', label="Assistant replié", default=False, contexts=()),
    # La VOIX (vocalisation des réponses) — durable elle aussi depuis le 2026-09-22 : elle n'était
    # qu'une clé de `localStorage` de l'accueil, et le mini-chat du volet (toutes les pages) doit
    # parler pareil. Surface = le bouton 🔊/🔇/⏹ commun (`wama-assistant-voice.js`).
    Param(name='voice', type='toggle', label="Voix de l'assistant", default=True, contexts=()),
    # Les PAUSES de la voix (2026-10-18, demande de Fabien : « la voix pourrait prendre un peu
    # plus son temps sur les ponctuations »). Deux réglages parce que le moteur connaît DEUX
    # marques : fin de phrase (`. ! ? …`) et fin de proposition (`, ; :`) — parenthèses et tirets
    # d'incise y arrivent réécrits en virgules (`tts_text.say_incises`). Le moteur les lit dans
    # `options` (`kokoro_onnx_backend.process`) ; la vue de vocalisation les lui passe.
    # Défauts plus longs que ceux du moteur (0,25 / 0,1 s) : c'est l'objet de la demande.
    # Rangées dans le groupe « Voix », REPLIÉ : réglées une fois, elles ne chargent pas la surface.
    Param(name='voice_sentence_pause', type='range', label="Pause en fin de phrase",
          icon='fa-pause', default=0.4, min=0, max=1.5, step=0.05, contexts=SURFACES,
          group='voice',
          help="Silence, en secondes, après un point, un point d'exclamation ou d'interrogation."),
    Param(name='voice_clause_pause', type='range', label="Pause sur virgule, parenthèse, tiret",
          icon='fa-pause', default=0.15, min=0, max=1, step=0.05, contexts=SURFACES,
          group='voice',
          help="Silence, en secondes, après une virgule, un point-virgule, deux-points, une "
               "parenthèse ou un tiret d'incise. À 0, la phrase est dite d'un seul souffle."),
]

#: Groupes d'affichage (`ParamGroup`, la brique des apps — anonymizer) : la voix, repliée.
GROUPS = [ParamGroup(key='voice', title='Voix', icon='fa-volume-up', collapsed=True)]

#: Défauts des réglages utilisateur — DÉRIVÉS du schéma (patron imager) : aucune seconde liste.
USER_SETTINGS_DEFAULTS = {p.name: p.default for p in PARAMS}

PARAMS_JSON = schema_to_dicts(PARAMS)
GROUPS_JSON = groups_to_dicts(GROUPS)
