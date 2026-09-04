"""
Reader — OCR document views.
"""
import io
from wama.accounts.permissions import app_access
import os
import json
import logging
import zipfile
import datetime
import tempfile

from django.shortcuts import render, get_object_or_404
from django.views import View
from django.http import JsonResponse, FileResponse, HttpResponse, HttpResponseBadRequest
from django.core.cache import cache
from django.views.decorators.http import require_POST
from django.db import transaction
from django.utils.http import content_disposition_header

import re

from .models import ReadingItem, BatchReadingItem, BatchReadingItemLink
from .tasks import read_document_task, _count_pdf_pages, _extract_natural_text
from wama.accounts.views import get_or_create_anonymous_user
from wama.common.utils.console_utils import get_console_lines
from wama.common.utils.input_match import input_labels as _input_labels
from wama.common.utils.queue_duplication import safe_delete_file, duplicate_instance

logger = logging.getLogger(__name__)


def _compact_preview(text: str, max_chars: int = 400) -> str:
    """Strip markdown syntax and collapse whitespace for card compact preview."""
    if not text:
        return ''
    t = str(text)
    t = re.sub(r'^#{1,6}\s+', '', t, flags=re.MULTILINE)
    t = re.sub(r'\*{1,3}|_{1,3}', '', t)
    t = re.sub(r'^\s*[-*+]\s+', '', t, flags=re.MULTILINE)
    t = re.sub(r'\|', ' ', t)
    t = re.sub(r'`+', '', t)
    t = re.sub(r'\s+', ' ', t).strip()
    return t[:max_chars]


ACCEPTED_EXTENSIONS = {'.pdf', '.jpg', '.jpeg', '.png', '.tiff', '.tif', '.webp', '.bmp'}


def _get_user(request):
    if request.user.is_authenticated:
        return request.user
    return get_or_create_anonymous_user()


def _item_to_dict(item: ReadingItem) -> dict:
    cached = cache.get(f'reader_progress_{item.id}')
    progress = cached.get('pct', item.progress) if cached else item.progress
    progress_msg = cached.get('msg', '') if cached else ''
    return {
        'id': item.id,
        'filename': item.filename,
        'backend': item.backend,
        'mode': item.mode,
        'output_format': item.output_format,
        'language': item.language,
        'status': item.status,
        'progress': progress,
        'progress_msg': progress_msg,
        'page_count': item.page_count,
        'result_preview': _compact_preview(item.result_text) if item.result_text else '',
        'has_result': bool(item.result_text),
        'has_raw_result': bool(item.raw_result),
        'used_backend': item.used_backend,
        'error_message': item.error_message,
        'analysis': item.analysis,
        'created_at': item.created_at.isoformat(),
        'estimated_seconds': _reader_eta_seed(item),
    }


def _reader_eta_seed(item: ReadingItem) -> float:
    """Seed ETA (s) tant que l'item n'est pas terminé ; 0 sinon. Défensif."""
    if item.status not in ('PENDING', 'RUNNING'):
        return 0.0
    try:
        from wama.model_manager.services.eta_estimator import estimate
        bk = item.used_backend or item.backend  # 'auto' avant résolution → EMA propre à 'auto'
        return estimate(f'reader:{bk}', size=max(int(item.page_count or 0), 1),
                        unit='page', model_loaded=True)
    except Exception:
        return 0.0


def _wrap_reading_in_batch(reading):
    """Wrap a standalone ReadingItem in a new BatchReadingItem-of-1 (brique commune)."""
    from wama.common.utils.batch_common import wrap_in_batch
    return wrap_in_batch(reading, batch_model=BatchReadingItem,
                         item_model=BatchReadingItemLink, fk_name='reading')


def _auto_wrap_orphans(user):
    """Wrap any ReadingItem not yet in a batch into a batch-of-1 (brique commune)."""
    from wama.common.utils.batch_common import auto_wrap_orphans
    auto_wrap_orphans(user, work_model=ReadingItem, batch_model=BatchReadingItem,
                      item_model=BatchReadingItemLink, fk_name='reading')


def consolidate_readings_into_batches(ids, user):
    """Regroupe des ReadingItem importés ENSEMBLE en UN of-N — helper PUBLIC (filemanager).
    Remplace le bloc inline historique d'api_import_to_app (généralisation 14/08) ; défait
    les batch-of-1 posés par import_to_reader avant de créer le lot."""
    from wama.common.utils.batch_common import (
        consolidate_into_batch, delete_singleton_batches, load_in_import_order,
    )
    items = load_in_import_order(ReadingItem, ids, user)
    if len(items) < 2:
        return None
    return consolidate_into_batch(
        items,
        create_batch=lambda total: BatchReadingItem.objects.create(user=user, total=total),
        link_item=lambda batch, r, idx: BatchReadingItemLink.objects.create(
            batch=batch, reading=r, row_index=idx),
        unwrap_singletons=lambda i: delete_singleton_batches(
            BatchReadingItem, 'reading', user, i))


