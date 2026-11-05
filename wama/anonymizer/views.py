import os
import re
import cv2
import yt_dlp
import mimetypes
import requests
from PIL import Image
from urllib.parse import urlparse
from celery.result import AsyncResult

from django.http import Http404, HttpResponseForbidden, HttpResponseNotAllowed, JsonResponse
from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.db import close_old_connections, transaction
from django.core.cache import cache
from django.contrib.auth.models import User
from django.template import loader
from django.template.loader import render_to_string
from django.views import View
from django.views.generic import TemplateView

from .models import Media, BatchAnonymizer, BatchAnonymizerItem
from .tasks import process_single_media, stop_process
from .utils.media_utils import get_unique_filename
from .utils.yolo_utils import get_model_path
from .utils.sam3_manager import (
    get_sam3_status, validate_sam3_prompt,
    get_sam3_requirements, get_recommended_prompt_examples
)

from ..accounts.views import get_or_create_anonymous_user
from ..common.utils.console_utils import get_console_lines
from ..common.utils.video_utils import get_media_info
from ..common.utils.media_paths import get_app_media_path, ensure_app_media_dirs
# Le chemin d'un fichier d'app se COMPOSE (`get_relative_media_path`), il ne
# s'écrit pas — préalable au domicile unique par utilisateur (2026-09-11).
from wama.common.utils.media_paths import get_relative_media_path


class IndexView(View):
    """Page principale de Anonymizer."""

    def get(self, request):
        user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()

        # Réconcilie les éléments RUNNING orphelins (worker mort/crash) — LA brique commune.
        from wama.common.utils.process_control import reconcile_queue_of
        reconcile_queue_of(Media, user)

        context = get_context(request)
        context.update(_queue_context(request, user))
        return render(request, 'anonymizer/index.html', context)

    def post(self, request):
        user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()

        try:
            # Un fichier TÉLÉVERSÉ, ou DÉSIGNÉ (médiathèque, arbre) — brique `received_inputs` :
            # une désignation se POINTE au lieu d'être recopiée, avec le même état du volet.
            from wama.common.utils.media_paths import received_inputs
            received = received_inputs(request, user, 'anonymizer')
            media_file = received[0] if received else None
            if received.refusal and not media_file and not request.POST.get('media_url'):
                raise ValueError(received.refusal)

            # Case 1: text file containing paths or URLs
            if media_file and media_file.name.endswith(('.txt', '.csv', '.log')):
                lines = b''.join(media_file.chunks()).decode('utf-8').splitlines()
                added, failed = [], []

                for line in lines:
                    path = windows_path_to_wsl(line)
                    if not path:
                        continue
                    try:
                        # Get user-specific input directory
                        user_input_dir = get_app_media_path('anonymizer', user.id, 'input')
                        user_input_dir.mkdir(parents=True, exist_ok=True)

                        if is_url(path):
                            # La SOURCE est enregistrée, le récepteur commun la télécharge dès
                            # la création hors requête (`source_ingest`, 2026-10-13) — même
                            # geste que `batch_create`.
                            added.append(_media_from_url(path, user, request.POST))
                            continue
                        else:
                            # Confinement (05/09) : ce site lisait N'IMPORTE QUEL chemin serveur
                            # cité dans un .txt — le seul du parc sans garde, alors que le
                            # gabarit généré et le converter confinent à MEDIA_ROOT. Même règle
                            # partout : un chemin de lot se résout SOUS MEDIA_ROOT, ou est
                            # refusé (`MEDIA_STORAGE_TIERING §8.6` D3).
                            from wama.common.utils.media_paths import reference_or_copy, resolve_under_media_root
                            from wama.common.utils.provenance import kind_of
                            abs_src, src_rel = resolve_under_media_root(path)   # OutsideMediaRoot / FileNotFoundError → failed[]
                            # Déjà dans l'arbre de l'utilisateur → POINTÉ (2026-09-23).
                            dest, _rel = reference_or_copy(abs_src, 'anonymizer', user.id, 'input')
                            video_path = str(dest)
                            origin = {'kind': kind_of(src_rel), 'ref': src_rel, 'source_path': abs_src}
                        # Crée Media en DB
                        media = process_media(
                            video_path, user,
                            post=request.POST,
                        )
                        added.append(media)
                        # Provenance : la copie se souvient de sa ligne de lot (brique commune).
                        from wama.common.utils.provenance import record_origin, ref_for
                        record_origin(ref_for(video_path), **origin)
                    except Exception as e:
                        failed.append((path, str(e)))

                return JsonResponse({'success': True, 'added': added, 'errors': failed})

            # Case 2: direct upload (file or URL)
            media_url = (request.POST.get('media_url') or '').strip()
            if not media_file and media_url:
                return JsonResponse({'success': True,
                                     'media': _media_from_url(media_url, user, request.POST)})
            video_path = upload_from_url(request, user, media_file)
            media_result = process_media(
                video_path, user,
                post=request.POST,
            )
            if isinstance(media_result, dict) and media_result.get('is_valid'):
                if media_file:
                    media_file.record(Media.objects.get(pk=media_result['id']), 'file')
                return JsonResponse({'success': True, 'media': media_result})
            else:
                # La copie TÉLÉVERSÉE n'a pas de card : elle ne reste pas sur le disque (2026-11-03,
                # deux copies orphelines d'un import refusé). Un fichier DÉSIGNÉ n'est jamais
                # effacé — il peut être le fichier de l'utilisateur, simplement pointé.
                if media_file and not media_file.designated:
                    if os.path.isfile(video_path):
                        os.remove(video_path)
                return JsonResponse({'success': False, 'error': media_result}, status=400)

        except ValueError as e:
            return JsonResponse({'is_valid': False, 'error': str(e)}, status=400)
        except Exception as e:
            return JsonResponse({'is_valid': False, 'error': f"Server error: {e}"}, status=500)


