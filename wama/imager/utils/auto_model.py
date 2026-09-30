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
Depuis le 2026-09-29 (route F4b) le tirage ne borne plus par `source='imager'` : les valeurs
stockées sont des CLÉS DE CATALOGUE (migration `0023`), la seule raison de l'ancrage est tombée.
"""

from wama.common.utils.auto_model import AUTO, resolve_model_choice  # noqa: F401 (AUTO ré-exporté — tasks.py l'importe d'ici)

from .model_config import DEFAULT_I2V_MODEL, DEFAULT_IMAGE_MODEL, DEFAULT_VIDEO_MODEL

# Mode de génération → ce dont on dispose et ce qu'on veut voir consommé.
# Déclaratif : ajouter un mode ne demande aucune logique, juste une ligne.
# `consumes`/`available_inputs` sont des affinages de RÉSOLUTION — permis ici,
# interdits dans une `options_query` d'UI (sélectionner n'est pas lister).
#: ⚠ Tirage PAR CAPACITÉ, sans `source` (route F4b, 2026-09-29) : il tire dans le MÊME lot que
#: le select (tous les modèles de diffusion de la modalité, sources confondues — un modèle
#: installé depuis le model manager y entre). `model_type` borne la CATÉGORIE, requise par le
#: sélecteur dès qu'aucune app n'est nommée. Le retour est donc une CLÉ DE CATALOGUE entière.
_BY_MODE = {
    'txt2vid': dict(model_type='diffusion', modality='video', available_inputs=['prompt'],
                    fallback=DEFAULT_VIDEO_MODEL),
    'img2vid': dict(model_type='diffusion', modality='video',
                    available_inputs=['prompt', 'work_image'],
                    consumes=['work_image'], fallback=DEFAULT_I2V_MODEL),
}
_DEFAULT_IMAGE = dict(model_type='diffusion', modality='image', fallback=DEFAULT_IMAGE_MODEL)


def resolve_auto_model(generation) -> str:
    """
    Modèle à utiliser pour cette génération — une CLÉ DE CATALOGUE. Renvoie le modèle demandé
    s'il est explicite (normalisé en clé : une valeur nue d'avant la migration est lue dans
    l'imager).

    Ne lève jamais (contrat de la brique commune) : refuser une génération pour un
    problème de tirage serait pire que la faire avec un modèle correct mais non optimal.
    """
    from wama.common.utils.model_keys import catalog_key
    spec = dict(_BY_MODE.get(generation.generation_mode, _DEFAULT_IMAGE))
    # Les défauts de REPLI sont déclarés par l'imager (identifiants de `IMAGER_MODELS`).
    fallback = catalog_key(spec.pop('fallback'), 'imager')
    # `item=generation` (chantier C, 2026-09-20) : le CURSEUR rapide/qualité de l'item (sinon
    # le réglage d'app de l'utilisateur, sinon 50) pèse dans le score du tirage — jusque-là la
    # brique était appelée SANS intention, et le curseur n'existait pas à l'imager.
    chosen = resolve_model_choice(catalog_key(generation.model, 'imager'),
                                  spec=spec, fallback=fallback, item=generation) or fallback
    return catalog_key(chosen, 'imager')