def _chips(reading):
    """Chips de la section RÉGLAGES (card v3, CARD_DESIGN §11) : moteur EFFECTIF
    (used_backend) prioritaire sur le réglage — brique commune card_chips.

    ⚠ « X pages » n'est PLUS ici : c'est une propriété de l'ENTRÉE (mesurée sur le fichier),
    pas un réglage. La v2 les mélangeait sur une seule ligne ; la v3 sépare les sections,
    donc chaque donnée rejoint la sienne (→ _input_props)."""
    from wama.common.utils.card_chips import chips_by_section
    from wama.reader.params import PARAMS_JSON

    # Le groupement vient du SCHÉMA (section=…), pas d'un tri écrit ici : la vue ne décide pas
    # où va un chip, elle lit ce que le champ déclare (métadonnée-driven). `values=` (brique,
    # 31/08) remplace le proxy _View recopié reader/transcriber (nettoyage audit, P6) :
    # une fois le run fait, le chip moteur montre used_backend.
    return chips_by_section(reading, PARAMS_JSON,
                            values={'backend': reading.used_backend or reading.backend})


def _input_props(reading):
    """Sous-ligne « propriétés RÉELLES du média » de la section ENTRÉE (§11).

    Relevées sur le fichier déposé, jamais dérivées des réglages : type, poids, pagination.
    Équivalent reader du « mp3 · 44,1 kHz · stéréo · durée » de la maquette."""
    # ADOPTION de la brique commune (31/08) — extraite d'ICI même (pilote), le corps local
    # est retiré (dupliquer le pilote et la brique était la dérive garantie). L'axe propre
    # au reader (pages) s'INSÈRE en position 1 : l'ordre HISTORIQUE de la card est
    # ext · pages · poids — l'insertion « en tête » aurait changé l'affichage du pilote
    # (réserve levée à l'audit du 31/08 avant adoption).
    from wama.common.utils.card_chips import input_props_for
    props = input_props_for(reading, 'input_file', reading.filename or '')
    pages = getattr(reading, 'page_count', 0) or 0
    if pages:
        props.insert(1 if props else 0, f"{pages} page" + ('s' if pages > 1 else ''))
    return props


def _output_chips(reading):
    """Section SORTIE **temporelle** (§11) — prototype du futur hook commun `predicted_output()`.

    AVANT/PENDANT : chips « blueprint » (pointillés) dérivés des réglages — ce qui VA sortir.
    APRÈS         : chips solides = propriétés RÉELLES mesurées sur le résultat.
    En ÉCHEC, le template remplace la sortie par l'erreur (même piste) — rien à produire ici.

    Volontairement dans la vue reader et pas dans common/ : le §11 pose l'anatomie, mais la
    forme du hook ne sera figée qu'une fois vue en réel sur le pilote (démarche de la v2)."""
    if reading.status == 'SUCCESS' and reading.result_text:
        words = len(reading.result_text.split())
        chips = [{'label': f"{words:,} mots".replace(',', ' '),
                  'icon': 'fa-align-left', 'title': 'Mots extraits', 'variant': ''}]
        pages = getattr(reading, 'page_count', 0) or 0
        if pages:
            label = f"{pages} pages lues" if pages > 1 else "1 page lue"
            chips.append({'label': label, 'icon': 'fa-file-lines',
                          'title': 'Pages traitées', 'variant': ''})
        return chips

    # Pas encore produit → prévision, signalée comme telle (variant blueprint = pointillés).
    # Le format prévu n'est PLUS écrit ici : il vient des chips déclarés section="output" dans
    # le schéma (params.py), qu'on repasse simplement en blueprint. Ajouter un futur champ de
    # sortie au schéma suffira à le voir apparaître — aucune vue à modifier.
    blueprint = []
    for chip in (reading.chips or {}).get('output', []):
        blueprint.append(dict(chip, variant='blueprint',
                              title=(chip.get('title') or '') + ' (prévu)'))
    blueprint.append({'label': 'TXT · MD · PDF · DOCX', 'icon': 'fa-download',
                      'title': 'Formats téléchargeables après traitement',
                      'variant': 'blueprint', 'section': 'output'})
    return blueprint


def _decorate_card(reading):
    """Attache les 3 jeux de données des sections v3 à l'instance (Entrée · Réglages · Sortie).
    Point d'attache UNIQUE : appelé par IndexView ET par card_html — sinon la card rendue par
    l'endpoint diverge de celle du chargement (leçon describer)."""
    reading.chips = _chips(reading)
    reading.input_props = _input_props(reading)
    reading.output_chips = _output_chips(reading)
    return reading


