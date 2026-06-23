"""
Métadonnée d'app — déclaration des « prompt targets » (ROADMAP §2bis / §16.6).

SOURCE UNIQUE décrivant, pour chaque app, quels champs sont des prompts et leur **KIND**.
Consommée par : la PromptPipeline (traitement), l'assistant IA et la méta-app (découverte de la
structure de prompt d'une app sans lire son code). Au lieu de coder `kind=...` dans chaque tâche,
le KIND est déclaré ICI, en un seul endroit.

Chaque target : {field, kind, [model_field, source, default_model_type, when]}.
- field             : nom du champ prompt sur l'instance.
- kind              : 'generative' | 'concept' | 'intent' | 'text' (cf. prompt_pipeline).
- model_field       : attribut de l'instance donnant l'id du modèle cible (pour ses capacités langue).
- source            : source du modèle dans le catalogue AIModel (défaut = nom de l'app).
- default_model_type: type de repli si le modèle est introuvable (ex. 'diffusion').
- when              : attribut booléen de l'instance qui conditionne le traitement (ex. 'use_sam3').
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

PROMPT_TARGETS = {
    'imager': [
        {'field': 'prompt',          'kind': 'generative', 'model_field': 'model',
         'source': 'imager', 'default_model_type': 'diffusion'},
        {'field': 'negative_prompt', 'kind': 'generative', 'model_field': 'model',
         'source': 'imager', 'default_model_type': 'diffusion'},
    ],
    'anonymizer': [
        {'field': 'sam3_prompt', 'kind': 'concept', 'when': 'use_sam3'},
    ],
    'assistant': [
        # Le message chat = intention pour un LLM. Modèle résolu dynamiquement (pas un champ
        # d'instance) → passer `model_id=` à process_prompt_for. LLM assistant multilingue →
        # routing direct → AUCUNE traduction/chargement (résource-safe). Ne traduit que si le
        # modèle résolu déclare explicitement ne pas gérer la langue de l'utilisateur.
        {'field': 'message', 'kind': 'intent', 'model_field': None, 'source': 'ollama'},
    ],
    # describer : le prompt vision est interne (piloté par output_language), pas un champ texte user.
}


def prompt_targets(app: str) -> list:
    """Targets de prompt déclarés pour une app (liste, vide si aucune)."""
    return PROMPT_TARGETS.get(app, [])


def _target(app: str, field: str):
    for t in PROMPT_TARGETS.get(app, []):
        if t['field'] == field:
            return t
    return None


def _resolve_model(app: str, instance, tgt, model_id=None):
    """
    Capacités + type du modèle cible (AIModel) pour ce target, ou (None, default_type).

    `model_id` (optionnel) court-circuite la lecture du `model_field` de l'instance : utile quand
    le modèle est résolu dynamiquement (ex. assistant : modèle Ollama choisi à l'exécution).
    """
    mid = model_id
    if mid is None:
        mfield = tgt.get('model_field')
        if not mfield or instance is None:
            return None, tgt.get('default_model_type')
        mid = getattr(instance, mfield, None)
    if not mid:
        return None, tgt.get('default_model_type')
    try:
        from wama.model_manager.models import AIModel
        source = tgt.get('source', app)
        m = AIModel.objects.filter(model_key=f"{source}:{mid}").first()
        return (m.capabilities if m else None), (m.model_type if m else tgt.get('default_model_type'))
    except Exception:
        return None, tgt.get('default_model_type')


def process_prompt_for(app: str, field: str, value, instance=None, user=None, console=None,
                       model_id=None):
    """
    Traite UN prompt d'une app selon sa déclaration `PROMPT_TARGETS` (KIND + modèle cible).
    L'app passe la VALEUR résolue (gère ses propres fallbacks) ; le KIND vient de la déclaration.
    `model_id` : id de modèle explicite (apps sans instance Django, ex. assistant).
    Fail-safe : retourne `value` inchangé si pas de target / valeur vide / erreur.
    """
    tgt = _target(app, field)
    if tgt is None or not value or not str(value).strip():
        return value
    from .prompt_pipeline import process_prompt
    caps, mtype = _resolve_model(app, instance, tgt, model_id=model_id)
    return process_prompt(value, kind=tgt.get('kind', 'text'),
                          model_capabilities=caps, model_type=mtype,
                          user=user, console=console)['prompt']
