import os
import logging
from django.shortcuts import render, get_object_or_404
from wama.accounts.permissions import app_access
from wama.common.utils.input_match import input_labels as _input_labels
from django.views import View
from django.http import JsonResponse, FileResponse, HttpResponseBadRequest
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.utils.encoding import smart_str
from django.core.cache import cache
from PIL import Image

import datetime
from .models import (Enhancement, AudioEnhancement,
                     BatchEnhancement, BatchEnhancementItem,
                     BatchAudioEnhancement, BatchAudioEnhancementItem)
from ..accounts.views import get_or_create_anonymous_user
from ..common.utils.console_utils import get_console_lines
from ..common.utils.video_utils import get_media_info
from ..common.utils.queue_duplication import release_card_files, duplicate_instance
from ..common.utils.scoping import visible_or_404

logger = logging.getLogger(__name__)


# Curseur POSTÉ (chantier C) : lecteur COMMUN — None quand il n'est pas posté (la colonne reste
# vide, la cascade retombe sur le réglage d'app puis 50). Était une copie locale, comme chez
# imager et composer (revérification 21/09).
from wama.common.utils.auto_model import posted_quality_intent as _intent_posted  # noqa: E402


def _factor_posted(source, default=None):
    """Facteur d'agrandissement POSTÉ (×2 / ×4), `default` sinon — le BESOIN que « auto »
    filtre avant de classer."""
    raw = source.get('upscale_factor') if hasattr(source, 'get') else None
    try:
        value = int(float(raw))
    except (TypeError, ValueError):
        return default
    return value if value in (2, 4) else default


def _wrap_enhancement_in_batch(enhancement):
    """Wrap a standalone Enhancement in a new BatchEnhancement-of-1."""
    batch = BatchEnhancement.objects.create(user=enhancement.user, total=1)
    BatchEnhancementItem.objects.create(batch=batch, enhancement=enhancement, row_index=0)
    return batch


def _enhancement_nature(e):
    """Nature d'une amélioration (image / vidéo) — ce qui peut cohabiter dans un lot.

    DEUX consommateurs, une seule déclaration, toutes deux par la fabrique commune (`group_key`) :
    le regroupement à l'arrivée (`consolidate_arrival`) et la fusion par drag&drop (`merge`).
    Écrite en lambda jusqu'au 2026-09-04, donc impartageable."""
    return e.media_type or 'image'


def _auto_wrap_orphans(user):
    """Range les Enhancement (médias) pas encore en batch — brique COMMUNE, stratégie
    par défaut (orphelin → batch-of-1). Le regroupement par nature ne se fait plus
    qu'à l'ARRIVÉE (`queue_manipulation.consolidate_arrival`, constat Fabien 14/08)."""
    from wama.common.utils.batch_common import auto_wrap_orphans
    auto_wrap_orphans(
        user, work_model=Enhancement, batch_model=BatchEnhancement,
        item_model=BatchEnhancementItem, fk_name='enhancement',
    )


def _wrap_audio_in_batch(audio_enhancement):
    """Wrap a standalone AudioEnhancement in a new BatchAudioEnhancement-of-1."""
    batch = BatchAudioEnhancement.objects.create(user=audio_enhancement.user, total=1)
    BatchAudioEnhancementItem.objects.create(batch=batch, audio_enhancement=audio_enhancement, row_index=0)
    return batch


def _auto_wrap_audio_orphans(user):
    """Range les AudioEnhancement pas encore en batch — brique COMMUNE, stratégie par
    défaut (orphelin → batch-of-1) ; l'of-N ne se fait plus qu'à l'ARRIVÉE
    (cf. auto_wrap_orphans, constat Fabien 14/08). Le scope user=user est porté par
    la brique : on n'enrôle jamais la card partagée d'autrui."""
    from wama.common.utils.batch_common import auto_wrap_orphans
    auto_wrap_orphans(
        user, work_model=AudioEnhancement, batch_model=BatchAudioEnhancement,
        item_model=BatchAudioEnhancementItem, fk_name='audio_enhancement',
    )


def _decorate_media_card(e, preloaded=False):
    """Chips de card générés du SCHÉMA (card_chips) — remplace les badges hand-built.
    Point d'attache UNIQUE : IndexView (par `decorate_cards`) ET card_html."""
    from wama.common.utils.card_chips import chips_by_section
    from wama.enhancer.params import MEDIA_PARAMS_JSON
    e.chips = chips_by_section(e, MEDIA_PARAMS_JSON)
    from wama.common.services.process_pipeline import decorate
    decorate(e, preloaded=preloaded)   # « Amélioration → Sortie » et l'état MONTRÉ (`ROUTE §10.6` 5.1)
    return e


def _decorate_audio_card(ae, preloaded=False):
    from wama.common.utils.card_chips import chips_by_section
    from wama.enhancer.params import AUDIO_PARAMS_JSON
    ae.chips = chips_by_section(ae, AUDIO_PARAMS_JSON)
    from wama.common.services.process_pipeline import decorate
    decorate(ae, preloaded=preloaded)
    return ae


def _input_match_meta_enhancer():
    """Meta de la brique COMMUNE, indexée par les VALEURS d'option des deux selects : le select
    MÉDIA porte des clés entières, tirées par TÂCHE (route F4b ⑤, 2026-10-06 — le mode `task`
    de la brique, qui sinon resterait muet sur un modèle d'une autre source, Swin2SR) ; le select
    AUDIO garde ses identifiants nus de la source `enhancer`."""
    from wama.common.utils.input_match import input_match_meta
    from wama.enhancer.utils.auto_model import MEDIA_SPEC
    return {**input_match_meta('enhancer'), **input_match_meta(task=MEDIA_SPEC['task'])}