def _input_match_meta():
    """Meta brique COMMUNE (clés catalogue = valeurs du select) + pseudo-choix 'auto'."""
    from wama.common.utils.input_match import auto_entry, input_match_meta
    meta = input_match_meta('reader')
    if meta:
        meta['auto'] = auto_entry(meta)
    return meta


class IndexView(View):
    def get(self, request):
        user = _get_user(request)

        # Lazily wrap any orphan readings into a batch-of-1
        _auto_wrap_orphans(user)

        # Agrégats de file — brique COMMUNE (contrat toolbar/_batch_card) + enrichissements reader.
        from wama.common.utils.batch_common import build_batches_list

        def _extra(batch, items, readings):
            from wama.common.utils.card_chips import common_chips_for_items as _ccfi
            from wama.reader.params import PARAMS_JSON as _RD_PARAMS_JSON
            success_count = sum(1 for r in readings if r.status == 'SUCCESS')
            first = readings[0] if readings else None
            for r in readings:
                _decorate_card(r)     # sections card v3 (générées, CARD_DESIGN §11)
            return {
                'success_pct': int(success_count / batch.total * 100) if batch.total > 0 else 0,
                'first_backend': first.backend if first else '',
                'first_mode': first.mode if first else '',
                'first_language': first.language if first else '',
                # ETA agrégée de la card mère (brique _batch_card.html)
                'eta_ids': ','.join(str(r.id) for r in readings),
                # Réglages COMMUNS aux filles (slot meta_template — porté le 31/08 ;
                # readings déjà décorées ci-dessus, attributs à jour).
                'common_chips': _ccfi(readings, _RD_PARAMS_JSON),
            }

        # Réconcilie les tâches RUNNING orphelines (worker mort/crash) — brique COMMUNE,
        # même câblage que transcriber : preuve positive de mort uniquement.
        try:
            from wama.common.utils.process_control import reconcile_orphaned_running
            running = list(ReadingItem.objects.filter(user=user, status='RUNNING'))
            reconcile_orphaned_running(running)
        except Exception:
            pass

        batches_list = build_batches_list(user, batch_model=BatchReadingItem,
                                          work_attr='reading', order_by='-id', extra=_extra)

        # Tri + filtrage de la file — brique COMMUNE (toolbar _queue_toolbar).
        from wama.common.utils.queue_view import apply_queue_sort_filter

        def _name(b):
            r = b['items'][0].reading if b['obj'].total == 1 and b['items'] and b['items'][0].reading else None
            return (r.filename or '').lower() if r else ''

        batches_list, q_sort, q_filter = apply_queue_sort_filter(request, batches_list, name_of=_name)

        queue_count = sum(len(b['items']) for b in batches_list)

        from wama.reader.params import PARAMS_JSON
        return render(request, 'reader/index.html', {
            'batches_list': batches_list,
            'queue_count': queue_count,
            'q_sort': q_sort,
            'q_filter': q_filter,
            'backend_choices': ReadingItem.Backend.choices,
            'mode_choices': ReadingItem.Mode.choices,
            'format_choices': ReadingItem.OutputFormat.choices,
            # Schéma params (source unique inspecteur + modale batch). Voir reader/params.py.
            'params_json': json.dumps(PARAMS_JSON),
            # Appariement entrée↔modèles (brique commune input_match) : clés catalogue =
            # valeurs du select (doctr/glm-ocr/olmocr) ; 'auto' = auto_entry (brique).
            'input_match_meta': json.dumps(_input_match_meta()),
            'input_labels': json.dumps(_input_labels()),
        })


@require_POST
def upload(request):
    """Upload one or more files to the reading queue."""
    user = _get_user(request)
    files = request.FILES.getlist('files')
    if not files:
        return JsonResponse({'error': 'Aucun fichier reçu'}, status=400)

    # Réglages persistés (brique user_settings, clés = noms de params.py) : le POST prime,
    # sinon DERNIER réglage utilisé (pattern converter). Sert surtout aux créations sans
    # formulaire (tool_api, imports serveur). ⚠ `language` : '' POSTé = auto-détection
    # VOULUE → test de présence, pas `or` (qui écraserait un champ vidé exprès).
    from wama.common.utils.user_settings import get_user_app_settings, save_user_app_settings
    last = get_user_app_settings(user, 'reader', {
        'backend': 'auto', 'mode': 'auto', 'output_format': 'txt', 'language': ''})
    backend       = request.POST.get('backend') or last['backend']
    mode          = request.POST.get('mode') or last['mode']
    output_format = request.POST.get('output_format') or last['output_format']
    language      = request.POST['language'] if 'language' in request.POST else last['language']

    items_created = []
    created = []
    for f in files:
        ext = os.path.splitext(f.name)[1].lower()
        if ext not in ACCEPTED_EXTENSIONS:
            continue  # skip unsupported types silently

        item = ReadingItem.objects.create(
            user=user,
            input_file=f,
            original_filename=f.name,
            backend=backend,
            mode=mode,
            output_format=output_format,
            language=language,
            status='PENDING',
        )

        # Count PDF pages immediately (quick, synchronous)
        if ext == '.pdf':
            try:
                n = _count_pdf_pages(item.input_file.path)
                if n:
                    item.page_count = n
                    item.save(update_fields=['page_count'])
            except Exception:
                pass

        items_created.append(item)
        created.append(_item_to_dict(item))

    if not items_created:
        return JsonResponse({'created': []})

    # Re-persiste les choix comme défauts du prochain dépôt.
    save_user_app_settings(user, 'reader', {
        'backend': backend, 'mode': mode,
        'output_format': output_format, 'language': language})

    if len(items_created) > 1:
        # Multiple files → one multi-item batch
        batch = BatchReadingItem.objects.create(user=user, total=len(items_created))
        for i, item in enumerate(items_created):
            BatchReadingItemLink.objects.create(batch=batch, reading=item, row_index=i)
        return JsonResponse({'created': created, 'batch_id': batch.id, 'multi': True})
    else:
        _wrap_reading_in_batch(items_created[0])
        return JsonResponse({'created': created})


