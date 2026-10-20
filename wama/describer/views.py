"""
WAMA Describer - Views
AI-powered content description and summarization
"""

import os
from wama.accounts.permissions import app_access
import json
import logging
import mimetypes
from pathlib import Path

from django.shortcuts import render, get_object_or_404
from django.http import JsonResponse, HttpResponse, FileResponse
from django.views.generic import TemplateView
from django.views.decorators.http import require_POST, require_GET
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.cache import cache
from django.conf import settings
from django.utils.http import content_disposition_header

from .models import Description, BatchDescription, BatchDescriptionItem
from wama.common.utils.queue_duplication import duplicate_instance, release_card_files
from ..accounts.views import get_or_create_anonymous_user

# Retiré par erreur le 2026-07-22 (portage de url_ingest) : les 9 `logger.*` de ce module levaient
# NameError — dont l'import par URL dès sa 1ʳᵉ ligne. Tenu par `tests_unbound_names`.
logger = logging.getLogger(__name__)

def new_description_settings(user, model=None, app='describer', post=None) -> dict:
    """Les colonnes de réglage d'une description NAISSANTE, par la cascade COMMUNE (défauts du
    schéma ← réglages de l'auteur ← ce que le dépôt poste, `user_settings.new_element_settings`,
    2026-10-18). Le dépôt de la card et l'import du gestionnaire de fichiers (« Envoyer vers »,
    sans volet donc sans POST) passent ici ; `model`/`app` : une jumelle de bac à sable passe les
    siens. Avant, seuls le style, la langue et la longueur naissaient de la préférence de l'auteur,
    avec leurs défauts recopiés ici ; les sept autres réglages prenaient le défaut du modèle. Un
    style mémorisé qui n'est plus proposé (« meeting », devenu un type de résumé) retombe sur le
    défaut par la règle de la brique."""
    from wama.common.utils.user_settings import new_element_settings
    from wama.describer.params import PARAMS_JSON, user_setting_key
    return new_element_settings(user, app, PARAMS_JSON, model or Description, post=post,
                                key=user_setting_key)


def _deposit_settings(user, post):
    """Les réglages d'un DÉPÔT (fichier, lien, lot) : ce que le volet poste est gardé comme
    préférences (`save_panel_settings`), puis la description naît par la cascade COMMUNE."""
    from wama.common.utils.user_settings import save_panel_settings
    from wama.describer.params import PARAMS_JSON, user_setting_key
    save_panel_settings(user, 'describer', PARAMS_JSON, post, key=user_setting_key)
    return new_description_settings(user, post=post)


def get_user(request):
    """Get authenticated user or anonymous user."""
    if request.user.is_authenticated:
        return request.user
    return get_or_create_anonymous_user()


# Jeux d'extensions : domicile unique de l'app (content_analyzer) — trois copies
# divergeaient en silence (heic accepté à l'upload, inconnu du routage).
from wama.describer.utils.content_analyzer import (
    DESCRIBER_AUD_EXTS as _DESCRIBER_AUD_EXTS,
    DESCRIBER_DOC_EXTS as _DESCRIBER_DOC_EXTS,
    DESCRIBER_IMG_EXTS as _DESCRIBER_IMG_EXTS,
    DESCRIBER_TEXT_LIKE_EXTS as _DESCRIBER_TEXT_LIKE_EXTS,
    DESCRIBER_VID_EXTS as _DESCRIBER_VID_EXTS,
)


def _describer_nature(description):
    """Nature d'une Description (image/video/audio/document) pour le groupement batch."""
    dt = (description.detected_type or '').lower()
    if dt in ('image', 'video', 'audio', 'document'):
        return dt
    name = (description.input_file.name if description.input_file else '') or (description.source_url or '')
    ext = name.rsplit('.', 1)[-1].lower() if '.' in name else ''
    if ext in _DESCRIBER_IMG_EXTS:
        return 'image'
    if ext in _DESCRIBER_VID_EXTS:
        return 'video'
    if ext in _DESCRIBER_AUD_EXTS:
        return 'audio'
    return 'document'


def _wrap_description_in_batch(description):
    """Wrap a standalone Description in a new BatchDescription-of-1."""
    batch = BatchDescription.objects.create(user=description.user, total=1)
    BatchDescriptionItem.objects.create(batch=batch, description=description, row_index=0)
    return batch


def _auto_wrap_orphans(user):
    """Range les Description pas encore en batch — brique COMMUNE, stratégie par défaut
    (orphelin → batch-of-1). Le regroupement par nature ne se fait plus qu'à l'ARRIVÉE
    (`queue_manipulation.consolidate_arrival`, constat Fabien 14/08)."""
    from wama.common.utils.batch_common import auto_wrap_orphans
    auto_wrap_orphans(user, work_model=Description, batch_model=BatchDescription,
                      item_model=BatchDescriptionItem, fk_name='description')


