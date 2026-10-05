"""
Composer Views — Music and SFX generation.
"""

import json
from wama.accounts.permissions import app_access
import logging
import os

from django.core.cache import cache
from django.http import FileResponse, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.views import View
from django.views.decorators.http import require_POST, require_GET
from django.utils.http import content_disposition_header

from wama.accounts.views import get_or_create_anonymous_user
from wama.common.utils.console_utils import get_console_lines
from wama.common.utils.queue_duplication import safe_delete_file, duplicate_instance, release_card_files
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
    """Champs supplémentaires du lien batch↔génération (nom de sortie dérivé du prompt)."""
    stem = os.path.splitext(generation.prompt[:30].replace(' ', '_'))[0] or 'generation_aleatoire'
    return {'output_filename': f"{stem}_{generation.id}.wav"}


def _wrap_generation_in_batch(generation: ComposerGeneration) -> ComposerBatch:
    """Wrap a standalone ComposerGeneration in a new ComposerBatch-of-1 (brique commune)."""
    from wama.common.utils.batch_common import wrap_in_batch
    return wrap_in_batch(generation, batch_model=ComposerBatch, item_model=ComposerBatchItem,
                         fk_name='generation', item_extra=_batch_item_extra)


def _auto_wrap_orphans(user):
    """Lazily wrap any ComposerGeneration not yet in a batch on page load (brique commune)."""
    from wama.common.utils.batch_common import auto_wrap_orphans
    auto_wrap_orphans(user, work_model=ComposerGeneration, batch_model=ComposerBatch,
                      item_model=ComposerBatchItem, fk_name='generation',
                      item_extra=_batch_item_extra)