class IndexView(View):
    def get(self, request):
        user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()

        # Lazily wrap any orphan enhancements into batches-of-1
        _auto_wrap_orphans(user)
        _auto_wrap_audio_orphans(user)

        # Réconcilie les items RUNNING orphelins (worker mort/crash machine) — brique
        # COMMUNE, preuve positive de mort uniquement. Les DEUX domaines.
        try:
            from wama.common.utils.process_control import reconcile_orphaned_running
            running = list(Enhancement.objects.filter(user=user, status='RUNNING')) + \
                      list(AudioEnhancement.objects.filter(user=user, status='RUNNING'))
            n = reconcile_orphaned_running(running, error_field='error_message')
            if n:
                logger.info(f"[enhancer] {n} tâche(s) RUNNING orpheline(s) réconciliée(s) → échec relançable")
        except Exception as exc:
            logger.debug(f"[enhancer] reconcile_orphaned_running ignoré: {exc}")

        # Files par domaine — brique COMMUNE build_batches_list (contrat _batch_card)
        # + tri/filtre persistés session (contrat _queue_toolbar).
        from wama.common.utils.batch_common import build_batches_list
        from wama.common.utils.queue_view import apply_queue_sort_filter

        def _make_extra(schema):
            # `schema` par FILE (media vs audio) : les réglages COMMUNS aux filles de la
            # card mère (slot meta_template, porté le 31/08) se dérivent du bon schéma.
            from wama.common.utils.card_chips import common_chips_for_items

            def _extra(batch, items, works):
                done = sum(1 for w in works if w.status == 'SUCCESS')
                return {
                    'success_pct': int(done / batch.total * 100) if batch.total > 0 else 0,
                    # (l'ETA agrégée de la card mère, `eta_ids`, vient de `build_batches_list`)
                    'common_chips': common_chips_for_items(works, schema),
                }
            return _extra

        from wama.enhancer.params import AUDIO_PARAMS_JSON, MEDIA_PARAMS_JSON
        batches_list = build_batches_list(
            user, batch_model=BatchEnhancement, work_attr='enhancement',
            extra=_make_extra(MEDIA_PARAMS_JSON))
        audio_batches_list = build_batches_list(
            user, batch_model=BatchAudioEnhancement, work_attr='audio_enhancement',
            extra=_make_extra(AUDIO_PARAMS_JSON))
        # Chips + process de card : les lignes d'exécution de TOUTES les cards d'une file sont
        # lues en une requête (`decorate_cards`, comme les neuf autres apps) — une file par domaine.
        from wama.common.services.process_pipeline import decorate_cards
        decorate_cards([link.enhancement for b in batches_list for link in b['items']],
                       _decorate_media_card)
        decorate_cards([link.audio_enhancement for b in audio_batches_list for link in b['items']],
                       _decorate_audio_card)

        # (« batchs d'abord » RETIRÉ le 2026-08-24 : règle abandonnée le 2026-06-29 au profit du
        # tri de la barre commune — `apply_queue_sort_filter` ci-dessous trie TOUJOURS, défaut
        # `recent`, et s'applique aux DEUX listes. Ces deux tris étaient donc écrasés juste après.)

        def _name_of(b):
            return (b['obj'].name or '') if hasattr(b['obj'], 'name') else str(b['obj'])

        batches_list, q_sort, q_filter = apply_queue_sort_filter(
            request, batches_list, name_of=_name_of)
        audio_batches_list, _, _ = apply_queue_sort_filter(
            request, audio_batches_list, name_of=_name_of)

        # Le volet reprend les réglages MÉMORISÉS de l'utilisateur — brique commune (2026-09-29,
        # `ROADMAP §23.3bis`). La table `UserSettings` propre à l'enhancer n'était jamais ÉCRITE
        # (seulement `get_or_create`) : ses « défauts » étaient ceux du modèle, pour tout le monde.
        from wama.common.utils.user_settings import read_panel_settings
        from wama.enhancer.params import AUDIO_PARAMS, MEDIA_PARAMS
        panel = read_panel_settings(user, 'enhancer', MEDIA_PARAMS)
        # Le volet AUDIO retient aussi les siens depuis le 2026-10-28 (même brique, même clé de
        # volet : ses `dom_id` sont distincts de ceux du domaine image/vidéo).
        audio_panel = read_panel_settings(user, 'enhancer', AUDIO_PARAMS)
        # Le volet parle en CLÉS de catalogue (route F4b ⑤, 2026-10-06) : une préférence
        # mémorisée avant la bascule (identifiant nu) est lue dans l'espace de l'enhancer.
        from wama.common.utils.model_keys import catalog_key
        panel['ai_model'] = catalog_key(panel.get('ai_model') or 'auto', 'enhancer')
        audio_panel['engine'] = catalog_key(audio_panel.get('engine') or 'auto', 'enhancer')

        import json as _json
        from wama.enhancer.params import MEDIA_PARAMS_JSON, AUDIO_PARAMS_JSON
        queue_count = sum(len(b['items']) for b in batches_list) +                       sum(len(b['items']) for b in audio_batches_list)

        return render(request, 'enhancer/index.html', {
            'batches_list': batches_list,
            'audio_batches_list': audio_batches_list,
            'queue_count': queue_count,
            'q_sort': q_sort,
            'q_filter': q_filter,
            # Valeurs du VOLET GÉNÉRÉ (domaine image/vidéo, 2026-10-11) — par NOM de param, ce
            # qu'attend `WamaParams.render`. Plus de pré-rendu des options (modèle, moteur audio,
            # formats) : le volet les reçoit du schéma et du catalogue, comme la modale.
            'panel_values_json': _json.dumps(panel).replace('<', '\\u003c'),
            'audio_panel_values_json': _json.dumps(audio_panel).replace('<', '\\u003c'),
            # Schémas déclaratifs par domaine → inspecteur contextuel (WamaInspector.initFromSchema).
            'media_params_json': _json.dumps(MEDIA_PARAMS_JSON),
            'audio_params_json': _json.dumps(AUDIO_PARAMS_JSON),
            # Appariement entrée↔modèles (brique commune input_match) : clés catalogue =
            # valeurs d'option depuis l'alignement 18/08 (artefact _fp16 retiré à la
            # découverte ; moteurs audio déjà alignés).
            'input_match_meta': _json.dumps(_input_match_meta_enhancer()),
            'input_labels': _json.dumps(_input_labels()),
        })


def new_enhancement_settings(user, model=None, app='enhancer', post=None):
    """Les colonnes de réglage d'une amélioration (image/vidéo) NAISSANTE, par la cascade COMMUNE
    (défauts du schéma ← réglages mémorisés au volet ← ce que le dépôt poste,
    `user_settings.new_element_settings`, 2026-10-18 — six défauts y étaient recopiés à la main).
    Règle propre gardée : le facteur d'agrandissement vaut ×2 ou ×4, ×4 sinon (`_factor_posted`).
    Le dépôt de la card, le lot et l'import du gestionnaire de fichiers (« Envoyer vers », sans
    volet donc sans POST) passent ici ; `model`/`app` : une jumelle de bac à sable passe les siens."""
    from wama.common.utils.user_settings import new_element_settings
    from wama.enhancer.params import MEDIA_PARAMS_JSON
    values = new_element_settings(user, app, MEDIA_PARAMS_JSON, model or Enhancement, post=post,
                                  empty_is_value=SETTINGS_EMPTY_IS_VALUE)
    if 'upscale_factor' in values:
        values['upscale_factor'] = _factor_posted(values, 4)
    return values


def _deposit_settings(user, post):
    """Réglages d'un DÉPÔT (`new_enhancement_settings`). Ce qui a été posté devient la mémoire
    du volet (`save_panel_settings`) : l'élément suivant et la page rechargée partent des
    derniers réglages employés."""
    from wama.common.utils.user_settings import save_panel_settings
    from wama.enhancer.params import MEDIA_PARAMS_JSON
    values = new_enhancement_settings(user, post=post)
    save_panel_settings(user, 'enhancer', MEDIA_PARAMS_JSON, post)
    return values


# ── Domaine AUDIO : le MÊME modèle que le domaine image/vidéo (portage du 2026-10-28) ─────────
# Jusque-là le dépôt audio créait l'élément sur les défauts du modèle, le volet ne s'appliquait
# qu'au LANCEMENT (chaque ▶ reprenait le volet), rien n'était retenu, et quatre vues recopiaient
# chacune leur liste de réglages (fiche d'élément, ▶, « Tout démarrer », ▶ de lot).

def new_audio_settings(user, model=None, app='enhancer', post=None):
    """Les colonnes de réglage d'une amélioration AUDIO naissante, par la cascade COMMUNE
    (défauts du schéma ← réglages retenus au volet ← ce que le dépôt poste). Le dépôt de la card,
    le lot, « Envoyer vers » et l'outil de l'assistant passent ici ; `model`/`app` : une jumelle
    de bac à sable passe les siens."""
    from wama.common.utils.user_settings import new_element_settings
    from wama.enhancer.params import AUDIO_PARAMS_JSON
    return new_element_settings(user, app, AUDIO_PARAMS_JSON, model or AudioEnhancement, post=post,
                                empty_is_value=SETTINGS_EMPTY_IS_VALUE)


def _audio_deposit_settings(user, post):
    """Réglages d'un DÉPÔT audio (`new_audio_settings`) ; ce qui a été posté devient la mémoire du
    volet audio (`save_panel_settings`), comme au domaine image/vidéo."""
    from wama.common.utils.user_settings import save_panel_settings
    from wama.enhancer.params import AUDIO_PARAMS_JSON
    values = new_audio_settings(user, post=post)
    save_panel_settings(user, 'enhancer', AUDIO_PARAMS_JSON, post or {})
    return values


