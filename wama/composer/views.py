"""
Composer Views — Music and SFX generation.
"""

import json
import logging
import os
from urllib.parse import urlsplit

from django.core.cache import cache
from django.http import JsonResponse
from django.shortcuts import render
from django.views import View
from django.views.decorators.http import require_POST, require_GET

from wama.accounts.views import get_or_create_anonymous_user
from wama.common.utils.console_utils import get_console_lines
from wama.common.utils.queue_duplication import safe_delete_file
from .models import ComposerBatch, ComposerBatchItem, ComposerGeneration
from .utils.model_choice import (AUTO_MUSIC, AUTO_SFX, DEFAULT_MODEL, accepts_input, is_valid,
                                 normalize)
from .utils.model_config import COMPOSER_MODELS, clamp_duration
from .utils import vocals

# Route F4b (2026-10-01) : le modèle est une CLÉ DE CATALOGUE (ou un « auto » de groupe), le type
# musique/bruitage s'en DÉRIVE au `save()` (utils/model_choice) — plus de pseudo-modèles propres
# au composer ni de liste de l'app pour valider.

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _batch_item_extra(generation: ComposerGeneration) -> dict:
    """Champs supplémentaires du lien batch↔génération : le nom de sortie vient de ce qui nomme
    l'ENTRÉE — le morceau repris (son fichier, ou son URL), sinon la consigne (la règle de la face
    Entrée, `apps.py`). Le prompt seul appelait « generation_aleatoire » un cover sans consigne
    (2026-11-03, un lot de 12 morceaux)."""
    source = generation.melody_reference or generation.reference_score
    named = source.name if source else urlsplit(generation.source_url or '').path
    stem = os.path.splitext(os.path.basename(named))[0] or generation.prompt[:30].replace(' ', '_')
    return {'output_filename': f"{stem or 'generation_aleatoire'}_{generation.id}.wav"}


def _wrap_generation_in_batch(generation: ComposerGeneration) -> ComposerBatch:
    """Wrap a standalone ComposerGeneration in a new ComposerBatch-of-1 (brique commune). Les
    modèles de lot sont ceux de l'app de la génération : une jumelle range dans les siens."""
    from django.apps import apps as django_apps
    from wama.common.utils.batch_common import wrap_in_batch
    app = generation._meta.app_label
    return wrap_in_batch(generation, batch_model=django_apps.get_model(app, 'ComposerBatch'),
                         item_model=django_apps.get_model(app, 'ComposerBatchItem'),
                         fk_name='generation', item_extra=_batch_item_extra)


def _auto_wrap_orphans(user):
    """Lazily wrap any ComposerGeneration not yet in a batch on page load (brique commune)."""
    from wama.common.utils.batch_common import auto_wrap_orphans
    auto_wrap_orphans(user, work_model=ComposerGeneration, batch_model=ComposerBatch,
                      item_model=ComposerBatchItem, fk_name='generation',
                      item_extra=_batch_item_extra)


#: Durée d'une génération quand rien ne la précise : le défaut du CHAMP (un seul lieu).
_DEFAULT_DURATION = float(ComposerGeneration._meta.get_field('duration').default)


def new_generation_settings(user, model=None, app='composer', post=None, inputs=None) -> dict:
    """Les colonnes de réglage d'une génération NAISSANTE, par la cascade COMMUNE (défauts du
    schéma ← réglages de l'auteur ← ce qui est posté, `user_settings.new_element_settings`,
    2026-10-18) — avant, cinq réglages relus avec leurs défauts recopiés ici, les autres au défaut
    du modèle. Les règles PROPRES au composer s'appliquent ensuite, chez l'appelant : le modèle
    normalisé et validé, la durée bornée par ce qu'il sait produire, la voix normalisée.
    `model`/`app` : une jumelle de bac à sable passe les siens."""
    from wama.common.utils.user_settings import new_element_settings
    from wama.composer.params import PARAMS_JSON, user_setting_key
    return new_element_settings(user, app, PARAMS_JSON, model or ComposerGeneration, post=post,
                                inputs=inputs,
                                key=user_setting_key)


def composer_rules(values) -> dict:
    """Les règles PROPRES au composer sur des réglages naissants (`new_generation_settings`) : la
    consigne n'en est pas un réglage, le modèle normalisé, la durée bornée par le schéma (le plafond
    du modèle se pose au lancement, `clamp_duration`), la voix normalisée. La validité du modèle
    reste à l'appelant. Lues par la card (`generate`) et par l'outil de l'assistant
    (`tool_api.compose_music`) — elles y étaient écrites deux fois (2026-10-29)."""
    values.pop('prompt', None)
    values['model'] = normalize(values.get('model'))
    values['duration'] = clamp_duration(values.get('duration'))
    values['vocals'] = vocals.normalize(values.get('vocals'))
    return values


