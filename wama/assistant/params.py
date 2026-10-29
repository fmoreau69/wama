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
from wama.common.tts.constants import VOICE_PAUSE_SETTINGS
from wama.common.utils.auto_model import AUTO, intent_param
from wama.common.utils.param_schema import (Param, ParamGroup, groups_to_dicts, schema_to_dicts,
                                            seed_param, temperature_param, top_p_param, voices_of)

#: Deux SURFACES pour un schéma, comme les apps (2026-10-18, décision de Fabien) : la section
#: « Paramètres » du VOLET droit de l'accueil (`panel`) et la modale ⚙ du chat (`item`), chemin du
#: mode simplifié — volets masqués — et du mini-chat des autres pages. Un identifiant par contexte :
#: les deux peuvent être rendus sur la même page.
SURFACES = ('panel', 'item')

#: Les sous-agents : « auto » (le curseur décide) en tête, puis les deux choix manuels.
SUB_AGENTS_AUTO, SUB_AGENTS_ALWAYS, SUB_AGENTS_NEVER = AUTO, 'always', 'never'
SUB_AGENTS_CHOICES = [(SUB_AGENTS_AUTO, 'Auto (selon le curseur)'),
                      (SUB_AGENTS_ALWAYS, 'Toujours proposés'), (SUB_AGENTS_NEVER, 'Jamais')]

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
    # La TEMPÉRATURE du modèle de conversation (2026-10-21) — le réglage commun, lié au select :
    # vide = celle du modèle (c'était 0,7 imposé en local). Elle ne vaut que pour la conversation,
    # pas pour les tâches qu'il lance (chacune a la sienne, sur sa card).
    Param(name='temperature', **temperature_param(
        'model', dom_id={'panel': 'ai-temperature', 'item': 'ai-temperature-modal'},
        contexts=SURFACES)),
    # Ses deux voisins (2026-10-22, réglages proposés par Albert) : vides = ceux du modèle.
    Param(name='seed', **seed_param(
        'model', dom_id={'panel': 'ai-seed', 'item': 'ai-seed-modal'}, contexts=SURFACES)),
    Param(name='top_p', **top_p_param(
        'model', dom_id={'panel': 'ai-top-p', 'item': 'ai-top-p-modal'}, contexts=SURFACES)),
    # Les SOUS-AGENTS (2026-10-29, `WAMA_HARNESS §7.4` étapes 3 et 5) : le geste commun « auto +
    # curseur + manuel », sur la forme de la voix du composer (`composer/utils/vocals.py`). « Auto »
    # suit le curseur Rapide ↔ Qualité, au même cran que la réflexion du modèle
    # (`assistant_engine.delegation_wanted`) ; « Jamais », l'outil `delegate` n'est pas annoncé.
    # Jusqu'au 29/10 au soir, un interrupteur éteint par défaut : allumé, il vaut « Toujours ».
    Param(name='sub_agents', type='select', label='Sous-agents', icon='fa-sitemap',
          choices=SUB_AGENTS_CHOICES, default=SUB_AGENTS_AUTO,
          dom_id={'panel': 'ai-sub-agents', 'item': 'ai-sub-agents-modal'}, contexts=SURFACES,
          help="L'assistant peut confier des recherches ou des lectures à des sous-agents, qui "
               "travaillent en lecture seule et lui rendent leur rapport — et réunir plusieurs "
               "agents sur une question de recherche. « Auto » : proposés quand le curseur est sur "
               "Qualité. Plus d'appels au modèle, donc plus lent et plus coûteux sur un modèle "
               "distant."),
    # L'ARBITRE d'un council (2026-10-29, décision de Fabien : « Claude par l'abonnement en
    # arbitre ») — le geste commun du sélecteur de modèle : « auto » tire au curseur Qualité hors
    # des modèles qui ont donné un avis (`assistant_engine._decider_lane`) ; un modèle CHOISI arbitre
    # toujours. Sur l'abonnement, il est appelé sans aucun outil de WAMA. Le tirage ne retient
    # jamais l'abonnement de lui-même : il faut le choisir.
    Param(name='council_decider', type='select', label='Arbitre du council', icon='fa-gavel',
          default=AUTO, dom_id={'panel': 'ai-council-decider', 'item': 'ai-council-decider-modal'},
          contexts=SURFACES, options_source='catalog', options_query={'model_type': 'llm'},
          options_auto=True, options_cloud=True,
          help="Le modèle qui tranche quand l'assistant réunit plusieurs agents sur une question. "
               "« Automatique » : le meilleur modèle disponible, hors de ceux qui ont donné un "
               "avis. Choisir l'abonnement Claude le fait arbitrer, sans aucun outil."),
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
    # Le MODÈLE qui dit les réponses et sa VOIX (2026-10-28, Fabien : « en plus du choix du modèle
    # de réflexion, ne faut-il pas permettre de choisir son modèle de vocalisation ? »). Le geste
    # commun des apps : « auto » en tête, puis tout modèle de synthèse du catalogue. « Auto » tire
    # celui qui répond le plus vite dans la langue du profil (`assistant_voice.voice_model_for`) —
    # sans prévision : ce tirage ne dépend pas du curseur. La voix vient de la source COMMUNE des
    # voix, bornée au modèle choisi (`voices_of`) : sous « auto », celle de la langue. Remplace le
    # sélecteur de voix Kokoro que la seule page d'accueil proposait, sans le retenir.
    Param(name='voice_model', type='select', label='Modèle de voix', icon='fa-microphone-lines',
          default=AUTO, dom_id={'panel': 'ai-voice-model', 'item': 'ai-voice-model-modal'},
          contexts=SURFACES, group='voice',
          options_source='catalog', options_query={'task': 'text-to-speech'},
          options_auto='silent', help_source='assistant',
          help_fallback={AUTO: "Le modèle de voix installé qui répond le plus vite dans votre langue."},
          help="Le modèle qui dit les réponses de l'assistant à voix haute."),
    Param(name='voice_preset', type='select', label='Voix', icon='fa-user', default='default',
          dom_id={'panel': 'ai-voice', 'item': 'ai-voice-modal'}, contexts=SURFACES, group='voice',
          options_source='voices', cap_from=voices_of('voice_model'),
          help="Les voix que le modèle choisi sait dire ; « Voix par défaut » : celle de votre langue."),
    # Les PAUSES de la voix (2026-10-18, demande de Fabien : « la voix pourrait prendre un peu
    # plus son temps sur les ponctuations »). Deux réglages parce que le moteur connaît DEUX
    # marques : fin de phrase (`. ! ? …`) et fin de proposition (`, ; :`) — parenthèses et tirets
    # d'incise y arrivent réécrits en virgules (`tts_text.say_incises`). Le contrat commun des
    # moteurs les pose (`tts_base.TTSBackend.synthesize`) ; la vue de vocalisation les lui passe.
    # Libellé, bornes, aide et défaut : la déclaration COMMUNE (`VOICE_PAUSE_SETTINGS`), lue aussi
    # par le synthesizer. Défauts plus longs que ceux du moteur : c'est l'objet de la demande.
    # Rangées dans le groupe « Voix », REPLIÉ : réglées une fois, elles ne chargent pas la surface.
    Param(name='voice_sentence_pause', contexts=SURFACES, group='voice',
          **VOICE_PAUSE_SETTINGS['sentence_pause']),
    Param(name='voice_clause_pause', contexts=SURFACES, group='voice',
          **VOICE_PAUSE_SETTINGS['clause_pause']),
]

#: Groupes d'affichage (`ParamGroup`, la brique des apps — anonymizer) : la voix, repliée.
GROUPS = [ParamGroup(key='voice', title='Voix', icon='fa-volume-up', collapsed=True)]

#: Défauts des réglages utilisateur — DÉRIVÉS du schéma (patron imager) : aucune seconde liste.
USER_SETTINGS_DEFAULTS = {p.name: p.default for p in PARAMS}

PARAMS_JSON = schema_to_dicts(PARAMS)
GROUPS_JSON = groups_to_dicts(GROUPS)