def _apply_audio_settings(ae, data):
    """LES réglages d'une amélioration audio, posés sans sauver — la route de l'élément, « Tout
    démarrer » et le ▶ de lot passent ici. Les colonnes par la brique COMMUNE (valeur hors choix
    ignorée) ; le curseur à part : clé ABSENTE = inchangé, posée vide = curseur effacé."""
    from wama.common.utils.batch_views import apply_item_settings
    from wama.enhancer.params import AUDIO_PARAMS
    apply_item_settings(ae, {k: v for k, v in (data or {}).items() if v not in (None, '')},
                        params_fields=tuple(p.name for p in AUDIO_PARAMS
                                            if p.name != 'quality_intent'))
    if 'quality_intent' in (data or {}):
        ae.quality_intent = _intent_posted(data)


def _read_audio_settings(request):
    """Les réglages audio postés — JSON (inspecteur) OU FormData (modale ⚙), lecteur COMMUN."""
    from wama.common.utils.batch_views import read_settings_payload
    from wama.enhancer.params import AUDIO_PARAMS_JSON
    return read_settings_payload(request, AUDIO_PARAMS_JSON,
                                 [p['name'] for p in AUDIO_PARAMS_JSON],
                                 empty_is_value=SETTINGS_EMPTY_IS_VALUE)


@require_POST
@app_access('enhancer')
def upload(request):
    """Upload and analyze image/video file, or download from URL."""
    print("=== ENHANCER UPLOAD CALLED ===")  # DEBUG
    logger.info("=== UPLOAD START ===")

    # Check for URL upload first
    media_url = request.POST.get('media_url', '').strip()
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
    # Un fichier TÉLÉVERSÉ, ou DÉSIGNÉ (médiathèque, arbre) — brique `received_inputs` : une
    # désignation se POINTE au lieu d'être recopiée, avec le même état du volet.
    from wama.common.utils.media_paths import received_inputs
    received = received_inputs(request, user, 'enhancer')
    file = received[0] if received else None

    if not file and not media_url:
        logger.error("Upload failed: No file or URL provided")
        if received.refusal:
            return JsonResponse({'error': received.refusal}, status=400)
        return HttpResponseBadRequest('Missing file or URL')

    logger.info(f"Upload by user: {user.username} (ID: {user.id})")

    image_extensions = ['.jpg', '.jpeg', '.png', '.bmp', '.tif', '.tiff', '.webp', '.heic']
    video_extensions = ['.mp4', '.webm', '.mkv', '.flv', '.gif', '.avi', '.mov', '.mpg', '.qt', '.3gp']

    # URL : la SOURCE est enregistrée, le récepteur commun la télécharge dès la création, HORS
    # de la requête (`source_ingest`, 2026-10-13) — même geste que `batch_create`. Une nature
    # connue d'avance hors image/vidéo est refusée ici ; inconnue, le `derive` la pose à l'arrivée.
    if media_url and not file:
        from wama.common.utils.url_ingest import url_nature
        nature = url_nature(media_url)
        if nature and nature not in ('image', 'video'):
            return JsonResponse({'error': 'Format non supporté'}, status=400)
        enhancement = Enhancement.objects.create(
            user=user, media_type=nature, source_url=media_url,
            **_deposit_settings(user, request.POST),
        )
        try:
            _wrap_enhancement_in_batch(enhancement)
        except Exception:
            pass
        return JsonResponse({'id': enhancement.id, 'media_type': enhancement.media_type,
                             'source_url': media_url, 'status': enhancement.status})

    # Handle regular file upload
    # Detect media type
    file_ext = os.path.splitext(file.name)[1].lower()
    logger.info(f"File: {file.name} (extension: {file_ext}, size: {file.size} bytes)")

    if file_ext in image_extensions:
        media_type = 'image'
    elif file_ext in video_extensions:
        media_type = 'video'
    else:
        logger.error(f"Unsupported format: {file_ext}")
        return JsonResponse({'error': 'Format non supporté'}, status=400)

    logger.info(f"Detected media type: {media_type}")

    # Create enhancement record
    enhancement = Enhancement.objects.create(
        user=user,
        media_type=media_type,
        input_file=file.value,
        **_deposit_settings(user, request.POST),
    )
    file.record(enhancement, 'input_file')
    logger.info(f"Created Enhancement ID: {enhancement.id}")

    # Wrap in batch-of-1
    try:
        _wrap_enhancement_in_batch(enhancement)
    except Exception:
        pass

    # Analyze file
    try:
        _analyze_media(enhancement)
        logger.info(f"Media analyzed: {enhancement.width}x{enhancement.height}")
    except Exception as e:
        logger.warning(f"Could not analyze media: {e}")

    return JsonResponse({
        'id': enhancement.id,
        'media_type': enhancement.media_type,
        'input_url': enhancement.input_file.url,
        'input_filename': enhancement.get_input_filename(),
        'width': enhancement.width,
        'height': enhancement.height,
        'file_size': enhancement.file_size,
        'status': enhancement.status,
    })


def _analyze_media(enhancement: Enhancement):
    """Analyze media file to extract dimensions and metadata using common utility."""
    file_path = enhancement.input_file.path
    logger.info(f"[_analyze_media] Starting analysis for: {file_path}")

    try:
        info = get_media_info(file_path)
        logger.info(f"[_analyze_media] get_media_info returned: {info}")
        enhancement.width = info['width']
        enhancement.height = info['height']
        enhancement.duration = info['duration']
        enhancement.file_size = info['file_size']
        enhancement.save(update_fields=['width', 'height', 'duration', 'file_size'])
        logger.info(f"[_analyze_media] Saved: {enhancement.width}x{enhancement.height}")
    except Exception as e:
        logger.error(f"[_analyze_media] FAILED for {file_path}: {e}", exc_info=True)


@require_POST
def stop(request, pk: int):
    """Stoppe l'amélioration image/vidéo en cours → item relançable (↻). Brique commune process_control."""
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
    from wama.common.utils.scoping import editable_or_404
    enhancement = editable_or_404(Enhancement, user, pk=pk)
    if enhancement.status not in ('RUNNING', 'PENDING'):
        return JsonResponse({'id': enhancement.id, 'status': enhancement.status})
    from wama.common.utils.process_control import stop_instance
    new_status = stop_instance(enhancement, error_field='error_message')
    return JsonResponse({'id': enhancement.id, 'status': new_status})


@require_POST
def start(request, pk: int):
    """Start enhancement processing."""
    logger.info(f"=== START ENHANCEMENT {pk} ===")

    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()

    # Réglages de la requête (JSON ou form-data) — appliqués SOUS le verrou via reset()
    try:
        import json
        data = json.loads(request.body) if request.body else {}
    except (json.JSONDecodeError, ValueError):
        data = request.POST

    def _apply_settings(enh):
        enh.ai_model = data.get('ai_model', enh.ai_model)
        denoise_value = data.get('denoise', enh.denoise)
        enh.denoise = (denoise_value.lower() in ('1', 'true', 'on')
                       if isinstance(denoise_value, str) else bool(denoise_value))
        enh.blend_factor = float(data.get('blend_factor', enh.blend_factor))
        enh.upscale_factor = _factor_posted(data, enh.upscale_factor)
        if 'quality_intent' in data:
            enh.quality_intent = _intent_posted(data)
        enh.progress = 0
        enh.error_message = ''

    # Anti-race COMMUN (atomic + select_for_update + revoke) — audit 2026-07-11
    from wama.common.utils.process_control import begin_processing
    enhancement, err = begin_processing(Enhancement, pk, user=user, reset=_apply_settings)
    if err:
        return JsonResponse({'error': err}, status=404 if err == 'not_found' else 400)

    from .tasks import enhance_media
    try:
        task = enhance_media.delay(pk)
        enhancement.task_id = task.id
        enhancement.save(update_fields=['task_id'])
        return JsonResponse({'task_id': task.id, 'status': 'RUNNING'})
    except Exception as e:
        logger.error(f"Failed to start task for Enhancement {pk}: {e}", exc_info=True)
        enhancement.status = 'PENDING'
        enhancement.save(update_fields=['status'])
        return JsonResponse({
            'error': str(e),
            'message': 'Failed to start task. Is Celery running?',
        }, status=500)


