"""Résolution du choix de modèle « auto » du Composer — 1er consommateur réel de select_model().

Chaîne respectée (INPUT_MODEL_MATCHING.md + feedback_ui_from_model_capabilities) :
- les CANDIDATS viennent des capacités du CATALOGUE `AIModel` (MÊME source que WamaInputMatch :
  `task` text-to-music/text-to-audio pour le mode musique/ambiance, `inputs_required/optional`
  pour la référence mélodique) — aucune liste de modèles en dur ;
- l'ARBITRAGE VRAM est délégué à la brique centrale `select_model()` du model_manager
  (« le plus gros qui tient », préférence au modèle déjà résident) ;
- replis étagés si la brique est indisponible : plus petit candidat du catalogue (vram_gb),
  puis défaut déclaré du schéma (params.py).

La résolution se fait AU LANCEMENT de la tâche (la VRAM libre du moment fait foi), jamais à la
création de l'item — un batch résout donc chaque élément avec l'état GPU de son tour.
"""


def resolve_auto_model(gen):
    """gen (ComposerGeneration, model ∈ auto-music/auto-sfx) → model_id concret.

    Le type music/sfx vient de gen.generation_type (posé par les vues via _model_type
    depuis le pseudo-modèle choisi — un « auto » par optgroup, décision 2026-07-02)."""
    from wama.model_manager.models import AIModel

    need_ref = bool(gen.melody_reference)
    task = 'text-to-music' if gen.generation_type == 'music' else 'text-to-audio'

    candidates = []
    for m in AIModel.objects.filter(source='composer', is_proposed=False):
        caps = m.capabilities or {}
        accepted = list(caps.get('inputs_required') or []) + list(caps.get('inputs_optional') or [])
        if need_ref:
            # Une référence mélodique est fournie : seuls les modèles qui l'acceptent
            # (cohérent avec le grisage WamaInputMatch côté UI).
            if 'reference_melody' not in accepted:
                continue
        elif caps.get('task') and caps.get('task') != task:
            continue
        candidates.append(m.model_key)

    if candidates:
        try:
            from wama.model_manager.services import select_model
            chosen = select_model(source='composer', candidates=candidates)
            if isinstance(chosen, (list, tuple)):
                chosen = chosen[0] if chosen else None
            model_id = getattr(chosen, 'model_id', None)
            if model_id:
                return model_id
        except Exception:
            pass  # sonde VRAM/catalogue indisponible → repli ci-dessous
        smallest = (AIModel.objects.filter(model_key__in=candidates)
                    .order_by('vram_gb').first())
        if smallest:
            return smallest.model_id
    # Catalogue vide ou injoignable : plus petit modèle du bon type dans la config
    # déclarative de l'app (COMPOSER_MODELS), puis défaut du schéma en dernier ressort.
    from wama.composer.utils.model_config import COMPOSER_MODELS
    wanted = 'sfx' if gen.generation_type == 'sfx' else 'music'
    pool = {k: v for k, v in COMPOSER_MODELS.items() if v.get('type') == wanted}
    if pool:
        return min(pool, key=lambda k: pool[k].get('vram_gb', 99))
    return 'musicgen-small'
