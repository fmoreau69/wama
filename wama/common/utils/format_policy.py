"""
Format de POIDS recommandé d'un modèle — DÉRIVÉ de son moteur DÉCLARÉ, jamais de son type.

Jusqu'au 2026-11-08 ce module tenait une politique PAR CATÉGORIE (`FORMAT_POLICY`, huit
catégories), atteinte par deux tables recopiées à la main : le type du modèle
(`MODEL_TYPE_TO_CATEGORY`, sept des onze `ModelType`) et l'app qui le déclare
(`SOURCE_TO_CATEGORY`), plus une troisième devinée d'après le nom du dossier
(`format_converter.dir_to_category`). Un type absent — embedding, music, ocr, nlp — retombait EN
SILENCE sur « diffusion ». Mesuré sur le catalogue réel ce jour-là : 60 des 145 modèles installés
affichaient « Recommended: onnx » alors que leur moteur lit leur format actuel (48 YOLO que lit
ultralytics, des NeMo, Kokoro, Higgs, Whisper…) — convertir aurait produit un fichier qu'aucun
moteur de la ligne ne charge (`REMOVAL_LEDGER R229`).

Le format qu'un modèle DEVRAIT avoir est celui que lit le moteur qui l'exécute — et ce moteur est
DÉCLARÉ par modèle (`composition.runtime.engine`). Le seul savoir de WAMA sur « quel format lit
quel moteur » est la table des formats qui PROUVENT un moteur (`prospector.WEIGHT_FORMAT_ENGINES` :
un `.onnx` ne s'ouvre que par onnxruntime, une archive `.nemo` que par NeMo). D'où la règle :
  * un moteur que la table nomme recommande SON format ;
  * un moteur qui lit plusieurs formats (transformers, diffusers, ultralytics…), ou aucun moteur
    déclaré : AUCUNE recommandation — on ne recommande pas ce qu'on ne sait pas.
Les conversions restent offertes à la main (`AIModel.can_convert_to`).
"""

from typing import Dict


def engine_weight_format(engine: str) -> str:
    """Le format (sans point) que `engine` lit PAR NATURE — l'inverse de
    `prospector.WEIGHT_FORMAT_ENGINES` ; '' pour un moteur que la table ne nomme pas."""
    if not engine:
        return ''
    from wama.model_manager.services.prospector import WEIGHT_FORMAT_ENGINES
    return next((ext.lstrip('.') for ext, reader in WEIGHT_FORMAT_ENGINES.items()
                 if reader == engine), '')


def preferred_format(composition) -> str:
    """Le format recommandé d'un modèle de cette composition : celui de son moteur DÉCLARÉ
    (`composition.runtime.engine`), sinon ''."""
    runtime = ((composition or {}).get('runtime') or {}) if isinstance(composition, dict) else {}
    return engine_weight_format(runtime.get('engine') or '')


def declared_weight_format(composition) -> str:
    """Le format des poids que l'anatomie DÉCLARE (`composition.components` : `format` du
    composant, sinon l'extension de son motif), quand tous les composants en ont un et le MÊME ;
    '' sinon. Ce qu'exécute le moteur, quand le dépôt range d'autres formats à côté : LinTO porte
    sa conversion `transformers` (`.safetensors`) près de l'archive `.nemo` qu'il déclare, et le
    format « dominant » du disque le disait `safetensors` (2026-11-08)."""
    from wama.model_manager.services.prospector import _WEIGHT_EXTS
    found = set()
    for component in ((composition or {}).get('components') or []) if isinstance(composition, dict) else []:
        if not isinstance(component, dict) or not component.get('pattern'):
            continue
        pattern = component['pattern'].lower()
        fmt = (component.get('format') or '').lower() or next(
            (ext.lstrip('.') for ext in _WEIGHT_EXTS if pattern.endswith(ext)), '')
        if fmt:
            found.add(fmt)
    return found.pop() if len(found) == 1 else ''


def conversion_suggestion(current_format: str, composition) -> str:
    """Le format vers lequel convertir un modèle au format `current_format`, ou '' : il n'y a
    rien à suggérer sans format recommandé, ni quand le modèle l'a déjà."""
    preferred = preferred_format(composition)
    if not preferred or not current_format:
        return ''
    return preferred if current_format.lower() != preferred else ''


def get_format_stats_template() -> Dict[str, int]:
    """Compteurs à zéro des formats de poids courants (un format absent s'y ajoute en comptant)."""
    return {
        'pt': 0,
        'pth': 0,
        'safetensors': 0,
        'onnx': 0,
        'bin': 0,
        'gguf': 0,
        'ckpt': 0,
        'unknown': 0,
    }