# Les vues de PROGRESSION : fabrique COMMUNE (`progress_views.make_progress_views`, ROUTE §11 #37,
# 2026-10-03), pour ses DEUX files (média, audio). L'ETA est celle de ses PROCESS
# (`function_specs.PIPELINE`, 2026-10-05).
from wama.common.utils.progress_views import make_progress_views  # noqa: E402

_pv = make_progress_views(work_model=Enhancement, app_id='enhancer')
progress, global_progress = _pv['progress'], _pv['global_progress']
_apv = make_progress_views(work_model=AudioEnhancement, app_id='audio_enhancer')
audio_progress, audio_global_progress = _apv['progress'], _apv['global_progress']


def download(request, pk: int):
    """Download enhanced file."""
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
    enhancement = visible_or_404(Enhancement, user, pk=pk)   # LECTURE

    logger.info(f"Download request for enhancement {pk}")
    logger.info(f"  - output_file field: {enhancement.output_file}")
    logger.info(f"  - output_file.name: {enhancement.output_file.name if enhancement.output_file else 'None'}")

    if not enhancement.output_file:
        logger.error(f"No output file available for enhancement {pk}")
        return HttpResponseBadRequest('No output file available')

    # Check if file exists in storage
    from django.core.files.storage import default_storage
    if not default_storage.exists(enhancement.output_file.name):
        logger.error(f"Output file does not exist in storage: {enhancement.output_file.name}")
        return HttpResponseBadRequest(f'Output file not found in storage: {enhancement.output_file.name}')

    logger.info(f"Opening file for download: {enhancement.output_file.name}")
    try:
        return FileResponse(
            enhancement.output_file.open('rb'),
            as_attachment=True,
            filename=enhancement.get_output_filename()
        )
    except Exception as e:
        logger.error(f"Error opening file for download: {e}", exc_info=True)
        return HttpResponseBadRequest(f'Error opening file: {e}')


@require_POST
def delete(request, pk: int):
    """Delete enhancement."""
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
    enhancement = get_object_or_404(Enhancement, pk=pk, user=user)

    # Lot de l'élément, relevé AVANT la suppression — brique commune (`batch_common`).
    from wama.common.utils.batch_common import batch_snapshot, batch_state
    snapshot = batch_snapshot(enhancement)

    # Entrée et sortie LIBÉRÉES par la brique (une entrée partagée avec un doublon reste)
    release_card_files(enhancement)

    enhancement.delete()  # signal batch_sync : recale total / supprime le batch vidé
    cache.delete(f"enhancer_progress_{pk}")

    return JsonResponse({'deleted': pk, 'batch': batch_state(snapshot, Enhancement)})


@require_POST
def duplicate(request, pk: int):
    """Duplicate an Enhancement sharing the same input_file, resetting results."""
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
    from wama.common.utils.scoping import duplicable_or_404
    enhancement = duplicable_or_404(Enhancement, user, pk=pk)
    new_e = duplicate_instance(
        enhancement,
        for_user=user,
        reset_fields={
            'status': 'PENDING',
            'progress': 0,
            'task_id': '',
            'error_message': '',
            'output_width': 0,
            'output_height': 0,
            'output_file_size': 0,
            'processing_time': 0,
        },
        clear_fields=['output_file'],
    )
    # Aligné sur le Synthesizer (référence) : un doublon va dans SON PROPRE batch-of-1.
    # On ne rejoint le batch de l'original QUE si c'est un VRAI batch multi-éléments (>1).
    # Sinon une carte seule (batch-of-1) deviendrait un batch en la dupliquant (bug).
    orig_item = BatchEnhancementItem.objects.filter(enhancement=enhancement).select_related('batch').first()
    if orig_item and orig_item.batch.items.count() > 1:
        from django.db.models import Max
        batch = orig_item.batch
        next_idx = (batch.items.aggregate(m=Max('row_index'))['m'] or 0) + 1
        BatchEnhancementItem.objects.create(batch=batch, enhancement=new_e, row_index=next_idx)
        batch.total = batch.items.count()
        batch.save(update_fields=['total'])
    else:
        try:
            _wrap_enhancement_in_batch(new_e)
        except Exception:
            pass
    return JsonResponse({'duplicated': new_e.id})


@require_POST
def start_all(request):
    """Start all enhancements (including reprocessing completed ones)."""
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
    enhancements = Enhancement.objects.filter(user=user)

    # Get global settings from request (support both JSON and form-data)
    try:
        import json
        data = json.loads(request.body) if request.body else {}
    except (json.JSONDecodeError, ValueError):
        data = request.POST

    from .tasks import enhance_media
    from wama.common.utils.process_control import begin_processing

    started = []
    errors = []

    def _apply_globals(enh):
        # Le volet posté s'applique à toute la file par LA fonction des réglages d'un élément
        # (2026-10-28) — sa liste de cinq réglages écrite ici en était une recopie, sans la sortie.
        _apply_enhancement_settings(enh, data)
        enh.progress = 0
        enh.error_message = ''

    for enhancement in enhancements:
        try:
            # Anti-race COMMUN (atomic + select_for_update + revoke) — même brique que start()
            locked, err = begin_processing(Enhancement, enhancement.pk, user=user,
                                           reset=_apply_globals)
            if err:
                continue  # already_running / not_found
            task = enhance_media.delay(locked.id)
            locked.task_id = task.id
            locked.save(update_fields=['task_id'])
            started.append(locked.id)
        except Exception as e:
            errors.append({'id': enhancement.id, 'error': str(e)})

    return JsonResponse({
        'started_ids': started,
        'count': len(started),
        'errors': errors,
    })


@require_POST
def clear_all(request):
    """Clear all enhancements."""
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
    enhancements = Enhancement.objects.filter(user=user)

    cleared = []
    for enhancement in enhancements:
        cleared.append(enhancement.id)
        release_card_files(enhancement)
        cache.delete(f"enhancer_progress_{enhancement.id}")

    enhancements.delete()

    return JsonResponse({'cleared_ids': cleared, 'count': len(cleared)})


# ⬇ « Télécharger tout » de la barre de file : le ZIP de la file que compte la barre globale,
# par la fabrique commune (`make_progress_views`, 2026-10-17 — REMOVAL_LEDGER R142).
download_all = _pv['download_all']


#: Réglages pour lesquels une valeur postée VIDE est une valeur (curseur effacé) — lus par la
#: route d'un élément ET par la fabrique de lots : une seule déclaration pour les deux.
SETTINGS_EMPTY_IS_VALUE = ('quality_intent',)


def _read_enhancement_settings(request):
    """Les réglages postés — JSON (inspecteur) OU FormData (modale ⚙), par le lecteur COMMUN.
    La vue lisait `request.POST` seul : le JSON de l'inspecteur n'était jamais écrit (relevé
    par le contrat générique `tests_item_settings_contract`, 2026-09-26). Un curseur posé VIDE
    reste une valeur (curseur effacé)."""
    from wama.common.utils.batch_views import read_settings_payload
    from wama.enhancer.params import MEDIA_PARAMS_JSON
    return read_settings_payload(request, MEDIA_PARAMS_JSON,
                                 [p['name'] for p in MEDIA_PARAMS_JSON],
                                 empty_is_value=SETTINGS_EMPTY_IS_VALUE)