def windows_path_to_wsl(path):
    r"""
    Convertit un chemin Windows D:\... en chemin WSL /mnt/d/...
    Ignore les URLs (http:// ou https://).
    """
    path = path.strip().replace('\\', '/')
    if path.lower().startswith(('http://', 'https://')):
        return path
    import re
    match = re.match(r'^([a-zA-Z]):/(.*)', path)
    if match:
        drive = match.group(1).lower()
        rest = match.group(2)
        return f"/mnt/{drive}/{rest}"
    return path


def is_url(path):
    """Check if the string is a valid URL."""
    try:
        result = urlparse(path)
        return all([result.scheme, result.netloc])
    except Exception:
        return False


def process_media(video_path, user, post=None, app='anonymizer'):
    """Create a Media object from the given path and assign metadata.
    `app` re-cible une JUMELLE de bac à sable (son modèle, son dossier, ses réglages retenus) —
    le contrat d'`importer_for`, que l'outil `add_to_<jumelle>` emprunte (2026-10-29)."""
    from django.apps import apps as django_apps
    model = django_apps.get_model(app, 'Media')
    try:
        filename = os.path.basename(video_path)
        ext = os.path.splitext(filename)[1]
        # ⚠ Le chemin enregistré est celui du fichier RÉEL, jamais un chemin recomposé
        # (2026-09-23) : depuis que la brique commune PEUT pointer un fichier déjà rangé dans
        # l'arbre de l'utilisateur, « anonymizer/<uid>/input/<nom> » serait un chemin où le
        # fichier n'est pas — la 3ᵉ route du disque, celle du NOM enregistré.
        from wama.common.utils.media_paths import OutsideMediaRoot, resolve_under_media_root
        try:
            _abs, relative_path = resolve_under_media_root(str(video_path))
        except (OutsideMediaRoot, FileNotFoundError):
            relative_path = get_relative_media_path(app, user.id, 'input', filename)
        # Le média NAÎT avec les réglages de son auteur ; ce que le dépôt poste prime ; le fichier
        # PROPOSE les siens (`inputs_by_port`, `Param.default_from`, 2026-10-29). Sa NATURE dit son
        # domaine, donc son schéma (2026-11-02 : un document naît avec celui du domaine document).
        from wama.common.app_registry import category_of_path
        from wama.common.utils.user_settings import inputs_by_port
        nature = category_of_path(video_path)
        media = model.objects.create(file=relative_path, file_ext=ext, user=user, media_type=nature,
                                     **new_media_settings(user, model=model, app=app, post=post,
                                                          inputs=inputs_by_port(app, str(video_path)),
                                                          nature=nature))

        mime_type, _ = mimetypes.guess_type(video_path)
        if mime_type and mime_type.startswith("video/"):
            vid = cv2.VideoCapture(str(video_path))
            add_media_to_db(media, vid)
        else:
            add_media_to_db(media, video_path)

        return {
            'is_valid': True,
            'id': media.id,
            'name': filename,
            'url': media.file.url,
            'file_ext': media.file_ext,
            'username': user.username,
            'fps': media.fps,
            'width': media.width,
            'height': media.height,
            'duration': media.duration_inMinSec,
        }
    except Exception as e:
        return str(e)


def _media_from_url(url, user, post=None):
    """Un Media créé depuis une URL : la source est enregistrée, le fichier arrive par le
    récepteur commun dès la création, hors requête (`source_ingest`), avec ses métadonnées
    (`derive` déclaré dans `WAMA_INGEST`). Même forme que les lignes de `batch_create`."""
    filename = url.split('?')[0].rstrip('/').split('/')[-1] or url
    media = Media.objects.create(user=user, title=filename, source_url=url, file='',
                                 file_ext='', **new_media_settings(user, post=post))
    return {'is_valid': True, 'id': media.id, 'name': filename, 'source_url': url,
            'username': user.username}


def upload_from_url(request, user, media_file=None):
    """Handle media from a received file (`media_paths.ReceivedInput` : téléversé ou désigné).
    Une URL ne passe plus par ici : elle devient une SOURCE (`_media_from_url`)."""
    # Use user-specific input directory
    output_path = get_app_media_path('anonymizer', user.id, 'input')
    output_path.mkdir(parents=True, exist_ok=True)
    output_path = str(output_path)

    if media_file and media_file.designated:
        # Déjà pointé (ou copié) par la brique : même filtre de types qu'un téléversement.
        _check_media_type(media_file.name)
        return media_file.local_path
    if media_file:
        return handle_uploaded_media_file(media_file.value, output_path)

    raise ValueError("No media file or URL provided.")


def _check_media_type(name):
    """La porte de l'anonymizer — pour un fichier téléversé comme désigné : la porte COMMUNE de sa
    surface (`app_modes.surface_file_nature` : les extensions déclarées, puis un domaine qui prend
    sa nature), celle que lisent « Envoyer vers », les importeurs et l'outil de l'assistant. Une
    liste de types MIME écrite ici la remplaçait (2026-11-02) : elle refusait un document, et des
    formats d'image et de vidéo que la zone de dépôt proposait (`.webp`, `.webm`, `.tif`…).
    Rend la nature du fichier."""
    from wama.common.utils.app_modes import surface_file_nature
    nature = surface_file_nature('anonymizer', 'anonymizer', name)
    if not nature:
        raise ValueError(f"Unsupported file type: {os.path.splitext(str(name))[1] or name}")
    return nature


def handle_uploaded_media_file(media_file, output_path):
    """Save uploaded media file to disk with a unique name."""
    _check_media_type(media_file.name)

    filename = get_unique_filename(output_path, media_file.name)
    save_path = os.path.join(output_path, filename)

    with open(save_path, 'wb+') as dest:
        for chunk in media_file.chunks():
            dest.write(chunk)

    return save_path