@require_POST
@app_access('reader')
def stop(request, pk: int):
    """
    Stoppe l'OCR en cours (révoque la tâche Celery) → item relançable (bouton de cycle ↻).
    Brique commune : wama.common.utils.process_control.stop_instance.
    """
    user = _get_user(request)
    item = get_object_or_404(ReadingItem, pk=pk, user=user)
    if item.status not in ('RUNNING', 'PENDING'):
        return JsonResponse({'id': item.id, 'status': item.status})
    from wama.common.utils.process_control import stop_instance
    new_status = stop_instance(item, to_status='FAILURE')   # FAILURE = état terminal relançable côté Reader
    return JsonResponse({'id': item.id, 'status': new_status})


def _reset_for_relaunch(item):
    """Remise à zéro avant (re)lancement — appliquée SOUS le verrou anti-race."""
    item.result_text = ''
    item.raw_result = ''
    item.error_message = ''
    item.progress = 0


@app_access('reader')
def start(request, pk: int):
    """Start OCR processing for a single item — anti-race via la brique commune."""
    user = _get_user(request)
    from wama.common.utils.process_control import begin_processing
    item, err = begin_processing(ReadingItem, pk, user=user, reset=_reset_for_relaunch)
    if err == 'not_found':
        return JsonResponse({'error': 'Not found'}, status=404)
    if err == 'already_running':
        return JsonResponse({'error': 'Déjà en cours'}, status=409)

    task = read_document_task.delay(item.id)
    item.task_id = task.id
    item.save(update_fields=['task_id'])
    return JsonResponse({'ok': True, 'task_id': task.id})


def card_html(request, pk: int):
    """Card RENDUE serveur — source UNIQUE du markup v3 (partial _item_card.html ;
    CARD_DESIGN §3, update JS en place). Le flag in_batch est déduit du batch parent."""
    from wama.common.utils.scoping import visible_or_404  # lecture → partage F7
    item = visible_or_404(ReadingItem, _get_user(request), pk=pk)
    _decorate_card(item)
    link = BatchReadingItemLink.objects.filter(reading=item).select_related('batch').first()
    in_batch = bool(link and link.batch.total > 1)
    return render(request, 'reader/_item_card.html', {'elem': item, 'in_batch': in_batch})


def progress(request, pk: int):
    """Poll the current processing status of an item."""
    from wama.common.utils.scoping import visible_or_404  # lecture → partage F7
    item = visible_or_404(ReadingItem, _get_user(request), pk=pk)
    return JsonResponse(_item_to_dict(item))


def text_view(request, pk: int):
    """Return the full extracted text as JSON (used by the in-page full-text modal)."""
    from wama.common.utils.scoping import visible_or_404  # lecture → partage F7
    item = visible_or_404(ReadingItem, _get_user(request), pk=pk)
    return JsonResponse({'text': _extract_natural_text(item.result_text) or '', 'filename': item.filename})