def _apply_enhancement_settings(e, data):
    """Applique les réglages d'un Enhancement (sans save). Les colonnes simples passent par la
    brique COMMUNE (valeur hors choix ignorée) ; restent ici le facteur (×2/×4) et le curseur,
    propres à l'enhancer."""
    from wama.common.utils.batch_views import apply_item_settings
    from wama.enhancer.params import MEDIA_PARAMS
    # Les colonnes simples = le schéma MÉDIA, moins les deux réglages traités ci-dessous. Lues du
    # schéma (2026-10-16) : la liste écrite ici en recopiait les noms (`check_redundancy`), et un
    # réglage ajouté au schéma n'était pas appliqué tant qu'on ne l'y recopiait pas.
    apply_item_settings(e, {k: v for k, v in data.items() if v not in (None, '')},
                        params_fields=tuple(p.name for p in MEDIA_PARAMS
                                            if p.name not in ('upscale_factor', 'quality_intent')))
    # Curseur + facteur (chantier C) : clé ABSENTE = inchangé ; posée vide = curseur effacé
    # (la cascade retombe sur le réglage d'app, puis 50).
    e.upscale_factor = _factor_posted(data, e.upscale_factor)
    if 'quality_intent' in data:
        e.quality_intent = _intent_posted(data)


@require_POST
def update_settings(request, pk: int):
    """Update enhancement settings."""
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
    from wama.common.utils.scoping import editable_or_404
    enhancement = editable_or_404(Enhancement, user, pk=pk)
    # Réglages enregistrables PENDANT un traitement (2026-10-22) : seules les colonnes CHANGÉES
    # s'écrivent, jamais le statut ni les sorties que la tâche pose en base.
    from wama.common.utils.batch_views import columns_changed, columns_snapshot
    before = columns_snapshot(enhancement)
    _apply_enhancement_settings(enhancement, _read_enhancement_settings(request))
    enhancement.save(update_fields=columns_changed(enhancement, before))

    return JsonResponse({
        'id': enhancement.id,
        'ai_model': enhancement.ai_model,
        'denoise': enhancement.denoise,
        'blend_factor': enhancement.blend_factor,
        'upscale_factor': enhancement.upscale_factor,
        'quality_intent': enhancement.quality_intent,
    })


# ===========================================================================
# Batch Enhancement Views (image/video only)
# ===========================================================================

def batch_template(request):
    """Download a batch file template (.txt)."""
    from django.http import HttpResponse
    content = (
        "# WAMA Enhancer - Batch Import\n"
        "# Format : une URL ou chemin de fichier image/vidéo par ligne\n"
        "# Les lignes commençant par # sont des commentaires.\n\n"
        "https://example.com/image.jpg\n"
        "https://example.com/video.mp4\n"
        "/media/uploads/photo.png\n"
    )
    response = HttpResponse(content, content_type='text/plain; charset=utf-8')
    response['Content-Disposition'] = 'attachment; filename="batch_enhancer_template.txt"'
    return response


@require_POST
def batch_preview(request):
    """Parse a batch file (one URL/path per line) and return the list for preview."""
    from wama.common.utils.batch_parsers import batch_media_list_preview_response
    from wama.common.app_registry import normalize_types

    def _enrich(item):
        # Même geste de classement que `tasks._derive`, défaut différent ('media' ici) :
        # c'est la POLITIQUE qui diffère, pas la classification.
        ext_item = item['filename'].rsplit('.', 1)[-1] if '.' in item['filename'] else ''
        cat = (normalize_types([ext_item]) or [''])[0]
        item['detected_type'] = cat if cat in ('image', 'video') else 'media'

    return batch_media_list_preview_response(request, item_enricher=_enrich)


@require_POST
def batch_create(request):
    """Parse batch file (URLs/paths), create BatchEnhancement + Enhancement entries."""
    from wama.common.utils.batch_parsers import parse_batch_file_from_request
    from wama.common.app_registry import IMAGE_EXTENSIONS, VIDEO_EXTENSIONS

    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
    # Chaque fille naît par la cascade COMMUNE d'un dépôt (2026-10-18) : elle lisait quatre
    # réglages dans le POST, avec leur défaut écrit ici, et le format de sortie jamais.
    settings_values = _deposit_settings(user, request.POST)

    try:
        items, warnings = parse_batch_file_from_request(request)
    except ValueError as e:
        return JsonResponse({'error': str(e)}, status=400)

    if not items:
        return JsonResponse({'error': 'Aucun élément valide trouvé dans le fichier'}, status=400)

    image_extensions = {'.jpg', '.jpeg', '.png', '.bmp', '.tif', '.tiff', '.webp', '.heic'}
    video_extensions = {'.mp4', '.webm', '.mkv', '.flv', '.gif', '.avi', '.mov', '.mpg', '.qt', '.3gp'}

    # parse_batch_file_from_request a consommé FILES['batch_file'] : on le re-lit
    # pour l'archiver sur le batch (NameError avant 2026-08-03).
    batch_file = request.FILES.get('batch_file')
    if batch_file:
        batch_file.seek(0)
    batch = BatchEnhancement.objects.create(
        user=user,
        total=len(items),
        batch_file=batch_file,
    )

    created_ids = []
    for i, item in enumerate(items):
        url_or_path = item['path']
        fname = url_or_path.split('/')[-1].split('\\')[-1] or url_or_path
        ext_item = '.' + fname.rsplit('.', 1)[-1].lower() if '.' in fname else ''
        if ext_item in image_extensions:
            media_type = 'image'
        elif ext_item in video_extensions:
            media_type = 'video'
        else:
            media_type = 'image'  # default

        enhancement = Enhancement.objects.create(
            **settings_values,
            user=user,
            source_url=url_or_path,
            media_type=media_type,
        )
        BatchEnhancementItem.objects.create(batch=batch, enhancement=enhancement, row_index=i)
        created_ids.append(enhancement.id)

    return JsonResponse({
        'batch_id': batch.id,
        'enhancement_ids': created_ids,
        'total': len(items),
        'warnings': warnings,
    })


def batch_list(request):
    """List current user's batches with status counts."""
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
    batches = BatchEnhancement.objects.filter(user=user).prefetch_related('items__enhancement')

    from wama.common.utils.batch_common import batch_elements
    data = []
    for batch in batches:
        counts = {'success': 0, 'running': 0, 'pending': 0, 'failure': 0}
        for e in batch_elements(batch, Enhancement):     # lit le cache du prefetch, 0 requête
            k = e.status.lower()
            counts[k] = counts.get(k, 0) + 1

        total = batch.total
        if total > 0 and counts['success'] == total:
            status = 'SUCCESS'
        elif counts['running'] > 0:
            status = 'RUNNING'
        elif counts['pending'] == 0 and counts['running'] == 0 and counts['failure'] > 0:
            status = 'FAILURE'
        else:
            status = 'PENDING'

        data.append({
            'id': batch.id,
            'created_at': batch.created_at.strftime('%d/%m/%Y %H:%M'),
            'total': total,
            'status': status,
            'counts': counts,
        })

    return JsonResponse({'batches': data})


# ── Vues de lot MÉDIA : fabrique COMMUNE (`batch_views.make_batch_views`, portage 2026-09-23,
# 6ᵉ app réelle — ROUTE §11 #36 ; l'enhancer a DEUX files, donc deux fabriques). Spécificités
# DÉCLARÉES en kwargs : remise à zéro + cache de progression `enhancer_progress_<id>` à 0 sous le
# verrou, libellé = nom d'entrée ou URL, nom de chaque entrée du ZIP = `get_output_filename()`,
# dimensions/poids/durée de sortie remis à 0 à la duplication, cache purgé à la suppression.
# `batch_update` vient AUSSI de la fabrique depuis le 2026-10-02 : elle lit les réglages postés
# selon le schéma et les pose par `_apply_enhancement_settings` — LA fonction que la route d'un
# élément appelle aussi (`apply_settings`). La vue locale ne faisait que refaire sa boucle.
from wama.common.utils.batch_views import DEFAULT_RESET, make_batch_views
from wama.enhancer.params import MEDIA_PARAMS_JSON as _MEDIA_SCHEMA