def add_media_to_db(media, vid_or_path):
    """Populate the Media model with metadata from a video or image using common utility.
    Un DOCUMENT (2026-11-02) n'a ni dimensions, ni cadence, ni durée : seule sa nature se pose."""
    from wama.common.app_registry import category_of_path
    if isinstance(vid_or_path, str) and category_of_path(vid_or_path) == 'document':
        media.media_type = 'document'
        media.save()
        return
    if isinstance(vid_or_path, str):
        # It's a file path - use the common utility
        info = get_media_info(vid_or_path)
        media.width = info['width']
        media.height = info['height']
        media.fps = info['fps']
        media.duration_inSec = info['duration']
        media.duration_inMinSec = f"{int(info['duration'] // 60)}:{int(info['duration'] % 60):02d}"
        media.properties = info['properties']
        media.media_type = info['media_type']
        media.save()
    else:
        # It's already a VideoCapture object - process directly
        vid = vid_or_path
        if not vid.isOpened():
            raise ValueError("Could not open video file")

        fps = vid.get(cv2.CAP_PROP_FPS)
        if not fps or fps <= 0:
            fps = 25  # Default fallback

        media.fps = fps
        media.width = int(vid.get(cv2.CAP_PROP_FRAME_WIDTH))
        media.height = int(vid.get(cv2.CAP_PROP_FRAME_HEIGHT))
        total_frames = vid.get(cv2.CAP_PROP_FRAME_COUNT)
        media.duration_inSec = total_frames / fps if fps > 0 else 0
        media.duration_inMinSec = f"{int(media.duration_inSec // 60)}:{int(media.duration_inSec % 60):02d}"
        media.properties = f"{media.width}x{media.height} ({media.fps:.2f}fps)"
        media.media_type = "video"
        media.save()


def console_content(request):
    """Retourne un flux textuel des logs en cours pour affichage console (via Redis/Cache + logs Celery)."""
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
    all_lines = get_console_lines(user.id, limit=200)
    return JsonResponse({'output': all_lines})


def debug_media_status(request):
    """Debug view to check media status."""
    import logging
    logger = logging.getLogger('anonymizer.debug')

    # Session info
    session_info = {
        'session_key': request.session.session_key,
        'session_data': dict(request.session.items()) if hasattr(request.session, 'items') else {},
        'session_age': request.session.get_expiry_age() if hasattr(request.session, 'get_expiry_age') else None,
    }

    # User info
    user_info = {
        'is_authenticated': request.user.is_authenticated,
        'username': request.user.username if request.user.is_authenticated else 'AnonymousUser',
        'user_id': request.user.id if request.user.is_authenticated else None,
    }

    logger.info(f"[debug_media_status] Session: {session_info}")
    logger.info(f"[debug_media_status] User: {user_info}")

    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()

    medias = Media.objects.filter(user=user).order_by('-id')[:10]

    result = {
        'session': session_info,
        'user_info': user_info,
        'effective_user': user.username,
        'effective_user_id': user.id,
        'total_medias': Media.objects.filter(user=user).count(),
        'unprocessed_medias': Media.objects.filter(user=user).exclude(status='SUCCESS').count(),
        'medias': []
    }

    for m in medias:
        result['medias'].append({
            'id': m.id,
            'title': m.title or f"Media {m.id}",
            'processed': m.processed,
            'status': m.status,
            'blur_progress': m.blur_progress,
            'file': str(m.file),
            'user': m.user.username,
            'user_id': m.user.id,
        })

    return JsonResponse(result, json_dumps_params={'indent': 2})


def _live_progress(media):
    """La progression vivante d'un média : clé `media_progress_<id>`, sinon `blur_progress`."""
    cached = cache.get(f"media_progress_{media.id}")
    return cached if cached is not None else (media.blur_progress or 0)


# Les vues de PROGRESSION : fabrique COMMUNE (`progress_views.make_progress_views`, ROUTE §11 #37,
# 2026-10-03) — l'app n'y déclare que sa progression vivante (`media_progress_<id>`,
# `blur_progress`). L'ETA est celle de ses PROCESS (`function_specs.PIPELINE`, 2026-10-05).
from wama.common.utils.progress_views import make_progress_views  # noqa: E402

_pv = make_progress_views(work_model=Media, app_id='anonymizer',
                          progress_field='blur_progress', progress_of=_live_progress)
progress, global_progress = _pv['progress'], _pv['global_progress']


def task_status(request, task_id):
    res = AsyncResult(task_id)
    return JsonResponse({"status": res.status})


# `download_media` et `_servir_media_traite` RETIRÉS le 2026-11-02 (REMOVAL_LEDGER R205) : l'ancienne
# forme POST + `media_id` du ⬇, sans appelant ; le ⬇ d'une card est celui de la fabrique commune
# (`download/<pk>/`), qui sert le champ `output_file` déclaré au lot.


# ⬇ « Télécharger tout » de la barre de file : le ZIP de la file que compte la barre globale,
# par la fabrique commune (`make_progress_views`, 2026-10-17 — REMOVAL_LEDGER R142).
download_all_media = _pv['download_all']


def stop_process_view(request):
    if request.method != 'POST':
        return HttpResponseNotAllowed(['POST'])

    user_id = request.user.id
    task_id = cache.get(f"user_task_{user_id}")
    if task_id:
        res = AsyncResult(task_id)
        res.revoke(terminate=True)
        cache.delete(f"user_task_{user_id}")
        cache.delete(f"process_progress_{user_id}")
        stop_process(user_id)  # set stop flag pour toutes les tasks individuelles

    # Clear all dedup locks for this user
    cache.delete(f"anon_lock:batch:{user_id}")
    for m in Media.objects.filter(user_id=user_id):
        cache.delete(f"anon_lock:media:{m.id}")
        cache.delete(f"anon_task_owner:media:{m.id}")

    return JsonResponse({"status": "stopped"})


# Card média = partial serveur UNIQUE, par la fabrique commune (`make_card_view`, 2026-11-02).
from wama.common.utils.item_views import make_card_view  # noqa: E402

card_html = make_card_view(work_model=Media, template='anonymizer/_media_card.html',
                           decorate=lambda media: _decorate_card(media))


def _reset_for_relaunch(media):
    """Remise à zéro d'un média AVANT relance (sous le verrou begin_processing)."""
    media.blur_progress = 0
    media.error_message = ''