#: Durée d'une génération quand rien ne la précise : le défaut du CHAMP (un seul lieu).
_DEFAULT_DURATION = float(ComposerGeneration._meta.get_field('duration').default)


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
# lance QUE les PENDING (« créer ≠ démarrer », contrat WamaBatchImport) et garde `@app_access` ;
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
    output_fields=('audio_output', 'planned_score', 'extracted_score'),
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
batch_start = app_access('composer')(_bv['batch_start'])
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
                                 # ETA agrégée + réglages COMMUNS aux filles de la card
                                 # mère (slot meta_template — porté le 31/08).
                                 extra=lambda b, items, gens: {
                                     'eta_ids': ','.join(str(g.id) for g in gens),
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

        # Réconcilie les tâches RUNNING orphelines (worker mort/crash) — brique COMMUNE,
        # même câblage que transcriber : preuve positive de mort uniquement.
        try:
            from wama.common.utils.process_control import reconcile_orphaned_running
            running = list(ComposerGeneration.objects.filter(user=user, status='RUNNING'))
            n = reconcile_orphaned_running(running)
            if n:
                logger.info(f"[composer] {n} tâche(s) RUNNING orpheline(s) réconciliée(s) → échec relançable")
        except Exception as exc:
            logger.debug(f"[composer] reconcile_orphaned_running ignoré: {exc}")

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

    # Réglages persistés (brique user_settings, clés = noms de params.py) : le POST prime,
    # sinon DERNIER réglage utilisé (pattern converter) — une création sans formulaire
    # (tool_api/studio) hérite ainsi du modèle préféré au lieu d'un défaut codé en dur.
    from wama.common.utils.user_settings import get_user_app_settings, save_user_app_settings
    last = get_user_app_settings(user, 'composer', {
        'model': DEFAULT_MODEL, 'duration': _DEFAULT_DURATION, 'vocals': vocals.AUTO,
        'output_format': 'original', 'output_quality': 'balanced'})

    model_id = normalize(request.POST.get('model') or last['model'])
    if not is_valid(model_id):
        return JsonResponse({'error': 'Modèle invalide'}, status=400)

    try:
        duration = float(request.POST.get('duration') or last['duration'])
        duration = clamp_duration(duration)
    except (ValueError, TypeError):
        duration = _DEFAULT_DURATION

    gen = ComposerGeneration.objects.create(
        user=user,
        prompt=prompt,
        model=model_id,
        quality_intent=_intent_posted(request.POST),
        duration=duration,
        vocals=vocals.normalize(request.POST.get('vocals') or last.get('vocals')),
        output_format=request.POST.get('output_format') or last['output_format'],
        output_quality=request.POST.get('output_quality') or last['output_quality'],
        # Mélodie par URL (WAMA_INGEST) : téléchargée en tête de tâche par ensure_local_input.
        source_url=request.POST.get('source_url', '').strip(),
    )

    # Re-persiste les choix comme défauts de la prochaine génération.
    save_user_app_settings(user, 'composer', {
        'model': model_id, 'duration': duration, 'vocals': gen.vocals,
        'output_format': gen.output_format, 'output_quality': gen.output_quality})

    # Le MORCEAU À REPRENDRE (cover) — ports de TRAVAIL depuis le 2026-10-03 (décision de Fabien) :
    # l'audio de MusicGen Melody (`work_audio`) et la partition de YuE2 (`work_score`). Chacun est
    # reçu sous le nom de son PORT, téléversé ou DÉSIGNÉ (brique `received_inputs` : une
    # désignation se POINTE), et rangé dans son champ — les champs, des données stockées, gardent
    # leur nom (`melody_reference`, `reference_score`). Joint si le modèle le DÉCLARE (un « auto »
    # le fera tirer parmi ceux qui le consomment).
    from wama.common.utils.media_paths import received_inputs
    # « Le modèle le déclare » s'entend AU SEIN DU PIPELINE : l'audio d'un cover est aussi joint
    # pour un modèle qui en suivra la partition extraite (`accepts_input`, 2026-10-03).
    for port, field, accepted in (('work_audio', 'melody_reference',
                                   accepts_input(model_id, 'work_audio')),
                                  ('work_score', 'reference_score',
                                   accepts_input(model_id, 'work_score'))):
        if not accepted:
            continue
        received = received_inputs(request, user, 'composer', field=port)
        if received:
            received[0].assign(gen, field)

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
    vocabulaire commun ; l'ordre positionnel hérité reste sortie|prompt|modèle|durée)."""
    from django.http import HttpResponse
    from wama.common.utils.batch_parsers import build_batch_template
    text = build_batch_template(
        ['sortie', 'prompt', 'modele', 'duree'],
        {'sortie': 'piano.wav', 'prompt': 'upbeat jazz piano with soft drums',
         'modele': 'musicgen-small', 'duree': 30},
        app_label='Composer (musique / bruitages)')
    resp = HttpResponse(text, content_type='text/plain; charset=utf-8')
    resp['Content-Disposition'] = 'attachment; filename="composer_batch_template.txt"'
    return resp


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


@require_POST
def import_batch(request):
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()

    if 'batch_file' not in request.FILES:
        return JsonResponse({'error': 'Aucun fichier batch fourni'}, status=400)

    batch_file = request.FILES['batch_file']

    # Default params for items without explicit model/duration
    default_model = normalize(request.POST.get('default_model') or DEFAULT_MODEL)
    if not is_valid(default_model):
        default_model = DEFAULT_MODEL
    try:
        default_duration = float(request.POST.get('default_duration', _DEFAULT_DURATION))
        default_duration = clamp_duration(default_duration)
    except (ValueError, TypeError):
        default_duration = _DEFAULT_DURATION

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

    if not tasks:
        os.remove(tmp_path)
        return JsonResponse({
            'error': 'Aucune tâche valide dans le fichier batch',
            'warnings': warnings,
        }, status=400)

    # Create batch container
    batch = ComposerBatch.objects.create(user=user, total=len(tasks))
    # Save the batch file on the batch object
    rel_path = os.path.relpath(tmp_path, settings.MEDIA_ROOT)
    batch.batch_file = rel_path
    batch.save(update_fields=['batch_file'])

    # Créer SANS lancer (contrat WamaBatchImport : créer ≠ démarrer ; l'auto-start passe par
    # batch_start, appelé par afterCreate — avant, le serveur lançait tout inconditionnellement
    # et « Créer seulement » était illusoire + double lancement avec l'auto-start client).
    created_ids = []
    for task_data in tasks:
        gen = ComposerGeneration.objects.create(
            user=user,
            prompt=task_data['prompt'],
            model=task_data['model'],
            duration=task_data['duration'],
        )
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

@require_POST
@app_access('composer')
def start(request, pk):
    """Relance la génération d'une composition (bouton de cycle ▶/↻) sans changer les réglages."""
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
    # Anti-race (pattern AGENTS.md) : select_for_update + revoke — brique commune.
    from wama.common.utils.process_control import begin_processing
    gen, err = begin_processing(ComposerGeneration, pk, user=user, reset=_reset_for_relaunch)
    if err == 'not_found':
        return JsonResponse({'error': 'Not found'}, status=404)
    if err == 'already_running':
        return JsonResponse({'error': 'Déjà en cours'}, status=400)
    from .tasks import compose_task
    task = compose_task.apply_async(args=(gen.id,))
    gen.task_id = task.id
    gen.save(update_fields=['task_id'])
    return JsonResponse({'id': gen.id, 'status': 'RUNNING'})


from wama.common.utils.process_views import make_process_start_view  # noqa: E402

# ▶ d'UN process de la card (P5, `ROUTE §10.6` 5.1) : fabrique COMMUNE. Seules les sorties
# DÉCLARÉES du process lancé sont remplacées (`_reset_for_relaunch(gen, only)`).
start_process = app_access('composer')(make_process_start_view(
    work_model=ComposerGeneration, task_for=_task_for, reset_for_process=_reset_for_relaunch))


@require_POST
@app_access('composer')
def stop(request, pk):
    """
    Stoppe la génération en cours (révoque la tâche Celery) → composition relançable (bouton ↻).
    Brique commune : wama.common.utils.process_control.stop_instance.
    """
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
    from wama.common.utils.scoping import editable_or_404
    gen = editable_or_404(ComposerGeneration, user, id=pk)
    if gen.status not in ('RUNNING', 'PENDING'):
        return JsonResponse({'id': gen.id, 'status': gen.status})
    from wama.common.utils.process_control import stop_instance
    new_status = stop_instance(gen, error_field='error_message')
    return JsonResponse({'id': gen.id, 'status': new_status})


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
    return None


@require_POST
def update_settings(request, pk):
    """Update model and/or duration on an existing generation, then re-run."""
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
    from wama.common.utils.scoping import editable_or_404
    gen = editable_or_404(ComposerGeneration, user, id=pk)

    if gen.status == 'RUNNING':
        return JsonResponse({'error': 'Impossible de modifier une génération en cours'}, status=400)

    # JSON (inspecteur) OU FormData (modale ⚙) par le lecteur COMMUN — la vue lisait
    # `request.POST` seul (contrat générique `tests_item_settings_contract`, 2026-09-26).
    from wama.common.utils.batch_views import read_settings_payload
    data = read_settings_payload(request, _SETTINGS_SCHEMA,
                                 [p['name'] for p in _SETTINGS_SCHEMA], empty_is_value=('lyrics',))

    try:
        _apply_generation_settings(gen, data)
    except ValueError as refusal:
        return JsonResponse({'error': str(refusal)}, status=400)

    # Pied de modale CONFORME : « Enregistrer » (restart=0) sauve SANS purger la sortie ni
    # relancer ; « Enregistrer et relancer » (restart=1) purge + re-run. ⚠ Le défaut était
    # `1` : un enregistrement qui ne le posait pas (JSON de l'inspecteur) RELANÇAIT la
    # génération. La modale le pose toujours (`index.js` collect) ; absent = on ne relance pas.
    restart = str(data.get('restart', '0')) == '1'
    if not restart:
        gen.save()
        return JsonResponse({'success': True, 'status': gen.status, 'restarted': False})

    # Sauvegarde des réglages PUIS relance ANTI-RACE (brique commune : verrou + revoke + reset)
    gen.save()
    from wama.common.utils.process_control import begin_processing
    gen, err = begin_processing(ComposerGeneration, gen.pk, user=user, reset=_reset_for_relaunch)
    if err:
        return JsonResponse({'success': True, 'status': 'RUNNING', 'restarted': False})

    from .tasks import compose_task
    task = compose_task.apply_async(args=(gen.id,))
    gen.task_id = task.id
    gen.save(update_fields=['task_id'])

    return JsonResponse({'success': True, 'status': 'RUNNING', 'restarted': True})


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
# Download
# ---------------------------------------------------------------------------

def download(request, pk):
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
    from wama.common.utils.scoping import visible_or_404  # lecture → partage F7
    gen = visible_or_404(ComposerGeneration, user, id=pk)
    if not gen.audio_output:
        return JsonResponse({'error': 'Aucun fichier disponible'}, status=404)

    filename = os.path.basename(gen.audio_output.name)
    response = FileResponse(gen.audio_output.open('rb'), content_type='audio/wav')
    response['Content-Disposition'] = content_disposition_header(True, f"{filename}")
    return response


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------

@require_POST
def delete(request, pk):
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
    gen = get_object_or_404(ComposerGeneration, id=pk, user=user)

    # Lot de l'élément, relevé AVANT la cascade — brique commune (`batch_common`).
    from wama.common.utils.batch_common import batch_snapshot, batch_state
    snapshot = batch_snapshot(gen)

    # Sortie et références (mélodie, partition) : LIBÉRÉES par la brique, à l'échelle de la card.
    release_card_files(gen)

    gen.delete()

    # batch.total / suppression du batch vidé (+ fichier batch) : gérés par le signal batch_sync.
    return JsonResponse({'success': True, 'batch': batch_state(snapshot, ComposerGeneration)})


# ---------------------------------------------------------------------------
# Batch delete
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Export to media library — RETIRÉ (2026-09-18, décision Fabien ; `REMOVAL_LEDGER R64`)
# ---------------------------------------------------------------------------
# La route `export/<pk>/` était une SECONDE PORTE du geste commun (elle déléguait déjà à
# `media_library.services.export_item_to_library` depuis le 12/09) : plus de front depuis le
# retrait du bouton dédié, GET des rôles/état et retrait absents, et un refus du double export
# que la brique fait déjà par provenance. Le seul savoir qu'elle portait — une génération
# `music` est une musique, le reste un bruitage — est DÉCLARÉ dans le détail canonique
# (`apps.py`, `result_role`) et lu par le geste commun, pour toutes les apps.


# ---------------------------------------------------------------------------
# Duplicate & Download All
# ---------------------------------------------------------------------------

@require_POST
def duplicate(request, pk):
    """Duplicate a single generation sharing the source, resetting the result."""
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
    from wama.common.utils.scoping import duplicable_or_404
    gen = duplicable_or_404(ComposerGeneration, user, id=pk)
    try:
        output_filename = gen.batch_item.output_filename
    except ComposerBatchItem.DoesNotExist:
        output_filename = ''

    new_gen = duplicate_instance(
        gen,
        for_user=user,
        reset_fields={
            'status': 'PENDING', 'progress': 0,
            'task_id': None, 'error_message': '',
            'exported_to_library': False,
        },
        clear_fields=['audio_output', 'planned_score', 'extracted_score'],
    )
    # Fille d'un VRAI batch (total > 1) : dupliquer en frère DANS le batch.
    # Card UNITAIRE (batch-de-1) : la copie devient une card indépendante (nouveau batch-de-1) —
    # sinon la duplication transformait la card en batch de 2 (bug signalé 2026-07-03).
    # La copie d'une card REÇUE se range chez celui qui duplique, jamais dans le lot d'autrui.
    orig_item = (ComposerBatchItem.objects.filter(generation=gen).select_related('batch').first()
                 if new_gen.user_id == gen.user_id else None)
    if orig_item and orig_item.batch.total > 1:
        from django.db.models import Max
        batch = orig_item.batch
        next_idx = (batch.items.aggregate(m=Max('row_index'))['m'] or 0) + 1
        ComposerBatchItem.objects.create(
            batch=batch, generation=new_gen, output_filename=output_filename, row_index=next_idx)
        batch.total = batch.items.count()
        batch.save(update_fields=['total'])
    else:
        _wrap_generation_in_batch(new_gen)
    # `duplicated` = contrat de la brique queue-actions.js : elle focalise la copie
    # après rechargement (sessionStorage wama_focus_card).
    return JsonResponse({'success': True, 'id': new_gen.id, 'duplicated': new_gen.id})


def download_all(request):
    """Download all completed audio outputs as a ZIP archive."""
    import io as _io
    import zipfile
    from django.http import HttpResponse

    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
    gens = (ComposerGeneration.objects
            .filter(user=user, status='SUCCESS')
            .exclude(audio_output=''))

    if not gens.exists():
        return JsonResponse({'error': 'Aucun fichier disponible'}, status=404)

    buffer = _io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
        for gen in gens:
            if not gen.audio_output:
                continue
            try:
                zf.write(gen.audio_output.path, os.path.basename(gen.audio_output.name))
            except Exception:
                pass

    buffer.seek(0)
    response = HttpResponse(buffer.getvalue(), content_type='application/zip')
    response['Content-Disposition'] = 'attachment; filename="composer_audio.zip"'
    return response


# ---------------------------------------------------------------------------
# Start all / Clear all
# ---------------------------------------------------------------------------

@require_POST
@app_access('composer')
def start_all(request):
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
    from .tasks import compose_task

    from wama.common.utils.process_control import begin_processing
    gens = ComposerGeneration.objects.filter(user=user, status__in=('PENDING', 'FAILURE'))
    count = 0
    for gen in gens:
        # Anti-race par item (brique commune) : skip si déjà lancé entre-temps.
        gen, err = begin_processing(ComposerGeneration, gen.pk, user=user,
                                    reset=_reset_for_relaunch)
        if err:
            continue
        task = compose_task.apply_async(args=(gen.id,))
        gen.task_id = task.id
        gen.save(update_fields=['task_id'])
        count += 1

    return JsonResponse({'launched': count})


@require_POST
def clear_all(request):
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()

    gens = ComposerGeneration.objects.filter(user=user).exclude(status='RUNNING')
    for gen in gens:
        release_card_files(gen)

    gens.delete()
    ComposerBatch.objects.filter(user=user).delete()
    return JsonResponse({'success': True})


# ---------------------------------------------------------------------------
# Console & global progress
# ---------------------------------------------------------------------------

def console_content(request):
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
    lines = get_console_lines(user.id, app='composer')
    return JsonResponse({'lines': lines})


def card_html(request, pk):
    """Card RENDUE serveur — SOURCE UNIQUE du markup de card (partial _generation_card.html ;
    CARD_DESIGN : « partial server-side + update JS en place, PAS de rebuild »). Consommée par
    le JS à la création (insertion) et en fin de tâche (remplacement in-place : waveform +
    boutons complets sans injection de chaînes HTML — audit B2-4/5)."""
    from django.http import HttpResponse
    from django.template.loader import render_to_string
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
    from wama.common.utils.scoping import visible_or_404  # lecture → partage F7
    gen = visible_or_404(ComposerGeneration, user, id=pk)
    try:
        label = gen.batch_item.output_filename
    except ComposerBatchItem.DoesNotExist:
        label = ''
    from wama.common.utils.batch_common import is_batch_child
    html = render_to_string('composer/_generation_card.html',
                            {'elem': _decorate_generation(gen), 'card_label': label,
                             'in_batch': is_batch_child(gen)}, request=request)
    return HttpResponse(html)


