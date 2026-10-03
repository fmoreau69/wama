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
    """Le modèle prend-il l'AUDIO du morceau à reprendre (cover) ? Capacité DÉCLARÉE
    (`work_audio`), plus le test d'un identifiant en dur (`musicgen-melody`, catalogue absent).

    Un « auto » de groupe suit la règle de `consumes_input` : oui si un modèle de sa tâche le
    déclare — le tirage choisira parmi eux (2026-10-03). Il répondait NON jusque-là : avec
    « auto », un audio joint était ignoré en silence à la création, alors que le tirage savait
    retenir MusicGen Melody pour une mélodie fournie."""
    key = normalize(value)
    return consumes_input(key, 'work_audio') or model_id(key) == 'musicgen-melody'


def consumes_input(value, token: str) -> bool:
    """Le modèle prend-il l'entrée `token` (capacité DÉCLARÉE au catalogue) ? Pour un « auto » de
    groupe : oui si AU MOINS UN modèle de sa tâche la déclare — le tirage choisira alors parmi
    eux (`auto_model.resolve_auto_model`, `consumes`). Le jugement est celui du sélecteur
    commun (`model_selector.matches_inputs`, `consumes`) — jamais une relecture des capacités
    ici. Ne lève jamais."""
    key = normalize(value)
    try:
        from wama.model_manager.models import AIModel
        from wama.model_manager.services.model_selector import matches_inputs
        task = auto_task(key)
        rows = (AIModel.objects.filter(capabilities__task=task) if task
                else AIModel.objects.filter(model_key=key))
        return any(matches_inputs(m, consumes=[token]) for m in rows.only('capabilities'))
    except Exception:
        return False


#: La tâche du modèle qui EXTRAIT la partition d'un audio (process `extract_score`, 2026-10-03).
SCORE_EXTRACTION_TASK = 'audio-to-score'


def score_extractor() -> str:
    """Clé de catalogue du modèle qui extrait la partition d'un audio — tirée par le sélecteur
    commun parmi les modèles INSTALLÉS de la tâche (VRAM du moment comprise), '' s'il n'y en a
    aucun. Jamais un nom de modèle ici."""
    from wama.model_manager.services.model_selector import select_model_id
    return select_model_id(source=None, task=SCORE_EXTRACTION_TASK, fallback='') or ''


def score_extraction_available() -> bool:
    """Un modèle d'extraction de partition est-il INSTALLÉ ? Requête simple, sans tirage : c'est la
    disponibilité (`ProcessSpec.available`) du process `extract_score`, lue pour chaque card."""
    try:
        from wama.model_manager.models import AIModel
        return AIModel.objects.filter(capabilities__task=SCORE_EXTRACTION_TASK, is_downloaded=True,
                                      is_available=True).exists()
    except Exception:
        return False


def covers_audio_by_score(value) -> bool:
    """Le modèle reprend-il un audio PAR SA PARTITION ? Il suit une partition (`work_score`) sans
    prendre l'audio lui-même (YuE2). Jugement du MODÈLE seul — que le process ait lieu dépend aussi
    de l'installation, ce que tranche `AppPipeline.takes_place`."""
    return consumes_input(value, 'work_score') and not consumes_melody(value)


def accepts_input(value, token: str) -> bool:
    """Le modèle, AU SEIN DU PIPELINE du composer, accepte-t-il l'entrée `token` ? Ce qu'il
    consomme, ou tout port par lequel le pipeline la lui amène (`AppPipeline.covering_inputs` :
    l'audio d'un cover, via la partition qu'en extrait `extract_score`). C'est la question que
    posent la création et l'outil de l'assistant — `consumes_input` reste celle du MODÈLE seul."""
    from wama.composer.function_specs import PIPELINE
    if token == 'work_audio' and consumes_melody(value):
        return True
    return any(consumes_input(value, port) for port in PIPELINE.covering_inputs(token))


def models_accepting(token: str, task: str) -> list:
    """Clés des modèles de `task` qui acceptent `token` au sein du pipeline — les CANDIDATS du
    tirage « auto » quand l'élément porte cette entrée. Le filtre `consumes` du sélecteur est un
    ET ; « prend l'audio, OU suit une partition qu'on en extrait » est un OU : il se pose ici, sur
    le jugement du sélecteur commun (`matches_inputs`), jamais en relisant les capacités."""
    from wama.composer.function_specs import PIPELINE
    try:
        from wama.model_manager.models import AIModel
        from wama.model_manager.services.model_selector import matches_inputs
        ports = PIPELINE.covering_inputs(token)
        rows = AIModel.objects.filter(capabilities__task=task).only('model_key', 'capabilities')
        return [m.model_key for m in rows
                if any(matches_inputs(m, consumes=[port]) for port in ports)]
    except Exception:
        return []


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