# ── Quatre vues de lot par la fabrique COMMUNE (`batch_views.make_batch_views`, portage
# 2026-09-23, 9ᵉ app réelle — ROUTE §11 #36). Spécificités DÉCLARÉES : la remise à zéro du ▶ est
# celle de `start` (`_reset_for_relaunch`) plus l'oubli du cache de progression ; les réglages
# de lot sont le SCHÉMA de l'app (`PARAMS_JSON`, coercé par la brique) et chaque média réglé
# passe `MSValues_customised` (`after_update`) ; la duplication VIDE la sortie (`output_file`,
# champ fichier depuis le 2026-09-27) et remet `blur_progress` à 0 ; la suppression purge
# verrous et cache (`_forget_outputs`) avant que la brique ne supprime `file` ET `output_file`
# (propriété + partage jugés) et la ligne. `batch_download` est
# désormais celui de la fabrique : il n'était local que parce que la sortie n'était pas un
# champ fichier — et il cherchait le nom `<entrée>_blurred`, que plus rien n'écrit.
from wama.common.utils.batch_views import make_batch_views
from .params import CLASSES_SETTING


def _get_user(request):
    return request.user if request.user.is_authenticated else get_or_create_anonymous_user()


def _reset_and_forget_progress(media):
    _reset_for_relaunch(media)
    cache.delete(f"media_progress_{media.id}")


from wama.common.utils.process_views import make_process_start_view  # noqa: E402


# ▶ d'UN process de la card (`ROUTE §10.6` 5.1) : fabrique COMMUNE — refaire la sortie seule
# (format, qualité) sans re-flouter, ou re-flouter sans attendre qu'un réglage change.
start_process = make_process_start_view(
    work_model=Media, task_for=lambda _media: process_single_media,
    reset_on_start=_reset_and_forget_progress)


def _mark_customised(media):
    media.MSValues_customised = True
    return ['MSValues_customised']


#: Champs du schéma pour qui `''` EST une valeur : un prompt vidé s'efface, un modèle vidé revient
#: au choix automatique — lu par la route d'élément ET par la fabrique de lot.
SETTINGS_EMPTY_IS_VALUE = ('sam3_prompt', 'model_to_use')


def _apply_media_settings(media, data):
    """LES réglages d'un média, posés sans sauver — rend les champs touchés. La route d'un élément
    (`update_settings`) ET la fabrique des vues de lot passent ici, comme au reader : le lot ne
    validait pas le prompt SAM3 que la route d'élément refusait. Restent explicites les seuls cas à
    sémantique PROPRE ; le reste du schéma passe par l'écrivain COMMUN (choix, longueurs).
    Lève `ValueError` sur un prompt SAM3 invalide (rien n'est sauvé)."""
    from wama.common.utils.batch_views import apply_item_settings
    from wama.anonymizer.params import CLASSES_SETTING, clean_classes
    data = dict(data)
    touched = []
    if 'sam3_prompt' in data:
        prompt = str(data.pop('sam3_prompt') or '').strip()
        if prompt:
            is_valid, error = validate_sam3_prompt(prompt)
            if not is_valid:
                raise ValueError(f'Invalid SAM3 prompt: {error}')
        media.sam3_prompt = prompt or None
        touched.append('sam3_prompt')
    if 'model_to_use' in data:
        # Clé de catalogue, ou « auto » / vide = choix automatique au lancement ; un identifiant
        # d'avant est normalisé par `Media.save` (route F4b ⑤).
        from wama.common.utils.auto_model import AUTO, is_auto
        model = data.pop('model_to_use')
        media.model_to_use = AUTO if is_auto(model) else str(model).strip()
        touched.append('model_to_use')
    # Les classes à flouter : multi-sélection hors schéma — une liste vide ne touche à rien.
    classes = data.pop(CLASSES_SETTING, None)
    if isinstance(classes, list) and classes:
        media.classes2blur = clean_classes(classes)
        touched.append(CLASSES_SETTING)
    names = tuple(p['name'] for p in _media_schema(media) if p.get('name'))
    return touched + apply_item_settings(media, data, params_fields=names)


def _media_schema(media):
    """Le schéma du DOMAINE du média (image / vidéo, ou document — `app_modes.domain_schema`) :
    la ⚙ d'une card, celle d'un lot et l'écrivain des réglages lisent le même objet."""
    from wama.common.utils.app_modes import element_schema
    return element_schema(media)


def _forget_outputs(media):
    """Ce qu'aucune brique ne connaît d'un média : ses verrous et son cache. Appelé par la
    fabrique (`on_delete`) AVANT les fichiers — la sortie floutée, champ fichier depuis le
    2026-09-27, est supprimée par la brique avec `file`."""
    cache.delete(f"anon_lock:media:{media.id}")
    cache.delete(f"anon_task_owner:media:{media.id}")


# ▶ de la card, ▶ et 🗑 de la file : fabrique COMMUNE (`item_views.make_item_views`, ROUTE §11
# #39, 2026-10-29) — la même déclaration que lit l'outil `start_anonymizer`. Le clic principal de
# « tout lancer » relance ce qui n'a pas abouti ; « Tout relancer », réussis compris (ce que faisait
# la chaîne de lot `ProcessView`, retirée), est au menu ▾ (décision de Fabien, même jour).
# (`force_individual` n'était plus lu par la tâche, `anonymizer/tasks.py:137`.)
from wama.common.utils.item_views import make_item_views  # noqa: E402

_iv = make_item_views(work_model=Media, app_id='anonymizer', task=process_single_media,
                      get_user=_get_user, reset_on_start=_reset_for_relaunch,
                      pending={}, pending_exclude={'status': 'SUCCESS'},
                      progress_key='media_progress_{pk}', on_stop=_forget_outputs,
                      batch_model=BatchAnonymizer)
start = _iv['start']
start_all = _iv['start_all']
clear_all_media = _iv['clear_all']
# ⏹ ⬇ 🗑 ⧉ ⚙ d'une card : la fabrique COMMUNE (2026-11-02, ROUTE §11 #42 ④), qui lit ce que l'app
# déclare à sa fabrique de lot (`_bv`, plus bas) : le nettoyage de ses verrous (`_forget_outputs`,
# au retrait comme à l'arrêt), LA fonction de réglage d'un média et ses classes à flouter, une
# liste (`list_settings`). ⏹ suit la règle commune : la card s'arrête en échec « Interrompu par
# l'utilisateur », relançable — elle revenait en attente sans le dire, ses process restant ouverts.
stop = _iv['stop']
download = _iv['download']
delete = _iv['delete']
duplicate = _iv['duplicate']
update_settings = _iv['update_settings']