#: Les ports du MORCEAU À REPRENDRE (cover) — ports de TRAVAIL depuis le 2026-10-03 —, le champ où
#: chacun se range (des données : ils gardent leur nom) et ce qu'il porte, dit dans un refus. Lus par
#: la card (`generate`), l'outil de l'assistant (`tool_api.compose_music`) et le lot
#: (`import_batch`) : la liste était écrite deux fois (2026-11-06).
COVER_PORTS = (('work_score', 'reference_score', 'de partition'),
               ('work_audio', 'melody_reference', "d'audio à reprendre"))
#: Le champ de chaque port, pour la brique des lignes de lot (`batch_parsers.line_file_inputs`).
COVER_FIELDS = {port: field for port, field, _what in COVER_PORTS}


def cover_refusal(model, port) -> str:
    """Le motif du refus quand `model` ne prend pas `port` au sein du pipeline (`accepts_input` :
    l'audio d'un cover est aussi pris par un modèle qui en suivra la partition extraite), `''` s'il
    le prend. Jamais ignoré en silence."""
    if accepts_input(model, port):
        return ''
    what = next(w for p, _f, w in COVER_PORTS if p == port)
    return (f"Le modèle « {model} » ne prend pas {what} — choisir un modèle qui le déclare, ou un "
            f"« auto » de groupe ('{AUTO_MUSIC}').")


def designated_cover(user, model, paths: dict, app: str = 'composer') -> list:
    """Les fichiers DÉSIGNÉS du morceau à reprendre, `{port: chemin}` → `[(entrée reçue, champ)]`,
    reçus par LA fonction de désignation (`media_paths.designate` : confinement, existence,
    lisibilité, puis pointer ou copier). Refusés AVANT toute création si le modèle ne prend pas le
    port (`cover_refusal`) : lève `InputRefused`."""
    from wama.common.utils.media_paths import InputRefused, designate
    received = []
    for port, field, _what in COVER_PORTS:
        path = (paths or {}).get(port)
        if not path:
            continue
        refusal = cover_refusal(model, port)
        if refusal:
            raise InputRefused(refusal)
        received.append((designate(path, user, app), field))
    return received


def _remember_settings(user, post):
    """Ce que le volet a posté devient la mémoire du volet (`save_panel_settings`) — APRÈS la
    validation : un modèle refusé ne doit pas devenir la préférence qui ferait échouer les
    dépôts suivants."""
    from wama.common.utils.user_settings import save_panel_settings
    from wama.composer.params import PARAMS_JSON, user_setting_key
    save_panel_settings(user, 'composer', PARAMS_JSON, post, key=user_setting_key)


def _reset_for_relaunch(gen, only=None):
    """Remise à zéro avant (re)lancement — appliquée SOUS le verrou anti-race (begin_processing).

    ⚠ `planned_score` (et `extracted_score`) n'est PAS remis à zéro : c'est le résultat du process `plan`, qu'un
    lancement REPREND quand il vaut encore (`function_specs.PIPELINE`) — le moteur le réécrit
    quand il rejoue ce process.
    `only` (P5, ▶ par process) : lancement BORNÉ — seules les sorties DÉCLARÉES de ce process
    sont remplacées (`PIPELINE.reset_outputs`) : relancer la partition seule n'emporte pas
    l'audio, qui se périmera de lui-même."""
    from .function_specs import PIPELINE
    # ⚠ Un lancement COMPLET ne retire plus l'audio au clic (2026-10-03) : il ne rejoue que ce
    # qui n'est plus à jour, et un format changé ne rejoue que la sortie — depuis l'audio que le
    # rendu a laissé. C'est la glu du rendu qui remplace l'audio quand elle rejoue.
    if only:
        PIPELINE.reset_outputs(gen, (only,))
    gen.progress = 0
    gen.error_message = None
    gen.exported_to_library = False


# ── Les vues de lot du composer : fabrique COMMUNE (`batch_views.make_batch_views`, portage
# 2026-09-23, 5ᵉ app réelle — ROUTE §11 #36). Spécificités DÉCLARÉES en kwargs : ▶ de lot ne
# lance QUE les PENDING (« créer ≠ démarrer », contrat WamaBatchImport) ;
# `task_id` nullable ; `exported_to_library` remis à False ; la ligne de liaison de la copie
# reprend l'`output_filename` de l'original (`item_extra`), le lot copié partage le fichier de
# lot (`batch_extra`) ; cache de progression purgé à la suppression ; le nom de chaque fichier
# de l'archive est celui de la ligne de liaison (`batch_link.output_filename`, posé par
# `batch_elements` depuis le 23/09 — `batch_download` restait local pour cette seule raison).
# `batch_update` vient AUSSI de la fabrique depuis le 2026-10-02 : elle lit le posté selon le
# schéma et appelle `_apply_generation_settings`, la fonction de la route d'élément (validation
# du modèle contre le catalogue, curseur — `generation_type` se dérive au `save()`).
from wama.common.utils.batch_views import make_batch_views


def _get_user(request):
    return request.user if request.user.is_authenticated else get_or_create_anonymous_user()


def _task_for(gen):
    from .tasks import compose_task
    return compose_task


def _link_name(gen):
    return getattr(getattr(gen, 'batch_link', None), 'output_filename', '') or ''


