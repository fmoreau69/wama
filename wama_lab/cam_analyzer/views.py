"""
Django views for Cam Analyzer.
"""
import csv
import io
import json
import logging
import os

import mimetypes
import re

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import FileResponse, HttpResponse, JsonResponse, StreamingHttpResponse
from django.shortcuts import render, get_object_or_404
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from django.core.cache import cache

from .models import AnalysisSession, AnalysisProfile, CameraView, DetectionFrame, TemporalSegment
from .models import get_unique_filename
from wama.common.utils.console_utils import push_console_line, get_console_lines
from .utils.features import catalog as _features_catalog

logger = logging.getLogger(__name__)


def _console(user_id: int, message: str) -> None:
    """Send message to WAMA console."""
    try:
        push_console_line(user_id, f"[Cam Analyzer] {message}")
        logger.info(message)
    except Exception as e:
        logger.warning(f"Failed to push console line: {e}")


def _get_available_models():
    """List available YOLO models from AI-models directory."""
    models_dir = os.path.join(settings.BASE_DIR, 'AI-models', 'models', 'vision', 'yolo')
    available = []

    for task_dir in ['detect', 'segment']:
        task_path = os.path.join(models_dir, task_dir)
        if not os.path.isdir(task_path):
            continue
        for root, dirs, files in os.walk(task_path):
            for f in files:
                if f.endswith('.pt'):
                    rel_path = os.path.relpath(os.path.join(root, f), settings.BASE_DIR)
                    available.append({
                        'name': f,
                        'path': rel_path.replace('\\', '/'),
                        'task': task_dir,
                    })

    available.sort(key=lambda x: (x['task'], x['name']))
    return available


def _extract_video_metadata(file_path):
    """Extract video metadata (duration, fps, resolution) using cv2."""
    try:
        import cv2
        cap = cv2.VideoCapture(file_path)
        if not cap.isOpened():
            return {}
        fps = cap.get(cv2.CAP_PROP_FPS)
        frame_count = cap.get(cv2.CAP_PROP_FRAME_COUNT)
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        duration = frame_count / fps if fps > 0 else 0
        cap.release()
        return {
            'duration': round(duration, 2),
            'fps': round(fps, 2),
            'width': width,
            'height': height,
        }
    except Exception as e:
        logger.warning(f"Failed to extract video metadata: {e}")
        return {}


# Backwards-compat shim — the real implementation lives in
# ``wama.common.utils.video_compat.ensure_h264`` since this helper is
# shared by upload_camera and the legacy quad-extraction fallback (and
# eventually by other apps + Converter as its trivial H.264 backend).
from wama.common.utils.video_compat import ensure_h264 as _ensure_h264  # noqa: F401


# COCO classes relevant for road analysis
COCO_ROAD_CLASSES = {
    0: 'person',
    1: 'bicycle',
    2: 'car',
    3: 'motorcycle',
    5: 'bus',
    7: 'truck',
    9: 'traffic light',
    11: 'stop sign',
    13: 'bench',
    15: 'cat',
    16: 'dog',
}


# =============================================================================
# Video streaming with Range request support (for seeking)
# =============================================================================

@login_required
@require_http_methods(["GET"])
def stream_video(request, camera_id):
    """Stream a camera video with HTTP Range support for seeking."""
    camera = get_object_or_404(CameraView, id=camera_id, session__user=request.user)
    if not camera.video_file:
        return HttpResponse(status=404)

    file_path = camera.video_file.path
    if not os.path.isfile(file_path):
        return HttpResponse(status=404)

    file_size = os.path.getsize(file_path)
    content_type = mimetypes.guess_type(file_path)[0] or 'video/mp4'

    range_header = request.META.get('HTTP_RANGE', '')
    range_match = re.match(r'bytes=(\d+)-(\d*)', range_header)

    if range_match:
        start = int(range_match.group(1))
        end = int(range_match.group(2)) if range_match.group(2) else file_size - 1
        end = min(end, file_size - 1)
        length = end - start + 1

        def file_iterator():
            with open(file_path, 'rb') as f:
                f.seek(start)
                remaining = length
                while remaining > 0:
                    chunk_size = min(8192, remaining)
                    data = f.read(chunk_size)
                    if not data:
                        break
                    remaining -= len(data)
                    yield data

        response = StreamingHttpResponse(file_iterator(), status=206, content_type=content_type)
        response['Content-Length'] = length
        response['Content-Range'] = f'bytes {start}-{end}/{file_size}'
    else:
        response = FileResponse(open(file_path, 'rb'), content_type=content_type)
        response['Content-Length'] = file_size

    response['Accept-Ranges'] = 'bytes'
    return response


# =============================================================================
# Main view
# =============================================================================

@login_required
def index(request):
    """Main Cam Analyzer page."""
    sessions = AnalysisSession.objects.filter(user=request.user)[:20]
    profiles = AnalysisProfile.objects.filter(user=request.user)
    available_models = _get_available_models()

    context = {
        'sessions': sessions,
        'profiles': profiles,
        'available_models': json.dumps(available_models),
        'coco_classes': json.dumps(COCO_ROAD_CLASSES),
    }

    return render(request, 'cam_analyzer/index.html', context)


# =============================================================================
# Sessions API
# =============================================================================

@login_required
@require_http_methods(["GET"])
def list_sessions(request):
    """List all sessions for current user."""
    sessions = AnalysisSession.objects.filter(user=request.user)

    data = []
    for s in sessions:
        cameras = []
        for c in s.cameras.all():
            cameras.append({
                'id': c.id,
                'position': c.position,
                'label': c.label,
                'video_url': f'/lab/cam-analyzer/api/cameras/{c.id}/stream/' if c.video_file else None,
                'duration': c.duration,
                'fps': c.fps,
                'width': c.width,
                'height': c.height,
                'time_offset': c.time_offset,
            })
        data.append({
            'id': str(s.id),
            'name': s.name,
            'status': s.status,
            'camera_count': len(cameras),
            'cameras': cameras,
            'profile_id': s.profile_id,
            'created_at': s.created_at.isoformat(),
            'progress': s.progress,
        })

    return JsonResponse({'sessions': data})