def _read_batch(user, pk):
    """Un lot PARTAGÉ se lit (téléchargement, état) — partage F7, comme avant le portage."""
    from wama.common.utils.scoping import visible_or_404
    return visible_or_404(BatchAnonymizer, user, pk=pk)


_bv = make_batch_views(
    work_model=Media, batch_model=BatchAnonymizer, get_user=_get_user,
    task=process_single_media, reset_on_start=_reset_and_forget_progress,
    # Les détections, la sortie et les lignes de l'OCR : ce que les process ont écrit, la brique le
    # vide elle-même (`AppPipeline.produced_fields`, 2026-10-21) — `output_file` est déclaré par le
    # floutage et l'occultation depuis le 2026-11-02 (le lister ici le disait deux fois).
    read_lookup=_read_batch,
    schema=_media_schema, empty_is_value=SETTINGS_EMPTY_IS_VALUE,
    list_settings=(CLASSES_SETTING,),
    apply_settings=_apply_media_settings, after_update=_mark_customised,
    item_model=BatchAnonymizerItem, fk_name='media',
    reset_on_duplicate={'status': 'PENDING', 'blur_progress': 0},
    on_delete=_forget_outputs,
)
batch_start = _bv['batch_start']
batch_update = _bv['batch_update']
batch_delete = _bv['batch_delete']
batch_duplicate = _bv['batch_duplicate']
batch_download = _bv['batch_download']
batch_promote = _bv['batch_promote']
batch_realign = _bv['batch_realign']


def queue_count(request):
    """Returns the current queue count for AJAX updates."""
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
    count = Media.objects.filter(user=user).count()
    return JsonResponse({'count': count})



def _anonymizer_nature(m):
    """Nature d'un média (image / vidéo / audio) — ce qui peut cohabiter dans un lot.

    DEUX consommateurs, une seule déclaration, toutes deux par la fabrique commune (`group_key`) :
    le regroupement à l'arrivée (`consolidate_arrival`) et la fusion par drag&drop (`merge`)."""
    return m.media_type or 'video'


def _auto_wrap_orphans(user):
    """Range les Media pas encore en batch — brique COMMUNE, stratégie par défaut
    (chaque orphelin → batch-of-1). Le regroupement par nature ne se fait plus qu'à
    l'ARRIVÉE (`queue_manipulation.consolidate_arrival`) : indexé sur l'accumulation,
    il fusionnait des envois individuels espacés (constat Fabien 14/08)."""
    from wama.common.utils.batch_common import auto_wrap_orphans
    auto_wrap_orphans(
        user, work_model=Media, batch_model=BatchAnonymizer,
        item_model=BatchAnonymizerItem, fk_name='media',
    )


def _decorate_card(media, preloaded=False):
    """Attache les chips de card (générés du SCHÉMA, card_chips) à l'instance, et les PROCESS de
    la card (« Floutage → Sortie ») avec son état MONTRÉ (`process_pipeline.decorate`).
    Point d'attache UNIQUE : appelé par IndexView ET par card_html — sinon la card
    rendue par l'endpoint diverge de celle du chargement (leçon describer)."""
    from wama.common.services.process_pipeline import decorate
    from wama.common.utils.card_chips import chips_by_section
    decorate(media, preloaded=preloaded)
    schema = _media_schema(media)
    extra = []
    if 'target_mode' in {p['name'] for p in schema} and media.target_mode == 'classes' and media.classes2blur:
        extra.append({'label': ', '.join(media.classes2blur[:3])
                                + ('…' if len(media.classes2blur) > 3 else ''),
                      'icon': 'fa-eye-slash',
                      'title': 'Objets floutés : ' + ', '.join(media.classes2blur),
                      'section': 'settings'})
    media.chips = chips_by_section(media, schema, extra=extra)
    return media


def _queue_context(request, user):
    """Contexte de FILE (toolbar + batches + schéma params) — briques communes."""
    import json as _json
    from wama.common.utils.batch_common import build_batches_list
    from wama.common.utils.queue_view import apply_queue_sort_filter
    from wama.anonymizer.params import GROUPS_JSON, PARAMS_JSON

    _auto_wrap_orphans(user)

    def _extra(batch, items, medias):
        from wama.common.utils.card_chips import common_chips_for_items
        success_count = sum(1 for m in medias if m.status == 'SUCCESS')
        return {
            'success_pct': int(success_count / batch.total * 100) if batch.total else 0,
            # (l'ETA agrégée de la card mère, `eta_ids`, vient de `build_batches_list`)
            # Réglages COMMUNS aux filles (slot meta_template, mécanisme du parc — porté
            # le 31/08 depuis le pilote transcriber, brique commune schéma-driven).
            # Un lot ne mêle pas les natures (`group_key`) : le schéma de son premier média.
            'common_chips': common_chips_for_items(medias, _media_schema(medias[0]) if medias else []),
        }

    batches_list = build_batches_list(user, batch_model=BatchAnonymizer,
                                      work_attr='media', order_by='-created_at',
                                      extra=_extra)
    # Les lignes d'exécution de TOUTES les cards de la page en une requête (`decorate_cards`,
    # comme les neuf autres apps) — elle se faisait dans `_extra`, donc une fois PAR LOT
    # (mesuré le 2026-10-14 par `tests_page_cost.QueuePageReadsStepStatesOnceTest`).
    from wama.common.services.process_pipeline import decorate_cards
    decorate_cards([link.media for b in batches_list for link in b['items']], _decorate_card)

    def _name(b):
        m = b['items'][0].media if b['obj'].total == 1 and b['items'] and b['items'][0].media else None
        return (m.get_filename() or '').lower() if m else ''

    batches_list, q_sort, q_filter = apply_queue_sort_filter(request, batches_list, name_of=_name)
    # Une file PAR DOMAINE (2026-11-02) : un lot ne mêle pas les natures (`group_key`), son
    # premier média dit son domaine — la règle de la card (`element_domain_or_first`).
    from wama.common.utils.app_modes import element_domain_or_first
    from wama.anonymizer.params import DOCUMENT_PARAMS_JSON

    def _domain_of(b):
        first = b['items'][0].media if b['items'] and b['items'][0].media else None
        return element_domain_or_first(first) if first is not None else 'image_video'

    image_batches = [b for b in batches_list if _domain_of(b) != 'document']
    document_batches = [b for b in batches_list if _domain_of(b) == 'document']

    return {
        'batches_list': image_batches,
        'document_batches': document_batches,
        'queue_count': sum(len(b['items']) for b in image_batches),
        'q_sort': q_sort,
        'q_filter': q_filter,
        # Schéma params (source unique modale item/batch + inspecteur). Voir params.py.
        'params_json': _json.dumps(PARAMS_JSON),
        'document_params_json': _json.dumps(DOCUMENT_PARAMS_JSON),
        # Groupes de la modale (sections calquées sur le volet droit). Voir params.py GROUPS.
        'groups_json': _json.dumps(GROUPS_JSON),
    }