def _copy_link_extra(new_gen, old_gen):
    return {'output_filename': _link_name(old_gen) or _batch_item_extra(new_gen)['output_filename']}


from wama.composer.params import PARAMS_JSON as _SETTINGS_SCHEMA  # noqa: E402

_bv = make_batch_views(
    work_model=ComposerGeneration, batch_model=ComposerBatch, get_user=_get_user,
    task_for=_task_for, start_only_pending=True,
    item_model=ComposerBatchItem, fk_name='generation',
    reset_on_start=_reset_for_relaunch,
    reset_on_duplicate={'status': 'PENDING', 'progress': 0, 'task_id': None,
                        'error_message': '', 'exported_to_library': False},
    item_extra=_copy_link_extra,
    batch_extra=lambda lot: {'batch_file': lot.batch_file.name} if lot.batch_file else {},
    on_delete=lambda gen: cache.delete(f'composer_progress_{gen.id}'),
    output_field='audio_output', output_name=_link_name,
    zip_name=lambda lot: f"batch_composer_{lot.pk}.zip",
    schema=_SETTINGS_SCHEMA,
    apply_settings=lambda gen, data: _apply_generation_settings(gen, data),
)
batch_start = _bv['batch_start']
batch_delete = _bv['batch_delete']
batch_duplicate = _bv['batch_duplicate']
batch_download = _bv['batch_download']
batch_update = _bv['batch_update']
batch_promote = _bv['batch_promote']
batch_realign = _bv['batch_realign']


def _decorate_generation(g, preloaded=False):
    """Chips de card générés du SCHÉMA (params.py chip=True) — brique commune card_chips ;
    PROCESS de la card et état MONTRÉ, générés des lignes d'exécution (P5, `_pipeline_view`)."""
    from wama.common.utils.card_chips import chips_by_section
    from wama.composer.params import PARAMS_JSON
    g.chips = chips_by_section(g, PARAMS_JSON)
    g.processes, g.shown_state, g.shown_state_label = _pipeline_view(g, preloaded=preloaded)
    return g


def _pipeline_view(gen, preloaded=False):
    """Ce que la card et la vue de progression montrent du PIPELINE de l'élément (ROUTE §10.6
    5.1) : ses lignes de process et l'état déduit — par l'adaptateur unique
    (`AppPipeline.shown_state`), jamais `status` en dur. Sous « auto » le modèle du prochain
    lancement n'est pas connu : on montre ce qui a tourné."""
    from wama.common.services.process_pipeline import card_view
    return card_view(gen, preloaded=preloaded)


def _get_batches_list(user):
    """Agrégats de file pour le template — brique commune (contrat toolbar queue_view.py)."""
    from wama.common.utils.batch_common import build_batches_list
    _auto_wrap_orphans(user)
    from wama.common.utils.card_chips import common_chips_for_items
    from wama.composer.params import PARAMS_JSON as _COMPOSER_PARAMS_JSON
    batches = build_batches_list(user, batch_model=ComposerBatch, work_attr='generation',
                                 order_by='-created_at',
                                 has_output=lambda g: bool(g.audio_output),
                                 # Réglages COMMUNS aux filles de la card mère (slot
                                 # meta_template — porté le 31/08) ; l'ETA agrégée
                                 # (`eta_ids`) vient de `build_batches_list`.
                                 extra=lambda b, items, gens: {
                                     'common_chips': common_chips_for_items(
                                         gens, _COMPOSER_PARAMS_JSON)})
    # Chips de card GÉNÉRÉS du schéma — même décoration que card_html. Les lignes d'exécution de
    # TOUTES les cards de la page sont lues en une requête (bande des process).
    from wama.common.services.process_pipeline import decorate_cards
    decorate_cards([link.generation for b in batches for link in b['items']],
                   _decorate_generation)
    return batches


# Manipulation directe de la file (CARD_DESIGN §3bis) — vues GÉNÉRÉES par la brique
# commune queue_manipulation (composer n'en avait AUCUNE, audit 2026-07-06).
from wama.common.utils.queue_manipulation import make_queue_manipulation_views

_qm = make_queue_manipulation_views(
    work_model=ComposerGeneration, batch_model=ComposerBatch,
    item_model=ComposerBatchItem, fk_name='generation',
    get_user=lambda r: r.user if r.user.is_authenticated else get_or_create_anonymous_user(),
    item_extra=_batch_item_extra,
)
remove_from_batch = _qm['remove_from_batch']
reorder = _qm['reorder']
reorder_queue = _qm['reorder_queue']
merge = _qm['merge']
move_to_batch = _qm['move_to_batch']
consolidate = _qm['consolidate']


# ---------------------------------------------------------------------------
# Main page
# ---------------------------------------------------------------------------

