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
    """gen (ComposerGeneration, model ∈ auto-music/auto-sfx) → model_id concret.

    Le type music/sfx vient de gen.generation_type (posé par les vues via _model_type
    depuis le pseudo-modèle choisi — un « auto » par optgroup, décision 2026-07-02)."""
    # Appariement entrée↔modèle : si une référence mélodique est fournie, seuls les
    # modèles qui la CONSOMMENT (cohérent avec le grisage WamaInputMatch côté UI) ;
    # sinon, filtrage sur la tâche. `consumes` est un affinage de RÉSOLUTION — permis
    # ici, interdit dans une `options_query` d'UI (sélectionner n'est pas lister).
    spec = {'source': 'composer'}
    if gen.melody_reference:
        spec['consumes'] = ['reference_melody']
    else:
        spec['task'] = 'text-to-music' if gen.generation_type == 'music' else 'text-to-audio'
    return resolve_model_choice(AUTO, spec=spec, fallback=_config_fallback(gen))


def _config_fallback(gen) -> str:
    """Catalogue vide ou injoignable : plus petit modèle du bon type déclaré par l'app."""
    from wama.composer.utils.model_config import COMPOSER_MODELS
    wanted = 'sfx' if gen.generation_type == 'sfx' else 'music'
    pool = {k: v for k, v in COMPOSER_MODELS.items() if v.get('type') == wanted}
    if pool:
        return min(pool, key=lambda k: pool[k].get('vram_gb', 99))
    return 'musicgen-small'