# ── Manipulation directe de la file (fabrique COMMUNE, variante liaison) ─────────────
#
# L'anonymizer était la DERNIÈRE app hors fabrique (relevé du 2026-09-04 : 11 apps sur 12 avaient
# les routes, elle n'avait qu'un `consolidate`). Rien ne s'y opposait — elle a bien l'architecture
# batch unifiée (BatchAnonymizer + BatchAnonymizerItem + FK `media`) que la fabrique demande ;
# personne n'était simplement venu la brancher, faute d'UI qui l'exige.
#
# `consolidate` vient de la fabrique (2026-10-16) : elle range désormais PAR NATURE, par ce même
# `group_key` — la version locale qui le faisait, et le helper que l'import du gestionnaire de
# fichiers appelait, sont retirés (`queue_manipulation.consolidate_arrival`). `group_key` porte
# la règle jusqu'au geste de drag&drop : sans elle, glisser une vidéo dans un lot d'images
# produisait un lot mixte qu'aucun import n'aurait pu créer.
from wama.common.utils.queue_manipulation import make_queue_manipulation_views as _make_qm

_qm = _make_qm(
    work_model=Media, batch_model=BatchAnonymizer, item_model=BatchAnonymizerItem,
    fk_name='media',
    get_user=lambda r: r.user if r.user.is_authenticated else get_or_create_anonymous_user(),
    group_key=_anonymizer_nature,      # l'arrivée (`consolidate_arrival`) ET le glisser-déposer
)
remove_from_batch = _qm['remove_from_batch']
reorder           = _qm['reorder']
reorder_queue     = _qm['reorder_queue']
merge             = _qm['merge']
move_to_batch     = _qm['move_to_batch']
consolidate       = _qm['consolidate']


# ── Réglages UTILISATEUR — brique commune `user_settings`, dérivés du schéma (2026-09-27) ──
# Remplacent les tables `UserSettings` / `GlobalSettings`. Lire, garder, remettre à zéro, faire
# naître un média et les deux routes JSON : la brique commune, sur la déclaration de params.py.
from wama.anonymizer.params import PANEL_SETTINGS, PARAMS as _PARAMS  # noqa: E402
from wama.anonymizer.params import DOCUMENT_PARAMS as _DOCUMENT_PARAMS  # noqa: E402
from wama.common.utils.user_settings import (  # noqa: E402
    make_panel_settings_views, new_element_settings, read_panel_settings, reset_panel_settings,
)

#: Le VOLET porte les réglages des DEUX domaines (2026-11-02) : leurs noms ne se recoupent pas, une
#: seule mémoire de l'utilisateur les garde, une seule remise à zéro les rend.
_PANEL_PARAMS = list(_PARAMS) + list(_DOCUMENT_PARAMS)

get_user_anonymizer_settings, save_user_anonymizer_settings = make_panel_settings_views(
    'anonymizer', _PANEL_PARAMS, **PANEL_SETTINGS)


def _request_user(request):
    return request.user if request.user.is_authenticated else get_or_create_anonymous_user()


#: Le schéma de NAISSANCE de chaque domaine, par le nom que le domaine déclare (`params_schema`) —
#: le volet de l'image / vidéo porte en plus les classes à flouter (hors schéma).
_BIRTH = {'PARAMS_JSON': (_PARAMS, PANEL_SETTINGS),
          'DOCUMENT_PARAMS_JSON': (_DOCUMENT_PARAMS, {'key': PANEL_SETTINGS['key']})}


def new_media_settings(user, model=None, app='anonymizer', post=None, inputs=None, nature=None):
    """Les colonnes de réglage d'un média NAISSANT (brique commune : défauts ← réglages de
    l'auteur ← ce que le dépôt poste). `model`/`app` : une jumelle de bac à sable passe les
    siens (import du gestionnaire de fichiers). `nature` : celle du fichier reçu — le schéma est
    celui du domaine où elle range le média (`app_modes.element_domain`, sur le média pas encore
    sauvé, la règle de l'imager) ; inconnue, celui de l'image / vidéo."""
    from wama.common.utils.app_modes import element_schema_name
    item_model = model or Media
    name = element_schema_name(item_model(media_type=nature)) if nature else ''
    params, settings = _BIRTH.get(name, _BIRTH['PARAMS_JSON'])
    return new_element_settings(user, app, params, item_model, post=post, inputs=inputs, **settings)