class IndexView(View):
    def get(self, request):
        user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()

        # Réconcilie les éléments RUNNING orphelins (worker mort/crash) — LA brique commune.
        from wama.common.utils.process_control import reconcile_queue_of
        reconcile_queue_of(ComposerGeneration, user)

        batches_list = _get_batches_list(user)

        # Tri + filtrage de la file — brique COMMUNE (persistés en session).
        from wama.common.utils.queue_view import apply_queue_sort_filter

        def _name(b):
            if b['obj'].total == 1 and b['items'] and b['items'][0].generation:
                g = b['items'][0].generation
                return (g.prompt or '').lower() or f"generation {g.id:08d}"
            return f"batch {b['obj'].id:08d}"
        batches_list, q_sort, q_filter = apply_queue_sort_filter(
            request, batches_list, name_of=_name)

        # queue_count = TOTAL d'items (badge d'onglet commun, sémantique transcriber) ;
        # active_count = en attente/en cours (amorçage de la barre globale côté JS).
        queue_count = sum(len(b['items']) for b in batches_list)
        active_count = sum(
            1 for b in batches_list
            for item in b['items']
            if item.generation and item.generation.status in ('PENDING', 'RUNNING')
        )

        import json
        from .params import PARAMS_JSON as _COMPOSER_PARAMS_JSON
        return render(request, 'composer/index.html', {
            'batches_list': batches_list,
            'queue_count': queue_count,
            'active_count': active_count,
            'q_sort': q_sort,
            'q_filter': q_filter,
            # Estimation côté JS : facteurs des modèles DU composer, indexés par la valeur même
            # des options (la clé de catalogue).
            'all_models': {f'composer:{mid}': cfg for mid, cfg in COMPOSER_MODELS.items()},
            'params_json': json.dumps(_COMPOSER_PARAMS_JSON),
            # Appariement card↔modèles (WamaInputMatch) : besoins d'entrées par modèle depuis le
            # CATALOGUE + libellés d'INPUT_TYPES. Cf. INPUT_MODEL_MATCHING.md.
            'input_match_meta': json.dumps(_input_match_meta()),
            'input_labels': json.dumps(_input_labels()),
        })


# ---------------------------------------------------------------------------
# Generate single item
# ---------------------------------------------------------------------------

@require_POST
def generate(request):
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()

    # Prompt VIDE autorisé = génération ALÉATOIRE (inconditionnelle — le modèle improvise).
    # L'UI l'annonce dans le placeholder de la card d'entrée (INPUT_MODEL_MATCHING.md).
    prompt = request.POST.get('prompt', '').strip()

    # Réglages : la cascade COMMUNE (défauts du schéma ← réglages de l'auteur ← le POST), puis les
    # règles du composer (`composer_rules`) ; le modèle est validé.
    settings_values = composer_rules(new_generation_settings(user, post=request.POST))
    model_id = settings_values['model']
    if not is_valid(model_id):
        return JsonResponse({'error': 'Modèle invalide'}, status=400)

    # Le MORCEAU À REPRENDRE (cover) — ports de TRAVAIL depuis le 2026-10-03 (décision de Fabien) :
    # l'audio de MusicGen Melody (`work_audio`) et la partition de YuE2 (`work_score`). Chacun est
    # reçu sous le nom de son PORT, téléversé ou DÉSIGNÉ (brique `received_inputs` : une
    # désignation se POINTE), et rangé dans son champ — les champs, des données stockées, gardent
    # leur nom (`melody_reference`, `reference_score`). Joint si le modèle le DÉCLARE (un « auto »
    # le fera tirer parmi ceux qui le consomment).
    # Reçus AVANT la création (2026-10-13) : une désignation REFUSÉE (fichier d'un autre) était
    # ignorée en silence — la card naissait sans le morceau, sans un mot. Elle refuse désormais
    # l'ajout avec son motif, comme l'imager et l'avatarizer, et rien n'est créé.
    from wama.common.utils.media_paths import received_inputs
    # « Le modèle le déclare » s'entend AU SEIN DU PIPELINE : l'audio d'un cover est aussi joint
    # pour un modèle qui en suivra la partition extraite (`accepts_input`, 2026-10-03).
    joined = []
    for port, field, _what in COVER_PORTS:
        if not accepts_input(model_id, port):
            continue
        received = received_inputs(request, user, 'composer', field=port)
        if received:
            joined.append((received[0], field))
        elif received.refusal:
            return JsonResponse({'error': received.refusal}, status=400)

    # Le morceau à reprendre PROPOSE ses réglages (`default_from` : sa durée, 2026-10-29) — la
    # naissance refaite avec lui ; le modèle, déjà choisi pour juger les ports, reste celui-là. Un
    # réglage POSTÉ l'emporte toujours (la card le lit déjà côté navigateur).
    from wama.common.utils.user_settings import inputs_by_port
    inputs = inputs_by_port('composer', *(received for received, _ in joined))
    if inputs:
        proposed = composer_rules(new_generation_settings(user, post=request.POST, inputs=inputs))
        settings_values.update({k: v for k, v in proposed.items() if k != 'model'})

    gen = ComposerGeneration.objects.create(
        **settings_values,
        user=user,
        prompt=prompt,   # la consigne de la card, nettoyée — jamais une préférence
        # Mélodie par URL (WAMA_INGEST) : téléchargée en tête de tâche par ensure_local_input.
        source_url=request.POST.get('source_url', '').strip(),
    )

    # Ce que le volet a posté devient la mémoire des prochaines générations.
    _remember_settings(user, request.POST)

    for received, field in joined:
        received.assign(gen, field)

    # Wrap in batch-of-1
    _wrap_generation_in_batch(gen)

    # AJOUTE à la file, ne lance RIEN (2026-09-29 — règle des deux temps, CARD_DESIGN §11.11
    # Étape 3, point 3 : « on ajoute, on règle, puis on lance »). Cette vue expédiait
    # `compose_task` à la création ; le ▶ de la card (`start`, `begin_processing`) lance.
    return JsonResponse({
        'id': gen.id,
        'status': gen.status,
        'model': gen.model,
        'model_label': gen.get_model_label(),
        'generation_type': gen.generation_type,
        'prompt': gen.prompt,
        'duration': gen.duration,
    })