def _get_user(request):
    return request.user if request.user.is_authenticated else get_or_create_anonymous_user()


def _media_task(e):
    from .tasks import enhance_media
    return enhance_media


def _reset_media_and_clear_progress(e):
    e.progress = 0
    e.error_message = ''
    cache.set(f"enhancer_progress_{e.id}", 0, timeout=3600)


# ▶ d'UN process de la card (`ROUTE §10.6` 5.1) : fabrique COMMUNE — refaire la sortie seule
# (format, qualité) sans relancer l'amélioration. Le lancement lit les réglages STOCKÉS.
from wama.common.utils.process_views import make_process_start_view  # noqa: E402

start_process = make_process_start_view(
    work_model=Enhancement, task_for=_media_task,
    reset_on_start=_reset_media_and_clear_progress)


_bv = make_batch_views(
    work_model=Enhancement, batch_model=BatchEnhancement, get_user=_get_user,
    task_for=_media_task,
    output_fields=('output_file',),
    output_name=lambda e: e.get_output_filename(),
    zip_name=lambda b: f"batch_enhancer_{b.id}_{datetime.date.today()}.zip",
    item_model=BatchEnhancementItem, fk_name='enhancement',
    reset_on_start=_reset_media_and_clear_progress,
    reset_on_duplicate={**DEFAULT_RESET, 'output_width': 0, 'output_height': 0,
                        'output_file_size': 0, 'processing_time': 0},
    progress_of=lambda e: cache.get(f"enhancer_progress_{e.id}", e.progress or 0),
    item_label=lambda e: e.get_input_filename() or e.source_url,
    on_delete=lambda e: cache.delete(f"enhancer_progress_{e.id}"),
    schema=_MEDIA_SCHEMA, empty_is_value=SETTINGS_EMPTY_IS_VALUE,
    apply_settings=_apply_enhancement_settings,
)
batch_start = _bv['batch_start']
batch_update = _bv['batch_update']
batch_status = _bv['batch_status']
batch_download = _bv['batch_download']
batch_delete = _bv['batch_delete']
batch_duplicate = _bv['batch_duplicate']
batch_promote = _bv['batch_promote']
batch_realign = _bv['batch_realign']


# ===========================================================================
# Audio Enhancement Views
# ===========================================================================

# Jeu d'extensions audio : LE commun (`app_registry.AUDIO_EXTENSIONS`), pas une copie.
# La copie locale qui vivait ici omettait `.aif`/`.aiff` — deux portes (dépôt médiathèque et
# upload direct) rendaient donc un 400 « Format audio non supporté » sur un fichier que la
# dropzone (`audio/*`) laissait choisir et que la médiathèque classe en audio. Divergence
# MUETTE : un sous-ensemble ne lève rien, il refuse. Décodage vérifié avant d'élargir —
# soundfile (vers qui torchaudio est patché) écrit et relit l'AIFF.
def _audio_extensions() -> set:
    from wama.common.app_registry import AUDIO_EXTENSIONS
    return {e if e.startswith('.') else '.' + e for e in AUDIO_EXTENSIONS}


@require_POST
def audio_upload(request):
    """Upload an audio file for speech enhancement, or register from file_path."""
    import json as _json
    from pathlib import Path as _Path
    from django.conf import settings as _settings
    from django.core.files import File as _File

    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()

    # --- Option A: file_path from filemanager (server-side path) ---
    file_path = None
    try:
        body = _json.loads(request.body)
        file_path = body.get('file_path', '').strip()
    except Exception:
        pass

    if file_path:
        from wama.common.utils.media_paths import OutsideMediaRoot, resolve_under_media_root
        try:
            src, _ = resolve_under_media_root(file_path)
        except (OutsideMediaRoot, FileNotFoundError):
            return JsonResponse({'error': 'Fichier introuvable ou accès refusé'}, status=400)
        if src.suffix.lower() not in _audio_extensions():
            return JsonResponse({'error': f'Format audio non supporté : {src.suffix}'}, status=400)

        try:
            with open(str(src), 'rb') as f:
                django_file = _File(f, name=src.name)
                ae = AudioEnhancement.objects.create(
                    user=user,
                    input_file=django_file,
                    file_size=src.stat().st_size,
                    # Naissance COMMUNE (2026-10-28) : défauts ← volet retenu ← ce qui est posté.
                    **_audio_deposit_settings(user, {k: v for k, v in body.items()
                                                     if k != 'file_path'}),
                )
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=500)

        _wrap_audio_in_batch(ae)
        return JsonResponse({
            'id': ae.id,
            'input_filename': ae.get_input_filename(),
            'file_size': ae.file_size,
            'duration': ae.duration,
            'status': ae.status,
        })

    # --- Option B: fichier TÉLÉVERSÉ, ou DÉSIGNÉ (médiathèque, arbre) — brique `received_inputs`,
    # comme la vue `upload` de la même app. ⚠ Jusqu'au 2026-09-30 cette vue ne lisait que
    # `request.FILES['file']` : la désignation (28/09 — la tuile Médiathèque et le glisser depuis
    # l'arbre POINTENT au lieu de recopier) tombait en « Bad Request » sur la card AUDIO, en v3
    # comme en v4. Trouvé par le geste `enhancer.tree_drop`, le premier à mesurer cette card.
    from wama.common.utils.media_paths import received_inputs
    received = received_inputs(request, user, 'enhancer')
    if not received:
        return JsonResponse({'error': received.refusal or 'Aucun fichier fourni'}, status=400)
    file = received[0]

    ext = os.path.splitext(file.name)[1].lower()
    if ext not in _audio_extensions():
        return JsonResponse({'error': f'Format audio non supporté : {ext}'}, status=400)

    try:
        ae = AudioEnhancement.objects.create(
            user=user,
            input_file=file.value,
            file_size=getattr(file.value, 'size', 0) or 0,
            # Naissance COMMUNE (2026-10-28) : défauts ← volet retenu ← ce que le dépôt poste ;
            # ce qui est posté devient la mémoire du volet audio.
            **_audio_deposit_settings(user, request.POST),
        )
        file.record(ae, 'input_file')
        if not ae.file_size:
            try:
                ae.file_size = ae.input_file.size
                ae.save(update_fields=['file_size'])
            except Exception:
                pass
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)

    # Attempt to get duration via ffprobe
    try:
        from ..common.utils.video_utils import get_media_info
        info = get_media_info(ae.input_file.path)
        ae.duration = info.get('duration', 0)
        ae.file_size = info.get('file_size', ae.file_size)
        ae.save(update_fields=['duration', 'file_size'])
    except Exception:
        pass

    _wrap_audio_in_batch(ae)
    return JsonResponse({
        'id': ae.id,
        'input_filename': ae.get_input_filename(),
        'file_size': ae.file_size,
        'duration': ae.duration,
        'status': ae.status,
    })


@require_POST
def audio_stop(request, pk: int):
    """Stoppe le débruitage audio en cours → item relançable (↻). Brique commune process_control."""
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
    from wama.common.utils.scoping import editable_or_404
    ae = editable_or_404(AudioEnhancement, user, pk=pk)
    if ae.status not in ('RUNNING', 'PENDING'):
        return JsonResponse({'id': ae.id, 'status': ae.status})
    from wama.common.utils.process_control import stop_instance
    new_status = stop_instance(ae, error_field='error_message')
    return JsonResponse({'id': ae.id, 'status': new_status})


