"""
Registre des backends TTS du synthesizer (contrat commun `BaseModelBackend`).

Consommé par `tts_service.py` (le process qui charge réellement) et par les
outils transverses (model_installer, tests nocturnes) via `is_available()` /
`missing_packages()` — SANS charger de modèle.
"""
from __future__ import annotations

from wama.common.tts.constants import COQUI_MODEL_MAPPING

from .bark_backend import BarkBackend
from .base import CATALOG_KEYS, TTSBackend
from .audio8_backend import Audio8Backend
from .coqui_backend import CoquiBackend
from .qwen3_tts_backend import Qwen3TTSBackend
from .higgs_backend import HiggsAudioBackend
from .kokoro_backend import KokoroBackend
from .kokoro_onnx_backend import KokoroOnnxBackend

#: Moteur → classe de backend (vocabulaire `SYNTHESIZER_MODELS[*]['engine']`).
#: Cette table est AUSSI l'inventaire du grisage automatique (apps.ready → un moteur
#: ajouté ici se RÉ-AUTORISE partout : select dégrisé, tirage auto rouvert — 02/09).
ENGINE_BACKENDS = {
    'coqui': CoquiBackend,
    'bark': BarkBackend,
    'higgs': HiggsAudioBackend,
    'kokoro': KokoroBackend,
    'kokoro-onnx': KokoroOnnxBackend,
    # 1er consommateur du moteur générique « code de modèle fourni par le dépôt » —
    # Audio8 par défaut ; un 2ᵉ modèle remote-code fera passer le backend au `model`
    # transmis par le contrat d'appel (généralisation au 2ᵉ, jamais avant).
    'transformers-remote-code': Audio8Backend,
    # Backend ÉCRIT, runtime PAS ENCORE installé (qwen-tts==0.1.1 épingle
    # transformers 4.57.3 — venv partagé : installation sur GO humain,
    # ensure_backend_deps). L'inventaire du grisage ne sert que les moteurs
    # EXÉCUTABLES : celui-ci reste grisé jusqu'à l'installation, puis se
    # dé-grise tout seul.
    'qwen3-tts': Qwen3TTSBackend,
}


#: Moteur d'un nom de modèle UI quand il diffère du nom de moteur (table d'EXCEPTIONS).
_MODELE_VERS_MOTEUR = {'higgs-audio': 'higgs'}


def engine_for_model(model_name: str, engine: str | None = None) -> str:
    """Nom de moteur pour un modèle UI — ou pour une CLÉ DE CATALOGUE.

    ⚠ Le repli historique était `return 'coqui'` pour TOUT nom inconnu — donc un nom mal
    orthographié, hérité, ou d'un moteur pas encore enregistré faisait **charger XTTS v2
    (plusieurs Go, des dizaines de secondes) EN SILENCE**, à la place du moteur demandé.
    C'est un candidat sérieux au « XTTS qui prend la relève » observé sans explication
    (Fabien, 2026-08-31) : rien dans les journaux ne distingue ce cas d'un choix délibéré.
    Un routage qui se trompe doit le DIRE — on lève, l'appelant a déjà son repli.

    `engine` (2026-09-01, route F4b) : le moteur DÉCLARÉ du modèle, tel que le porte
    `composition.runtime.engine` au catalogue. C'est la voie GÉNÉRALE — celle qui permet
    d'exécuter un modèle qu'aucune app ne déclare (installé par la prospection), dont le nom
    ne ressemble à aucun moteur : `onnx-community/Kokoro-82M-v1.0-ONNX` → `kokoro-onnx`.
    Cette couche est **Django-free** (le service TTS n'initialise pas Django) : elle ne peut
    pas lire le catalogue elle-même, l'appelant Django résout et PASSE la réponse.
    Un `engine` inconnu n'est jamais avalé en silence — même règle que ci-dessus.

    Tolérance d'ESPACE DE CLÉS : les valeurs stockées ont porté le suffixe nu (`kokoro`) avant
    de porter la clé entière (`synthesizer:kokoro`). Les deux se résolvent, définitivement —
    une ligne écrite avant la migration du 2026-09-01, ou un appel d'une surface pas encore
    portée, ne doit pas échouer sur une question de préfixe.
    """
    if engine:
        if engine in ENGINE_BACKENDS:
            return engine
        raise ValueError(
            f"Moteur TTS déclaré {engine!r} (modèle {model_name!r}) sans backend enregistré — "
            f"moteurs disponibles : {sorted(ENGINE_BACKENDS)}. Un modèle catalogué dont le "
            f"moteur n'est pas intégré se propose mais ne s'exécute pas encore.")

    for nom in _candidats(model_name):
        if nom in COQUI_MODEL_MAPPING:
            return 'coqui'
        if nom in _MODELE_VERS_MOTEUR:
            return _MODELE_VERS_MOTEUR[nom]
        if nom in ENGINE_BACKENDS:
            return nom             # le nom de modèle EST le nom de moteur (bark, kokoro…)
    raise ValueError(
        f"Moteur TTS inconnu pour le modèle {model_name!r} — moteurs enregistrés : "
        f"{sorted(ENGINE_BACKENDS)} ; modèles Coqui : {sorted(COQUI_MODEL_MAPPING)}")


def local_model_name(model_name: str) -> str:
    """Nom du modèle tel que le BACKEND le comprend — la clé catalogue sans sa source.

    Les backends n'ont jamais connu que le nom nu (`coqui-xtts`, `kokoro`) : `CoquiBackend`
    l'utilise pour indexer `COQUI_MODEL_MAPPING`, et une clé entière y tomberait dans le
    repli `.get(model, model)` — donc `TTS('synthesizer:coqui-xtts')`, un identifiant que
    Coqui ne connaît pas. La traduction se fait ICI, au seuil du service, plutôt que dans
    chaque backend : c'est le même geste que `engine_for_model`, et il n'a pas à être
    réappris cinq fois.
    """
    return model_name.split(':', 1)[1] if ':' in (model_name or '') else model_name


def _candidats(model_name: str):
    """Le nom tel quel, puis son suffixe sans le préfixe `source:` de la clé catalogue.

    L'ordre compte : on essaie TOUJOURS la valeur entière d'abord. Un moteur qui porterait
    un `:` dans son propre nom resterait ainsi résoluble, et le découpage ne devient une
    hypothèse que lorsque la valeur entière n'a rien donné.
    """
    yield model_name
    if ':' in (model_name or ''):
        yield model_name.split(':', 1)[1]


__all__ = [
    'BarkBackend', 'CoquiBackend', 'HiggsAudioBackend', 'KokoroBackend',
    'KokoroOnnxBackend', 'TTSBackend', 'ENGINE_BACKENDS', 'CATALOG_KEYS',
    'engine_for_model', 'local_model_name',
]