# ---------------------------------------------------------------------------
# Import batch file
# ---------------------------------------------------------------------------

def batch_template(request):
    """Template batch téléchargeable, GÉNÉRÉ depuis la déclaration des champs (brique
    commune build_batch_template — plus de contenu en dur, A5-23). NB : la colonne de
    nom de fichier est « sortie » (l'alias « fichier » désigne l'ENTRÉE dans le
    vocabulaire commun ; l'ordre positionnel hérité reste sortie|prompt|modèle|durée).
    Servi par `batch_template_response` (le nom de fichier commun, 2026-11-02)."""
    from wama.common.utils.batch_parsers import batch_template_response
    return batch_template_response(
        'composer', ['sortie', 'prompt', 'modele', 'duree'],
        {'sortie': 'piano.wav', 'prompt': 'upbeat jazz piano with soft drums',
         'modele': 'musicgen-small', 'duree': 30},
        label='Composer (musique / bruitages)')


@require_POST
def batch_preview(request):
    """Aperçu d'un fichier batch (contrat WamaBatchImport) : parse SANS créer.

    Réponse : {'count', 'items': [{'filename', 'path'}], 'warnings'} — le tableau de la
    detect bar affiche item.filename (title = item.path, ici le prompt)."""
    if 'batch_file' not in request.FILES:
        return JsonResponse({'error': 'Aucun fichier batch fourni'}, status=400)
    batch_file = request.FILES['batch_file']

    import tempfile
    from .utils.batch_parser import parse_batch_file
    suffix = os.path.splitext(batch_file.name)[1] or '.txt'
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        for chunk in batch_file.chunks():
            tmp.write(chunk)
        tmp_path = tmp.name
    try:
        tasks, warnings = parse_batch_file(
            tmp_path, DEFAULT_MODEL, _DEFAULT_DURATION, source_name=batch_file.name)
    except Exception as exc:
        return JsonResponse({'error': str(exc)}, status=400)
    finally:
        try:
            os.remove(tmp_path)
        except OSError:
            pass

    items = [{'filename': t['output_filename'], 'path': t['prompt']} for t in tasks]
    return JsonResponse({'count': len(items), 'items': items, 'warnings': warnings})


def _batch_line(user, post, task_data, default_model, default_duration, warnings):
    """UNE ligne de lot → `(ligne, réglages, fichiers reçus, adresses)`, ou None (raison ajoutée à
    `warnings`). La ligne POSTE ses réglages comme un dépôt (`given` : son modèle, sa durée), sur
    ceux du lot ; la cascade commune et les règles du composer font le reste, comme `generate`.

    Son MORCEAU À REPRENDRE (`-r`, 2026-11-06) se reçoit comme sur la card, par la brique commune
    des lignes de lot (`batch_parsers.line_file_ports` / `line_file_inputs`) : il va au port de sa
    nature (audio ou partition), un chemin se DÉSIGNE, une URL devient la source téléchargée
    (`WAMA_INGEST`) ; sa durée PROPOSE celle de la card (`default_from`) quand la ligne n'en dit pas.
    Jusque-là la référence était lue puis PERDUE, et elle imposait MusicGen Melody par son nom.
    Une ligne qui ne nomme pas de modèle passe à l'« auto » de sa tâche quand celui du lot ne prend
    pas ce qu'elle donne : le tirage retient l'un de ceux qui le prennent (`models_accepting`)."""
    from wama.common.utils.auto_model import is_auto
    from wama.common.utils.batch_parsers import line_file_inputs, line_file_ports
    from wama.common.utils.model_keys import AUTO_TASK_PREFIX
    from wama.common.utils.user_settings import inputs_by_port
    from .utils.model_choice import task_of
    given = task_data.get('given')
    if given is None:      # format positionnel `nom|prompt|modèle|durée` : tout y est donné
        given = {'model': task_data['model'], 'duration': task_data['duration']}
    line_post = {name: post.get(name) for name in post}
    line_post.update({'model': default_model, 'duration': default_duration, **given})
    model = normalize(line_post['model'])
    reference = (task_data.get('reference') or '').strip()
    try:
        files = line_file_ports('composer', {'reference': reference,
                                             'line_num': task_data.get('line_num')}) if reference else {}
        if (files and 'model' not in given and not is_auto(model)
                and any(cover_refusal(model, port) for port in files)):
            model = AUTO_TASK_PREFIX + task_of(model)
        refusal = next((r for r in (cover_refusal(model, port) for port in files) if r), '')
        if refusal:
            raise ValueError(refusal)
        received, remote = line_file_inputs(user, 'composer', files, COVER_FIELDS,
                                            model=ComposerGeneration)
    except ValueError as exc:            # `InputRefused` compris : une désignation refusée
        warnings.append(f"Ligne {task_data.get('line_num') or '?'} : {exc} — ignorée")
        return None
    line_post['model'] = model
    inputs = inputs_by_port('composer', *received.values())
    if inputs and 'duration' not in given:
        line_post.pop('duration')       # le morceau repris propose sa durée (`default_from`)
    values = composer_rules(new_generation_settings(user, post=line_post, inputs=inputs))
    return task_data, values, received, remote