# Manipulation directe de la file (CARD_DESIGN §3bis) — vues GÉNÉRÉES par la brique commune.
# `consolidate` aussi depuis le 2026-10-16 : la fabrique range PAR NATURE par ce `group_key` — la
# version locale et le helper de l'import du gestionnaire de fichiers sont retirés.
from wama.common.utils.queue_manipulation import make_queue_manipulation_views

_qm = make_queue_manipulation_views(
    work_model=Description, batch_model=BatchDescription,
    item_model=BatchDescriptionItem, fk_name='description',
    group_key=_describer_nature,        # l'arrivée (`consolidate_arrival`) ET le glisser-déposer
    get_user=get_user,
)
remove_from_batch = _qm['remove_from_batch']
reorder = _qm['reorder']
reorder_queue = _qm['reorder_queue']
merge = _qm['merge']
move_to_batch = _qm['move_to_batch']
consolidate = _qm['consolidate']


class IndexView(TemplateView):
    """Main page with file queue."""
    template_name = 'describer/index.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = get_user(self.request)

        # Lazily wrap any orphan descriptions into a batch-of-1
        _auto_wrap_orphans(user)

        # Réconcilie les tâches RUNNING orphelines (worker mort/crash) — brique COMMUNE,
        # même câblage que transcriber : preuve positive de mort uniquement.
        try:
            from wama.common.utils.process_control import reconcile_orphaned_running
            running = list(Description.objects.filter(user=user, status='RUNNING'))
            n = reconcile_orphaned_running(running)
            if n:
                logging.getLogger(__name__).info(
                    f"[describer] {n} tâche(s) RUNNING orpheline(s) réconciliée(s) → échec relançable")
        except Exception:
            pass

        # Agrégats de file — brique COMMUNE (contrat toolbar) + enrichissements describer.
        from wama.common.utils.batch_common import build_batches_list

        def _extra(batch, items, descs):
            from wama.common.utils.card_chips import common_chips_for_items
            from wama.describer.params import PARAMS_JSON
            success_count = sum(1 for d in descs if d.status == 'SUCCESS')
            return {
                'success_pct': int(success_count / batch.total * 100) if batch.total > 0 else 0,
                # (l'ETA agrégée de la card mère, `eta_ids`, vient de `build_batches_list`)
                # Réglages COMMUNS aux filles (slot meta_template — porté le 31/08).
                'common_chips': common_chips_for_items(descs, PARAMS_JSON),
            }

        batches_list = build_batches_list(user, batch_model=BatchDescription,
                                          work_attr='description', order_by='-id',
                                          extra=_extra)

        # Chips de card GÉNÉRÉS du schéma (brique card_chips) + process — même décoration que
        # card_html ; les lignes d'exécution de la page lues en UNE requête (`decorate_cards`).
        from wama.common.services.process_pipeline import decorate_cards
        decorate_cards([link.description for b in batches_list for link in b['items']
                        if link.description], each=_decorate_desc)

        # Tri + filtrage de la file — brique COMMUNE (remplace le « batchs d'abord » codé en dur).
        from wama.common.utils.queue_view import apply_queue_sort_filter

        def _name(b):
            if b['obj'].total == 1 and b['items'] and b['items'][0].description:
                return (b['items'][0].description.filename or '').lower()
            return f"batch {b['obj'].id:08d}"
        batches_list, q_sort, q_filter = apply_queue_sort_filter(
            self.request, batches_list, name_of=_name)
        context['q_sort'] = q_sort
        context['q_filter'] = q_filter

        queue_count = sum(len(b['items']) for b in batches_list)

        # Also provide total counts for global progress bar
        all_descs = Description.objects.filter(user=user)
        context['batches_list'] = batches_list
        context['queue_count'] = queue_count
        context['output_style_choices'] = Description.OUTPUT_STYLE_CHOICES
        context['language_choices'] = Description.LANGUAGE_CHOICES
        # Schéma de params (source unique modale+inspecteur, rendu par WamaParams). Voir describer/params.py.
        from wama.describer.params import PARAMS_JSON
        context['params_json'] = json.dumps(PARAMS_JSON)
        # Appariement entrée ↔ modèles (brique commune, 2026-10-13) : le fichier de la card va
        # au modèle de transcription s'il s'entend, au modèle de vision s'il se voit — jugé par
        # les MODALITÉS que chaque modèle lit (`WamaInputMatch.modalitySlot`), sur le domaine
        # DÉCLARÉ de chaque select. Sans les entrées du catalogue : la card ne les fournit pas,
        # le pipeline les compose (la consigne, la piste son). Le modèle de langage reçoit du
        # texte du pipeline, jamais le fichier : pas d'appariement.
        from wama.common.app_registry import media_extensions
        from wama.common.utils.input_match import select_match_meta
        context['input_match_json'] = json.dumps({
            field: select_match_meta('describer', field, extra_caps=('modalities',), inputs=False)
            for field in ('asr_model', 'vision_model')})
        context['media_extensions_json'] = json.dumps(media_extensions())
        context['success_count'] = all_descs.filter(status='SUCCESS').count()
        context['descriptions'] = all_descs  # kept for global progress bar template ref

        return context