def get_context(request):
    """Contexte du VOLET DROIT — les réglages de l'utilisateur (brique commune) ; la file, elle,
    vient de `_queue_context` (briques communes)."""
    user = _request_user(request)
    # `gs_values` : nom historique du gabarit du volet, qui lit ces valeurs par NOM de param.
    gs_values = read_panel_settings(user, 'anonymizer', _PANEL_PARAMS, **PANEL_SETTINGS)
    gs_values['sam3_prompt'] = gs_values.get('sam3_prompt') or ''
    # Le menu de modèle est rempli par le CATALOGUE (source `catalog`, `options_mode`) : sa
    # valeur est une CLÉ de catalogue ou « auto » (route F4b ⑤, 2026-10-07) — un réglage
    # mémorisé avant la bascule (identifiant, ancien chemin) s'y traduit à la lecture.
    from .utils.yolo_utils import catalogue_key_for, get_all_class_choices
    gs_values['model_to_use'] = catalogue_key_for(gs_values.get('model_to_use')) or 'auto'

    import json as _json
    from wama.common.utils.output_formats import OUTPUT_PARAM_NAMES
    return {
        'user': user,
        'gs_values': gs_values,
        # Les valeurs de la section du volet GÉNÉRÉE du schéma (Sortie, 2026-10-28) — elles seules,
        # et `<` échappé : la chaîne est posée telle quelle dans un `<script>`.
        'panel_values_json': _json.dumps({k: v for k, v in gs_values.items()
                                          if k in OUTPUT_PARAM_NAMES}).replace('<', '\\u003c'),
        # Celles du volet du domaine DOCUMENT (2026-11-02), généré de son schéma.
        'document_panel_values_json': _json.dumps(
            {p.name: gs_values.get(p.name) for p in _DOCUMENT_PARAMS}).replace('<', '\\u003c'),
        'classes': get_all_class_choices(),
        # Appariement entrée↔modèles (brique commune input_match) — JSON déjà sérialisé, clé =
        # identifiant du catalogue (valeur d'option du menu).
        'input_match_meta': _input_match_meta(),
        'input_labels': _input_labels(),
        # Couverture de classes PAR MODÈLE (brique d'alias model_coverage, JSON) → meta
        # WamaModelCaps : griser les checkboxes de classes hors modèle (jamais cachées).
        'class_coverage_meta': _class_coverage_meta(),
    }


def _class_coverage_meta():
    """{model_key: {covered_classes: [ids d'app]}} — l'appariement d'alias est fait CÔTÉ
    SERVEUR par la brique commune `classes_couvertes` (le vocabulaire du catalogue n'est pas
    celui des checkboxes ; leçon couvrir_classes : ne jamais re-apparier en JS)."""
    import json as _json
    try:
        from wama.common.services.model_coverage import classes_couvertes
        from wama.model_manager.models import AIModel
        from .utils.yolo_utils import get_all_class_choices
        from .utils.model_config import DETECTION_TASKS
        voulues = [c[0] for c in get_all_class_choices()]
        meta = {}
        # Entrée « auto » (chantier C, 2026-09-20) : sur « auto » rien n'était grisé (caps = null),
        # alors qu'une classe qu'AUCUN modèle installé ne détecte restait cochable et passait en
        # silence jusqu'à l'avertissement de la tâche. La couverture ne dépend PAS du curseur
        # (taille et segmentation sont des préférences de départage, jamais des filtres) : ce que
        # « auto » peut couvrir = l'union des modèles de détection installés.
        auto_covered = set()
        # Système et publics seuls, comme le tirage de l'anonymizer (`couvrir_classes` sans
        # compte) : la clé d'un modèle privé d'autrui ne sort pas dans la page (ROADMAP §29).
        for m in AIModel.objects.catalogue_visible_to(None).filter(source='anonymizer',
                                                                   is_proposed=False):
            if (m.capabilities or {}).get('classes'):
                covered = classes_couvertes(m, voulues)
                meta[m.model_key] = {'covered_classes': sorted(covered)}
                if m.is_downloaded and (m.capabilities or {}).get('task') in DETECTION_TASKS:
                    auto_covered |= covered
        meta['auto'] = {'covered_classes': sorted(auto_covered)}
        return _json.dumps(meta)
    except Exception:
        return '{}'


def _input_match_meta(models_by_type=None):
    """Meta JSON brique COMMUNE, clée sur les VALEURS D'OPTION du select de modèle — les
    identifiants du CATALOGUE sans la source (`yolo:<fichier>`, `sam3`), servis par la source
    `catalog` depuis le 2026-09-27 — plus l'entrée `auto`."""
    import json as _json
    from wama.common.utils.input_match import auto_entry, input_match_meta
    meta = input_match_meta('anonymizer', key=lambda mk: mk.split(':', 1)[-1])
    if not meta:
        return '{}'
    meta['auto'] = auto_entry({k: v for k, v in meta.items() if k != 'sam3'} or meta)
    return _json.dumps(meta)


def _input_labels():
    """Libellés d'INPUT_TYPES (JSON) — brique commune (extraction 2026-08-17)."""
    import json as _json
    from wama.common.utils.input_match import input_labels
    return _json.dumps(input_labels())


# `_model_help_meta` RETIRÉ le 2026-09-27 : l'aide sous le menu de modèle vient de la voie
# commune `WamaModelHelp.fetchCatalogMeta('anonymizer')`, clée comme les options du catalogue.


# `update_settings` (réglage PAR CHAMP : média, utilisateur ou « global »), `expand_area` (drapeaux
# d'affichage `show_gs`/`show_ms`) RETIRÉS le 2026-09-27 avec les tables `UserSettings` et
# `GlobalSettings` : le volet enregistre par l'inspecteur commun (élément, lot ou préférences
# de l'utilisateur), la brique `user_settings` garde les préférences.


# `clear_media` RETIRÉE le 2026-11-02 (REMOVAL_LEDGER R205) : l'ancienne forme POST + `media_id` de
# la 🗑, sans appelant — elle acceptait l'id de N'IMPORTE QUEL utilisateur jusqu'au portage de la
# veille ; la 🗑 d'une card est celle de la fabrique commune (`delete/<pk>/`, son propriétaire).


# `reset_media_settings` RETIRÉ le 2026-09-27 : sans consommateur, il remettait un média sur les
# défauts de `GlobalSettings`.


def check_all_processed(request):
    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
    medias = Media.objects.filter(user=user)
    all_processed = medias.exists() and all(m.processed for m in medias)
    return JsonResponse({"all_processed": all_processed})