@login_required
@require_http_methods(["POST"])
def create_session(request):
    """Create a new analysis session."""
    user_id = request.user.id
    name = request.POST.get('name', '').strip()
    profile_id = request.POST.get('profile_id')

    try:
        profile = None
        if profile_id:
            profile = AnalysisProfile.objects.filter(pk=profile_id, user=request.user).first()

        session = AnalysisSession.objects.create(
            user=request.user,
            name=name or f"Session {AnalysisSession.objects.filter(user=request.user).count() + 1}",
            profile=profile,
            status=AnalysisSession.Status.DRAFT,
        )
        _console(user_id, f"Session créée : {session.name}")

        return JsonResponse({
            'success': True,
            'session_id': str(session.id),
            'name': session.name,
        })

    except Exception as e:
        logger.error(f"Error creating session: {e}", exc_info=True)
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@login_required
@require_http_methods(["GET"])
def get_session(request, session_id):
    """Get full session details."""
    session = get_object_or_404(AnalysisSession, id=session_id, user=request.user)

    cameras = []
    for c in session.cameras.all():
        cameras.append({
            'id': c.id,
            'position': c.position,
            'label': c.label,
            'video_url': f'/lab/cam-analyzer/api/cameras/{c.id}/stream/' if c.video_file else None,
            'filename': os.path.basename(c.video_file.name) if c.video_file else '',
            'duration': c.duration,
            'fps': c.fps,
            'width': c.width,
            'height': c.height,
            'time_offset': c.time_offset,
        })

    # Downsample gps_track for the mini-map. With 24k points across 2h20 of
    # driving, 1500 samples = 1 point per ~5.5s ≈ 46m at 30 km/h, which
    # under-samples sharp turns. 3000 points (~22m gap) tracks corners
    # cleanly while keeping the JSON payload around 250 KB.
    gps_full = session.gps_track or []
    if len(gps_full) > 3000:
        step = max(1, len(gps_full) // 3000)
        gps_sampled = [
            {'ts': p.get('ts'), 'lat': p.get('lat'), 'lon': p.get('lon'),
             'heading': p.get('heading'), 'speed_kmh': p.get('speed_kmh')}
            for p in gps_full[::step]
        ]
    else:
        gps_sampled = [
            {'ts': p.get('ts'), 'lat': p.get('lat'), 'lon': p.get('lon'),
             'heading': p.get('heading'), 'speed_kmh': p.get('speed_kmh')}
            for p in gps_full
        ]

    return JsonResponse({
        'id': str(session.id),
        'name': session.name,
        'status': session.status,
        'profile_id': session.profile_id,
        'config': session.config,
        'cameras': cameras,
        'progress': session.progress,
        'results_summary': session.results_summary,
        # Catalogue des bascules ⚑ Modes (registre + état effectif) — l'UI s'auto-génère
        # depuis ces métadonnées (libellé/description/scope), zéro HTML par bascule.
        'features': _features_catalog(session),
        'intersection_windows': session.intersection_windows,
        'gps_track': gps_sampled,
        'gps_time_offset': getattr(session, 'gps_time_offset', 0.0) or 0.0,
        'gps_time_scale': getattr(session, 'gps_time_scale', 1.0) or 1.0,
        'lane_width_m': getattr(session, 'lane_width_m', 0.0) or 0.0,
        'created_at': session.created_at.isoformat(),
        'error_message': session.error_message,
    })


@login_required
@require_http_methods(["POST"])
def set_gps_offset(request, session_id):
    """Enregistre l'offset de synchro GPS↔vidéo (secondes) — recalage manuel, appliqué
    à l'affichage, sans ré-analyse. Réutilisable à tout moment en cas de désync."""
    session = get_object_or_404(AnalysisSession, id=session_id, user=request.user)
    try:
        offset = float(json.loads(request.body or '{}').get('gps_time_offset', 0.0))
    except (ValueError, TypeError):
        return JsonResponse({'error': 'offset invalide'}, status=400)
    session.gps_time_offset = offset
    session.save(update_fields=['gps_time_offset'])
    return JsonResponse({'success': True, 'gps_time_offset': offset})


@login_required
@require_http_methods(["POST"])
def set_camera_yaw(request, session_id):
    """Enregistre le yaw de montage réel de chaque caméra (deg, sens horaire depuis
    l'avant véhicule) dans `session.config['camera_yaw']` — les caméras terrain ne sont
    pas toutes exactement à 0/±90/180°, et une erreur de yaw décale latéralement tous
    les objets de la vue (sin(Δyaw)·distance). Appliqué immédiatement au rendu vue de
    dessus, et au tracking 360°/prédiction au prochain calcul (pas de ré-analyse)."""
    session = get_object_or_404(AnalysisSession, id=session_id, user=request.user)
    _POS = ('front', 'right', 'rear', 'left')
    try:
        body = json.loads(request.body or '{}')
        yaw = {k: float(v) for k, v in (body.get('camera_yaw') or {}).items() if k in _POS}
        # FOV réels par caméra (vari-focales latérales : réglage terrain incertain 52-97°H).
        fov = {k: {a: float(x) for a, x in (v or {}).items() if a in ('h', 'v')}
               for k, v in (body.get('camera_fov') or {}).items() if k in _POS}
    except (ValueError, TypeError, AttributeError):
        return JsonResponse({'error': 'camera_yaw/camera_fov invalide'}, status=400)
    cfg = session.config or {}
    if yaw or 'camera_yaw' in (body or {}):
        cfg['camera_yaw'] = yaw
    if fov:
        cfg['camera_fov'] = {**(cfg.get('camera_fov') or {}), **fov}
    session.config = cfg
    session.save(update_fields=['config'])
    return JsonResponse({'success': True, 'camera_yaw': cfg.get('camera_yaw'),
                         'camera_fov': cfg.get('camera_fov')})


@login_required
@require_http_methods(["POST"])
def set_features(request, session_id):
    """Surcharges des bascules de fonctionnalités (⚑ Modes) — comparer AVEC/SANS chaque
    amélioration du positionnement/cap/distances. Registre : `utils/features.py` ;
    mécanisme générique : `wama/common/utils/feature_flags.py`. Les bascules `live`
    agissent au rendu suivant ; les `compute` au prochain calcul d'indicateurs."""
    from .utils.features import clean_overrides, catalog
    session = get_object_or_404(AnalysisSession, id=session_id, user=request.user)
    try:
        raw = json.loads(request.body or '{}').get('features')
    except ValueError:
        return JsonResponse({'error': 'JSON invalide'}, status=400)
    cfg = session.config or {}
    cfg['features'] = {**(cfg.get('features') or {}), **clean_overrides(raw)}
    session.config = cfg
    session.save(update_fields=['config'])
    return JsonResponse({'success': True, 'features': catalog(session)})


@login_required
@require_http_methods(["POST"])
def sync_from_rec(request, session_id):
    """Recalcule la synchro GPS↔vidéo (scale+offset) depuis le .rec RTMaps + la largeur
    de voie. Cherche un .rec dans le dossier input de l'utilisateur (best-effort)."""
    import glob
    from django.conf import settings
    from wama.common.rtmaps.rec_parser import parse_rec
    session = get_object_or_404(AnalysisSession, id=session_id, user=request.user)
    base = os.path.join(settings.MEDIA_ROOT, 'cam_analyzer', str(request.user.id), 'input')
    recs = [r for r in glob.glob(os.path.join(base, '**', '*.rec'), recursive=True)
            if 'LogConsole' not in os.path.basename(r)]
    if not recs:
        return JsonResponse({'error': 'Aucun .rec trouvé dans le dossier input.'}, status=404)
    p = parse_rec(recs[0])
    vt = p.get('video_timestamps') or []
    gp = p.get('gps') or []
    if len(vt) < 100 or len(gp) < 10:
        return JsonResponse({'error': 'Parsing .rec insuffisant (vidéo/GPS).'}, status=422)
    front = session.cameras.filter(position='front').first()
    fps = getattr(front, 'fps', None) or 12.0
    session.gps_time_scale = round(fps * (vt[-1] - vt[0]) / (len(vt) - 1), 5)
    session.gps_time_offset = round(vt[0] - gp[0]['ts'], 4)
    lane = None
    try:
        from .utils.lane_estimator import estimate_lane_width
        if front and getattr(front, 'ground_homography', None):
            lane = estimate_lane_width(front)
            if lane:
                session.lane_width_m = lane
    except Exception:
        pass
    session.save(update_fields=['gps_time_scale', 'gps_time_offset', 'lane_width_m'])
    return JsonResponse({'success': True, 'gps_time_scale': session.gps_time_scale,
                         'gps_time_offset': session.gps_time_offset, 'lane_width_m': lane,
                         'rec': os.path.basename(recs[0])})


@login_required
@require_http_methods(["POST"])
def prediction_annotate(request, session_id):
    """Lance (en tâche de fond) le calcul des indicateurs Prédiction (TTC/PET par
    trajectoire) pour la session → stockés sur les détections (prediction_ttc/pet)."""
    session = get_object_or_404(AnalysisSession, id=session_id, user=request.user)
    from .tasks import annotate_prediction_task
    annotate_prediction_task.delay(str(session.id))
    return JsonResponse({'success': True})


@login_required
@require_http_methods(["POST"])
def update_session(request, session_id):
    """Update session name or profile."""
    session = get_object_or_404(AnalysisSession, id=session_id, user=request.user)

    name = request.POST.get('name')
    profile_id = request.POST.get('profile_id')

    if name is not None:
        session.name = name.strip()
    if profile_id is not None:
        if profile_id:
            session.profile = AnalysisProfile.objects.filter(pk=profile_id, user=request.user).first()
        else:
            session.profile = None

    session.save()
    return JsonResponse({'success': True})


@login_required
@require_http_methods(["POST", "DELETE"])
def delete_session(request, session_id):
    """Delete an analysis session and its files."""
    session = get_object_or_404(AnalysisSession, id=session_id, user=request.user)
    user_id = request.user.id

    # Delete camera video files — mais SEULEMENT si aucune AUTRE session ne référence
    # le même fichier (une session dupliquée partage les vidéos source) : sinon on
    # abîmerait la copie/l'original. Réf-aware (cf. safe_delete_file de common/).
    for camera in session.cameras.all():
        if camera.video_file:
            try:
                fname = camera.video_file.name
                shared = CameraView.objects.filter(video_file=fname).exclude(
                    session_id=session.id).exists()
                if shared:
                    logger.info(f"Fichier vidéo conservé (partagé) : {fname}")
                else:
                    camera.video_file.delete(save=False)
            except Exception as e:
                logger.warning(f"Failed to delete camera file: {e}")

    session.delete()
    _console(user_id, f"Session supprimée : {session.name}")

    return JsonResponse({'success': True})


@login_required
@require_http_methods(["POST"])
def duplicate_session(request, session_id):
    """
    Duplique une session À L'IDENTIQUE (données extraites + détections + passes +
    événements + calibration par caméra), en **partageant les fichiers vidéo source**
    (suppression réf-aware côté delete_session) → tester/debug sur une copie sans
    risquer la session d'origine (indispensable en WAMA Lab). Ne relance aucune analyse.
    """
    import uuid
    from django.db import transaction
    from .models import AnalysisPass, LaneEvent, ConflictEvent
    src = get_object_or_404(AnalysisSession, id=session_id, user=request.user)
    with transaction.atomic():
        # 1) Session (nouveau pk UUID).
        new = AnalysisSession.objects.get(pk=src.pk)
        new._state.adding = True
        new.id = uuid.uuid4()
        new.name = f"{src.name} (copie)"
        new.task_id = ''
        new.save(force_insert=True)

        # 2) Caméras — fichiers vidéo PARTAGÉS (même chemin), ground_homography copiée.
        cam_map = {}
        for c in CameraView.objects.filter(session=src):
            old_id = c.pk
            c.pk = None
            c._state.adding = True
            c.session = new
            c.save(force_insert=True)
            cam_map[old_id] = c

        # 3) DetectionFrame (volumineux → bulk batché, streaming).
        BATCH = 2000
        buf = []

        def _flush(model, rows):
            if rows:
                model.objects.bulk_create(rows, batch_size=BATCH)

        for df in DetectionFrame.objects.filter(camera__session=src).iterator(chunk_size=BATCH):
            nc = cam_map.get(df.camera_id)
            if not nc:
                continue
            df.pk = None
            df._state.adding = True
            df.camera = nc
            buf.append(df)
            if len(buf) >= BATCH:
                _flush(DetectionFrame, buf)
                buf = []
        _flush(DetectionFrame, buf)

        # 4) LaneEvent (lié caméra).
        buf = []
        for ev in LaneEvent.objects.filter(camera__session=src).iterator():
            nc = cam_map.get(ev.camera_id)
            if not nc:
                continue
            ev.pk = None
            ev._state.adding = True
            ev.camera = nc
            buf.append(ev)
        _flush(LaneEvent, buf)

        # 5) Événements liés session (+ camera éventuelle, None pour les passes session-level).
        for Model in (AnalysisPass, ConflictEvent, TemporalSegment):
            buf = []
            for ev in Model.objects.filter(session=src).iterator():
                ev.pk = None
                ev._state.adding = True
                ev.session = new
                cid = getattr(ev, 'camera_id', None)
                if cid:
                    ev.camera = cam_map.get(cid)
                buf.append(ev)
            _flush(Model, buf)

    _console(request.user.id, f"Session dupliquée : {new.name}")
    return JsonResponse({'success': True, 'id': str(new.id), 'name': new.name})


@login_required
@require_http_methods(["POST"])
def calibrate_homography(request, session_id):
    """
    Calibration de l'homographie sol par 4 coins d'un objet-sol normé (passage
    piéton). Reçoit les 4 coins cliqués (repère pixel de la caméra) + les
    dimensions réelles du passage → calcule les coords sol (repère navette) →
    homographie par DLT → l'enregistre dans camera.ground_homography (par session)
    + profile.geometry_enabled.

    Conçu pour être RÉUTILISÉ tel quel par une future auto-détection SAM3 : seule
    la source des 4 coins changerait (clics → détection), tout l'aval est partagé.
    """
    session = get_object_or_404(AnalysisSession, id=session_id, user=request.user)
    profile = session.profile
    if not profile:
        return JsonResponse({'error': "La session n'a pas de profil"}, status=400)
    try:
        data = json.loads(request.body or '{}')
        position = data['position']
        image_points = [[float(u), float(v)] for u, v in data['image_points']]
        crossing_width_m = float(data['crossing_width_m'])   # en travers (axe X)
        crossing_length_m = float(data['crossing_length_m'])  # le long (axe Y, proche→loin)
        near_distance_m = float(data.get('near_distance_m', 0.0))
        lateral_offset_m = float(data.get('lateral_offset_m', 0.0))
    except (KeyError, ValueError, TypeError) as e:
        return JsonResponse({'error': f'Paramètres invalides : {e}'}, status=400)
    if len(image_points) != 4:
        return JsonResponse(
            {'error': 'Il faut exactement 4 coins : proche-G, proche-D, loin-D, loin-G'},
            status=400)

    # Cœur partagé auto/manuel : coins ordonnés (clics dans l'ordre) → DLT + validation.
    import numpy as np
    from .utils.calibration import homography_from_quad
    res = homography_from_quad(
        image_points, crossing_width_m, crossing_length_m,
        near_distance_m=near_distance_m, lateral_offset_m=lateral_offset_m,
        reorder=False,   # les 4 clics sont déjà dans l'ordre proche-G/D, loin-D/G
    )
    if res is None:
        return JsonResponse(
            {'error': 'Homographie non résoluble (coins alignés / dégénérés)'}, status=400)
    H = np.asarray(res['H'])

    # Sanity : distance projetée du bas-centre de l'image (point sol le plus proche).
    cam = session.cameras.filter(position=position).first()
    if not cam:
        return JsonResponse({'error': f'Caméra « {position} » introuvable'}, status=400)
    sample = None
    if cam.width and cam.height:
        p = H @ np.array([cam.width / 2.0, cam.height - 1.0, 1.0])
        if abs(p[2]) > 1e-9:
            sample = {'pixel': [cam.width / 2.0, cam.height - 1.0],
                      'ground_xy': [round(float(p[0] / p[2]), 2), round(float(p[1] / p[2]), 2)]}

    # Stockage PAR CAMÉRA (par session) — plus sur le profil partagé (Phase 0).
    cam.ground_homography = {
        'homography': res['H'],
        'source': 'crossing_dlt',
        'rms_error_m': res['rms_error_m'],
        'crossing': {'width_m': crossing_width_m, 'length_m': crossing_length_m,
                     'near_distance_m': near_distance_m, 'lateral_offset_m': lateral_offset_m},
    }
    cam.save(update_fields=['ground_homography'])
    if not profile.geometry_enabled:
        profile.geometry_enabled = True
        profile.save(update_fields=['geometry_enabled'])
    _console(request.user.id,
             f"Calibration homographie « {position} » enregistrée (RMS {res['rms_error_m']} m)")
    return JsonResponse({'success': True, 'position': position, 'sample': sample,
                         'rms_error_m': res['rms_error_m']})


@login_required
@require_http_methods(["POST"])
def sam3_test_frame(request, session_id):
    """Lance un test SAM3 sur UNE frame (tâche gpu). Le front interroge sam3_test_result."""
    session = get_object_or_404(AnalysisSession, id=session_id, user=request.user)
    try:
        data = json.loads(request.body or '{}')
        position = data['position']
        frame_number = int(data['frame_number'])
        min_conf = float(data.get('min_confidence', 0.0))
        calibrate = bool(data.get('calibrate', False))
    except (KeyError, ValueError, TypeError) as e:
        return JsonResponse({'error': f'Paramètres invalides : {e}'}, status=400)
    from django.core.cache import cache
    cache.set(f"sam3_test_{session_id}", {'status': 'running'}, 600)
    from .tasks import sam3_test_frame_task
    sam3_test_frame_task.delay(str(session_id), position, frame_number, min_conf, calibrate)
    return JsonResponse({'success': True, 'status': 'running'})


@login_required
@require_http_methods(["GET"])
def sam3_test_result(request, session_id):
    """Résultat du dernier test SAM3 (cache) : {status: running|done|error|idle, ...}."""
    get_object_or_404(AnalysisSession, id=session_id, user=request.user)
    from django.core.cache import cache
    return JsonResponse(cache.get(f"sam3_test_{session_id}") or {'status': 'idle'})


# =============================================================================
# Camera management
# =============================================================================

@login_required
@require_http_methods(["POST"])
def upload_camera(request, session_id):
    """Upload a video file and assign it to a camera position."""
    session = get_object_or_404(AnalysisSession, id=session_id, user=request.user)
    user_id = request.user.id

    position = request.POST.get('position')
    video_file = request.FILES.get('video_file')

    if not position or position not in dict(CameraView.Position.choices):
        return JsonResponse({'success': False, 'error': 'Position invalide'}, status=400)

    if not video_file:
        return JsonResponse({'success': False, 'error': 'Aucun fichier vidéo'}, status=400)

    try:
        # Delete existing camera at this position if any
        existing = session.cameras.filter(position=position).first()
        if existing:
            if existing.video_file:
                existing.video_file.delete()
            existing.delete()

        # Create new camera view
        camera = CameraView.objects.create(
            session=session,
            position=position,
            video_file=video_file,
            label=os.path.splitext(video_file.name)[0],
        )

        # Re-encode to H.264 if needed (MPEG-4 Part 2 etc. not playable in browser)
        from wama.common.utils.video_compat import ensure_h264
        converted = ensure_h264(camera.video_file.path)
        if converted:
            _console(user_id, f"  Vidéo ré-encodée en H.264 pour compatibilité navigateur")
            # If the extension was promoted (e.g. .avi → .mp4), update the DB pointer
            if isinstance(converted, str) and converted != camera.video_file.path:
                new_rel = os.path.relpath(converted, settings.MEDIA_ROOT).replace('\\', '/')
                camera.video_file.name = new_rel
                camera.save(update_fields=['video_file'])

        # Extract metadata
        meta = _extract_video_metadata(camera.video_file.path)
        if meta:
            camera.duration = meta.get('duration')
            camera.fps = meta.get('fps')
            camera.width = meta.get('width')
            camera.height = meta.get('height')
            camera.save()

        _console(user_id, f"Caméra {camera.get_position_display()} : {video_file.name}")

        return JsonResponse({
            'success': True,
            'camera': {
                'id': camera.id,
                'position': camera.position,
                'label': camera.label,
                'video_url': f'/lab/cam-analyzer/api/cameras/{camera.id}/stream/',
                'filename': video_file.name,
                'duration': camera.duration,
                'fps': camera.fps,
                'width': camera.width,
                'height': camera.height,
                'time_offset': camera.time_offset,
            }
        })

    except Exception as e:
        logger.error(f"Error uploading camera: {e}", exc_info=True)
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@login_required
@require_http_methods(["POST", "DELETE"])
def delete_camera(request, camera_id):
    """Delete a camera from a session."""
    camera = get_object_or_404(CameraView, pk=camera_id, session__user=request.user)

    if camera.video_file:
        try:
            camera.video_file.delete()
        except Exception:
            pass

    camera.delete()
    return JsonResponse({'success': True})


@login_required
@require_http_methods(["POST"])
def update_camera_position(request, camera_id):
    """Update a camera's position (drag & drop reassignment)."""
    camera = get_object_or_404(CameraView, pk=camera_id, session__user=request.user)

    data = json.loads(request.body) if request.content_type == 'application/json' else request.POST
    new_position = data.get('position')

    if not new_position or new_position not in dict(CameraView.Position.choices):
        return JsonResponse({'success': False, 'error': 'Position invalide'}, status=400)

    # Swap if target position is occupied
    existing = CameraView.objects.filter(session=camera.session, position=new_position).first()
    if existing and existing.pk != camera.pk:
        old_position = camera.position
        existing.position = old_position
        existing.save()

    camera.position = new_position
    camera.save()

    return JsonResponse({'success': True})


# =============================================================================
# Analysis
# =============================================================================

@login_required
@require_http_methods(["POST"])
def start_analysis(request, session_id):
    """Start YOLO detection analysis for a session."""
    from .tasks import process_session_task

    session = get_object_or_404(AnalysisSession, id=session_id, user=request.user)
    user_id = request.user.id

    if session.cameras.count() == 0:
        return JsonResponse({'success': False, 'error': 'Aucune caméra assignée'}, status=400)

    if not session.profile:
        return JsonResponse({'success': False, 'error': 'Aucun profil d\'analyse sélectionné'}, status=400)

    if session.status in (AnalysisSession.Status.PROCESSING, AnalysisSession.Status.PENDING):
        return JsonResponse({'success': False, 'error': 'Analyse déjà en cours ou en attente'}, status=400)

    # Clear previous detection results if re-running
    DetectionFrame.objects.filter(camera__session=session).delete()

    session.status = AnalysisSession.Status.PENDING
    session.progress = 0.0
    session.error_message = ''
    session.results_summary = {}
    session.save()

    task = process_session_task.delay(str(session_id))
    cache.set(f"cam_analyzer_task_{session_id}", task.id, timeout=86400)
    _console(user_id, f"Analyse lancée pour la session : {session.name}")

    return JsonResponse({
        'success': True,
        'task_id': task.id,
    })


@login_required
@require_http_methods(["POST"])
def cancel_analysis(request, session_id):
    """Cancel a running analysis."""
    from .tasks import stop_cam_analyzer

    session = get_object_or_404(AnalysisSession, id=session_id, user=request.user)
    user_id = request.user.id

    if session.status not in (AnalysisSession.Status.PROCESSING, AnalysisSession.Status.PENDING):
        return JsonResponse({'success': False, 'error': 'Aucune analyse en cours'})

    _console(user_id, f"Annulation demandée pour la session : {session.name}")

    # Set cache flag (cooperative cancellation, checked every 100 frames)
    stop_cam_analyzer(user_id)

    # Force-revoke the running task — sends SIGTERM if YOLO is stuck
    task_id = cache.get(f"cam_analyzer_task_{session_id}")
    if task_id:
        try:
            from celery import current_app
            current_app.control.revoke(task_id, terminate=True, signal='SIGTERM')
            _console(user_id, f"Révocation forcée du task {task_id[:8]}...")
        except Exception as e:
            logger.warning(f"Failed to revoke task {task_id}: {e}")
        cache.delete(f"cam_analyzer_task_{session_id}")

    # Proposition C — Cancel maps to PAUSED, not FAILED, so partial data
    # (DetectionFrames already committed) remains usable. The user can
    # restart and the skip-if-done logic in process_session_task preserves
    # what was done.
    if session.status == AnalysisSession.Status.PENDING:
        session.status = AnalysisSession.Status.PAUSED
        session.error_message = "Annulé par l'utilisateur"
        session.progress = 0
        session.save()
        return JsonResponse({'success': True, 'message': 'Analyse annulée', 'immediate': True})

    session.status = AnalysisSession.Status.PAUSED
    session.error_message = "Annulé par l'utilisateur (données partielles conservées)"
    session.save(update_fields=['status', 'error_message'])

    return JsonResponse({'success': True, 'message': 'Annulation envoyée — données partielles conservées'})


@login_required
@require_http_methods(["GET"])
def list_passes(request, session_id):
    """
    Pipeline status: list of every AnalysisPass for this session, with
    stale/missing detection computed on the fly so the UI badge is fresh.
    """
    session = get_object_or_404(AnalysisSession, id=session_id, user=request.user)
    from .utils.pass_tracking import recompute_stale, get_passes_status
    try:
        recompute_stale(session)
    except Exception as exc:
        logger.warning(f"recompute_stale failed: {exc}")
    return JsonResponse({'passes': get_passes_status(session)})


@login_required
@require_http_methods(["POST"])
def run_passes(request, session_id):
    """
    Orchestrator: dispatch the right Celery tasks for the requested
    pass types. Body: {"types": [...], "force": bool}. When ``types`` is
    empty or omitted, runs every missing-or-stale pass.
    """
    session = get_object_or_404(AnalysisSession, id=session_id, user=request.user)
    if not session.profile:
        return JsonResponse({'success': False, 'error': 'Aucun profil assigné'}, status=400)

    try:
        body = json.loads(request.body) if request.content_type == 'application/json' else {}
    except Exception:
        body = {}
    requested = list(body.get('types') or [])
    force = bool(body.get('force', False))

    from .utils.pass_tracking import recompute_stale, get_passes_status
    recompute_stale(session)
    statuses = get_passes_status(session)

    needs_run = set()
    if force and requested:
        needs_run.update(requested)
    elif force:
        needs_run.update(s['pass_type'] for s in statuses)
    elif requested:
        needs_run.update(requested)
    else:
        # default: all missing or stale or failed
        for s in statuses:
            if s['status'] in ('never', 'stale', 'failed'):
                needs_run.add(s['pass_type'])

    # Dispatch matrix : a request can mix derived computers + full passes.
    # Order matters — heavy passes (process_session_task) before light ones.
    launched = []

    # 1. Windows recompute (synchronous, cheapest)
    if 'intersection_windows' in needs_run:
        from .utils.window_recompute import recompute_intersection_windows
        recompute_intersection_windows(session, session.profile)
        launched.append('intersection_windows')
        needs_run.discard('intersection_windows')

    # 2. Heavy pass : YOLO / YOLOPv2 require process_session_task.
    #    This task internally calls lane_events for the front camera, so
    #    if lane_events is the only "downstream" needed and YOLO is also
    #    being requested, we don't need a separate compute_lane_events_task.
    heavy_needed = needs_run & {'yolo_detect', 'yolopv2_lanes'}
    if heavy_needed:
        from .tasks import process_session_task
        # N'enchaîner SAM3 (post-pass GPU lourd) QUE s'il a été explicitement demandé.
        # Sinon lancer « ▶ yolopv2 » relançait SAM3 à tort (→ charge GPU / crash).
        _chain_sam3 = 'sam3_markings' in needs_run
        # Une relance EXPLICITE de yolo/yolopv2 = l'utilisateur veut la RE-exécuter →
        # forcer. Sinon le STALE la considère « déjà faite » (des frames existent) et la
        # skip, exécutant seulement les étapes aval (« segments temporels ») — la relance
        # semblait sans effet. Ré-exécute toute la détection (yolo+yolopv2, toutes vues).
        _explicit_heavy = bool(heavy_needed & set(requested))
        _force_detection = force or _explicit_heavy
        cache.delete(f"stop_cam_analyzer_{request.user.id}")
        session.status = AnalysisSession.Status.PENDING
        session.progress = 0
        session.save(update_fields=['status', 'progress'])
        task = process_session_task.delay(str(session.id), force_rerun=_force_detection,
                                          chain_sam3=_chain_sam3)
        cache.set(f"cam_analyzer_task_{session.id}", task.id, timeout=86400)
        launched.append('process_session_task')
        # process_session_task takes care of these downstream passes
        needs_run -= {'yolo_detect', 'yolopv2_lanes', 'lane_events', 'distance'}
        # SAM3 is chained at the end of process_session_task when enabled,
        # so we don't dispatch analyze_sam3_only_task here.
        needs_run.discard('sam3_markings')
        # temporal_segments + conflicts are also chained in process_session_task
        needs_run -= {'temporal_segments', 'conflicts'}

    # 3. Decoupled computers (Proposition D) — light tasks, no GPU loading
    elif needs_run:
        from .tasks import (
            compute_lane_events_task,
            compute_distance_task,
            compute_global_tracking_task,
            compute_temporal_segments_task,
            compute_conflict_events_task,
            analyze_sam3_only_task,
        )
        cache.delete(f"stop_cam_analyzer_{request.user.id}")

        dispatch_map = {
            'lane_events':       compute_lane_events_task,
            'distance':          compute_distance_task,
            'global_tracking':   compute_global_tracking_task,
            'temporal_segments': compute_temporal_segments_task,
            'conflicts':         compute_conflict_events_task,
            'sam3_markings':     analyze_sam3_only_task,
        }
        for pt in list(needs_run):
            task_fn = dispatch_map.get(pt)
            if task_fn is None:
                continue
            task = task_fn.delay(str(session.id))
            cache.set(f"cam_analyzer_task_{session.id}", task.id, timeout=86400)
            launched.append(task_fn.__name__)
            needs_run.discard(pt)

    return JsonResponse({
        'success': True,
        'launched': launched,
        'requested': sorted({s for s in needs_run} | {l for l in launched}),
        'force': force,
    })


@login_required
@require_http_methods(["POST"])
def complete_analysis(request, session_id):
    """Complétion d'analyse (étape 2 analyse incrémentale) : analyse UNIQUEMENT les
    tranches du scope demandé absentes du registre de couverture. Body :
    {"scope": "full" | "windows"}. Ne wipe rien ; les coutures se réparent au prochain
    « Calculer les indicateurs » (tracking 360°)."""
    session = get_object_or_404(AnalysisSession, id=session_id, user=request.user)
    if not session.profile:
        return JsonResponse({'success': False, 'error': 'Aucun profil assigné'}, status=400)
    try:
        scope = (json.loads(request.body or '{}').get('scope') or 'full')
    except ValueError:
        scope = 'full'
    if scope not in ('full', 'windows'):
        return JsonResponse({'success': False, 'error': f'scope invalide: {scope}'}, status=400)
    if scope == 'windows' and not session.intersection_windows:
        return JsonResponse({'success': False,
                             'error': 'Aucune fenêtre d\'intersection sur cette session'}, status=400)
    from .tasks import process_session_task
    cache.delete(f"stop_cam_analyzer_{request.user.id}")
    session.status = AnalysisSession.Status.PENDING
    session.progress = 0
    session.save(update_fields=['status', 'progress'])
    task = process_session_task.delay(str(session.id), force_rerun=False,
                                      chain_sam3=False, completion_scope=scope)
    cache.set(f"cam_analyzer_task_{session.id}", task.id, timeout=86400)
    return JsonResponse({'success': True, 'scope': scope, 'task_id': task.id})


@login_required
@require_http_methods(["POST"])
def live_cursor(request, session_id):
    """Curseur du mode « analyse au fil de la lecture » (étape 3). Body :
    {"t": secondes_video, "enabled": bool, "lookahead": s}. Pose le curseur en cache et
    démarre `live_analysis_task` si aucune instance ne tourne (verrou). enabled=false
    efface le curseur (la tâche s'éteint d'elle-même après inactivité)."""
    session = get_object_or_404(AnalysisSession, id=session_id, user=request.user)
    if not session.profile:
        return JsonResponse({'success': False, 'error': 'Aucun profil assigné'}, status=400)
    try:
        body = json.loads(request.body or '{}')
    except ValueError:
        body = {}
    cursor_key = f"cam_live_cursor_{session_id}"
    lock_key = f"cam_live_lock_{session_id}"
    if not body.get('enabled', True):
        cache.delete(cursor_key)
        # Arrêt EXPLICITE : la tâche sort immédiatement (au lieu d'attendre le délai
        # d'inactivité) et enchaîne le tracking global si elle a produit.
        if cache.get(lock_key):
            cache.set(f"cam_live_stop_{session_id}", 1, timeout=120)
        return JsonResponse({'success': True, 'running': bool(cache.get(lock_key))})
    try:
        t = max(0.0, float(body.get('t', 0.0)))
        lookahead = float(body.get('lookahead', 15.0))
    except (TypeError, ValueError):
        return JsonResponse({'success': False, 'error': 't invalide'}, status=400)
    cache.set(cursor_key, {'t': t, 'lookahead': lookahead}, timeout=120)
    started = False
    if not cache.get(lock_key):
        from .tasks import live_analysis_task
        live_analysis_task.delay(str(session.id))
        started = True
    return JsonResponse({'success': True, 'running': True, 'started': started})


@login_required
@require_http_methods(["POST"])
def recompute_windows(request, session_id):
    """
    Pass A — recompute session.intersection_windows from the current profile
    + GPS track. No GPU, runs synchronously (~ms). Triggered manually from
    the right panel; also called automatically by save_profile.
    """
    session = get_object_or_404(AnalysisSession, id=session_id, user=request.user)
    if not session.profile:
        return JsonResponse({'success': False, 'error': 'Aucun profil assigné'}, status=400)

    from .utils.window_recompute import recompute_intersection_windows
    try:
        windows = recompute_intersection_windows(session, session.profile)
    except Exception as exc:
        logger.error(f"recompute_windows failed for session {session_id}: {exc}", exc_info=True)
        return JsonResponse({'success': False, 'error': str(exc)}, status=500)

    return JsonResponse({
        'success': True,
        'count': len(windows),
        'intersection_windows': windows,
    })


@login_required
@require_http_methods(["POST"])
def start_sam3_only(request, session_id):
    """
    Pass C — re-run SAM3 markings on the front camera, in-window only,
    without re-running YOLO. Reuses existing extracted MP4 + current
    session.intersection_windows. Patches DetectionFrame.detections in
    place: drops old SAM3/road_mask entries, appends fresh ones.
    """
    from .tasks import analyze_sam3_only_task

    session = get_object_or_404(AnalysisSession, id=session_id, user=request.user)
    user_id = request.user.id

    if not session.profile:
        return JsonResponse({'success': False, 'error': 'Aucun profil assigné'}, status=400)
    if not session.profile.sam3_markings_enabled:
        return JsonResponse({'success': False, 'error': 'SAM3 désactivé sur ce profil'}, status=400)
    if session.status == AnalysisSession.Status.PROCESSING:
        return JsonResponse({'success': False, 'error': 'Une analyse est déjà en cours'}, status=400)
    if not session.cameras.filter(position='front').exists():
        return JsonResponse({'success': False, 'error': 'Caméra avant introuvable'}, status=400)

    cache.delete(f"stop_cam_analyzer_{user_id}")
    task = analyze_sam3_only_task.delay(str(session.id))
    cache.set(f"cam_analyzer_task_{session_id}", task.id, timeout=86400)
    _console(user_id, f"SAM3 seul — lancement pour la session : {session.name}")

    return JsonResponse({'success': True, 'task_id': task.id})


@login_required
@require_http_methods(["GET"])
def get_session_status(request, session_id):
    """Get session status and progress."""
    from django.core.cache import cache

    session = get_object_or_404(AnalysisSession, id=session_id, user=request.user)

    # Detect lost tasks: PENDING for > 300s without extraction activity = task dropped
    if session.status == AnalysisSession.Status.PENDING and session.updated_at:
        elapsed = (timezone.now() - session.updated_at).total_seconds()
        # Also check RTMaps extraction cache — if active, the task is running
        extract_active = bool(cache.get(f"cam_analyzer_extract_{session_id}"))
        if elapsed > 300 and not extract_active:
            session.status = AnalysisSession.Status.FAILED
            session.error_message = (
                "La tâche n'a pas été prise en charge par le worker. "
                "Vérifiez que le worker GPU Celery est démarré et relancez l'analyse."
            )
            session.save()

    # Get real-time progress from cache if processing/pending
    progress = session.progress
    status_message = None
    if session.status in (AnalysisSession.Status.PROCESSING, AnalysisSession.Status.PENDING):
        cached_progress = cache.get(f"cam_analyzer_progress_{session_id}")
        if cached_progress is not None:
            progress = cached_progress
        status_message = cache.get(f"cam_analyzer_status_{session_id}")

    return JsonResponse({
        'id': str(session.id),
        'status': session.status,
        'progress': progress,
        'status_message': status_message,
        'error_message': session.error_message,
        'results_summary': session.results_summary,
        'intersection_windows': session.intersection_windows,
    })


@login_required
@require_http_methods(["GET"])
def get_detections(request, session_id, camera_id):
    """Get detection frames for a camera (for canvas overlay)."""
    session = get_object_or_404(AnalysisSession, id=session_id, user=request.user)
    camera = get_object_or_404(CameraView, pk=camera_id, session=session)

    start_frame = int(request.GET.get('start', 0))
    end_frame = int(request.GET.get('end', 100000))

    frames = DetectionFrame.objects.filter(
        camera=camera,
        frame_number__gte=start_frame,
        frame_number__lt=end_frame,
    ).order_by('frame_number').values('frame_number', 'timestamp', 'detections')

    return JsonResponse({
        'camera_id': camera_id,
        'position': camera.position,
        'fps': camera.fps,
        'width': camera.width,
        'height': camera.height,
        'frames': list(frames),
    })


# =============================================================================
# Profiles
# =============================================================================

@login_required
@require_http_methods(["GET"])
def list_profiles(request):
    """List analysis profiles."""
    profiles = AnalysisProfile.objects.filter(user=request.user)

    data = [{
        'id': p.id,
        'name': p.name,
        'report_type': p.report_type,
        'intersections': p.intersections,
        'road_model_path': p.road_model_path,
        'sam3_markings_enabled': p.sam3_markings_enabled,
        'sam3_markings_prompts': p.sam3_markings_prompts,
        'sam3_as_road_fallback': p.sam3_as_road_fallback,
        'restrict_to_intersection_windows': p.restrict_to_intersection_windows,
        'analyzed_positions': p.analyzed_positions or ['front', 'rear'],
        'model_path': p.model_path,
        'task_type': p.task_type,
        'target_classes': p.target_classes,
        'confidence': p.confidence,
        'iou_threshold': p.iou_threshold,
        'tracker': p.tracker,
    } for p in profiles]

    return JsonResponse({'profiles': data})


@login_required
@require_http_methods(["POST"])
def save_profile(request):
    """Create or update an analysis profile."""
    try:
        data = json.loads(request.body) if request.content_type == 'application/json' else request.POST

        profile_id = data.get('id')
        name = data.get('name', '').strip()
        report_type = data.get('report_type', 'proximity_overtaking')
        intersections = data.get('intersections', [])
        road_model_path = data.get('road_model_path', '').strip()
        sam3_markings_enabled = bool(data.get('sam3_markings_enabled', False))
        sam3_markings_prompts = data.get('sam3_markings_prompts', [])
        sam3_as_road_fallback = bool(data.get('sam3_as_road_fallback', False))
        # Master switch: if SAM3 markings is off, force the fallback off too —
        # otherwise its checkbox stays hidden but its value persists, silently
        # triggering SAM3 loading on the next analysis.
        if not sam3_markings_enabled:
            sam3_as_road_fallback = False
        restrict_to_intersection_windows = bool(data.get('restrict_to_intersection_windows', True))
        yolopv2_all_views = bool(data.get('yolopv2_all_views', False))
        # Validate analyzed_positions against allowed positions; fall back to
        # front+rear if the payload is missing or empty.
        valid_positions = ['front', 'rear', 'left', 'right']
        analyzed_positions = data.get('analyzed_positions') or []
        if isinstance(analyzed_positions, str):
            analyzed_positions = json.loads(analyzed_positions)
        analyzed_positions = [p for p in analyzed_positions if p in valid_positions]
        if not analyzed_positions:
            analyzed_positions = ['front', 'rear']
        model_path = data.get('model_path', '')
        task_type = data.get('task_type', 'detect')
        target_classes = data.get('target_classes', [])
        confidence = float(data.get('confidence', 0.25))
        iou_threshold = float(data.get('iou_threshold', 0.45))
        tracker = data.get('tracker', 'botsort')

        if not name:
            return JsonResponse({'success': False, 'error': 'Nom requis'}, status=400)
        if not model_path:
            return JsonResponse({'success': False, 'error': 'Modèle requis'}, status=400)

        valid_report_types = [r[0] for r in AnalysisProfile.REPORT_TYPE_CHOICES]
        if report_type not in valid_report_types:
            report_type = 'proximity_overtaking'

        if isinstance(target_classes, str):
            target_classes = json.loads(target_classes)
        if isinstance(intersections, str):
            intersections = json.loads(intersections)
        if isinstance(sam3_markings_prompts, str):
            sam3_markings_prompts = json.loads(sam3_markings_prompts)

        if profile_id:
            profile = get_object_or_404(AnalysisProfile, pk=profile_id, user=request.user)
            profile.name = name
            profile.report_type = report_type
            profile.intersections = intersections
            profile.road_model_path = road_model_path
            profile.sam3_markings_enabled = sam3_markings_enabled
            profile.sam3_markings_prompts = sam3_markings_prompts
            profile.sam3_as_road_fallback = sam3_as_road_fallback
            profile.restrict_to_intersection_windows = restrict_to_intersection_windows
            profile.yolopv2_all_views = yolopv2_all_views
            profile.analyzed_positions = analyzed_positions
            profile.model_path = model_path
            profile.task_type = task_type
            profile.target_classes = target_classes
            profile.confidence = confidence
            profile.iou_threshold = iou_threshold
            profile.tracker = tracker
            profile.save()
        else:
            profile = AnalysisProfile.objects.create(
                user=request.user,
                name=name,
                report_type=report_type,
                intersections=intersections,
                road_model_path=road_model_path,
                sam3_markings_enabled=sam3_markings_enabled,
                sam3_markings_prompts=sam3_markings_prompts,
                sam3_as_road_fallback=sam3_as_road_fallback,
                restrict_to_intersection_windows=restrict_to_intersection_windows,
                yolopv2_all_views=yolopv2_all_views,
                analyzed_positions=analyzed_positions,
                model_path=model_path,
                task_type=task_type,
                target_classes=target_classes,
                confidence=confidence,
                iou_threshold=iou_threshold,
                tracker=tracker,
            )

        # Auto-recompute intersection_windows for sessions using this profile
        # — light-weight, no GPU. Keeps mini-map circles + YOLO/SAM3 gating
        # aligned with the just-edited radii / centres.
        recomputed_session_ids = []
        try:
            from .utils.window_recompute import recompute_intersection_windows
            from .utils.pass_tracking import recompute_stale
            for s in profile.sessions.filter(user=request.user):
                if s.gps_track:
                    recompute_intersection_windows(s, profile)
                    recomputed_session_ids.append(str(s.id))
                # Watched parameters changed → re-evaluate stale flags so the
                # UI pipeline panel reflects the impact of this save.
                try:
                    recompute_stale(s)
                except Exception:
                    pass
        except Exception as exc:
            logger.warning(f"recompute_intersection_windows failed for profile {profile.id}: {exc}")

        return JsonResponse({
            'success': True,
            'recomputed_sessions': recomputed_session_ids,
            'profile': {
                'id': profile.id,
                'name': profile.name,
                'report_type': profile.report_type,
                'intersections': profile.intersections,
                'road_model_path': profile.road_model_path,
                'sam3_markings_enabled': profile.sam3_markings_enabled,
                'sam3_markings_prompts': profile.sam3_markings_prompts,
                'sam3_as_road_fallback': profile.sam3_as_road_fallback,
                'restrict_to_intersection_windows': profile.restrict_to_intersection_windows,
                'analyzed_positions': profile.analyzed_positions or ['front', 'rear'],
                'model_path': profile.model_path,
                'task_type': profile.task_type,
                'target_classes': profile.target_classes,
                'confidence': profile.confidence,
                'iou_threshold': profile.iou_threshold,
                'tracker': profile.tracker,
            }
        })

    except Exception as e:
        logger.error(f"Error saving profile: {e}", exc_info=True)
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@login_required
@require_http_methods(["POST"])
def download_road_model(request):
    """
    Auto-download keremberke/yolov8m-bdd100k-seg/best.pt into the segment dir
    so the model dropdown picks it up. Returns the relative path the user
    should set on their profile.
    """
    from .utils.road_model_downloader import ensure_bdd100k_seg, ROAD_MODELS_DIR, BDD100K_SEG_LOCAL_NAME

    force = bool(request.GET.get('force') or request.POST.get('force'))
    ok, abs_path, msg = ensure_bdd100k_seg(force=force)
    if not ok:
        return JsonResponse({'success': False, 'error': msg}, status=500)

    rel = os.path.relpath(abs_path, settings.BASE_DIR).replace('\\', '/')
    return JsonResponse({
        'success': True,
        'message': msg,
        'path': rel,
        'name': BDD100K_SEG_LOCAL_NAME,
    })


@login_required
@require_http_methods(["POST", "DELETE"])
def delete_profile(request, profile_id):
    """Delete an analysis profile."""
    profile = get_object_or_404(AnalysisProfile, pk=profile_id, user=request.user)
    profile.delete()
    return JsonResponse({'success': True})


# =============================================================================
# Console
# =============================================================================

@login_required
@require_http_methods(["POST"])
def upload_rtmaps(request, session_id):
    """
    Upload a RTMaps .rec file (+ optional API CSV) and launch extraction.
    The extraction task will parse the .rec, crop the quadrature video into
    front/rear views, extract GPS data, and finally trigger the YOLO analysis.
    """
    from .tasks import extract_rtmaps_task

    session = get_object_or_404(AnalysisSession, id=session_id, user=request.user)
    user_id = request.user.id

    rec_file = request.FILES.get('rec_file')
    csv_file = request.FILES.get('csv_file')

    if not rec_file:
        return JsonResponse({'success': False, 'error': 'Fichier .rec manquant'}, status=400)

    if not session.profile:
        return JsonResponse({'success': False, 'error': "Aucun profil d'analyse sélectionné"}, status=400)

    # Block if YOLO analysis is already running
    if session.status in (AnalysisSession.Status.PROCESSING, AnalysisSession.Status.PENDING):
        return JsonResponse(
            {'success': False, 'error': "Une analyse est déjà en cours sur cette session. Annulez-la avant de lancer l'extraction RTMaps."},
            status=400,
        )

    # Save uploaded files (under input/rtmaps/ to keep all source data under input/)
    rtmaps_dir = os.path.join(settings.MEDIA_ROOT, 'cam_analyzer', str(user_id), 'input', 'rtmaps')
    os.makedirs(rtmaps_dir, exist_ok=True)

    rec_filename = get_unique_filename(rtmaps_dir, rec_file.name)
    rec_path = os.path.join(rtmaps_dir, rec_filename)
    with open(rec_path, 'wb') as f:
        for chunk in rec_file.chunks():
            f.write(chunk)

    csv_path = None
    if csv_file:
        csv_filename = get_unique_filename(rtmaps_dir, csv_file.name)
        csv_path = os.path.join(rtmaps_dir, csv_filename)
        with open(csv_path, 'wb') as f:
            for chunk in csv_file.chunks():
                f.write(chunk)

    # Reset session state
    session.status = AnalysisSession.Status.PENDING
    session.progress = 0.0
    session.error_message = ''
    session.results_summary = {}
    session.save(update_fields=['status', 'progress', 'error_message', 'results_summary'])

    task = extract_rtmaps_task.delay(str(session_id), rec_path, csv_path)
    _console(user_id, f"Extraction RTMaps lancée : {rec_file.name}")

    return JsonResponse({'success': True, 'task_id': task.id})


@login_required
@require_http_methods(["POST"])
def upload_quadrature_avi(request, session_id):
    """
    Import a pre-exported RTMaps quadrature AVI (800×500) + optional GPS CSV.
    Launches extract_rtmaps_task in AVI mode (skips binary .rec extraction).
    """
    from .tasks import extract_rtmaps_task

    session = get_object_or_404(AnalysisSession, id=session_id, user=request.user)
    user_id = request.user.id

    avi_file = request.FILES.get('avi_file')
    gps_csv_file = request.FILES.get('gps_csv_file')

    if not avi_file:
        return JsonResponse({'success': False, 'error': 'Fichier AVI manquant'}, status=400)

    if not session.profile:
        return JsonResponse({'success': False, 'error': "Aucun profil d'analyse sélectionné"}, status=400)

    if session.status in (AnalysisSession.Status.PROCESSING, AnalysisSession.Status.PENDING):
        return JsonResponse(
            {'success': False, 'error': "Une analyse est déjà en cours. Annulez-la d'abord."},
            status=400,
        )

    rtmaps_dir = os.path.join(settings.MEDIA_ROOT, 'cam_analyzer', str(user_id), 'input', 'rtmaps')
    os.makedirs(rtmaps_dir, exist_ok=True)

    avi_filename = get_unique_filename(rtmaps_dir, avi_file.name)
    avi_path = os.path.join(rtmaps_dir, avi_filename)
    with open(avi_path, 'wb') as f:
        for chunk in avi_file.chunks():
            f.write(chunk)

    gps_csv_path = None
    if gps_csv_file:
        csv_filename = get_unique_filename(rtmaps_dir, gps_csv_file.name)
        gps_csv_path = os.path.join(rtmaps_dir, csv_filename)
        with open(gps_csv_path, 'wb') as f:
            for chunk in gps_csv_file.chunks():
                f.write(chunk)

    session.status = AnalysisSession.Status.PENDING
    session.progress = 0.0
    session.error_message = ''
    session.results_summary = {}
    session.save(update_fields=['status', 'progress', 'error_message', 'results_summary'])

    task = extract_rtmaps_task.delay(
        str(session_id),
        rec_path=None,
        csv_path=gps_csv_path,
        quad_avi_path=avi_path,
    )
    _console(user_id, f"Import quadrature AVI lancé : {avi_file.name}")

    return JsonResponse({'success': True, 'task_id': task.id})


@login_required
@require_http_methods(["GET"])
def rtmaps_status(request, session_id):
    """Return extraction progress for a RTMaps session."""
    session = get_object_or_404(AnalysisSession, id=session_id, user=request.user)
    cached = cache.get(f"cam_analyzer_extract_{session_id}") or {}
    return JsonResponse({
        'session_status': session.status,
        'progress': cached.get('progress', 0),
        'status_message': cached.get('status', ''),
    })


@login_required
@require_http_methods(["GET"])
def console_content(request):
    """Get console output for the current user."""
    console_lines = get_console_lines(request.user.id, limit=100)
    return JsonResponse({'output': console_lines})


# =============================================================================
# Export & Analytics (Phase 3)
# =============================================================================

@login_required
@require_http_methods(["GET"])
def export_detections_csv(request, session_id):
    """
    Export all detections as CSV — extended with Phase 2 (lane attribution)
    and Phase 4 (distance/speed/TTC) fields. Filters at read time using the
    profile's target_classes + confidence so the CSV reflects the user's
    current settings without requiring re-inference.
    """
    session = get_object_or_404(AnalysisSession, id=session_id, user=request.user)

    profile = session.profile
    target_set = None
    min_conf = 0.0
    if profile:
        # COCO names → user's target classes (typically int ids on the profile)
        if profile.target_classes:
            tc = profile.target_classes
            if tc and isinstance(tc[0], int):
                target_set = set(tc)
            else:
                target_set = {str(c).lower() for c in tc}
        min_conf = float(profile.confidence or 0)

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow([
        'camera', 'frame', 'timestamp', 'type',
        'class_name', 'class_id', 'confidence', 'track_id',
        'bbox_x1', 'bbox_y1', 'bbox_x2', 'bbox_y2',
        'proximity', 'lane_id', 'in_shuttle_lane',
        'distance_m', 'relative_speed_kmh', 'ttc_s',
    ])

    for camera in session.cameras.all():
        for df in DetectionFrame.objects.filter(camera=camera).order_by('frame_number'):
            for det in df.detections or []:
                # Filtrage cohérent storage 0.10 → user threshold
                conf = det.get('confidence')
                if conf is not None and conf < min_conf:
                    continue
                if target_set is not None and det.get('type') not in ('road_mask', 'sam3_marking'):
                    cid = det.get('class_id')
                    cname = (det.get('class_name') or '').lower()
                    if not (cid in target_set or cname in target_set):
                        continue
                bbox = det.get('bbox', ['', '', '', ''])
                if len(bbox) < 4:
                    bbox = ['', '', '', '']
                writer.writerow([
                    camera.position, df.frame_number, df.timestamp,
                    det.get('type', 'object'),
                    det.get('class_name', ''), det.get('class_id', ''),
                    det.get('confidence', ''), det.get('track_id', ''),
                    *bbox,
                    det.get('proximity', ''),
                    det.get('lane_id', ''), det.get('in_shuttle_lane', ''),
                    det.get('distance_m', ''),
                    det.get('relative_speed_kmh', ''),
                    det.get('ttc_s', ''),
                ])

    return FileResponse(
        io.BytesIO(buffer.getvalue().encode('utf-8')),
        as_attachment=True,
        filename=f"{session.name or 'session'}_detections.csv",
        content_type='text/csv; charset=utf-8',
    )


@login_required
@require_http_methods(["GET"])
def export_session_json(request, session_id):
    """Export full session data as JSON."""
    session = get_object_or_404(AnalysisSession, id=session_id, user=request.user)

    cameras_data = []
    for c in session.cameras.all():
        cameras_data.append({
            'position': c.position,
            'label': c.label,
            'duration': c.duration,
            'fps': c.fps,
            'width': c.width,
            'height': c.height,
        })

    profile_data = None
    if session.profile:
        p = session.profile
        profile_data = {
            'name': p.name,
            'model_path': p.model_path,
            'task_type': p.task_type,
            'target_classes': p.target_classes,
            'confidence': p.confidence,
            'iou_threshold': p.iou_threshold,
            'tracker': p.tracker,
        }

    segments_data = []
    for seg in TemporalSegment.objects.filter(session=session):
        segments_data.append({
            'type': seg.segment_type,
            'type_display': seg.get_segment_type_display(),
            'camera': seg.camera.position if seg.camera else None,
            'start_time': seg.start_time,
            'end_time': seg.end_time,
            'duration': round(seg.end_time - seg.start_time, 2),
            'metadata': seg.metadata,
        })

    # Phase 3 — lane events (already persisted by the YOLO pass)
    from .models import LaneEvent, ConflictEvent
    lane_events_data = [
        {
            'camera': le.camera.position,
            'track_id': le.track_id,
            'class_name': le.class_name,
            'lane_id': le.lane_id,
            'in_shuttle_lane': le.in_shuttle_lane,
            't_enter': le.t_enter,
            't_exit': le.t_exit,
            'intersection_window_idx': le.intersection_window_idx,
        }
        for le in LaneEvent.objects.filter(camera__session=session).select_related('camera')
    ]

    # Phase 5 — conflict events
    conflicts_data = [
        {
            'camera': c.camera.position,
            'track_id': c.track_id,
            'class_name': c.class_name,
            'intersection_window_idx': c.intersection_window_idx,
            'conflict_type': c.conflict_type,
            'navette_passed_first': c.navette_passed_first,
            'delta_t_s': c.delta_t_s,
            'min_distance_m': c.min_distance_m,
            'min_ttc_s': c.min_ttc_s,
            't_start': c.t_start,
            't_end': c.t_end,
            'severity': c.severity,
        }
        for c in ConflictEvent.objects.filter(session=session).select_related('camera')
    ]

    data = {
        'session': {
            'id': str(session.id),
            'name': session.name,
            'status': session.status,
            'created_at': session.created_at.isoformat(),
            'completed_at': session.completed_at.isoformat() if session.completed_at else None,
        },
        'profile': profile_data,
        'cameras': cameras_data,
        'results_summary': session.results_summary,
        'intersection_windows': session.intersection_windows or [],
        'segments': segments_data,
        'lane_events': lane_events_data,
        'conflict_events': conflicts_data,
    }

    content = json.dumps(data, indent=2, ensure_ascii=False).encode('utf-8')
    return FileResponse(
        io.BytesIO(content),
        as_attachment=True,
        filename=f"{session.name or 'session'}_report.json",
        content_type='application/json; charset=utf-8',
    )


@login_required
@require_http_methods(["GET"])
def export_conflicts_csv(request, session_id):
    """
    Phase 6 — export ConflictEvent rows as CSV. One row per (track_id ×
    intersection_window) conflict, with severity, delta_t and min values.
    Sortable by severity then t_start so the user reads critical events first.
    """
    session = get_object_or_404(AnalysisSession, id=session_id, user=request.user)

    from .models import ConflictEvent
    severity_order = {'critical': 0, 'warn': 1, 'info': 2}

    rows = list(
        ConflictEvent.objects.filter(session=session).select_related('camera')
    )
    rows.sort(key=lambda r: (severity_order.get(r.severity, 3), r.t_start))

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow([
        'severity', 'camera', 'track_id', 'class_name',
        'intersection_window_idx', 'intersection_name',
        'conflict_type', 'navette_passed_first', 'delta_t_s',
        'min_distance_m', 'min_ttc_s', 't_start', 't_end',
    ])
    windows = session.intersection_windows or []
    for c in rows:
        wname = ''
        if 0 <= c.intersection_window_idx < len(windows):
            wname = windows[c.intersection_window_idx].get('name', '')
        writer.writerow([
            c.severity, c.camera.position, c.track_id, c.class_name,
            c.intersection_window_idx, wname,
            c.conflict_type,
            '' if c.navette_passed_first is None else int(c.navette_passed_first),
            c.delta_t_s if c.delta_t_s is not None else '',
            c.min_distance_m if c.min_distance_m is not None else '',
            c.min_ttc_s if c.min_ttc_s is not None else '',
            c.t_start, c.t_end,
        ])

    return FileResponse(
        io.BytesIO(buffer.getvalue().encode('utf-8')),
        as_attachment=True,
        filename=f"{session.name or 'session'}_conflicts.csv",
        content_type='text/csv; charset=utf-8',
    )


@login_required
@require_http_methods(["GET"])
def export_segments_csv(request, session_id):
    """Export temporal segments as CSV."""
    session = get_object_or_404(AnalysisSession, id=session_id, user=request.user)

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(['type', 'type_display', 'camera', 'start_time', 'end_time', 'duration', 'metadata'])

    for seg in TemporalSegment.objects.filter(session=session):
        writer.writerow([
            seg.segment_type,
            seg.get_segment_type_display(),
            seg.camera.position if seg.camera else '',
            seg.start_time,
            seg.end_time,
            round(seg.end_time - seg.start_time, 2),
            json.dumps(seg.metadata, ensure_ascii=False),
        ])

    return FileResponse(
        io.BytesIO(buffer.getvalue().encode('utf-8')),
        as_attachment=True,
        filename=f"{session.name or 'session'}_segments.csv",
        content_type='text/csv; charset=utf-8',
    )


@login_required
@require_http_methods(["GET"])
def get_segments(request, session_id):
    """Get temporal segments for a session."""
    session = get_object_or_404(AnalysisSession, id=session_id, user=request.user)

    segments = []
    for seg in TemporalSegment.objects.filter(session=session).select_related('camera'):
        segments.append({
            'id': seg.id,
            'type': seg.segment_type,
            'type_display': seg.get_segment_type_display(),
            'camera_position': seg.camera.position if seg.camera else None,
            'start_time': seg.start_time,
            'end_time': seg.end_time,
            'duration': round(seg.end_time - seg.start_time, 2),
            'metadata': seg.metadata,
        })

    return JsonResponse({'segments': segments})


@login_required
@require_http_methods(["GET"])
def get_analytics_data(request, session_id):
    """Get pre-computed analytics data for Chart.js visualization."""
    session = get_object_or_404(AnalysisSession, id=session_id, user=request.user)

    # Build proximity timeline: 1-second bins per camera
    proximity_timeline = {'timestamps': [], 'series': {}}
    cameras = list(session.cameras.all())

    if cameras:
        # Find max duration across cameras
        max_duration = 0
        for cam in cameras:
            if cam.duration and cam.duration > max_duration:
                max_duration = cam.duration

        if max_duration > 0:
            bin_size = 1.0
            num_bins = int(max_duration / bin_size) + 1
            proximity_timeline['timestamps'] = [round(i * bin_size, 1) for i in range(num_bins)]

            for cam in cameras:
                series = [0.0] * num_bins
                frames = DetectionFrame.objects.filter(camera=cam).order_by('frame_number')

                for frame in frames:
                    bin_idx = int(frame.timestamp / bin_size)
                    if 0 <= bin_idx < num_bins:
                        max_prox = max(
                            (d.get('proximity', 0) for d in frame.detections),
                            default=0
                        )
                        if max_prox > series[bin_idx]:
                            series[bin_idx] = round(max_prox, 3)

                proximity_timeline['series'][cam.position] = series

    # Class distribution from results_summary
    class_distribution = session.results_summary.get('by_class', {})

    # Segments count
    segments_count = TemporalSegment.objects.filter(session=session).count()

    return JsonResponse({
        'proximity_timeline': proximity_timeline,
        'class_distribution': class_distribution,
        'segments_count': segments_count,
    })
