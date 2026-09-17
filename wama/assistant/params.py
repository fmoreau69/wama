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
        options_auto=True, options_cloud=True, options_aptitudes=True,
        help="« Automatique » choisit au lancement selon le curseur, la mémoire GPU libre et "
             "les clés d'API que vous avez enregistrées.",
    ),
    Param(name='quality_intent', dom_id='ai-quality', contexts=('panel',), **intent_param()),
]

#: Défauts des réglages utilisateur — DÉRIVÉS du schéma (patron imager) : aucune seconde liste.
USER_SETTINGS_DEFAULTS = {p.name: p.default for p in PARAMS}

PARAMS_JSON = schema_to_dicts(PARAMS)