def download(request, pk: int):
    """Download the OCR result. Supported formats: txt (default), md, pdf, docx, json."""
    from wama.common.utils.scoping import visible_or_404  # lecture → partage F7
    item = visible_or_404(ReadingItem, _get_user(request), pk=pk)

    fmt = request.GET.get('format', 'txt').lower()
    base = os.path.splitext(item.filename)[0]

    # JSON format — serve raw backend output
    if fmt == 'json':
        if not item.raw_result:
            return HttpResponseBadRequest('Pas de données JSON disponibles')
        buffer = io.BytesIO(item.raw_result.encode('utf-8'))
        buffer.seek(0)
        return FileResponse(
            buffer,
            as_attachment=True,
            filename=f"{base}_ocr_raw.json",
            content_type='application/json; charset=utf-8',
        )

    if not item.result_text:
        return HttpResponseBadRequest('Pas encore de résultat')

    if fmt == 'pdf':
        try:
            from wama.common.utils.document_export import generate_reader_pdf
            pdf_bytes = generate_reader_pdf(item)
            response = HttpResponse(pdf_bytes, content_type='application/pdf')
            response['Content-Disposition'] = content_disposition_header(True, f"{base}_ocr.pdf")
            return response
        except ImportError as e:
            return HttpResponseBadRequest(str(e))
        except Exception as e:
            logger.error(f"[Reader] PDF generation failed: {e}")
            return HttpResponseBadRequest(f'Erreur PDF : {e}')

    if fmt == 'docx':
        try:
            from wama.common.utils.document_export import generate_reader_docx
            docx_bytes = generate_reader_docx(item)
            response = HttpResponse(
                docx_bytes,
                content_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            )
            response['Content-Disposition'] = content_disposition_header(True, f"{base}_ocr.docx")
            return response
        except ImportError as e:
            return HttpResponseBadRequest(str(e))
        except Exception as e:
            logger.error(f"[Reader] DOCX generation failed: {e}")
            return HttpResponseBadRequest(f'Erreur DOCX : {e}')

    # txt / md (default)
    is_md = (fmt == 'md')
    ext = '.md' if is_md else '.txt'
    content_type = 'text/markdown' if is_md else 'text/plain'
    buffer = io.BytesIO(_extract_natural_text(item.result_text).encode('utf-8'))
    buffer.seek(0)
    return FileResponse(
        buffer,
        as_attachment=True,
        filename=f"{base}_ocr{ext}",
        content_type=f'{content_type}; charset=utf-8',
    )


@require_POST
def delete(request, pk: int):
    """Delete an item and its input file (if not shared). Also removes parent batch-of-1."""
    item = get_object_or_404(ReadingItem, pk=pk, user=_get_user(request))
    # Capture parent batch before deletion
    parent_batch = None
    try:
        link = item.batch_item
        parent_batch = link.batch
    except Exception:
        pass
    safe_delete_file(item, 'input_file')
    cache.delete(f'reader_progress_{pk}')
    item.delete()  # signal batch_sync : recale total / supprime le batch vidé (+ son fichier batch)
    return JsonResponse({'deleted': pk, 'batch_changed': parent_batch is not None})


@require_POST
def duplicate(request, pk: int):
    """Duplicate an item, sharing the input file but resetting all results."""
    item = get_object_or_404(ReadingItem, pk=pk, user=_get_user(request))
    new_item = duplicate_instance(
        item,
        reset_fields={
            'status': 'PENDING',
            'progress': 0,
            'task_id': '',
            'result_text': '',
            'used_backend': '',
            'error_message': '',
        },
    )
    # 'duplicated' = contrat de la brique commune queue-actions.js (focus + reload)
    return JsonResponse({**_item_to_dict(new_item), 'duplicated': new_item.id})


@require_POST
@app_access('reader')
def start_all(request):
    """Start all PENDING items for the current user."""
    user = _get_user(request)
    from wama.common.utils.process_control import begin_processing
    items = ReadingItem.objects.filter(user=user, status='PENDING').order_by('-created_at')
    count = 0
    for item in items:
        item, err = begin_processing(ReadingItem, item.pk, user=user, reset=_reset_for_relaunch)
        if err:
            continue
        task = read_document_task.delay(item.id)
        item.task_id = task.id
        item.save(update_fields=['task_id'])
        count += 1
    return JsonResponse({'started': count})