@require_POST
def import_batch(request):
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()

    if 'batch_file' not in request.FILES:
        return JsonResponse({'error': 'Aucun fichier batch fourni'}, status=400)

    batch_file = request.FILES['batch_file']

    # Chaque génération du lot naît par la cascade COMMUNE ; une ligne qui précise son modèle ou sa
    # durée les impose, sinon ceux du lot (`default_model` / `default_duration`), sinon la cascade.
    base = new_generation_settings(user, post=request.POST)
    base.pop('prompt', None)
    default_model = normalize(request.POST.get('default_model') or base.get('model'))
    if not is_valid(default_model):
        default_model = normalize(base.get('model'))
    try:
        default_duration = clamp_duration(float(request.POST.get('default_duration')
                                                or base.get('duration')))
    except (ValueError, TypeError):
        default_duration = clamp_duration(base.get('duration'))

    # Save batch file temporarily to parse it
    from django.conf import settings
    import uuid
    import shutil
    from wama.common.utils.media_paths import app_media_dir
    tmp_dir = os.path.join(settings.MEDIA_ROOT,
                           app_media_dir('composer', user.id, 'batch_imports'))
    os.makedirs(tmp_dir, exist_ok=True)
    tmp_path = os.path.join(tmp_dir, f"batch_{uuid.uuid4().hex[:8]}_{batch_file.name}")
    with open(tmp_path, 'wb') as f:
        for chunk in batch_file.chunks():
            f.write(chunk)

    try:
        from .utils.batch_parser import parse_batch_file
        tasks, warnings = parse_batch_file(
            tmp_path, default_model, default_duration, source_name=batch_file.name,
        )
    except Exception as exc:
        os.remove(tmp_path)
        return JsonResponse({'error': str(exc)}, status=400)

    # Chaque ligne se JUGE avant que rien ne soit créé : ses réglages, son morceau à reprendre.
    lines = [line for line in (_batch_line(user, request.POST, task_data, default_model,
                                           default_duration, warnings) for task_data in tasks)
             if line]
    if not lines:
        os.remove(tmp_path)
        return JsonResponse({
            'error': 'Aucune tâche valide dans le fichier batch',
            'warnings': warnings,
        }, status=400)

    # Create batch container
    batch = ComposerBatch.objects.create(user=user, total=len(lines))
    # Save the batch file on the batch object
    rel_path = os.path.relpath(tmp_path, settings.MEDIA_ROOT)
    batch.batch_file = rel_path
    batch.save(update_fields=['batch_file'])

    # Créer SANS lancer (contrat WamaBatchImport : créer ≠ démarrer ; l'auto-start passe par
    # batch_start, appelé par afterCreate — avant, le serveur lançait tout inconditionnellement
    # et « Créer seulement » était illusoire + double lancement avec l'auto-start client).
    created_ids = []
    from wama.common.utils.batch_parsers import attach_line_inputs
    for task_data, values, received, remote in lines:
        gen = ComposerGeneration.objects.create(
            **values,
            user=user,
            prompt=task_data['prompt'],
        )
        attach_line_inputs(gen, received, remote)
        ComposerBatchItem.objects.create(
            batch=batch,
            generation=gen,
            output_filename=task_data['output_filename'],
            row_index=task_data['line_num'],
        )
        created_ids.append(gen.id)

    return JsonResponse({
        'batch_id': batch.id,
        'total': batch.total,
        'created': created_ids,
        'warnings': warnings,
    })


# ---------------------------------------------------------------------------
# Update individual settings
# ---------------------------------------------------------------------------

# ▶ de la card (relance sans changer les réglages), ▶ et 🗑 de la file : fabrique COMMUNE
# (`item_views.make_item_views`, ROUTE §11 #39, 2026-10-29) — la même déclaration que lit l'outil
# `start_composer`. « Tout lancer » relance aussi les ÉCHECS : la règle du bouton, que l'outil
# de l'assistant ne suivait pas (il ne lançait que l'attente).
from wama.common.utils.item_views import make_item_views  # noqa: E402

_iv = make_item_views(work_model=ComposerGeneration, app_id='composer', task_for=_task_for,
                      reset_on_start=_reset_for_relaunch,
                      pending={'status__in': ('PENDING', 'FAILURE')}, batch_model=ComposerBatch,
                      item_empty_is_value=('lyrics',))