@require_POST
def upload(request):
    """Handle file upload or URL download."""
    user = get_user(request)

    # Check for URL upload first
    media_url = request.POST.get('media_url', '').strip()
    # Un fichier TÉLÉVERSÉ, ou DÉSIGNÉ (médiathèque, arbre) — brique `received_inputs` : une
    # désignation se POINTE au lieu d'être recopiée, avec le même état du volet.
    from wama.common.utils.media_paths import received_inputs
    received = received_inputs(request, user, 'describer')
    uploaded_file = received[0] if received else None

    if not uploaded_file and not media_url:
        return JsonResponse({'error': received.refusal or 'No file or URL provided'}, status=400)
    from wama.common.app_registry import accepts_file
    if uploaded_file and not accepts_file('describer', uploaded_file.name):
        return JsonResponse({'error': f'Format non pris en charge : '
                                      f'{os.path.splitext(uploaded_file.name)[1] or uploaded_file.name}'},
                            status=400)

    # URL : la SOURCE est enregistrée, le récepteur commun la télécharge dès la création, HORS
    # de la requête (`source_ingest`, 2026-10-13) — même geste que `batch_create`. La nature
    # exacte arrive avec le fichier (`derive` déclaré dans `WAMA_INGEST`).
    if media_url and not uploaded_file:
        settings_values = _deposit_settings(user, request.POST)
        fname = media_url.split('?')[0].rstrip('/').split('/')[-1] or media_url
        description = Description.objects.create(
            **settings_values,
            user=user,
            source_url=media_url,
            filename=fname,
            detected_type=_source_nature(media_url, fname),
        )
        _wrap_description_in_batch(description)
        return JsonResponse({
            'id': description.id,
            'filename': description.filename,
            'source_url': media_url,
            'detected_type': description.detected_type,
            'type_icon': description.get_type_icon(),
            'output_style': description.output_style,
            'output_language': description.output_language,
            'max_length': description.max_length,
            'status': description.status,
        })

    # Handle regular file upload
    filename = uploaded_file.name

    # Detect content type from extension
    ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
    detected_type = detect_type_from_extension(ext)

    # Réglages : la cascade COMMUNE d'un dépôt.
    settings_values = _deposit_settings(user, request.POST)

    # Create description record
    description = Description.objects.create(
        **settings_values,
        user=user,
        input_file=uploaded_file.value,
        filename=filename,
        file_size=uploaded_file.size,
        detected_type=detected_type,
    )
    uploaded_file.record(description, 'input_file')

    # Get file properties
    properties = get_file_properties(description)
    description.properties = properties
    description.save()

    _wrap_description_in_batch(description)

    return JsonResponse({
        'id': description.id,
        'filename': description.filename,
        'file_size': description.format_file_size(),
        'detected_type': description.detected_type,
        'type_icon': description.get_type_icon(),
        'output_style': description.output_style,
        'output_language': description.output_language,
        'max_length': description.max_length,
        'status': description.status,
        'properties': description.properties,
    })


def detect_type_from_extension(ext):
    """Detect content type from file extension (jeux d'extensions : content_analyzer).

    Vocabulaire de retour : image/video/audio/document — 'text' et 'pdf' ont fusionné dans
    'document' (2026-08-30, arbitrage taxonomie ; les deux routaient déjà vers describe_text).
    """
    if ext in _DESCRIBER_IMG_EXTS:
        return 'image'
    if ext in _DESCRIBER_VID_EXTS:
        return 'video'
    if ext in _DESCRIBER_AUD_EXTS:
        return 'audio'
    return 'document'


def _source_nature(source, fname):
    """Nature d'une ligne de lot AVANT son téléchargement. Une URL se lit d'abord par la table
    commune (`url_ingest.url_nature` : une vidéo YouTube `watch?v=…` est une vidéo, pas un
    document) ; sinon l'extension du nom ; à défaut, un document (une page web). La nature
    EXACTE est posée au téléchargement, dès la création (`_derive_detected_type`)."""
    from wama.common.utils.url_ingest import url_nature
    nature = url_nature(source) if source.lower().startswith(('http://', 'https://')) else ''
    if nature in ('image', 'video', 'audio'):
        return nature
    ext = fname.rsplit('.', 1)[-1].lower() if '.' in fname else ''
    return detect_type_from_extension(ext) if ext else 'document'