def download_all(request):
    """ZIP de tous les résultats, au format demandé (`?format=` txt/md/pdf/docx/json).

    Lit ENFIN la query que le menu ▾ du ⬇ commun envoie (`export_formats` déclarés) : jusqu'au
    2026-08-30 seule la vue d'ITEM la lisait — porter le menu sans cette vue aurait produit
    un « vert d'ADOPTION, faux en FONCTIONNEMENT » (WAMA_VERIFICATION §Geste 14). Idiome du
    transcriber : un item qui échoue dans un format retombe en txt, jamais un ZIP en erreur.
    Sans `?format=`, comportement historique inchangé (extension selon `output_format`).
    """
    from io import BytesIO
    user = _get_user(request)
    items = ReadingItem.objects.filter(user=user, status='SUCCESS')
    if not items.exists():
        return JsonResponse({'error': 'Aucun résultat disponible'}, status=400)

    fmt = (request.GET.get('format') or '').lower()
    buf = BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
        for item in items:
            base = os.path.splitext(item.original_filename)[0] if '.' in (item.original_filename or '') else (item.original_filename or f'item_{item.id}')
            entry = None
            try:
                if fmt == 'json' and item.raw_result:
                    entry = (f'{base}_ocr_raw.json', item.raw_result.encode('utf-8'))
                elif fmt == 'pdf' and item.result_text:
                    from wama.common.utils.document_export import generate_reader_pdf
                    entry = (f'{base}_ocr.pdf', generate_reader_pdf(item))
                elif fmt == 'docx' and item.result_text:
                    from wama.common.utils.document_export import generate_reader_docx
                    entry = (f'{base}_ocr.docx', generate_reader_docx(item))
                elif fmt in ('txt', 'md') and item.result_text:
                    entry = (f"{base}_ocr.{fmt}",
                             _extract_natural_text(item.result_text).encode('utf-8'))
            except Exception as e:
                logger.warning(f"[Reader] download_all: {fmt} failed for #{item.pk} ({e}); falling back to txt")
                entry = None
            if entry is None and item.result_text:
                ext = '.md' if item.output_format == 'markdown' else '.txt'
                entry = (f'{base}_ocr{ext}', item.result_text.encode('utf-8'))
            if entry:
                zf.writestr(*entry)
    buf.seek(0)
    suffix = f'_{fmt}' if fmt else ''
    response = HttpResponse(buf.read(), content_type='application/zip')
    response['Content-Disposition'] = content_disposition_header(True, f'reader_results{suffix}.zip')
    return response


@require_POST
def clear_all(request):
    """Delete all items and batches for the current user."""
    user = _get_user(request)
    items = ReadingItem.objects.filter(user=user)
    for item in items:
        safe_delete_file(item, 'input_file')
        cache.delete(f'reader_progress_{item.id}')
    items.delete()
    # Clean up orphan batch containers and their files
    batches = BatchReadingItem.objects.filter(user=user)
    for batch in batches:
        safe_delete_file(batch, 'batch_file')
    batches.delete()
    return JsonResponse({'ok': True})


@require_POST
def save_settings(request, pk: int):
    """Update per-item OCR settings (backend, mode, output_format, language)."""
    item = get_object_or_404(ReadingItem, pk=pk, user=_get_user(request))
    try:
        data = json.loads(request.body.decode('utf-8'))
    except (json.JSONDecodeError, UnicodeDecodeError):
        data = {}

    allowed_backends = [c[0] for c in ReadingItem.Backend.choices]
    allowed_modes    = [c[0] for c in ReadingItem.Mode.choices]
    allowed_formats  = [c[0] for c in ReadingItem.OutputFormat.choices]

    if 'backend' in data and data['backend'] in allowed_backends:
        item.backend = data['backend']
    if 'mode' in data and data['mode'] in allowed_modes:
        item.mode = data['mode']
    if 'output_format' in data and data['output_format'] in allowed_formats:
        item.output_format = data['output_format']
    if 'language' in data:
        item.language = data['language'].strip()[:16]

    item.save(update_fields=['backend', 'mode', 'output_format', 'language'])
    return JsonResponse(_item_to_dict(item))


@require_POST
def analyze(request, pk: int):
    """Lance une analyse LLM (résumé + points clés) sur le texte OCR extrait."""
    item = get_object_or_404(ReadingItem, pk=pk, user=_get_user(request))

    if not item.result_text:
        return JsonResponse({'error': 'Pas encore de texte extrait'}, status=400)

    from .tasks import analyze_document_task
    task = analyze_document_task.delay(item.id)
    return JsonResponse({'ok': True, 'task_id': task.id})


def batch_template(request):
    """Download a batch file template (.txt)."""
    template_content = (
        "# WAMA Reader - Batch Import\n"
        "# Format : une URL ou chemin de fichier par ligne\n"
        "# Les lignes commençant par # sont des commentaires.\n"
        "# Formats supportés : PDF, JPG, PNG, TIFF, WebP\n"
        "\n"
        "https://example.com/document.pdf\n"
        "/media/uploads/scan.jpg\n"
    )
    response = HttpResponse(template_content, content_type='text/plain; charset=utf-8')
    response['Content-Disposition'] = 'attachment; filename="batch_reader_template.txt"'
    return response


@require_POST
def batch_preview(request):
    """Parse a batch file (one URL/path per line) and return the list for preview."""
    from wama.common.utils.batch_parsers import batch_media_list_preview_response
    return batch_media_list_preview_response(request)