start = _iv['start']
start_all = _iv['start_all']
clear_all = _iv['clear_all']
# ⏹ ⬇ 🗑 ⧉ ⚙ d'une card : la fabrique COMMUNE (2026-11-02, ROUTE §11 #42 ④), qui lit ce que l'app
# déclare à sa fabrique de lot. Spécificité déclarée : des paroles VIDÉES s'effacent sur la card
# (au lot, vide = ne pas toucher). « Enregistrer et relancer » enchaîne le ▶ côté page, comme les
# autres apps : la vue de réglages relançait elle-même (`restart=1`).
stop = _iv['stop']
update_settings = _iv['update_settings']
download = _iv['download']
delete = _iv['delete']
duplicate = _iv['duplicate']


from wama.common.utils.process_views import make_process_start_view  # noqa: E402

# ▶ d'UN process de la card (P5, `ROUTE §10.6` 5.1) : fabrique COMMUNE. Seules les sorties
# DÉCLARÉES du process lancé sont remplacées (`_reset_for_relaunch(gen, only)`).
start_process = make_process_start_view(
    work_model=ComposerGeneration, task_for=_task_for, reset_for_process=_reset_for_relaunch)


def _input_match_meta():
    """Meta commune (brique `input_match`) sur le DOMAINE du select (les deux tâches) + les deux
    « auto » de groupe (POLITIQUE composer).

    Route F4b (2026-10-01) : bornée par la TÂCHE, la meta est clée sur les clés de catalogue
    entières — les valeurs mêmes des options (un modèle venu d'ailleurs, YuE2, y entre). Ne reste
    ici que l'union par groupe des « auto » — l'auto accepte ce qu'au moins UN candidat de son
    groupe accepte ; la résolution au lancement (utils/auto_model.py) restreint ensuite.
    """
    from wama.common.utils.input_match import input_match_meta
    from .utils.model_choice import SFX_TASK, TASKS
    meta = input_match_meta(task=','.join(TASKS), extra_caps=('task',))
    if not meta:
        return {}
    # Ce que le PIPELINE ajoute (2026-10-03) : les entrées qu'un process amont fabrique pour le
    # modèle (YuE2 suit une partition → il accepte l'audio d'un cover, dont `extract_score` la
    # tire). Règle GÉNÉRIQUE, dérivée des déclarations (`AppPipeline.extended_inputs`).
    from .function_specs import PIPELINE
    for entry in meta.values():
        accepted = set(entry['inputs_required']) | set(entry['inputs_optional'])
        added = PIPELINE.extended_inputs(accepted) - accepted
        if added:
            entry['inputs_optional'] = sorted(set(entry['inputs_optional']) | added)
    unions = {AUTO_MUSIC: set(), AUTO_SFX: set()}
    for entry in meta.values():
        auto_id = AUTO_SFX if entry.pop('task', None) == SFX_TASK else AUTO_MUSIC
        unions[auto_id] |= set(entry['inputs_required']) | set(entry['inputs_optional'])
    for auto_id, accepted in unions.items():
        meta[auto_id] = {'inputs_required': [], 'inputs_optional': sorted(accepted)}
    return meta


def _input_labels():
    """DÉLÉGUÉ à la brique commune (extraction 2026-08-17) — conservé pour les appels locaux."""
    from wama.common.utils.input_match import input_labels
    return input_labels()


# Curseur POSTÉ (chantier C) : lecteur COMMUN — None quand il n'est pas posté. La copie locale
# (identique chez imager et enhancer) est remontée dans la brique le 2026-09-21.
from wama.common.utils.auto_model import posted_quality_intent as _intent_posted  # noqa: E402


