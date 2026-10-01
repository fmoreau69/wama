"""
Le MODÈLE d'une génération du composer, en CLÉS DE CATALOGUE (route F4b, 2026-10-01).

Avant : un select peuplé depuis `COMPOSER_MODELS` (la liste de l'app) et des valeurs NUES
(`musicgen-small`, pseudo-valeurs `auto-music`/`auto-sfx`). Un modèle installé ailleurs — YuE2,
venu de la prospection (`huggingface:m-a-p/YuE2-3B`) — ne pouvait donc jamais y paraître.

Ici, UN SEUL endroit dit : la valeur canonique (`normalize`), sa tâche (`task_of`), le type
musique/bruitage qui s'en DÉRIVE (`generation_type`), si elle est admise (`is_valid`) et la
déclaration de l'app quand elle en a une (`config`). Le type n'est plus choisi : il découle du
modèle (décision du 2026-07-02, pas de switch de type), via la TÂCHE déclarée au catalogue.

Les deux « auto » de groupe sont l'« auto » borné à une tâche commun (`auto:<tâche>`) — la
décision « composer : un auto par groupe, groupé côté serveur, pas de 2 modes ».
"""
from wama.common.utils.model_keys import AUTO_TASK_PREFIX, auto_task, catalog_key, model_id, split_key

#: Le domaine du select : les deux tâches du composer, dans l'ordre des groupes.
MUSIC_TASK = 'text-to-music'
SFX_TASK = 'text-to-audio'
TASKS = (MUSIC_TASK, SFX_TASK)
AUTO_MUSIC = AUTO_TASK_PREFIX + MUSIC_TASK
AUTO_SFX = AUTO_TASK_PREFIX + SFX_TASK
#: Valeurs d'AVANT le passage aux clés (lignes, fichiers de lot, assistant) → leur forme actuelle.
LEGACY_AUTO = {'auto-music': AUTO_MUSIC, 'auto-sfx': AUTO_SFX, 'auto': AUTO_MUSIC}
#: Défaut d'une génération sans réglage : le modèle historique, désormais par sa clé.
DEFAULT_MODEL = 'composer:musicgen-small'


def normalize(value) -> str:
    """Valeur canonique : un « auto » de groupe, ou une clé de catalogue entière. Un identifiant
    nu (écrit avant le passage) est lu dans l'espace du composer ; le vide rend l'auto musique."""
    value = (str(value) if value is not None else '').strip()
    if not value:
        return AUTO_MUSIC
    if value in LEGACY_AUTO:
        return LEGACY_AUTO[value]
    return catalog_key(value, 'composer')


def _catalog_task(key: str) -> str:
    try:
        from wama.model_manager.models import AIModel
        row = AIModel.objects.filter(model_key=key).only('capabilities').first()
        return ((row.capabilities or {}).get('task') or '') if row else ''
    except Exception:
        return ''


def config(value) -> dict:
    """La déclaration de l'app (`COMPOSER_MODELS`) d'un modèle DU composer — {} pour un modèle
    venu d'ailleurs, qui n'en a pas (ses capacités vivent au catalogue)."""
    from wama.composer.utils.model_config import COMPOSER_MODELS
    key = normalize(value)
    source, ident = split_key(key)
    return dict(COMPOSER_MODELS.get(ident) or {}) if source == 'composer' else {}


def task_of(value) -> str:
    """La tâche du modèle : celle de l'auto de groupe, sinon celle DÉCLARÉE au catalogue, sinon
    celle que dit la déclaration de l'app (catalogue pas encore synchronisé)."""
    key = normalize(value)
    if auto_task(key):
        return auto_task(key)
    task = _catalog_task(key)
    if task:
        return task
    kind = config(key).get('type')
    return MUSIC_TASK if kind == 'music' else (SFX_TASK if kind else '')


def generation_type(value) -> str:
    """`music` / `sfx` — DÉRIVÉ de la tâche du modèle, jamais choisi."""
    return 'sfx' if task_of(value) == SFX_TASK else 'music'


def is_valid(value) -> bool:
    """La valeur désigne-t-elle un modèle du domaine du composer (ou l'un de ses deux auto) ?"""
    return task_of(value) in TASKS


def consumes_melody(value) -> bool:
    """Le modèle prend-il une mélodie de référence ? Capacité DÉCLARÉE (`reference_melody`),
    plus le test d'un identifiant en dur (`musicgen-melody`)."""
    key = normalize(value)
    if auto_task(key):
        return False
    try:
        from wama.model_manager.models import AIModel
        row = AIModel.objects.filter(model_key=key).only('capabilities').first()
        caps = (row.capabilities or {}) if row else {}
    except Exception:
        caps = {}
    accepted = set(caps.get('inputs_required') or []) | set(caps.get('inputs_optional') or [])
    return 'reference_melody' in accepted or model_id(key) == 'musicgen-melody'


def _accepted(caps) -> set:
    caps = caps or {}
    return set(caps.get('inputs_required') or []) | set(caps.get('inputs_optional') or [])


def consumes_input(value, token: str) -> bool:
    """Le modèle prend-il l'entrée `token` (capacité DÉCLARÉE au catalogue) ? Pour un « auto » de
    groupe : oui si AU MOINS UN modèle de sa tâche la déclare — le tirage choisira alors parmi
    eux (`auto_model.resolve_auto_model`, `consumes`). Ne lève jamais."""
    key = normalize(value)
    try:
        from wama.model_manager.models import AIModel
        task = auto_task(key)
        rows = (AIModel.objects.filter(capabilities__task=task) if task
                else AIModel.objects.filter(model_key=key))
        return any(token in _accepted(c) for c in rows.values_list('capabilities', flat=True))
    except Exception:
        return False


def label_of(value) -> str:
    """Libellé lisible : la description de l'app, sinon le nom du catalogue, sinon la valeur."""
    key = normalize(value)
    if auto_task(key):
        return 'Automatique — musique' if auto_task(key) == MUSIC_TASK else 'Automatique — ambiance'
    described = config(key).get('description')
    if described:
        return described
    try:
        from wama.model_manager.models import AIModel
        row = AIModel.objects.filter(model_key=key).only('name').first()
        if row and row.name:
            return row.name
    except Exception:
        pass
    return model_id(key) or key