def get_file_properties(description):
    """Get file properties string."""
    ext = description.filename.rsplit('.', 1)[-1].lower() if '.' in description.filename else ''
    size = description.format_file_size()

    if description.detected_type == 'image':
        try:
            from PIL import Image
            with Image.open(description.input_file.path) as img:
                return f"{img.width}x{img.height} - {size}"
        except:
            pass
    elif description.detected_type in ('video', 'audio'):
        try:
            import subprocess
            from wama.common.utils.ffmpeg_utils import get_ffprobe_exe, adapt_path_for_ffmpeg
            _fp = get_ffprobe_exe()
            result = subprocess.run(
                [_fp, '-v', 'error', '-show_entries', 'format=duration',
                 '-of', 'default=noprint_wrappers=1:nokey=1',
                 adapt_path_for_ffmpeg(description.input_file.path, _fp)],
                capture_output=True, text=True, timeout=10
            )
            if result.returncode == 0:
                duration = float(result.stdout.strip())
                description.duration_seconds = duration
                mins = int(duration // 60)
                secs = int(duration % 60)
                description.duration_display = f"{mins}:{secs:02d}"
                return f"{description.duration_display} - {size}"
        except:
            pass

    return f"{ext.upper()} - {size}"


@require_POST
@app_access('describer')
def stop(request, pk):
    """
    Stoppe la description en cours (révoque la tâche Celery) → item relançable (bouton de cycle ↻).
    Brique commune : wama.common.utils.process_control.stop_instance.
    """
    user = get_user(request)
    try:
        from wama.common.utils.scoping import can_edit
        description = Description.objects.get(pk=pk)
        if not can_edit(user, description):     # le sien, ou en collaboration (E1)
            raise Description.DoesNotExist
    except Description.DoesNotExist:
        return JsonResponse({'error': 'Not found'}, status=404)
    if description.status not in ('RUNNING', 'PENDING'):
        return JsonResponse({'id': description.id, 'status': description.status})
    from wama.common.utils.process_control import stop_instance
    new_status = stop_instance(description, error_field='error_message')
    return JsonResponse({'id': description.id, 'status': new_status})


def _reset_for_relaunch(description):
    """Remise à zéro avant (re)lancement — appliquée SOUS le verrou anti-race.

    ⚠ Depuis le 2026-10-13 la card porte un PIPELINE (`function_specs.PIPELINE`) : un lancement
    ne rejoue que ce qui n'est plus à jour. Le résultat d'un process s'efface donc QUAND CE
    PROCESS EST REJOUÉ (sa glu le réécrit, `workers.PROCESSES`), plus ici — sinon relancer le seul
    résumé effacerait la description qu'il résume (la règle du transcriber, 2026-10-03)."""
    description.progress = 0
    description.error_message = ''


#: Ce qu'une card DUPLIQUÉE ne porte pas de son original : ses résultats, ceux de chaque process.
#: Une seule liste pour la duplication d'un élément et celle d'un lot (`make_batch_views`).
DUPLICATE_RESET = {'result_text': '', 'transcript': '', 'frame_captions': [], 'summary': '',
                   'coherence_score': None, 'coherence_notes': '', 'coherence_suggestion': ''}


# ── Les SIX vues de lot : fabrique COMMUNE (`batch_views.make_batch_views`, portage 2026-09-22,
# 1ʳᵉ app réelle après le générateur — ROUTE §11 #36). Les spécificités du describer sont
# DÉCLARÉES en kwargs : remise à zéro sous verrou (`_reset_for_relaunch` + cache à 0), cache de
# progression `describer_progress_<id>` lu par `batch_status` et purgé à la suppression,
# `result_text` vidé à la duplication, gating `@app_access` sur le démarrage. `batch_download`
# vient AUSSI de la fabrique depuis le 2026-10-02 : le format se choisit au téléchargement
# (`export_binding='late'`), donc la fabrique lit les formats DÉCLARÉS au catalogue et le rendu
# ENREGISTRÉ (`build_description_bytes`, `apps.py`) — la vue locale recopiait les deux en dur.
# Seule la souche du nom de chaque entrée reste dite ici (`_output_stem`).
from wama.common.utils.batch_views import (DEFAULT_RESET, apply_item_settings, make_batch_views,
                                           read_settings_payload)
from wama.describer.params import PARAMS_JSON as _SCHEMA
from .workers import describe_content as _describe_content


def _output_stem(d):
    """Souche du nom d'une description RENDUE dans un ZIP de lot — règle commune de nommage
    (`compose_output_name`) sur le nom d'origine du fichier ; l'extension vient du rendu."""
    from wama.common.utils.output_naming import compose_output_name
    return os.path.splitext(compose_output_name(
        app='describer', source_name=d.filename or f'desc_{d.id}', item_id=d.id))[0]


#: Réglages d'un élément — les colonnes que la modale et le volet écrivent (schéma `params.py`).
SETTINGS_FIELDS = ('output_style', 'output_language', 'max_length', 'asr_model',
                   'quality_intent', 'vision_model', 'llm_model', 'generate_summary',
                   'summary_type', 'verify_coherence')


def _reset_and_clear_progress(description):
    """Remise à zéro AVANT (re)lancement d'une fille de lot — sous le verrou anti-race, comme
    `start`, plus le cache de progression à 0 (ce que `batch_start` faisait après le verrou)."""
    _reset_for_relaunch(description)
    cache.set(f"describer_progress_{description.id}", 0, timeout=3600)


_bv = make_batch_views(
    work_model=Description, batch_model=BatchDescription, get_user=get_user,
    task=_describe_content,
    output_fields=('result_file',),
    params_fields=SETTINGS_FIELDS, schema=_SCHEMA,
    item_model=BatchDescriptionItem, fk_name='description',
    reset_on_start=_reset_and_clear_progress,
    reset_on_duplicate={**DEFAULT_RESET, **DUPLICATE_RESET},
    progress_of=lambda d: cache.get(f"describer_progress_{d.id}", d.progress or 0),
    on_delete=lambda d: cache.delete(f"describer_progress_{d.id}"),
    output_name=_output_stem,
)
batch_start = app_access('describer')(_bv['batch_start'])
batch_update = _bv['batch_update']
batch_delete = _bv['batch_delete']
batch_duplicate = _bv['batch_duplicate']
batch_download = _bv['batch_download']
batch_status = _bv['batch_status']
batch_promote = _bv['batch_promote']
batch_realign = _bv['batch_realign']


@app_access('describer')
@require_POST   # un GET lançait le traitement (parcours des adresses, 2026-09-22)
def start(request, pk):
    """Start processing a description — anti-race via la brique commune (2026-07-06 :
    l'implémentation inline d'origine a été PROMUE en process_control.begin_processing)."""
    from .workers import describe_content
    from wama.common.utils.process_control import begin_processing

    user = get_user(request)
    description, err = begin_processing(Description, pk, user=user, reset=_reset_for_relaunch)
    if err == 'not_found':
        return JsonResponse({'error': 'Not found'}, status=404)
    if err == 'already_running':
        return JsonResponse({'error': 'Already running'}, status=400)

    task = describe_content.delay(description.id)
    description.task_id = task.id
    description.save(update_fields=['task_id'])

    return JsonResponse({
        'id': description.id,
        'task_id': task.id,
        'status': 'RUNNING',
    })


from wama.common.utils.process_views import make_process_start_view  # noqa: E402

# ▶ d'UN process de la card (`ROUTE §10.6` 5.1) : fabrique COMMUNE — c'est aussi le résumé ou la
# cohérence « à la demande » sur une description déjà faite.
start_process = app_access('describer')(make_process_start_view(
    work_model=Description, task_for=lambda d: _describe_content,
    get_user=get_user, reset_on_start=_reset_and_clear_progress))


def _decorate_desc(desc, preloaded=False):
    """Chips de card générés du SCHÉMA (params.py chip=True) — brique commune card_chips —, puis
    les PROCESS de la card et son état MONTRÉ (`process_pipeline.decorate`, `ROUTE §10.6` 5.1).
    Le modèle est celui que la card demande, « auto » compris : les process se montrent AVANT le
    premier lancement — c'est là que leurs cases à cocher servent."""
    from wama.common.services.process_pipeline import decorate
    from wama.common.utils.card_chips import chips_by_section
    from wama.describer.params import PARAMS_JSON
    desc.chips = chips_by_section(desc, PARAMS_JSON)
    decorate(desc, preloaded=preloaded)
    return desc


@require_GET
def card_html(request, pk):
    """Card RENDUE serveur — source UNIQUE du markup (partial _description_card.html ;
    CARD_DESIGN « partial server-side + update JS en place », recette T+C 2026-07-05)."""
    from django.http import HttpResponse
    from django.template.loader import render_to_string
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
    # Lecture → partage F7 (le sien, ou partagé unité/projet/public)
    from wama.common.utils.scoping import visible_or_404
    desc = visible_or_404(Description, user, pk=pk)
    from wama.common.utils.batch_common import is_batch_child
    html = render_to_string('describer/_description_card.html',
                            {'elem': _decorate_desc(desc), 'in_batch': is_batch_child(desc)},
                            request=request)
    return HttpResponse(html)


def _progress_extra(description):
    """Les clés PROPRES que le JS du describer lit : le résultat. Le texte qui se construit n'y
    est plus (2026-10-20) : la card le lit à la face Pendant commune, comme le volet.

    Résumé et cohérence ne sont rendus que si leur process est ACTIVÉ : depuis le pipeline, le
    lancement ne les efface plus (`_reset_for_relaunch`), et un optionnel désactivé ne pèse plus
    sur la card (`ROUTE §10.6` règle 4.4) — l'onglet d'un résumé qu'on a décoché reste vide, comme
    quand la relance l'effaçait."""
    data = {}
    if description.status == 'SUCCESS':
        data['result_text'] = description.result_text
        if description.result_file:
            data['result_url'] = description.result_file.url
        from .function_specs import summary_text
        on_summary = summary_text(description) is not None
        on_coherence = description.verify_coherence
        data['summary'] = (description.summary or '') if on_summary else ''
        data['coherence_score'] = description.coherence_score if on_coherence else None
        data['coherence_notes'] = (description.coherence_notes or '') if on_coherence else ''
        data['coherence_suggestion'] = ((description.coherence_suggestion or '')
                                        if on_coherence else '')
    return data


# Les DEUX vues de progression : fabrique COMMUNE (`progress_views.make_progress_views`, ROUTE §11
# #37, 2026-10-03) — le describer n'y déclare que ses clés propres. Plus de triplet d'ETA de vue
# depuis le pipeline (2026-10-13) : la card s'estime à la SOMME de ses process, chacun déclarant
# le sien (`ProcessSpec.eta`, `workers.*_eta`) — deux estimations pour une card divergeaient.
from wama.common.utils.progress_views import make_progress_views  # noqa: E402

_pv = make_progress_views(work_model=Description, app_id='describer', extra=_progress_extra)
progress = _pv['progress']
global_progress = require_GET(_pv['global_progress'])


@require_GET
def download(request, pk):
    """Download result in requested format: txt (default), pdf, docx."""
    user = get_user(request)
    # Lecture → partage F7 (le sien, ou partagé unité/projet/public)
    from wama.common.utils.scoping import visible_or_404
    description = visible_or_404(Description, user, pk=pk)

    if description.status != 'SUCCESS':
        return JsonResponse({'error': 'No result available'}, status=400)

    fmt = request.GET.get('format', 'txt').lower()
    # SOUCHE par la BRIQUE COMMUNE (`compose_output_name`, 2026-08-25) — le describer
    # composait `{base}_description` a la main. Le tag `description` est DECLARE, donc la
    # convention connue de l'utilisateur est preservee ; s'ajoute l'identifiant de card,
    # qui rend les entrees d'un ZIP uniques quand deux descriptions partagent une source.
    from wama.common.utils.output_naming import compose_output_name
    base_name = os.path.splitext(compose_output_name(
        app='describer', source_name=description.filename, item_id=description.pk))[0]

    if fmt == 'pdf':
        try:
            from wama.common.utils.document_export import generate_description_pdf
            pdf_bytes = generate_description_pdf(description)
            response = HttpResponse(pdf_bytes, content_type='application/pdf')
            response['Content-Disposition'] = content_disposition_header(True, f"{base_name}.pdf")
            return response
        except ImportError as e:
            return JsonResponse({'error': str(e)}, status=501)
        except Exception as e:
            logger.error(f"[Describer] PDF generation failed: {e}")
            return JsonResponse({'error': f'Erreur génération PDF : {e}'}, status=500)

    if fmt == 'docx':
        try:
            from wama.common.utils.document_export import generate_description_docx
            docx_bytes = generate_description_docx(description)
            response = HttpResponse(
                docx_bytes,
                content_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document'
            )
            response['Content-Disposition'] = content_disposition_header(True, f"{base_name}.docx")
            return response
        except ImportError as e:
            return JsonResponse({'error': str(e)}, status=501)
        except Exception as e:
            logger.error(f"[Describer] DOCX generation failed: {e}")
            return JsonResponse({'error': f'Erreur génération DOCX : {e}'}, status=500)

    # Default: txt
    if description.result_file and os.path.exists(description.result_file.path):
        return FileResponse(
            open(description.result_file.path, 'rb'),
            as_attachment=True,
            filename=description.result_file.name.split('/')[-1]
        )
    if description.result_text:
        content = description.result_text.encode('utf-8')
        response = HttpResponse(content, content_type='text/plain; charset=utf-8')
        response['Content-Disposition'] = content_disposition_header(True, f"{base_name}.txt")
        return response

    return JsonResponse({'error': 'No result available'}, status=400)


@require_POST
def duplicate(request, pk):
    """Duplicate a Description sharing the same input file, resetting results."""
    user = get_user(request)
    from wama.common.utils.scoping import duplicable_or_404
    description = duplicable_or_404(Description, user, pk=pk)
    new_desc = duplicate_instance(
        description,
        for_user=user,
        reset_fields={
            'status': 'PENDING',
            'progress': 0,
            'task_id': '',
            'properties': '',
            'error_message': '',
            **DUPLICATE_RESET,
        },
        clear_fields=['result_file'],
    )
    # Dupliquer DANS le même batch que l'original (élément frère).
    orig_item = BatchDescriptionItem.objects.filter(description=description).select_related('batch').first()
    if orig_item:
        from django.db.models import Max
        batch = orig_item.batch
        next_idx = (batch.items.aggregate(m=Max('row_index'))['m'] or 0) + 1
        BatchDescriptionItem.objects.create(batch=batch, description=new_desc, row_index=next_idx)
        batch.total = batch.items.count()
        batch.save(update_fields=['total'])
    else:
        _wrap_description_in_batch(new_desc)
    return JsonResponse({'duplicated': new_desc.id})


@require_POST
def delete(request, pk):
    """Delete a description."""
    user = get_user(request)
    description = get_object_or_404(Description, pk=pk, user=user)

    # Lot de l'élément, relevé AVANT la suppression — brique commune (`batch_common`).
    from wama.common.utils.batch_common import batch_snapshot, batch_state
    snapshot = batch_snapshot(description)

    # Fichiers LIBÉRÉS par la brique, à l'échelle de la card
    release_card_files(description)

    description.delete()  # signal batch_sync : recale total / supprime le batch vidé

    return JsonResponse({'deleted': True, 'id': pk, 'batch': batch_state(snapshot, Description)})


@require_GET
@require_POST
@app_access('describer')
def start_all(request):
    """Start all pending descriptions."""
    user = get_user(request)
    pending = Description.objects.filter(user=user, status='PENDING')

    from .workers import describe_content
    from wama.common.utils.process_control import begin_processing

    started = []
    for description in pending:
        locked, err = begin_processing(Description, description.pk, user=user,
                                       reset=_reset_for_relaunch)
        if err:
            continue
        task = describe_content.delay(locked.id)
        locked.task_id = task.id
        locked.save(update_fields=['task_id'])
        started.append(locked.id)

    return JsonResponse({'started': started, 'count': len(started)})


@require_POST
def clear_all(request):
    """Delete all descriptions."""
    user = get_user(request)
    descriptions = Description.objects.filter(user=user)

    count = descriptions.count()

    for desc in descriptions:
        release_card_files(desc)

    descriptions.delete()

    return JsonResponse({'deleted': count})


# ⬇ « Télécharger tout » de la barre de file : le ZIP de la file que compte la barre globale,
# par la fabrique commune (`make_progress_views`, 2026-10-17 — REMOVAL_LEDGER R142).
download_all = _pv['download_all']


@require_POST
def batch_preview(request):
    """Parse a batch file (one URL/path per line) and return the list for preview."""
    from wama.common.utils.batch_parsers import batch_media_list_preview_response

    def _enrich(item):
        item['detected_type'] = _source_nature(item.get('path') or '', item['filename'])

    return batch_media_list_preview_response(request, item_enricher=_enrich)


@require_POST
def batch_import(request):
    """
    Create Description entries from a batch file of URLs/paths.
    Files are not downloaded in the request — the common receiver downloads each URL right
    after creation, outside the request (`source_ingest`).
    """
    from wama.common.utils.batch_parsers import parse_batch_file_from_request

    user = get_user(request)
    settings_values = _deposit_settings(user, request.POST)

    try:
        items, warnings = parse_batch_file_from_request(request)
    except ValueError as e:
        return JsonResponse({'error': str(e)}, status=400)

    if not items:
        return JsonResponse({'error': 'Aucun élément valide trouvé dans le fichier'}, status=400)

    created = []
    for item in items:
        url_or_path = item['path']
        fname = url_or_path.split('/')[-1].split('\\')[-1] or url_or_path
        detected_type = _source_nature(url_or_path, fname)

        desc = Description.objects.create(
            **settings_values,
            user=user,
            source_url=url_or_path,
            filename=fname,
            detected_type=detected_type,
        )
        created.append({
            'id': desc.id,
            'filename': desc.filename,
            'detected_type': desc.detected_type,
            'type_icon': desc.get_type_icon(),
            'source_url': url_or_path,
            'output_style': desc.output_style,
            'output_language': desc.output_language,
            'status': desc.status,
        })

    return JsonResponse({'descriptions': created, 'total': len(created), 'warnings': warnings})


@require_POST
def batch_create(request):
    """
    Parse batch file (URLs/paths), create BatchDescription + Description entries.
    Returns batch_id and list of description IDs.
    """
    from wama.common.utils.batch_parsers import parse_batch_file_from_request

    user = get_user(request)
    settings_values = _deposit_settings(user, request.POST)

    try:
        items, warnings = parse_batch_file_from_request(request)
    except ValueError as e:
        return JsonResponse({'error': str(e)}, status=400)

    if not items:
        return JsonResponse({'error': 'Aucun élément valide trouvé dans le fichier'}, status=400)

    # parse_batch_file_from_request a consommé FILES['batch_file'] : on le re-lit
    # pour l'archiver sur le batch (NameError avant 2026-08-03).
    batch_file = request.FILES.get('batch_file')
    if batch_file:
        batch_file.seek(0)
    batch = BatchDescription.objects.create(
        user=user,
        total=len(items),
        batch_file=batch_file,
    )

    created_ids = []
    for i, item in enumerate(items):
        url_or_path = item['path']
        fname = url_or_path.split('/')[-1].split('\\')[-1] or url_or_path
        detected_type = _source_nature(url_or_path, fname)

        desc = Description.objects.create(
            **settings_values,
            user=user,
            source_url=url_or_path,
            filename=fname,
            detected_type=detected_type,
        )
        BatchDescriptionItem.objects.create(batch=batch, description=desc, row_index=i)
        created_ids.append(desc.id)

    return JsonResponse({
        'batch_id': batch.id,
        'description_ids': created_ids,
        'total': len(items),
        'warnings': warnings,
    })


def batch_template(request):
    """Download a batch file template (.txt)."""
    template_content = """# WAMA Describer - Batch Import
# Format : une URL ou chemin de fichier par ligne
# Les lignes commençant par # sont des commentaires.

# --- Exemples URLs ---
https://example.com/image.jpg
https://example.com/video.mp4
https://example.com/document.pdf

# --- Exemples chemins locaux ---
/media/uploads/image.png
C:\\Users\\user\\Documents\\rapport.pdf

# --- Fin ---
"""
    response = HttpResponse(template_content, content_type='text/plain; charset=utf-8')
    response['Content-Disposition'] = 'attachment; filename="batch_describer_template.txt"'
    return response


def batch_list(request):
    """List the current user's batches with status counts."""
    user = get_user(request)
    batches = BatchDescription.objects.filter(user=user).prefetch_related('items__description')

    from wama.common.utils.batch_common import batch_elements
    data = []
    for batch in batches:
        counts = {'success': 0, 'running': 0, 'pending': 0, 'failure': 0}
        for d in batch_elements(batch, Description):     # lit le cache du prefetch, 0 requête
            k = d.status.lower()
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


def build_description_bytes(d, fmt):
    """Return (ext, bytes) for a description in `fmt` (txt/pdf/docx), or None.

    Shared format builder for the batch ZIP dropdown (WAMA_APP_CONVENTIONS §9.10).
    """
    fmt = (fmt or 'txt').lower()
    if fmt == 'pdf':
        try:
            from wama.common.utils.document_export import generate_description_pdf
            return ('pdf', generate_description_pdf(d))
        except Exception as e:
            logger.warning(f"[Describer] PDF skipped for {d.id}: {e}")
            return None
    if fmt == 'docx':
        try:
            from wama.common.utils.document_export import generate_description_docx
            return ('docx', generate_description_docx(d))
        except Exception as e:
            logger.warning(f"[Describer] DOCX skipped for {d.id}: {e}")
            return None
    # txt: prefer the stored result file, else the raw text
    if d.result_file and os.path.exists(d.result_file.path):
        with d.result_file.open('rb') as f:
            return ('txt', f.read())
    if d.result_text:
        return ('txt', d.result_text.encode('utf-8'))
    return None



@require_GET
def console_content(request):
    """Get console output for live display."""
    user = get_user(request)
    cache_key = f"describer_console_{user.id}"
    lines = cache.get(cache_key, [])
    return JsonResponse({'lines': lines})


@require_POST
def update_settings(request, pk):
    """Réglages d'UN élément — même lecture (coercition par le schéma) et même affectation que
    `batch_update` de la fabrique : `read_settings_payload` + `apply_item_settings`. L'ancien
    `_apply_description_options` typait à la main (`int`, `bool`) ce que le schéma déclare."""
    user = get_user(request)
    from wama.common.utils.scoping import editable_or_404
    description = editable_or_404(Description, user, pk=pk)

    if description.status == 'RUNNING':
        return JsonResponse({'error': 'Cannot update while running'}, status=400)

    data = read_settings_payload(request, _SCHEMA, SETTINGS_FIELDS)
    touched = apply_item_settings(description, data, params_fields=SETTINGS_FIELDS)
    if touched:
        description.save(update_fields=touched)

    # Les réglages tels qu'ENREGISTRÉS — la liste du schéma, pas une seconde liste à tenir.
    return JsonResponse({'id': description.id,
                         **{name: getattr(description, name) for name in SETTINGS_FIELDS}})
