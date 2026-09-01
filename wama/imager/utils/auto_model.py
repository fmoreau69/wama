"""
Résolution du modèle « auto » de l'Imager — AU LANCEMENT de la tâche.

⚠️ **Le moment compte autant que la règle.** Le tirage lit la VRAM libre ; or entre le dépôt
dans la file et l'exécution réelle il peut s'écouler plusieurs minutes, pendant lesquelles une
autre app charge ou libère un modèle. Résoudre « auto » dans la VUE (au clic) donnerait donc un
choix fondé sur un état périmé. Même pattern que le composer, volontairement.

Depuis 2026-09-02, la STRUCTURE (valeur explicite respectée, tirage par capacité, repli,
« ne lève jamais ») vit dans la brique COMMUNE `wama/common/utils/auto_model.py` — ce
fichier et son jumeau composer en sont les modèles généralisés. Ne reste ici que la
spécificité LÉGITIME de l'app, déclarée : la correspondance mode de génération → domaine.
"""

from wama.common.utils.auto_model import AUTO, resolve_model_choice  # noqa: F401 (AUTO ré-exporté — tasks.py l'importe d'ici)

from .model_config import DEFAULT_I2V_MODEL, DEFAULT_IMAGE_MODEL, DEFAULT_VIDEO_MODEL

# Mode de génération → ce dont on dispose et ce qu'on veut voir consommé.
# Déclaratif : ajouter un mode ne demande aucune logique, juste une ligne.
# `consumes`/`available_inputs` sont des affinages de RÉSOLUTION — permis ici,
# interdits dans une `options_query` d'UI (sélectionner n'est pas lister).
_BY_MODE = {
    'txt2vid': dict(modality='video', available_inputs=['prompt'],
                    fallback=DEFAULT_VIDEO_MODEL),
    'img2vid': dict(modality='video', available_inputs=['prompt', 'work_image'],
                    consumes=['work_image'], fallback=DEFAULT_I2V_MODEL),
}
_DEFAULT_IMAGE = dict(modality='image', fallback=DEFAULT_IMAGE_MODEL)


def resolve_auto_model(generation) -> str:
    """
    Modèle à utiliser pour cette génération. Renvoie le modèle demandé s'il est explicite.

    Ne lève jamais (contrat de la brique commune) : refuser une génération pour un
    problème de tirage serait pire que la faire avec un modèle correct mais non optimal.
    """
    spec = dict(_BY_MODE.get(generation.generation_mode, _DEFAULT_IMAGE))
    fallback = spec.pop('fallback')
    spec['source'] = 'imager'   # valeurs stockées historiquement NUES (espace de clés d'app)
    return resolve_model_choice((generation.model or '').strip(),
                                spec=spec, fallback=fallback) or fallback