@require_POST
def reset_user_settings(request):
    """Remet les réglages de l'utilisateur sur les défauts du schéma (brique commune : ses
    préférences sont RETIRÉES, jamais réécrites avec les défauts du jour)."""
    values = reset_panel_settings(_request_user(request), 'anonymizer', _PANEL_PARAMS, **PANEL_SETTINGS)
    return JsonResponse({"success": True, "settings": values})


# `init_user_settings`, `init_global_settings`, `ensure_global_settings`,
# `reset_global_settings_safe` RETIRÉS le 2026-09-27 avec les tables `UserSettings` et
# `GlobalSettings` : les défauts sont ceux du schéma (`params.USER_SETTINGS_DEFAULTS`).


# ========================================
# Modern Modal-Based Settings Endpoints
# ========================================

def get_media_settings(request, media_id):
    """Valeurs COURANTES d'un média pour la modale paramètres — SCHÉMA-DRIVEN.

    Le payload est plat : `values[name]` pour chaque champ du schéma (params.py),
    + les deux cas à sémantique propre (classes2blur = liste à cocher ; modèles =
    options du select peuplées côté JS). Les listes sliders/booleans en dur ont
    disparu avec settings_modal.js (port 2026-08-03) : la modale est rendue par
    WamaParams.renderSettingsModal depuis le schéma."""
    try:
        from wama.common.utils.app_modes import domain_schema_name, element_domain_or_first
        from wama.common.utils.scoping import visible_or_404
        from wama.anonymizer.params import GROUPS_JSON
        user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()
        media = visible_or_404(Media, user, pk=media_id)
        # Le schéma du DOMAINE du média (2026-11-02) : un document a le sien — la modale le rend
        # tel que servi ici, avec ses groupes (seul le schéma image / vidéo en déclare).
        schema = _media_schema(media)
        names = {field['name'] for field in schema}
        domain = element_domain_or_first(media)

        values = {}
        for field in schema:
            v = getattr(media, field['name'], None)
            if v is not None:
                values[field['name']] = v
        classes2blur_list = []
        if 'model_to_use' in names:
            # La modale resélectionne la valeur STOCKÉE parmi ses options : même espace de clés.
            from .utils.yolo_utils import catalogue_key_for, get_all_class_choices
            values['model_to_use'] = catalogue_key_for(media.model_to_use) or 'auto'
            values['sam3_prompt'] = media.sam3_prompt or ''
            media_classes = media.classes2blur or []
            classes2blur_list = [
                {'value': code, 'label': label, 'checked': code in media_classes}
                for code, label in get_all_class_choices()
            ]
        # Les options du menu de modèle ne partent plus d'ici : la modale les tire du CATALOGUE
        # (source `catalog`, bornées par le mode de l'élément — `options_mode`).
        return JsonResponse({
            'success': True,
            'domain': domain,
            'schema': schema,
            'groups': GROUPS_JSON if domain_schema_name('anonymizer', domain) == 'PARAMS_JSON' else [],
            'values': values,
            'classes2blur': classes2blur_list,
        })

    except Http404:
        raise
    except Exception as e:
        import traceback
        return JsonResponse({
            'success': False,
            'error': str(e),
            'traceback': traceback.format_exc()
        }, status=500)


# ----------------------------------------------------------------------
# SAM3 Endpoints
# ----------------------------------------------------------------------

def get_sam3_status_view(request):
    """Return SAM3 installation and configuration status."""
    status = get_sam3_status()
    status['requirements'] = get_sam3_requirements()
    status['examples'] = get_recommended_prompt_examples()
    return JsonResponse(status)


# `configure_hf_token` RETIRÉ le 2026-09-27 : il écrivait le jeton HuggingFace dans le dossier
# personnel. Le jeton se pose au profil (source `huggingface`, clé de chacun) et ne sert qu'au
# téléchargement, fait depuis le gestionnaire de modèles avec le jeton de celui qui installe.

def validate_prompt_view(request):
    """Validate a SAM3 text prompt."""
    prompt = request.GET.get('prompt', '')
    is_valid, error = validate_sam3_prompt(prompt)
    return JsonResponse({
        'valid': is_valid,
        'error': error if not is_valid else None
    })


def get_sam3_examples(request):
    """Get recommended SAM3 prompt examples."""
    return JsonResponse({
        'examples': get_recommended_prompt_examples()
    })


# =============================================================================
# Batch import (Type A: media_list — one URL/path per line)
# =============================================================================

def batch_template(request):
    """Gabarit de fichier batch, par la brique commune (`batch_template_response`) : une source
    par ligne, les formats que l'app déclare. Écrit à la main jusqu'au 2026-11-02."""
    from wama.common.utils.batch_parsers import batch_template_response
    return batch_template_response(
        'anonymizer', ['source'], {'source': 'https://example.com/photo.jpg'},
        label='Anonymizer (une URL ou un chemin image/vidéo par ligne)')


@require_POST
def batch_preview(request):
    """Parse a batch file and return the list for preview (no DB entries created)."""
    from wama.common.utils.batch_parsers import batch_media_list_preview_response
    return batch_media_list_preview_response(request)


@require_POST
def batch_create(request):
    """
    Parse batch file (URLs/paths), create BatchAnonymizer + Media entries.
    Files are not downloaded yet — download happens when the task starts.
    """
    from wama.common.utils.batch_parsers import parse_batch_file_from_request

    user = request.user if request.user.is_authenticated else get_or_create_anonymous_user()

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
    batch = BatchAnonymizer.objects.create(
        user=user,
        total=len(items),
        batch_file=batch_file,
    )

    created_ids = []
    for i, item in enumerate(items):
        url_or_path = item['path']
        filename = url_or_path.split('/')[-1].split('\\')[-1] or f'item_{i+1}'
        m = Media.objects.create(
            user=user,
            title=filename,
            source_url=url_or_path,
            file='',
            file_ext='',
            **new_media_settings(user),
        )
        BatchAnonymizerItem.objects.create(batch=batch, media=m, row_index=i)
        created_ids.append(m.id)

    return JsonResponse({
        'batch_id': batch.id,
        'media_ids': created_ids,
        'total': len(items),
        'warnings': warnings,
    })


