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
from wama.common.utils.param_schema import Param, schema_to_dicts

PARAMS = [
    Param(
        name='model', type='select', label='Modèle', icon='fa-microchip',
        default=AUTO, dom_id='ai-model', contexts=('panel',),
        options_source='catalog',
        options_query={'model_type': 'llm'},
        options_auto=True, options_cloud=True, options_abilities=True,
        help="« Automatique » choisit au lancement selon le curseur, la mémoire GPU libre et "
             "les clés d'API que vous avez enregistrées.",
    ),
    # Le curseur de l'assistant vaut AUSSI pour les tâches qu'il lance (Fabien, 22/09) : dit ici,
    # dit dans la réponse de l'assistant (`quality_level` du résultat d'outil) — explicite partout.
    Param(name='quality_intent', dom_id='ai-quality', contexts=('panel',), **intent_param(
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
    Param(name='avatar_collapsed', type='toggle', label="Avatar replié", default=False, contexts=()),
]

#: Défauts des réglages utilisateur — DÉRIVÉS du schéma (patron imager) : aucune seconde liste.
USER_SETTINGS_DEFAULTS = {p.name: p.default for p in PARAMS}

PARAMS_JSON = schema_to_dicts(PARAMS)