@require_POST
def batch_create(request):
    """
    Parse batch file (URLs/paths), create BatchReadingItem + ReadingItem entries.
    Files are not downloaded yet — download happens when each task starts.
    """
    from wama.common.utils.batch_parsers import parse_batch_file_from_request

    user = _get_user(request)
    backend = request.POST.get('backend', 'auto')
    mode = request.POST.get('mode', 'auto')
    output_format = request.POST.get('output_format', 'txt')
    language = request.POST.get('language', '')

    try:
        items, warnings = parse_batch_file_from_request(request)
    except ValueError as e:
        return JsonResponse({'error': str(e)}, status=400)

    if not items:
        return JsonResponse({'error': 'Aucun élément valide trouvé dans le fichier'}, status=400)

    batch_file = request.FILES.get('batch_file')
    batch = BatchReadingItem.objects.create(
        user=user,
        total=len(items),
        batch_file=batch_file,
    )

    created_ids = []
    for i, item in enumerate(items):
        url_or_path = item['path']
        fname = url_or_path.split('/')[-1].split('\\')[-1] or url_or_path

        reading = ReadingItem.objects.create(
            user=user,
            source_url=url_or_path,
            original_filename=fname,
            backend=backend,
            mode=mode,
            output_format=output_format,
            language=language,
            status='PENDING',
        )
        BatchReadingItemLink.objects.create(batch=batch, reading=reading, row_index=i)
        created_ids.append(reading.id)

    return JsonResponse({
        'batch_id': batch.id,
        'reading_ids': created_ids,
        'total': len(items),
        'warnings': warnings,
    })


def batch_list(request):
    """List the current user's batches with status counts."""
    user = _get_user(request)
    batches = BatchReadingItem.objects.filter(user=user).prefetch_related('items__reading')

    data = []
    for batch in batches:
        counts = {'success': 0, 'running': 0, 'pending': 0, 'failure': 0}
        for item in batch.items.all():
            if item.reading:
                k = item.reading.status.lower()
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


@require_POST
@app_access('reader')
def batch_start(request, pk):
    """Start all PENDING readings in a batch."""
    user = _get_user(request)
    batch = get_object_or_404(BatchReadingItem, pk=pk, user=user)

    from wama.common.utils.process_control import begin_processing
    started = []
    for item in batch.items.select_related('reading').all():
        r = item.reading
        if not r:
            continue
        r, err = begin_processing(ReadingItem, r.pk, user=user, reset=_reset_for_relaunch)
        if err:
            continue
        task = read_document_task.delay(r.id)
        r.task_id = task.id
        r.save(update_fields=['task_id'])
        started.append(r.id)

    return JsonResponse({'started': started, 'count': len(started)})


# Manipulation directe de la file (CARD_DESIGN §3bis) — vues GÉNÉRÉES par la brique commune.
from wama.common.utils.queue_manipulation import make_queue_manipulation_views

_qm = make_queue_manipulation_views(
    work_model=ReadingItem, batch_model=BatchReadingItem,
    item_model=BatchReadingItemLink, fk_name='reading', get_user=_get_user,
)
remove_from_batch = _qm['remove_from_batch']
reorder = _qm['reorder']
reorder_queue = _qm['reorder_queue']
merge = _qm['merge']
move_to_batch = _qm['move_to_batch']
consolidate = _qm['consolidate']


def batch_status(request, pk):
    """Return status of all items in a batch."""
    user = _get_user(request)
    batch = get_object_or_404(BatchReadingItem, pk=pk, user=user)

    counts = {'success': 0, 'running': 0, 'pending': 0, 'failure': 0}
    items_data = []

    for item in batch.items.select_related('reading').all():
        r = item.reading
        if not r:
            continue
        key = r.status.lower()
        counts[key] = counts.get(key, 0) + 1
        cached = cache.get(f'reader_progress_{r.id}')
        p = cached.get('pct', r.progress) if cached else r.progress
        items_data.append({
            'id': r.id,
            'filename': r.filename,
            'status': r.status,
            'progress': p,
            'error': r.error_message if r.status == 'FAILURE' else None,
        })

    total = batch.total
    if total > 0 and counts['success'] == total:
        status_str = 'SUCCESS'
    elif counts['running'] > 0:
        status_str = 'RUNNING'
    elif counts['pending'] == 0 and counts['running'] == 0 and counts['failure'] > 0:
        status_str = 'FAILURE'
    else:
        status_str = 'PENDING'

    return JsonResponse({
        'batch_id': pk,
        'status': status_str,
        'total': total,
        'counts': counts,
        'items': items_data,
    })


def _build_reading_bytes(item, fmt):
    """Return (ext, bytes) for an OCR result in `fmt` (txt/md/pdf/docx/json), or None.

    Shared format builder for the batch ZIP dropdown (WAMA_APP_CONVENTIONS §9.10).
    """
    fmt = (fmt or 'txt').lower()
    if fmt == 'json':
        if not item.raw_result:
            return None
        return ('json', item.raw_result.encode('utf-8'))
    if not item.result_text:
        return None
    if fmt == 'pdf':
        try:
            from wama.common.utils.document_export import generate_reader_pdf
            return ('pdf', generate_reader_pdf(item))
        except Exception as e:
            logger.warning(f"[Reader] PDF skipped for {item.id}: {e}")
            return None
    if fmt == 'docx':
        try:
            from wama.common.utils.document_export import generate_reader_docx
            return ('docx', generate_reader_docx(item))
        except Exception as e:
            logger.warning(f"[Reader] DOCX skipped for {item.id}: {e}")
            return None
    ext = 'md' if fmt == 'md' else 'txt'
    return (ext, _extract_natural_text(item.result_text).encode('utf-8'))