def _apply_generation_settings(gen, data):
    """LES réglages d'une génération, posés sans sauver — la route d'un élément
    (`update_settings`) ET la fabrique des vues de lot passent ici. Jusqu'au 2026-10-02 la vue de
    lot relisait `request.POST` à côté : un modèle invalide y était ignoré en silence, là où la
    route d'élément le refuse. Un réglage refusé lève `ValueError` (400 ; au lot, aucune fille
    écrite). Rend `None` : tout l'élément est sauvé — le type musique/bruitage se DÉRIVE du
    modèle au `save()` (utils/model_choice)."""
    model_id = normalize(data.get('model', gen.model))
    if not is_valid(model_id):
        raise ValueError('Modèle invalide')
    gen.model = model_id
    try:
        gen.duration = clamp_duration(float(data.get('duration', gen.duration)))
    except (ValueError, TypeError):
        pass                    # durée illisible : celle de l'élément reste
    if str(data.get('quality_intent', '')) != '':
        gen.quality_intent = _intent_posted(data)
    # Voix : une valeur hors de ses choix est IGNORÉE (contrat commun des routes de réglages,
    # `tests_item_settings_contract`) — jamais écrite.
    if data.get('vocals') in vocals.VALUES:
        gen.vocals = data['vocals']
    # Paroles de la card (2026-10-04) : posées, corrigées ou EFFACÉES (le vide est une valeur —
    # `empty_is_value` à la lecture). Non postées (lot, inspecteur) : intactes.
    if 'lyrics' in data:
        gen.lyrics = str(data.get('lyrics') or '').strip()
    # Prompt éditable (modale complète P1) — on ne l'écrase pas s'il est vide. Champ à DEUX ÉTATS
    # (2026-10-04, la route de l'imager) : `apply_prompt_state` dit dans quel champ écrire — éditer
    # l'enrichi garde l'original ; reprendre son prompt rend l'enrichi périmé, donc vidé.
    prompt = data.get('prompt')
    if prompt is not None and str(prompt).strip():
        from wama.common.utils.app_metadata import apply_prompt_state
        apply_prompt_state(gen, 'prompt', str(prompt).strip(), data.get('prompt_state'))
    # Format/qualité de sortie (early-binding, per-item) si fournis
    if data.get('output_format'):
        gen.output_format = data['output_format']
    if data.get('output_quality'):
        gen.output_quality = data['output_quality']
    # Les AUTRES réglages du schéma, colonnes sans règle propre (la case « Partition complète »…),
    # par la brique commune — valeur hors choix ignorée. Écrits champ par champ, ils étaient tous à
    # recopier ici : `extract_parts` (2026-10-16) ne l'avait pas été, la case cochée dans la modale
    # ⚙ revenait à « non » et le process `parts` ne jouait pas (vécu sur #849, 2026-10-19).
    from wama.common.utils.batch_views import apply_item_settings
    apply_item_settings(gen, data, params_fields=_plain_settings())
    return None


#: Les réglages que `_apply_generation_settings` écrit avec une règle PROPRE (validation du modèle,
#: durée bornée, curseur, voix, paroles vidables, prompt à deux états, sortie non vide).
_SETTINGS_WITH_RULES = frozenset({'model', 'duration', 'quality_intent', 'vocals', 'lyrics',
                                  'prompt', 'output_format', 'output_quality'})


def _plain_settings():
    """Les réglages du schéma qui sont des colonnes de la génération sans règle propre."""
    columns = {f.name for f in ComposerGeneration._meta.concrete_fields}
    return [p['name'] for p in _SETTINGS_SCHEMA
            if p['name'] in columns and p['name'] not in _SETTINGS_WITH_RULES]


# ---------------------------------------------------------------------------
# Progress
# ---------------------------------------------------------------------------

def _progress_extra(gen):
    """Les clés PROPRES que le JS du composer lit : le résultat, une fois produit."""
    if gen.status != 'SUCCESS' or not gen.audio_output:
        return {}
    from django.urls import reverse
    return {'download_url': reverse('composer:download', args=[gen.id]),
            'audio_url': gen.audio_output.url, 'exported': gen.exported_to_library}


# Les vues de PROGRESSION : fabrique COMMUNE (`progress_views.make_progress_views`, ROUTE §11 #37,
# 2026-10-03) — l'app n'y déclare que ses clés propres. L'ETA est celle de ses PROCESS, a priori
# du catalogue compris (`function_specs.PIPELINE`, 2026-10-05).
from wama.common.utils.progress_views import make_progress_views  # noqa: E402

_pv = make_progress_views(work_model=ComposerGeneration, app_id='composer',
                          extra=_progress_extra)
progress = require_GET(_pv['progress'])
global_progress = _pv['global_progress']


# ---------------------------------------------------------------------------
# Export to media library — RETIRÉ (2026-09-18, décision Fabien ; `REMOVAL_LEDGER R64`)
# ---------------------------------------------------------------------------
# La route `export/<pk>/` était une SECONDE PORTE du geste commun (elle déléguait déjà à
# `media_library.services.export_item_to_library` depuis le 12/09) : plus de front depuis le
# retrait du bouton dédié, GET des rôles/état et retrait absents, et un refus du double export
# que la brique fait déjà par provenance. Le seul savoir qu'elle portait — une génération
# `music` est une musique, le reste un bruitage — est DÉCLARÉ dans le détail canonique
# (`apps.py`, `result_role`) et lu par le geste commun, pour toutes les apps.


# ⬇ « Télécharger tout » de la barre de file : le ZIP de la file que compte la barre globale,
# par la fabrique commune (`make_progress_views`, 2026-10-17 — REMOVAL_LEDGER R142).
download_all = _pv['download_all']


# ---------------------------------------------------------------------------
# Console & global progress
# ---------------------------------------------------------------------------

def console_content(request):
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
    lines = get_console_lines(user.id, app='composer')
    return JsonResponse({'lines': lines})


# Card RENDUE serveur — SOURCE UNIQUE du markup (partial _generation_card.html), consommée à la
# création et en fin de tâche : fabrique commune (`make_card_view`, 2026-11-02), qui pose
# `card_label` (le nom de sortie de la ligne de lot) pour toutes les apps — il ne l'était qu'ici.
from wama.common.utils.item_views import make_card_view  # noqa: E402

card_html = make_card_view(work_model=ComposerGeneration, template='composer/_generation_card.html',
                           decorate=lambda gen: _decorate_generation(gen))