@require_POST
def audio_update(request, pk: int):
    """Met à jour les réglages d'un item audio (inspecteur/modale). Miroir de update_settings."""
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
    from wama.common.utils.scoping import editable_or_404
    ae = editable_or_404(AudioEnhancement, user, pk=pk)
    from wama.common.utils.batch_views import columns_changed, columns_snapshot
    before = columns_snapshot(ae)      # en cours compris : seules les colonnes changées s'écrivent
    # Les réglages par LE schéma audio (JSON de l'inspecteur ou formulaire de la modale), posés par
    # la fonction unique du domaine (2026-10-28) — la liste écrite ici en était une recopie.
    _apply_audio_settings(ae, _read_audio_settings(request))
    ae.save(update_fields=columns_changed(ae, before))
    return JsonResponse({'id': ae.id, 'engine': ae.engine, 'mode': ae.mode,
                         'denoising_strength': ae.denoising_strength, 'quality': ae.quality,
                         'quality_intent': ae.quality_intent,
                         'output_format': ae.output_format, 'output_quality': ae.output_quality})


@require_POST
def audio_start(request, pk: int):
    """Start audio enhancement processing."""
    import json as _json

    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()

    try:
        data = _json.loads(request.body) if request.body else {}
    except Exception:
        data = {}

    def _apply_settings(a):
        # Le ▶ de la card lance avec les réglages STOCKÉS (corps vide, comme le domaine
        # image/vidéo) ; un appelant qui en poste passe par la fonction unique du domaine.
        _apply_audio_settings(a, data)
        a.progress = 0
        a.error_message = ''

    # Anti-race COMMUN (atomic + select_for_update + revoke) — audit 2026-07-11
    from wama.common.utils.process_control import begin_processing
    ae, err = begin_processing(AudioEnhancement, pk, user=user, reset=_apply_settings)
    if err:
        return JsonResponse({'error': err}, status=404 if err == 'not_found' else 400)

    from .tasks import enhance_audio
    try:
        task = enhance_audio.delay(pk)
        ae.task_id = task.id
        ae.save(update_fields=['task_id'])
        return JsonResponse({'task_id': task.id, 'status': 'RUNNING'})
    except Exception as e:
        ae.status = 'PENDING'
        ae.save(update_fields=['status'])
        return JsonResponse({'error': str(e)}, status=500)



def audio_download(request, pk: int):
    """Download enhanced audio file."""
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
    ae = visible_or_404(AudioEnhancement, user, pk=pk)        # LECTURE

    if not ae.output_file:
        return HttpResponseBadRequest('No output file available')

    from django.core.files.storage import default_storage
    if not default_storage.exists(ae.output_file.name):
        return HttpResponseBadRequest('Output file not found in storage')

    return FileResponse(
        ae.output_file.open('rb'),
        as_attachment=True,
        filename=ae.get_output_filename(),
    )


@require_POST
def audio_delete(request, pk: int):
    """Delete audio enhancement and clean up parent batch-of-1 if empty."""
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
    ae = get_object_or_404(AudioEnhancement, pk=pk, user=user)

    # Lot de l'élément, relevé AVANT la suppression — brique commune (`batch_common`).
    from wama.common.utils.batch_common import batch_snapshot, batch_state
    snapshot = batch_snapshot(ae)

    # Entrée et sortie LIBÉRÉES par la brique (une entrée partagée avec un doublon reste)
    release_card_files(ae)

    ae.delete()  # signal batch_sync : recale total / supprime le batch vidé (+ fichier batch)
    cache.delete(f"audio_enhancer_progress_{pk}")

    return JsonResponse({'deleted': pk, 'batch': batch_state(snapshot, AudioEnhancement)})


@require_POST
def audio_duplicate(request, pk: int):
    """Duplicate an AudioEnhancement sharing the same input_file, resetting results."""
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
    from wama.common.utils.scoping import duplicable_or_404
    ae = duplicable_or_404(AudioEnhancement, user, pk=pk)
    new_ae = duplicate_instance(
        ae,
        for_user=user,
        reset_fields={
            'status': 'PENDING',
            'progress': 0,
            'task_id': '',
            'error_message': '',
            'processing_time': 0,
        },
        clear_fields=['output_file'],
    )
    # Aligné sur l'image/vidéo + le Synthesizer : doublon dans SON PROPRE batch-of-1.
    # Sinon il reste orphelin et l'auto-wrap le groupe par nature → effet « batch » surprenant.
    try:
        _wrap_audio_in_batch(new_ae)
    except Exception:
        pass
    return JsonResponse({'duplicated': new_ae.id})


@require_POST
def audio_start_all(request):
    """Start all pending audio enhancements."""
    import json as _json

    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()

    try:
        data = _json.loads(request.body) if request.body else {}
    except Exception:
        data = {}

    from .tasks import enhance_audio
    from wama.common.utils.process_control import begin_processing

    pending = AudioEnhancement.objects.filter(user=user)
    started, errors = [], []

    def _apply_globals(ae):
        # « Tout démarrer » applique le volet à toute la file (comme le domaine image/vidéo), par
        # la fonction unique du domaine — sa liste de quatre réglages en était une recopie.
        _apply_audio_settings(ae, data)

    for ae in pending:
        try:
            # Anti-race COMMUN — même brique que audio_start()
            locked, err = begin_processing(AudioEnhancement, ae.pk, user=user,
                                           reset=_apply_globals)
            if err:
                continue  # already_running / not_found
            task = enhance_audio.delay(locked.id)
            locked.task_id = task.id
            locked.save(update_fields=['task_id'])
            started.append(locked.id)
        except Exception as e:
            errors.append({'id': ae.id, 'error': str(e)})

    return JsonResponse({'started_ids': started, 'count': len(started), 'errors': errors})


@require_POST
def audio_clear_all(request):
    """Clear all audio enhancements and batch containers."""
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
    aes = AudioEnhancement.objects.filter(user=user)
    cleared = []
    for ae in aes:
        cleared.append(ae.id)
        release_card_files(ae)
        cache.delete(f"audio_enhancer_progress_{ae.id}")
    aes.delete()
    # Clean up orphan batch containers and their files
    batches = BatchAudioEnhancement.objects.filter(user=user)
    for batch in batches:
        release_card_files(batch)
    batches.delete()
    return JsonResponse({'cleared_ids': cleared, 'count': len(cleared)})


# ⬇ « Télécharger tout » de la barre de file : le ZIP de la file que compte la barre globale,
# par la fabrique commune (`make_progress_views`, 2026-10-17 — REMOVAL_LEDGER R142).
audio_download_all = _apv['download_all']



# ===========================================================================
# Audio Batch Views
# ===========================================================================

def audio_batch_template(request):
    """Download a batch file template for audio enhancement."""
    content = (
        "# WAMA Enhancer — Batch Audio Import\n"
        "# Format : une URL ou chemin de fichier audio par ligne\n"
        "# Les lignes commençant par # sont des commentaires.\n"
        "# Formats supportés : MP3, WAV, FLAC, OGG, M4A, AAC, OPUS, WMA\n"
        "\n"
        "https://example.com/audio.mp3\n"
        "/media/uploads/voice.wav\n"
    )
    from django.http import HttpResponse
    response = HttpResponse(content, content_type='text/plain; charset=utf-8')
    response['Content-Disposition'] = 'attachment; filename="batch_audio_enhancer_template.txt"'
    return response


@require_POST
def audio_batch_preview(request):
    """Parse a batch file (one audio URL/path per line) and return the list for preview — the
    COMMON helper of the image/video batch (2026-10-28 : the file's reading was copied here)."""
    from wama.common.utils.batch_parsers import batch_media_list_preview_response
    return batch_media_list_preview_response(request)


