"""Le MODÈLE de chaque rôle, tel que la card le demande — lecture COMMUNE aux backends (ORM-free).

`options` porte les valeurs EFFECTIVES de la card (`params.py`, modèle événementiel §23.2quater) :
`vision_model`, `llm_model`, `asr_model`. « auto » garde le comportement HISTORIQUE de chaque
backend — la cascade vision (`image_backend`), les tiers de `llm_utils.get_describer_model` —, une
clé de catalogue désigne le modèle, qui n'est JAMAIS remplacé en silence s'il ne répond pas (la
règle du transcriber : un modèle explicite qui échoue est une erreur dite, pas un repli).

Le Describer n'appelle que des modèles LOCAUX pour la vision et le langage : ses selects ne
proposent pas de modèle distant (`options_cloud` absent du schéma), et les aides de `llm_utils`
ne portent pas la clé d'un utilisateur — une clé distante posée par un autre chemin est refusée
en le disant, plutôt que partie avec la clé de l'instance.
"""
from wama.common.utils.auto_model import is_auto

#: Le modèle de légendage local du describer (repli historique de la cascade vision).
BLIP_KEY = 'describer:blip'
BLIP = 'blip'


_OWNER = 'le Describer'


def local_ollama_name(key: str, role: str) -> str:
    """Le nom Ollama d'une clé `ollama:<nom>` ; lève `ValueError` pour toute autre source
    (lecture COMMUNE `llm_utils.designated_local_model`)."""
    from wama.common.utils.llm_utils import designated_local_model
    return designated_local_model(key, role, _OWNER)


def llm_for(options: dict, content_type: str, output_style: str):
    """`(nom, fournisseur)` du modèle de LANGAGE pour ce contenu et ce style : sous « auto », le
    tier historique (`get_describer_model`, fournisseur du réglage global) ; sinon le modèle
    désigné, chez Ollama (lecture COMMUNE `llm_utils.card_llm`)."""
    from wama.common.utils.llm_utils import card_llm, get_describer_model
    return card_llm((options or {}).get('llm_model'),
                    auto=lambda: get_describer_model(content_type, output_style), owner=_OWNER)


def vision_for(options: dict):
    """Le modèle de VISION désigné : None sous « auto » (la cascade historique), `BLIP`, ou le
    nom Ollama du modèle choisi."""
    key = (options or {}).get('vision_model')
    if is_auto(key):
        return None
    if key == BLIP_KEY:
        return BLIP
    return local_ollama_name(key, 'vision')


def catalog_key_of(name: str) -> str:
    """La clé de catalogue d'un modèle de vision ou de langage nommé par un backend — ce que la
    ligne d'exécution du process retient (`models` du retour de glu)."""
    from wama.common.utils.llm_utils import ollama_catalog_key
    return BLIP_KEY if name == BLIP else ollama_catalog_key(name)