def batch_download(request, pk):
    """Download a ZIP of all completed OCR results in a batch.

    Format chosen via ?fmt=txt|md|pdf|docx|json (default txt) — dropdown variant
    of the multi-format batch ZIP convention (WAMA_APP_CONVENTIONS §9.10).
    """
    user = _get_user(request)
    batch = get_object_or_404(BatchReadingItem, pk=pk, user=user)
    fmt = (request.GET.get('fmt') or 'txt').lower()
    if fmt not in ('txt', 'md', 'pdf', 'docx', 'json'):
        fmt = 'txt'

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
        for item in batch.items.select_related('reading').order_by('row_index'):
            r = item.reading
            if r and r.status == 'SUCCESS':
                stem = os.path.splitext(r.filename)[0] if r.filename else f'item_{r.id}'
                built = _build_reading_bytes(r, fmt)
                if built:
                    ext, data = built
                    archive.writestr(f'{stem}_ocr.{ext}', data)

    buffer.seek(0)
    zip_name = f"batch_reader_{pk}_{fmt}_{datetime.date.today()}.zip"
    return FileResponse(buffer, as_attachment=True, filename=zip_name)


@require_POST
def batch_delete(request, pk):
    """Delete an entire batch: cascade-delete readings, clean up files."""
    user = _get_user(request)
    batch = get_object_or_404(BatchReadingItem, pk=pk, user=user)

    readings_to_delete = []
    for item in batch.items.select_related('reading').all():
        r = item.reading
        if not r:
            continue
        if r.task_id:
            try:
                from celery.result import AsyncResult
                AsyncResult(r.task_id).revoke(terminate=False)
            except Exception:
                pass
        readings_to_delete.append(r)

    safe_delete_file(batch, 'batch_file')
    batch.delete()  # CASCADE deletes BatchReadingItemLinks (not ReadingItem)

    for r in readings_to_delete:
        safe_delete_file(r, 'input_file')
        cache.delete(f'reader_progress_{r.id}')
        r.delete()

    return JsonResponse({'success': True, 'batch_id': pk})


@require_POST
def batch_duplicate(request, pk):
    """Duplicate an entire batch (shares source files/URLs, results cleared)."""
    user = _get_user(request)
    batch = get_object_or_404(BatchReadingItem, pk=pk, user=user)

    new_batch = BatchReadingItem.objects.create(user=user, total=batch.total)
    for item in batch.items.select_related('reading').order_by('row_index'):
        r = item.reading
        if not r:
            continue
        new_r = duplicate_instance(r, reset_fields={
            'status': 'PENDING', 'progress': 0, 'task_id': '',
            'result_text': '', 'used_backend': '', 'error_message': '',
        })
        BatchReadingItemLink.objects.create(batch=new_batch, reading=new_r, row_index=item.row_index)

    return JsonResponse({'success': True, 'batch_id': new_batch.id})


@require_POST
def batch_update(request, pk):
    """Update backend/mode/language on all non-RUNNING items in a batch."""
    user = _get_user(request)
    batch = get_object_or_404(BatchReadingItem, pk=pk, user=user)
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)

    backend = data.get('backend', '')
    mode = data.get('mode', '')
    language = data.get('language', '')

    updated = 0
    for item in batch.items.select_related('reading').all():
        r = item.reading
        if not r or r.status == 'RUNNING':
            continue
        r.backend = backend
        r.mode = mode
        r.language = language
        r.save(update_fields=['backend', 'mode', 'language'])
        updated += 1

    return JsonResponse({'success': True, 'updated': updated})


def console_content(request):
    user = _get_user(request)
    lines = get_console_lines(user.id)
    return JsonResponse({'lines': lines})


def global_progress(request):
    """Overall reading progress for all items of the current user."""
    user = _get_user(request)
    items = ReadingItem.objects.filter(user=user)
    total = items.count()
    if total == 0:
        return JsonResponse({'total': 0, 'done': 0, 'running': 0, 'pending': 0,
                             'error': 0, 'overall_progress': 0})
    done    = items.filter(status='SUCCESS').count()
    running = items.filter(status='RUNNING').count()
    pending = items.filter(status='PENDING').count()
    error   = items.filter(status='FAILURE').count()
    if done == total:
        overall_progress = 100
    else:
        total_progress = sum(i.progress for i in items)
        overall_progress = int(total_progress / total)
    return JsonResponse({
        'total': total,
        'done': done,
        'running': running,
        'pending': pending,
        'error': error,
        'overall_progress': overall_progress,
    })