@require_POST
def audio_batch_create(request):
    """Parse batch file, create BatchAudioEnhancement + AudioEnhancement entries — the batch file
    is read by the COMMON helper, as the image/video batch does (2026-10-28)."""
    from wama.common.utils.batch_parsers import parse_batch_file_from_request
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
    try:
        items, warnings = parse_batch_file_from_request(request)
    except ValueError as e:
        return JsonResponse({'error': str(e)}, status=400)

    if not items:
        return JsonResponse({'error': 'Aucun élément valide trouvé dans le fichier'}, status=400)

    batch_file = request.FILES.get('batch_file')  # re-lu après parsing (NameError avant 2026-08-03)
    if batch_file:
        batch_file.seek(0)
    batch = BatchAudioEnhancement.objects.create(user=user, total=len(items), batch_file=batch_file)

    # Chaque fille naît par la cascade COMMUNE d'un dépôt (2026-10-28) : elle naissait sur les
    # défauts du modèle, et le ▶ du lot devait lui reposter le volet.
    settings_values = _audio_deposit_settings(user, request.POST)
    created_ids = []
    for i, item in enumerate(items):
        url_or_path = item['path']
        ae = AudioEnhancement.objects.create(**settings_values, user=user, source_url=url_or_path)
        BatchAudioEnhancementItem.objects.create(batch=batch, audio_enhancement=ae, row_index=i)
        created_ids.append(ae.id)

    return JsonResponse({'batch_id': batch.id, 'audio_ids': created_ids, 'total': len(items), 'warnings': warnings})


# ── Vues de lot AUDIO : la seconde fabrique de l'enhancer (mêmes briques, autre file).
# ▶ de lot PORTE des réglages (moteur, mode, force du débruitage, qualité, curseur) postés en
# JSON avec le démarrage : `start_reset_for` fabrique la remise à zéro depuis la requête —
# sous le verrou, comme avant. Cache `audio_enhancer_progress_<id>`, ZIP `audio_batch_<id>_<date>`.
def _audio_task(ae):
    from .tasks import enhance_audio
    return enhance_audio


audio_start_process = make_process_start_view(
    work_model=AudioEnhancement, task_for=_audio_task,
    reset_on_start={'progress': 0, 'error_message': ''})


def _audio_reset_for(request):
    import json as _json
    try:
        data = _json.loads(request.body) if request.body else {}
    except Exception:
        data = {}

    def _reset(ae):
        ae.progress = 0
        ae.error_message = ''
        # Un ▶ de lot qui POSTE des réglages les pose par la fonction unique du domaine ; sans
        # corps (les filles sont nées complètes depuis le 2026-10-28), il lance tel quel.
        _apply_audio_settings(ae, data)
    return _reset


from wama.enhancer.params import AUDIO_PARAMS_JSON as _AUDIO_SCHEMA  # noqa: E402

# Le schéma et LA fonction de réglage du domaine (2026-10-28) : la fabrique en tire les réglages de
# LOT (`batch_update` — le ⚙ de la card mère audio était rendu sans que rien ne l'écoute), la
# promotion d'une fille au lot et le réalignement, comme au domaine image/vidéo.
_abv = make_batch_views(
    work_model=AudioEnhancement, batch_model=BatchAudioEnhancement, get_user=_get_user,
    task_for=_audio_task, start_reset_for=_audio_reset_for,
    output_fields=('output_file',),
    output_name=lambda ae: ae.get_output_filename(),
    zip_name=lambda b: f"audio_batch_{b.id}_{datetime.date.today()}.zip",
    item_model=BatchAudioEnhancementItem, fk_name='audio_enhancement',
    reset_on_duplicate={**DEFAULT_RESET, 'processing_time': 0},
    progress_of=lambda ae: cache.get(f"audio_enhancer_progress_{ae.id}", ae.progress or 0),
    item_label=lambda ae: ae.get_input_filename() or ae.source_url,
    on_delete=lambda ae: cache.delete(f"audio_enhancer_progress_{ae.id}"),
    schema=_AUDIO_SCHEMA, empty_is_value=SETTINGS_EMPTY_IS_VALUE,
    apply_settings=_apply_audio_settings,
)
audio_batch_start = _abv['batch_start']
audio_batch_update = _abv['batch_update']
audio_batch_status = _abv['batch_status']
audio_batch_download = _abv['batch_download']
audio_batch_delete = _abv['batch_delete']
audio_batch_duplicate = _abv['batch_duplicate']
audio_batch_promote = _abv['batch_promote']
audio_batch_realign = _abv['batch_realign']


def console_content(request):
    """
    Retourne le contenu de la console (logs Celery + cache).
    """
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()

    # Récupère les logs depuis le cache et Celery
    all_lines = get_console_lines(user.id, limit=200)
    return JsonResponse({'output': all_lines})



# ═══════════════════════════════════════════════════════════════════════════
# Vues standard communes (port schéma-driven 2026-07-26) — LES DEUX DOMAINES
# ═══════════════════════════════════════════════════════════════════════════

def _req_user(request):
    return request.user if request.user.is_authenticated else get_or_create_anonymous_user()


def card_html(request, pk):
    """Card média = partial serveur UNIQUE (source du markup, remplace appendRow JS)."""
    from wama.common.utils.scoping import visible_or_404
    e = visible_or_404(Enhancement, _req_user(request), pk=pk)   # LECTURE : le sien OU reçu (2026-10-02)
    _decorate_media_card(e)  # chips du schéma — même décoration que l'IndexView
    # `in_batch` : position dans la file, brique commune. L'ancien `.exists()` valait True pour
    # un lot UNITAIRE (toute card est enveloppée dans son lot) → card seule rendue en fille.
    from wama.common.utils.batch_common import is_batch_child
    return render(request, 'enhancer/_enhancement_card.html',
                  {'elem': e, 'in_batch': is_batch_child(e)})


def audio_card_html(request, pk):
    """Card audio = partial serveur UNIQUE (remplace appendAudioRow JS)."""
    from wama.common.utils.scoping import visible_or_404
    ae = visible_or_404(AudioEnhancement, _req_user(request), pk=pk)   # LECTURE : le sien OU reçu (2026-10-02)
    _decorate_audio_card(ae)  # chips du schéma — même décoration que l'IndexView
    from wama.common.utils.batch_common import is_batch_child
    return render(request, 'enhancer/_audio_card.html',
                  {'elem': ae, 'in_batch': is_batch_child(ae)})




# ── Manipulation directe de la file (fabrique COMMUNE, variante liaison) ──────
# Les deux domaines ont un MODÈLE DE LIAISON (BatchEnhancementItem /
# BatchAudioEnhancementItem) → fabrique standard, `consolidate` compris (2026-10-16).
from wama.common.utils.queue_manipulation import make_queue_manipulation_views

_qm_media = make_queue_manipulation_views(
    work_model=Enhancement, batch_model=BatchEnhancement,
    item_model=BatchEnhancementItem, fk_name='enhancement', get_user=_req_user,
    group_key=_enhancement_nature,      # l'arrivée (`consolidate_arrival`) ET le glisser-déposer
)
remove_from_batch = _qm_media['remove_from_batch']
reorder           = _qm_media['reorder']
reorder_queue     = _qm_media['reorder_queue']
merge             = _qm_media['merge']
move_to_batch     = _qm_media['move_to_batch']

_qm_audio = make_queue_manipulation_views(
    work_model=AudioEnhancement, batch_model=BatchAudioEnhancement,
    item_model=BatchAudioEnhancementItem, fk_name='audio_enhancement', get_user=_req_user,
)
audio_remove_from_batch = _qm_audio['remove_from_batch']
audio_reorder           = _qm_audio['reorder']
audio_reorder_queue     = _qm_audio['reorder_queue']
audio_merge             = _qm_audio['merge']
audio_move_to_batch     = _qm_audio['move_to_batch']
# `consolidate` des deux files (2026-10-16) : la fabrique range PAR NATURE à l'arrivée
# (`consolidate_arrival`) — les deux versions locales et leurs helpers sont retirés.
consolidate             = _qm_media['consolidate']
audio_consolidate       = _qm_audio['consolidate']
