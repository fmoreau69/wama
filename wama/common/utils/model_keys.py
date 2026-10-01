"""
Clé de CATALOGUE d'un modèle ↔ identifiant dans sa source — UNE sémantique pour tout WAMA.

La clé `AIModel.model_key` s'écrit `<source>:<identifiant>` : `imager:hunyuan-image-2.1`,
`huggingface:Bartholomheow/Supra2-IMG-ONNX`, `ollama:qwen3:4b`, `anonymizer:yolo:yolo11n.pt`.
**Seul le PREMIER segment est la source**, et une source se RECONNAÎT au vocabulaire
`ModelSource` — jamais à la forme de la chaîne.

POURQUOI UNE BRIQUE (2026-09-29, portage de l'imager sur la route F4b). La conversion était
réécrite une douzaine de fois, avec DEUX sémantiques qui divergent : `split(':', 1)[-1]` rend
`qwen3:4b` pour `ollama:qwen3:4b`, `rsplit(':', 1)[-1]` rend `4b` — juste pour un poids YOLO,
faux pour un tag Ollama. Et chaque app qui passait aux clés entières (synthesizer 09/01)
réécrivait sa propre tolérance à l'ancien identifiant nu (`engine_for_model`).

CE QU'ELLE NE FAIT PAS : départager un backend par `SUPPORTED_MODELS`. `backend_for_model`
compare le DERNIER segment (`yolo11n.pt`), une autre question — celle du vocabulaire d'un
backend, pas de l'espace de clés d'une app.
"""
from __future__ import annotations

#: Valeur d'un select de modèle qui demande le tirage au lancement (`auto_model.AUTO`).
AUTO = 'auto'
#: « auto » BORNÉ À UNE TÂCHE : `auto:text-to-music` (2026-10-01) — l'« auto » d'un GROUPE quand
#: un select réunit plusieurs tâches (composer : musique / ambiances). Jamais une clé de catalogue.
AUTO_TASK_PREFIX = 'auto:'


def auto_task(value) -> str:
    """La tâche d'un « auto » borné (`auto:text-to-music` → `text-to-music`), sinon ''."""
    value = (value or '').strip()
    return value[len(AUTO_TASK_PREFIX):] if value.startswith(AUTO_TASK_PREFIX) else ''
#: Préfixe des CANDIDATS de prospection (`prospect_ollama.PROPOSED_PREFIX`) — une source de fait.
PROPOSED = 'proposed'


def _known_sources() -> set:
    """Sources déclarées (`ModelSource`) + le préfixe des candidats. Import tardif : le module
    reste importable hors Django (un backend l'appelle), il ne reconnaît alors aucune source."""
    try:
        from wama.model_manager.models import ModelSource
        return set(ModelSource.values) | {PROPOSED}
    except Exception:
        return {PROPOSED}


def split_key(value: str) -> tuple:
    """`(source, identifiant)` — source vide quand la valeur n'est pas une clé de catalogue."""
    value = (value or '').strip()
    head, sep, tail = value.partition(':')
    if sep and head in _known_sources():
        return head, tail
    return '', value


def model_id(value: str) -> str:
    """L'identifiant DANS sa source : `imager:hunyuan-image-2.1` → `hunyuan-image-2.1`. Une
    valeur déjà nue est rendue telle quelle (lecture tolérante des lignes d'avant migration)."""
    return split_key(value)[1]


def catalog_key(value: str, default_source: str) -> str:
    """La clé de catalogue d'une valeur de modèle : une clé est rendue telle quelle, un
    identifiant nu reçoit `default_source` (l'app qui l'a écrit), `auto` et le vide restent.

    C'est la tolérance d'ENTRÉE d'une app passée aux clés entières : l'assistant, un fichier de
    lot, une ligne écrite avant la migration donnent encore l'identifiant nu."""
    value = (value or '').strip()
    if not value or value == AUTO or auto_task(value):
        return value
    source, _ = split_key(value)
    return value if source else f'{default_source}:{value}'
