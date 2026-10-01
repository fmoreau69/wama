"""Résolution du choix de modèle « auto » du Composer — 1er consommateur réel de select_model().

Chaîne respectée (INPUT_MODEL_MATCHING.md + feedback_ui_from_model_capabilities) :
- les CANDIDATS viennent des capacités du CATALOGUE `AIModel` (`task` text-to-music /
  text-to-audio pour le mode musique/ambiance, `consumes` pour la référence mélodique) —
  aucune liste de modèles en dur ;
- l'ARBITRAGE VRAM est délégué à la brique centrale du model_manager (« le meilleur qui
  tient », préférence au modèle déjà résident) ;
- repli si le catalogue ne propose rien : plus petit modèle du bon type dans la config
  déclarative de l'app (COMPOSER_MODELS), puis défaut historique.

La résolution se fait AU LANCEMENT de la tâche (la VRAM libre du moment fait foi), jamais à la
création de l'item — un batch résout donc chaque élément avec l'état GPU de son tour.

Depuis 2026-09-02, la STRUCTURE (tirage par capacité, repli, « ne lève jamais ») vit dans la
brique COMMUNE `wama/common/utils/auto_model.py` — ce fichier, 1er adopteur historique, en est
l'un des deux modèles généralisés. Ne reste ici que la spécificité LÉGITIME de l'app :
la correspondance type de génération / référence mélodique → domaine, et le repli config.
"""

from wama.common.utils.auto_model import AUTO, resolve_model_choice


def resolve_auto_model(gen):
    """gen (ComposerGeneration, model = un « auto » de groupe) → CLÉ de catalogue concrète.

    La tâche vient de l'« auto » choisi (`auto:text-to-music` / `auto:text-to-audio`, route F4b
    2026-10-01 — un « auto » par groupe, décision du 2026-07-02 conservée). Le domaine n'est PLUS
    borné à `source='composer'` : un modèle de la tâche venu d'ailleurs (YuE2) est candidat."""
    from wama.composer.utils.model_choice import task_of
    # Appariement entrée↔modèle : si une référence mélodique est fournie, seuls les
    # modèles qui la CONSOMMENT (cohérent avec le grisage WamaInputMatch côté UI) ;
    # sinon, filtrage sur la tâche. `consumes` est un affinage de RÉSOLUTION — permis
    # ici, interdit dans une `options_query` d'UI (sélectionner n'est pas lister).
    spec = {}
    if gen.melody_reference:
        spec['consumes'] = ['reference_melody']
    else:
        spec['task'] = task_of(gen.model)
    # `item=gen` (chantier C, 2026-09-20) : le curseur rapide/qualité de l'item (sinon le réglage
    # d'app de l'utilisateur, sinon 50) pèse dans le score — la brique était appelée SANS intention.
    return resolve_model_choice(AUTO, spec=spec, fallback=_config_fallback(gen), item=gen)


def _config_fallback(gen) -> str:
    """Catalogue vide ou injoignable : plus petit modèle du bon type déclaré par l'app (clé)."""
    from wama.composer.utils.model_choice import generation_type
    from wama.composer.utils.model_config import COMPOSER_MODELS
    wanted = generation_type(gen.model)
    pool = {k: v for k, v in COMPOSER_MODELS.items() if v.get('type') == wanted}
    if pool:
        return 'composer:' + min(pool, key=lambda k: pool[k].get('vram_gb', 99))
    return 'composer:musicgen-small'
