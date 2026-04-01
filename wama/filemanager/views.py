"""
FileManager views - API for file browsing and management.
"""
import os
import json
import mimetypes
import logging
from pathlib import Path
from urllib.parse import quote

from django.conf import settings
from django.http import JsonResponse, FileResponse, HttpResponseBadRequest
from django.views.decorators.http import require_POST, require_GET, require_http_methods
from django.core.files.storage import default_storage

from .models import UserFile, MountedFolder
from wama.accounts.views import get_or_create_anonymous_user

logger = logging.getLogger(__name__)


def get_user(request):
    """Get current user or anonymous user."""
    return request.user if request.user.is_authenticated else get_or_create_anonymous_user()


def get_user_media_root(user):
    """Get the media root path for a specific user."""
    return Path(settings.MEDIA_ROOT)


def build_file_tree(user):
    """
    Build a file tree structure for jstree with two collapsible sections:
    - Mes fichiers : temp folder + user-mounted folders
    - Applications : app-specific input/output folders
    """
    media_root = Path(settings.MEDIA_ROOT)
    user_id = user.id

    # ── Section 1 : Mes fichiers ─────────────────────────────────────────
    user_children = []

    temp_node = build_folder_node({
        'id': 'temp',
        'text': 'Temporaires',
        'icon': 'fa fa-folder text-warning',
        'path': f'users/{user_id}/temp',
    }, media_root, user_id)
    if temp_node:
        user_children.append(temp_node)

    for mount in MountedFolder.objects.filter(user=user).order_by('name'):
        user_children.append({
            'id': f'mount_{mount.id}',
            'text': mount.name,
            'icon': 'fa fa-plug text-info',
            'type': 'mount',
            'children': True,
            'data': {'path': f'mounts/{mount.id}', 'mount_id': mount.id},
        })

    # ── Section 2 : Applications ─────────────────────────────────────────
    app_folders_config = [
        {
            'id': 'anonymizer',
            'text': 'Anonymizer',
            'icon': 'fa fa-user-secret text-danger',
            'children': [
                {'id': 'anonymizer_input', 'text': 'Input', 'path': f'anonymizer/{user_id}/input', 'icon': 'fa fa-folder text-secondary'},
                {'id': 'anonymizer_output', 'text': 'Output', 'path': f'anonymizer/{user_id}/output', 'icon': 'fa fa-folder text-success'},
            ]
        },
        {
            'id': 'avatarizer',
            'text': 'Avatarizer',
            'icon': 'fa fa-user-circle text-info',
            'children': [
                {'id': 'avatarizer_input', 'text': 'Input', 'path': f'avatarizer/{user_id}/input', 'icon': 'fa fa-folder text-secondary'},
                {'id': 'avatarizer_output', 'text': 'Output', 'path': f'avatarizer/{user_id}/output', 'icon': 'fa fa-folder text-success'},
                {'id': 'avatarizer_gallery', 'text': 'Galerie', 'path': 'avatarizer/gallery', 'icon': 'fa fa-images text-info'},
            ]
        },
        {
            'id': 'composer',
            'text': 'Composer',
            'icon': 'fa fa-music text-success',
            'children': [
                {'id': 'composer_input', 'text': 'Input', 'path': f'composer/{user_id}/input', 'icon': 'fa fa-folder text-secondary'},
                {'id': 'composer_output', 'text': 'Output', 'path': f'composer/{user_id}/output', 'icon': 'fa fa-folder text-success'},
            ]
        },
        {
            'id': 'describer',
            'text': 'Describer',
            'icon': 'fa fa-search-plus text-info',
            'children': [
                {'id': 'describer_input', 'text': 'Input', 'path': f'describer/{user_id}/input', 'icon': 'fa fa-folder text-secondary'},
                {'id': 'describer_output', 'text': 'Output', 'path': f'describer/{user_id}/output', 'icon': 'fa fa-folder text-success'},
            ]
        },
        {
            'id': 'enhancer',
            'text': 'Enhancer',
            'icon': 'fa fa-magic text-info',
            'children': [
                {'id': 'enhancer_input_media', 'text': 'Input (Image/Vidéo)', 'path': f'enhancer/{user_id}/input/media', 'icon': 'fa fa-folder text-secondary'},
                {'id': 'enhancer_input_audio', 'text': 'Input (Audio)', 'path': f'enhancer/{user_id}/input/audio', 'icon': 'fa fa-folder text-secondary'},
                {'id': 'enhancer_output_media', 'text': 'Output (Image/Vidéo)', 'path': f'enhancer/{user_id}/output/media', 'icon': 'fa fa-folder text-success'},
                {'id': 'enhancer_output_audio', 'text': 'Output (Audio)', 'path': f'enhancer/{user_id}/output/audio', 'icon': 'fa fa-folder text-success'},
            ]
        },
        {
            'id': 'imager',
            'text': 'Imager',
            'icon': 'fa fa-image text-success',
            'children': [
                {'id': 'imager_prompts', 'text': 'Prompts', 'path': f'imager/{user_id}/input/prompts', 'icon': 'fa fa-file-alt text-secondary'},
                {'id': 'imager_references', 'text': 'References', 'path': f'imager/{user_id}/input/references', 'icon': 'fa fa-image text-secondary'},
                {'id': 'imager_output_image', 'text': 'Images', 'path': f'imager/{user_id}/output/image', 'icon': 'fa fa-image text-success'},
                {'id': 'imager_output_video', 'text': 'Vidéos', 'path': f'imager/{user_id}/output/video', 'icon': 'fa fa-film text-success'},
            ]
        },
        {
            'id': 'synthesizer',
            'text': 'Synthesizer',
            'icon': 'fa fa-microphone text-primary',
            'children': [
                {'id': 'synthesizer_input', 'text': 'Input', 'path': f'synthesizer/{user_id}/input', 'icon': 'fa fa-folder text-secondary'},
                {'id': 'synthesizer_output', 'text': 'Output', 'path': f'synthesizer/{user_id}/output', 'icon': 'fa fa-folder text-success'},
                {'id': 'synthesizer_voices', 'text': 'Custom_voices', 'path': f'synthesizer/{user_id}/custom_voices', 'icon': 'fa fa-user-circle text-info'},
            ]
        },
        {
            'id': 'reader',
            'text': 'Reader',
            'icon': 'fa fa-file-invoice text-cyan',
            'children': [
                {'id': 'reader_input', 'text': 'Input', 'path': f'reader/{user_id}/input', 'icon': 'fa fa-folder text-secondary'},
                {'id': 'reader_output', 'text': 'Output', 'path': f'reader/{user_id}/output', 'icon': 'fa fa-folder text-success'},
            ]
        },
        {
            'id': 'transcriber',
            'text': 'Transcriber',
            'icon': 'fa fa-file-alt text-warning',
            'children': [
                {'id': 'transcriber_input', 'text': 'Input', 'path': f'transcriber/{user_id}/input', 'icon': 'fa fa-folder text-secondary'},
                {'id': 'transcriber_output', 'text': 'Output', 'path': f'transcriber/{user_id}/output', 'icon': 'fa fa-folder text-success'},
            ]
        },
        {
            'id': 'wama_lab',
            'text': 'WAMA Lab',
            'icon': 'fa fa-flask text-info',
            'is_category': True,
            'children': [
                {
                    'id': 'face_analyzer',
                    'text': 'Face Analyzer',
                    'icon': 'fa fa-smile text-info',
                    'children': [
                        {'id': 'face_analyzer_input', 'text': 'Input', 'path': f'face_analyzer/{user_id}/input', 'icon': 'fa fa-folder text-secondary'},
                        {'id': 'face_analyzer_output', 'text': 'Output', 'path': f'face_analyzer/{user_id}/output', 'icon': 'fa fa-folder text-success'},
                    ]
                },
                {
                    'id': 'cam_analyzer',
                    'text': 'Cam Analyzer',
                    'icon': 'fa fa-video text-warning',
                    'children': [
                        {'id': 'cam_analyzer_input', 'text': 'Input', 'path': f'cam_analyzer/{user_id}/input', 'icon': 'fa fa-folder text-secondary'},
                        {'id': 'cam_analyzer_output', 'text': 'Output', 'path': f'cam_analyzer/{user_id}/output', 'icon': 'fa fa-folder text-success'},
                    ]
                },
            ]
        },
    ]

    app_children = []
    for config in app_folders_config:
        node = build_folder_node(config, media_root, user_id)
        if node:
            app_children.append(node)

    return [
        {
            'id': 'section_user',
            'text': 'Mes fichiers',
            'icon': 'fa fa-home text-light',
            'type': 'section',
            'state': {'opened': True},
            'children': user_children,
            'data': {},
        },
        {
            'id': 'section_apps',
            'text': 'Applications',
            'icon': 'fa fa-th-large text-secondary',
            'type': 'section',
            'state': {'opened': False},
            'children': app_children,
            'data': {},
        },
    ]


def build_folder_node(config, media_root, user_id):
    """Build a folder node with its children."""
    node = {
        'id': config['id'],
        'text': config['text'],
        'icon': config.get('icon', 'fa fa-folder'),
        'type': 'folder',
        'state': {'opened': config['id'] == 'temp'},  # Open temp folder by default
        'children': []
    }

    if 'path' in config:
        # Leaf folder: return lazy placeholder — jstree will call api_children on expand
        node['data'] = {'path': config['path']}
        node['children'] = True  # jstree lazy-load sentinel
    elif 'children' in config:
        # This is a parent folder with sub-folders
        for child_config in config['children']:
            child_node = build_folder_node(child_config, media_root, user_id)
            if child_node:
                node['children'].append(child_node)

    return node


def scan_folder_files(folder_path, relative_path, user_id):
    """Scan a folder for files and subfolders, returning jstree nodes recursively."""
    nodes = []
    try:
        # Sort: folders first, then files
        items = sorted(folder_path.iterdir(), key=lambda x: (x.is_file(), x.name.lower()))

        for item in items:
            if item.is_dir():
                # Recursively scan subfolder
                subfolder_relative = f'{relative_path}/{item.name}'
                subfolder_children = scan_folder_files(item, subfolder_relative, user_id)

                nodes.append({
                    'id': f'folder_{subfolder_relative}'.replace('/', '_').replace('\\', '_'),
                    'text': item.name,
                    'icon': 'fa fa-folder text-warning',
                    'type': 'folder',
                    'state': {'opened': False},
                    'data': {
                        'path': subfolder_relative,
                    },
                    'children': subfolder_children
                })
            elif item.is_file():
                # Get file info
                stat = item.stat()
                mime_type = mimetypes.guess_type(item.name)[0] or 'application/octet-stream'

                # Determine icon based on mime type
                if mime_type.startswith('image/'):
                    icon = 'fa fa-file-image text-info'
                elif mime_type.startswith('video/'):
                    icon = 'fa fa-file-video text-warning'
                elif mime_type.startswith('audio/'):
                    icon = 'fa fa-file-audio text-success'
                elif mime_type == 'application/pdf':
                    icon = 'fa fa-file-pdf text-danger'
                else:
                    icon = 'fa fa-file text-secondary'

                nodes.append({
                    'id': f'file_{relative_path}/{item.name}'.replace('/', '_').replace('\\', '_'),
                    'text': item.name,
                    'icon': icon,
                    'type': 'file',
                    'data': {
                        'path': f'{relative_path}/{item.name}',
                        'size': stat.st_size,
                        'mime': mime_type,
                        'modified': stat.st_mtime,
                    }
                })
    except PermissionError:
        logger.warning(f"Permission denied scanning {folder_path}")
    except Exception as e:
        logger.error(f"Error scanning {folder_path}: {e}")

    return nodes


def resolve_mount_path(rel_path, user):
    """
    Resolve a virtual 'mounts/<id>[/subpath]' to an absolute Path.
    Returns (abs_path, MountedFolder) or (None, None) if invalid/unauthorized.
    """
    parts = rel_path.strip('/').split('/', 2)
    if len(parts) < 2 or parts[0] != 'mounts':
        return None, None
    try:
        mount_id = int(parts[1])
    except ValueError:
        return None, None
    try:
        mount = MountedFolder.objects.get(id=mount_id, user=user)
    except MountedFolder.DoesNotExist:
        return None, None
    # Re-run _resolve_path on the stored value: on WSL2 a UNC path stored as
    # //server/share must be converted to the actual Linux mount point.
    # On Windows this is a no-op (//server/share is already valid).
    resolved_local = _resolve_path(mount.local_path)
    base = Path(resolved_local)
    logger.warning(f"[Filemanager] resolve_mount_path: local_path='{mount.local_path}' → resolved='{resolved_local}' → base='{base}'")
    subpath = parts[2] if len(parts) == 3 else ''
    if subpath:
        # Prevent path traversal without filesystem I/O (no .resolve())
        if '..' in Path(subpath).parts:
            logger.warning(f"[Filemanager] Path traversal attempt blocked: {subpath}")
            return None, None
        target = base / subpath
    else:
        target = base
    return target, mount


def scan_mount_folder(abs_folder, virtual_prefix):
    """Scan a mounted folder and return jstree nodes with virtual paths."""
    nodes = []
    err_id = f'mount_err_{virtual_prefix.replace("/", "_").replace(":", "_")}'
    try:
        items = list(abs_folder.iterdir())
        items.sort(key=lambda x: (x.is_file(), x.name.lower()))
        for item in items:
            virtual_path = f'{virtual_prefix}/{item.name}'
            safe_id = virtual_path.replace('/', '_').replace('\\', '_').replace(':', '_')
            if item.is_dir():
                nodes.append({
                    'id': f'mount_{safe_id}',
                    'text': item.name,
                    'icon': 'fa fa-folder text-warning',
                    'type': 'folder',
                    'children': True,
                    'data': {'path': virtual_path},
                })
            elif item.is_file():
                stat = item.stat()
                mime_type = mimetypes.guess_type(item.name)[0] or 'application/octet-stream'
                if mime_type.startswith('image/'):
                    icon = 'fa fa-file-image text-info'
                elif mime_type.startswith('video/'):
                    icon = 'fa fa-file-video text-warning'
                elif mime_type.startswith('audio/'):
                    icon = 'fa fa-file-audio text-success'
                elif mime_type == 'application/pdf':
                    icon = 'fa fa-file-pdf text-danger'
                else:
                    icon = 'fa fa-file text-secondary'
                nodes.append({
                    'id': f'mount_{safe_id}',
                    'text': item.name,
                    'icon': icon,
                    'type': 'file',
                    'data': {
                        'path': virtual_path,
                        'size': stat.st_size,
                        'mime': mime_type,
                        'modified': stat.st_mtime,
                    },
                })
    except PermissionError:
        logger.warning(f"Permission denied scanning mount {abs_folder}")
        nodes.append({
            'id': err_id, 'text': 'Accès refusé',
            'icon': 'fa fa-lock text-danger', 'type': 'error', 'children': False,
        })
    except Exception as e:
        logger.error(f"Error scanning mount {abs_folder}: {e}")
        nodes.append({
            'id': err_id, 'text': 'Erreur de lecture',
            'icon': 'fa fa-exclamation-triangle text-warning', 'type': 'error', 'children': False,
        })
    return nodes


@require_GET
def api_children(request):
    """
    Lazy-load children of a specific folder node (called by jstree when expanding).
    Returns file/subfolder nodes for the given path without scanning the whole tree.
    """
    user = get_user(request)
    rel_path = request.GET.get('path', '').strip('/')
    if not rel_path:
        return JsonResponse([], safe=False)

    # Handle mounted folder paths
    if rel_path.startswith('mounts/'):
        abs_path, mount = resolve_mount_path(rel_path, user)
        if abs_path is None:
            return JsonResponse([{
                'id': f'err_access_{rel_path.replace("/", "_")}',
                'text': 'Accès refusé', 'icon': 'fa fa-lock text-danger',
                'type': 'error', 'children': False,
            }], safe=False)
        try:
            import os
            path_ok = os.path.isdir(str(abs_path))
        except OSError as e:
            logger.warning(f"[Filemanager] Mount path check failed for '{abs_path}': {e}")
            path_ok = False
        logger.warning(f"[Filemanager] api_children mount: path='{abs_path}' ok={path_ok}")
        if not path_ok:
            import sys
            abs_str = str(abs_path)
            if sys.platform.startswith('linux') and abs_str.startswith('//'):
                err_text = (
                    f'Partage réseau inaccessible depuis WSL2 : {abs_str} — '
                    'montez le partage CIFS dans WSL2 puis re-créez ce montage '
                    'avec le chemin Linux (ex: /mnt/shares/SAVES)'
                )
            else:
                err_text = 'Dossier non accessible (hors ligne ?)'
            return JsonResponse([{
                'id': f'err_offline_{rel_path.replace("/", "_")}',
                'text': err_text,
                'icon': 'fa fa-exclamation-triangle text-warning',
                'type': 'error', 'children': False,
            }], safe=False)
        nodes = scan_mount_folder(abs_path, rel_path)
        return JsonResponse(nodes, safe=False)

    media_root = Path(settings.MEDIA_ROOT)
    folder_path = media_root / rel_path

    # Security: ensure resolved path stays within MEDIA_ROOT
    try:
        folder_path.resolve().relative_to(media_root.resolve())
    except ValueError:
        return JsonResponse({'error': 'Invalid path'}, status=400)

    if not folder_path.exists() or not folder_path.is_dir():
        return JsonResponse([], safe=False)

    nodes = scan_folder_files(folder_path, rel_path, user.id)
    return JsonResponse(nodes, safe=False)


@require_GET
def api_tree(request):
    """Get file tree for jstree."""
    user = get_user(request)
    tree = build_file_tree(user)
    return JsonResponse(tree, safe=False)


@require_GET
def api_tree_mtime(request):
    """
    Lightweight change-detection endpoint for polling.

    Returns a compact hash built from the mtime of each registered top-level
    folder — no recursion, one stat() per folder. The JS poller uses this
    instead of fetching the full tree every 5 s.
    """
    import hashlib
    user = get_user(request)
    media_root = Path(settings.MEDIA_ROOT)
    uid = user.id

    # Flat list of all app leaf folders (same set as build_file_tree)
    leaf_paths = [
        f'users/{uid}/temp',
        f'anonymizer/{uid}/input', f'anonymizer/{uid}/output',
        f'avatarizer/{uid}/input', f'avatarizer/{uid}/output', 'avatarizer/gallery',
        f'composer/{uid}/input', f'composer/{uid}/output',
        f'describer/{uid}/input', f'describer/{uid}/output',
        f'enhancer/{uid}/input/media', f'enhancer/{uid}/input/audio',
        f'enhancer/{uid}/output/media', f'enhancer/{uid}/output/audio',
        f'imager/{uid}/input/prompts', f'imager/{uid}/input/references',
        f'imager/{uid}/output/image', f'imager/{uid}/output/video',
        f'reader/{uid}/input', f'reader/{uid}/output',
        f'synthesizer/{uid}/input', f'synthesizer/{uid}/output', f'synthesizer/{uid}/custom_voices',
        f'transcriber/{uid}/input', f'transcriber/{uid}/output',
        f'face_analyzer/{uid}/input', f'face_analyzer/{uid}/output',
        f'cam_analyzer/{uid}/input', f'cam_analyzer/{uid}/output',
    ]

    h = hashlib.md5()
    for rel in leaf_paths:
        p = media_root / rel
        if p.exists():
            try:
                h.update(f'{rel}:{p.stat().st_mtime}'.encode())
            except OSError:
                pass

    return JsonResponse({'mtime_hash': h.hexdigest()})


@require_GET
def api_search(request):
    """Search files by name."""
    user = get_user(request)
    query = request.GET.get('q', '').lower()

    if len(query) < 2:
        return JsonResponse({'results': []})

    results = []
    media_root = Path(settings.MEDIA_ROOT)

    # Search in all user-accessible folders
    search_paths = [
        f'users/{user.id}/temp',
        f'anonymizer/{user.id}/input',
        f'anonymizer/{user.id}/output',
        f'avatarizer/{user.id}/input',
        f'avatarizer/{user.id}/output',
        f'composer/{user.id}/input',
        f'composer/{user.id}/output',
        f'describer/{user.id}/input',
        f'describer/{user.id}/output',
        f'enhancer/{user.id}/input',
        f'enhancer/{user.id}/output',
        f'imager/{user.id}/input/prompts',
        f'imager/{user.id}/input/references',
        f'imager/{user.id}/output/image',
        f'imager/{user.id}/output/video',
        f'reader/{user.id}/input',
        f'reader/{user.id}/output',
        f'synthesizer/{user.id}/input',
        f'synthesizer/{user.id}/output',
        f'synthesizer/{user.id}/custom_voices',
        f'transcriber/{user.id}/input',
        f'transcriber/{user.id}/output',
        f'face_analyzer/{user.id}/input',
        f'face_analyzer/{user.id}/output',
        f'cam_analyzer/{user.id}/input',
        f'cam_analyzer/{user.id}/output',
    ]

    for search_path in search_paths:
        folder = media_root / search_path
        if folder.exists():
            for item in folder.rglob('*'):
                if item.is_file() and query in item.name.lower():
                    relative_path = str(item.relative_to(media_root)).replace('\\', '/')
                    results.append({
                        'name': item.name,
                        'path': relative_path,
                        'folder': search_path,
                    })

    return JsonResponse({'results': results[:50]})  # Limit to 50 results


@require_POST
def api_upload(request):
    """Upload file(s) to user's temp folder, preserving folder structure if provided."""
    user = get_user(request)
    files = request.FILES.getlist('files')

    if not files:
        return HttpResponseBadRequest('No files provided')

    # Get relative paths if provided (for folder uploads)
    paths_json = request.POST.get('paths', '[]')
    try:
        relative_paths = json.loads(paths_json)
    except json.JSONDecodeError:
        relative_paths = []

    # Ensure paths list matches files list
    if len(relative_paths) != len(files):
        relative_paths = [None] * len(files)

    uploaded = []
    folders_created = set()

    for i, file in enumerate(files):
        try:
            relative_path = relative_paths[i] if relative_paths[i] else None

            if relative_path:
                # Upload with folder structure preservation
                # Sanitize the relative path
                safe_path = sanitize_relative_path(relative_path)

                if safe_path:
                    # Build the full path: users/{user_id}/temp/{relative_path}
                    dest_dir = Path(settings.MEDIA_ROOT) / f'users/{user.id}/temp' / Path(safe_path).parent

                    # Create directories if needed
                    if not dest_dir.exists():
                        dest_dir.mkdir(parents=True, exist_ok=True)
                        # Track created folders
                        folders_created.add(str(Path(safe_path).parent))

                    # Save file with its original folder structure
                    dest_path = f'users/{user.id}/temp/{safe_path}'
                    full_dest = Path(settings.MEDIA_ROOT) / dest_path

                    # Write file content
                    with open(full_dest, 'wb+') as destination:
                        for chunk in file.chunks():
                            destination.write(chunk)

                    # Create UserFile record with the structured path
                    user_file = UserFile.objects.create(
                        user=user,
                        original_name=file.name,
                        mime_type=file.content_type or mimetypes.guess_type(file.name)[0] or '',
                        file_size=file.size,
                    )
                    # Manually set the file path (bypass upload_to)
                    user_file.file.name = dest_path
                    user_file.save()

                    uploaded.append({
                        'id': user_file.id,
                        'name': user_file.original_name,
                        'path': dest_path,
                        'size': user_file.file_size,
                        'relative_path': safe_path,
                    })
                    continue

            # Standard upload (no folder structure)
            user_file = UserFile.objects.create(
                user=user,
                file=file,
                original_name=file.name,
                mime_type=file.content_type or mimetypes.guess_type(file.name)[0] or '',
                file_size=file.size,
            )
            uploaded.append({
                'id': user_file.id,
                'name': user_file.original_name,
                'path': user_file.file.name,
                'size': user_file.file_size,
            })
        except Exception as e:
            logger.error(f"Error uploading file {file.name}: {e}")

    return JsonResponse({
        'uploaded': uploaded,
        'count': len(uploaded),
        'folders_created': len(folders_created)
    })


def sanitize_relative_path(path):
    """
    Sanitize a relative path to prevent directory traversal attacks.
    Returns None if path is invalid.
    """
    if not path:
        return None

    # Normalize path separators
    path = path.replace('\\', '/')

    # Remove leading slashes
    path = path.lstrip('/')

    # Split and filter path components
    parts = path.split('/')
    safe_parts = []

    for part in parts:
        # Skip empty parts and parent directory references
        if not part or part == '.' or part == '..':
            continue
        # Remove any potentially dangerous characters
        safe_part = ''.join(c for c in part if c.isalnum() or c in '._- ')
        if safe_part:
            safe_parts.append(safe_part)

    if not safe_parts:
        return None

    return '/'.join(safe_parts)


@require_POST
def api_delete(request):
    """Delete a file."""
    user = get_user(request)

    try:
        data = json.loads(request.body)
        file_path = data.get('path', '')
    except (json.JSONDecodeError, ValueError):
        file_path = request.POST.get('path', '')

    if not file_path:
        return HttpResponseBadRequest('No file path provided')

    # Security check: ensure path is within allowed directories
    if not is_path_allowed(file_path, user):
        return JsonResponse({'error': 'Access denied'}, status=403)

    try:
        if default_storage.exists(file_path):
            default_storage.delete(file_path)

            # Also delete from UserFile if it's a temp file
            UserFile.objects.filter(user=user, file=file_path).delete()

            return JsonResponse({'deleted': True, 'path': file_path})
        else:
            return JsonResponse({'error': 'File not found'}, status=404)
    except Exception as e:
        logger.error(f"Error deleting {file_path}: {e}")
        return JsonResponse({'error': str(e)}, status=500)


@require_POST
def api_delete_all(request):
    """Delete all files in a folder and its subfolders."""
    user = get_user(request)

    try:
        data = json.loads(request.body)
        folder_path = data.get('path', '')
    except (json.JSONDecodeError, ValueError):
        folder_path = request.POST.get('path', '')

    if not folder_path:
        return HttpResponseBadRequest('No folder path provided')

    # Security check: ensure path is within allowed directories
    if not is_path_allowed(folder_path, user):
        return JsonResponse({'error': 'Access denied'}, status=403)

    try:
        full_path = Path(settings.MEDIA_ROOT) / folder_path

        if not full_path.exists():
            return JsonResponse({'error': 'Folder not found'}, status=404)

        if not full_path.is_dir():
            return JsonResponse({'error': 'Path is not a folder'}, status=400)

        deleted_count = 0
        deleted_folders = 0
        errors = []

        # Walk through all files in folder and subfolders
        for file_path in full_path.rglob('*'):
            if file_path.is_file():
                try:
                    relative_path = str(file_path.relative_to(settings.MEDIA_ROOT))
                    file_path.unlink()
                    deleted_count += 1

                    # Also delete from UserFile if exists
                    UserFile.objects.filter(user=user, file=relative_path).delete()
                except Exception as e:
                    errors.append(f"{file_path.name}: {str(e)}")
                    logger.error(f"Error deleting {file_path}: {e}")

        # Check if this is a user temp folder - if so, also delete empty subfolders
        # Application folders (enhancer, anonymizer, etc.) should keep their structure
        is_temp_folder = folder_path.startswith(f'users/{user.id}/temp')

        if is_temp_folder:
            # Delete empty folders (bottom-up to handle nested empty folders)
            # We need to sort by depth (deepest first) to delete nested folders correctly
            empty_folders = []
            for dir_path in full_path.rglob('*'):
                if dir_path.is_dir():
                    empty_folders.append(dir_path)

            # Sort by path length descending (deepest folders first)
            empty_folders.sort(key=lambda p: len(str(p)), reverse=True)

            for dir_path in empty_folders:
                try:
                    # Check if folder is empty (no files, no subdirs)
                    if not any(dir_path.iterdir()):
                        dir_path.rmdir()
                        deleted_folders += 1
                except Exception as e:
                    logger.error(f"Error deleting empty folder {dir_path}: {e}")

        response = {'deleted_count': deleted_count}
        if deleted_folders > 0:
            response['deleted_folders'] = deleted_folders
        if errors:
            response['errors'] = errors

        return JsonResponse(response)

    except Exception as e:
        logger.error(f"Error deleting all in {folder_path}: {e}")
        return JsonResponse({'error': str(e)}, status=500)


@require_POST
def api_rename(request):
    """Rename a file."""
    user = get_user(request)

    try:
        data = json.loads(request.body)
        old_path = data.get('path', '')
        new_name = data.get('new_name', '')
    except (json.JSONDecodeError, ValueError):
        old_path = request.POST.get('path', '')
        new_name = request.POST.get('new_name', '')

    if not old_path or not new_name:
        return HttpResponseBadRequest('Missing path or new_name')

    # Security check
    if not is_path_allowed(old_path, user):
        return JsonResponse({'error': 'Access denied'}, status=403)

    # Sanitize new name
    new_name = os.path.basename(new_name)  # Remove any path components
    if not new_name:
        return HttpResponseBadRequest('Invalid new name')

    try:
        old_full_path = Path(settings.MEDIA_ROOT) / old_path
        new_path = str(Path(old_path).parent / new_name)
        new_full_path = Path(settings.MEDIA_ROOT) / new_path

        if not old_full_path.exists():
            return JsonResponse({'error': 'File not found'}, status=404)

        if new_full_path.exists():
            return JsonResponse({'error': 'A file with this name already exists'}, status=400)

        old_full_path.rename(new_full_path)

        # Update UserFile if exists
        UserFile.objects.filter(user=user, file=old_path).update(
            file=new_path,
            original_name=new_name
        )

        return JsonResponse({'renamed': True, 'old_path': old_path, 'new_path': new_path})
    except Exception as e:
        logger.error(f"Error renaming {old_path} to {new_name}: {e}")
        return JsonResponse({'error': str(e)}, status=500)


@require_POST
def api_move(request):
    """Move a file or folder to a different location (only within temp folder)."""
    user = get_user(request)

    try:
        data = json.loads(request.body)
        source_path = data.get('source', '')
        dest_folder = data.get('destination', '')
    except (json.JSONDecodeError, ValueError):
        source_path = request.POST.get('source', '')
        dest_folder = request.POST.get('destination', '')

    if not source_path or not dest_folder:
        return HttpResponseBadRequest('Missing source or destination')

    # Security check - source must be allowed
    if not is_path_allowed(source_path, user):
        return JsonResponse({'error': 'Access denied to source'}, status=403)

    # Only allow moves within user's temp folder
    temp_prefix = f'users/{user.id}/temp'
    if not source_path.startswith(temp_prefix):
        return JsonResponse({'error': 'Déplacement autorisé uniquement dans le dossier temporaire'}, status=403)

    if not dest_folder.startswith(temp_prefix):
        return JsonResponse({'error': 'Destination doit être dans le dossier temporaire'}, status=403)

    try:
        import shutil
        source_full = Path(settings.MEDIA_ROOT) / source_path
        dest_dir_full = Path(settings.MEDIA_ROOT) / dest_folder

        if not source_full.exists():
            return JsonResponse({'error': 'Source non trouvée'}, status=404)

        is_folder = source_full.is_dir()

        # Prevent moving a folder into itself or its subdirectories
        if is_folder:
            dest_resolved = dest_dir_full.resolve()
            source_resolved = source_full.resolve()
            if dest_resolved == source_resolved or str(dest_resolved).startswith(str(source_resolved) + os.sep):
                return JsonResponse({'error': 'Impossible de déplacer un dossier dans lui-même'}, status=400)

        # Create destination directory if it doesn't exist
        dest_dir_full.mkdir(parents=True, exist_ok=True)

        # Build destination path
        dest_full = dest_dir_full / source_full.name

        # Handle duplicate names
        if dest_full.exists():
            stem = source_full.stem
            suffix = source_full.suffix if not is_folder else ''
            counter = 1
            while dest_full.exists():
                if is_folder:
                    dest_full = dest_dir_full / f"{stem}_{counter}"
                else:
                    dest_full = dest_dir_full / f"{stem}_{counter}{suffix}"
                counter += 1

        # Move the file or folder
        shutil.move(str(source_full), str(dest_full))

        new_path = f"{dest_folder}/{dest_full.name}"

        if is_folder:
            # Update all UserFile records that were inside this folder
            old_prefix = source_path + '/'
            new_prefix = new_path + '/'
            user_files = UserFile.objects.filter(user=user, file__startswith=old_prefix)
            for uf in user_files:
                uf.file = uf.file.replace(old_prefix, new_prefix, 1)
                uf.save()

            return JsonResponse({
                'moved': True,
                'is_folder': True,
                'old_path': source_path,
                'new_path': new_path
            })
        else:
            # Update UserFile if exists
            UserFile.objects.filter(user=user, file=source_path).update(
                file=new_path,
                original_name=dest_full.name
            )

            return JsonResponse({
                'moved': True,
                'is_folder': False,
                'old_path': source_path,
                'new_path': new_path
            })
    except Exception as e:
        logger.error(f"Error moving {source_path} to {dest_folder}: {e}")
        return JsonResponse({'error': str(e)}, status=500)


@require_POST
def api_mkdir(request):
    """Create a new subfolder in the user's temp directory."""
    import re
    user = get_user(request)
    try:
        data = json.loads(request.body)
        folder_name = data.get('name', '').strip()
        parent_path = data.get('parent', '').strip('/')
    except (json.JSONDecodeError, ValueError):
        return HttpResponseBadRequest('Invalid JSON')

    if not folder_name:
        return JsonResponse({'error': 'Nom de dossier manquant'}, status=400)

    # Sanitize folder name
    folder_name = re.sub(r'[<>:"/\\|?*]', '_', folder_name)
    if not folder_name:
        return JsonResponse({'error': 'Nom invalide'}, status=400)

    media_root = Path(settings.MEDIA_ROOT)
    user_temp = media_root / f'users/{user.id}/temp'

    if parent_path:
        # Validate parent is within user temp dir
        target = (user_temp / parent_path / folder_name).resolve()
        allowed_base = user_temp.resolve()
        if not str(target).startswith(str(allowed_base)):
            return JsonResponse({'error': 'Chemin non autorisé'}, status=403)
    else:
        target = (user_temp / folder_name).resolve()
        allowed_base = user_temp.resolve()
        if not str(target).startswith(str(allowed_base)):
            return JsonResponse({'error': 'Chemin non autorisé'}, status=403)

    try:
        target.mkdir(parents=True, exist_ok=False)
        return JsonResponse({'success': True, 'path': str(target.relative_to(media_root)).replace('\\', '/')})
    except FileExistsError:
        return JsonResponse({'error': 'Ce dossier existe déjà'}, status=409)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


def api_download(request, path):
    """Download a file."""
    user = get_user(request)

    # Security check
    if not is_path_allowed(path, user):
        return JsonResponse({'error': 'Access denied'}, status=403)

    if path.startswith('mounts/'):
        full_path, mount = resolve_mount_path(path, user)
        if full_path is None:
            return JsonResponse({'error': 'Access denied'}, status=403)
    else:
        full_path = Path(settings.MEDIA_ROOT) / path

    if not full_path.exists():
        return JsonResponse({'error': 'File not found'}, status=404)

    try:
        return FileResponse(
            open(full_path, 'rb'),
            as_attachment=True,
            filename=full_path.name
        )
    except Exception as e:
        logger.error(f"Error downloading {path}: {e}")
        return JsonResponse({'error': str(e)}, status=500)


@require_GET
def api_info(request):
    """Get file information."""
    user = get_user(request)
    file_path = request.GET.get('path', '')

    if not file_path:
        return HttpResponseBadRequest('No file path provided')

    # Security check
    if not is_path_allowed(file_path, user):
        return JsonResponse({'error': 'Access denied'}, status=403)

    if file_path.startswith('mounts/'):
        full_path, mount = resolve_mount_path(file_path, user)
        if full_path is None:
            return JsonResponse({'error': 'Access denied'}, status=403)
    else:
        full_path = Path(settings.MEDIA_ROOT) / file_path

    if not full_path.exists():
        return JsonResponse({'error': 'File not found'}, status=404)

    try:
        stat = full_path.stat()
        mime_type = mimetypes.guess_type(full_path.name)[0] or 'application/octet-stream'

        return JsonResponse({
            'name': full_path.name,
            'path': file_path,
            'size': stat.st_size,
            'mime': mime_type,
            'modified': stat.st_mtime,
            'created': stat.st_ctime,
        })
    except Exception as e:
        logger.error(f"Error getting info for {file_path}: {e}")
        return JsonResponse({'error': str(e)}, status=500)


@require_GET
def api_preview(request):
    """Get file preview URL or thumbnail."""
    user = get_user(request)
    file_path = request.GET.get('path', '')

    if not file_path:
        return HttpResponseBadRequest('No file path provided')

    # Security check
    if not is_path_allowed(file_path, user):
        return JsonResponse({'error': 'Access denied'}, status=403)

    # Resolve path: mounted folder or MEDIA_ROOT
    if file_path.startswith('mounts/'):
        full_path, mount = resolve_mount_path(file_path, user)
        if full_path is None:
            return JsonResponse({'error': 'Access denied'}, status=403)
        # Build serve URL for inline display of mounted files
        parts = file_path.strip('/').split('/', 2)
        subpath = parts[2] if len(parts) > 2 else ''
        media_url = f'/filemanager/api/mounts/{mount.id}/serve/{quote(subpath)}'
    else:
        full_path = Path(settings.MEDIA_ROOT) / file_path
        media_url = settings.MEDIA_URL + quote(file_path)

    if not full_path.exists():
        return JsonResponse({'error': 'File not found'}, status=404)

    ext = full_path.suffix.lower()

    # Robust MIME detection: mimetypes.guess_type can fail on Windows for common types
    _EXT_MIME = {
        '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.png': 'image/png',
        '.gif': 'image/gif',  '.webp': 'image/webp', '.bmp': 'image/bmp',
        '.tiff': 'image/tiff', '.tif': 'image/tiff', '.ico': 'image/x-icon',
        '.svg': 'image/svg+xml',
        '.mp4': 'video/mp4',   '.webm': 'video/webm', '.mov': 'video/quicktime',
        '.avi': 'video/x-msvideo', '.mkv': 'video/x-matroska', '.flv': 'video/x-flv',
        '.wmv': 'video/x-ms-wmv', '.m4v': 'video/mp4',
        '.mp3': 'audio/mpeg',  '.wav': 'audio/wav',   '.ogg': 'audio/ogg',
        '.flac': 'audio/flac', '.aac': 'audio/aac',   '.m4a': 'audio/mp4',
        '.opus': 'audio/opus', '.weba': 'audio/webm',
    }
    mime_type = mimetypes.guess_type(full_path.name)[0] or _EXT_MIME.get(ext, '')

    # Images, videos, audio — direct URL, browser renders natively
    if mime_type.startswith(('image/', 'video/', 'audio/')):
        return JsonResponse({'url': media_url, 'mime_type': mime_type, 'name': full_path.name})

    # PDF — browser renders via <embed>
    if ext == '.pdf':
        return JsonResponse({'url': media_url, 'mime_type': 'application/pdf', 'name': full_path.name})

    # Plain text, markdown, CSV, JSON, XML — direct URL, media-preview.js fetches content
    plain_text_extensions = {'.txt', '.md', '.csv', '.json', '.xml', '.log', '.yaml', '.yml', '.ini', '.cfg'}
    if ext in plain_text_extensions:
        return JsonResponse({'url': media_url, 'mime_type': mime_type or 'text/plain', 'name': full_path.name})

    # DOCX and other office formats — extract text server-side (no native browser renderer)
    if ext in {'.docx', '.odt', '.rtf'}:
        try:
            from wama.synthesizer.utils.text_extractor import extract_text_from_file
            text_content = extract_text_from_file(str(full_path))
            if len(text_content) > 10000:
                text_content = text_content[:10000] + '\n\n... [Contenu tronqué]'
            return JsonResponse({'url': None, 'mime_type': 'text/plain', 'name': full_path.name, 'text_content': text_content})
        except Exception as e:
            logger.error(f"Error extracting text from {full_path}: {e}")
            return JsonResponse({'url': None, 'mime_type': mime_type, 'name': full_path.name, 'error': str(e)})

    return JsonResponse({'url': None, 'mime_type': mime_type, 'name': full_path.name})


def is_path_allowed(path, user):
    """
    Check if a path is allowed for the given user.
    Users can only access:
    - Their own temp folder: users/{user_id}/temp/
    - App folders: enhancer/, anonymizer/, synthesizer/, transcriber/
    """
    path = path.replace('\\', '/')

    # Prevent path traversal
    if '..' in path:
        return False

    # Allow user's temp folder
    if path.startswith(f'users/{user.id}/temp/') or path.startswith(f'users/{user.id}/temp'):
        return True

    # Allow app folders (TODO: add per-user filtering for app files)
    allowed_prefixes = [
        'anonymizer/',
        'avatarizer/',
        'composer/',
        'describer/',
        'enhancer/',
        'imager/',
        'reader/',
        'synthesizer/',
        'transcriber/',
        'face_analyzer/',
        'cam_analyzer/',
    ]

    for prefix in allowed_prefixes:
        if path.startswith(prefix):
            return True

    # Allow mounted folders owned by this user
    if path.startswith('mounts/'):
        abs_path, mount = resolve_mount_path(path, user)
        return abs_path is not None

    return False


@require_POST
def api_import_to_app(request):
    """
    Import one or more files from FileManager to an app's input folder.
    Supports single path (``path``) or multiple paths (``paths`` list).
    """
    user = get_user(request)

    try:
        data = json.loads(request.body)
        file_path = data.get('path', '')
        paths = data.get('paths', [])  # Multiple paths
        target_app = data.get('app', '')
    except (json.JSONDecodeError, ValueError):
        return HttpResponseBadRequest('Invalid JSON')

    # Support both single path and multiple paths
    if paths:
        file_paths = [p for p in paths if p]
    elif file_path:
        file_paths = [file_path]
    else:
        return HttpResponseBadRequest('Missing path or app parameter')

    if not target_app:
        return HttpResponseBadRequest('Missing app parameter')

    # Validate app name
    # All apps accept file imports:
    # - Imager: accepts prompt files (.txt/.json/.yaml) and reference images
    valid_apps = ['anonymizer', 'describer', 'enhancer', 'imager', 'reader', 'synthesizer', 'transcriber', 'face_analyzer', 'cam_analyzer']
    if target_app not in valid_apps:
        return JsonResponse({'error': f'Invalid app: {target_app}'}, status=400)

    def _import_single_file(fp):
        """Import a single file path into target_app. Returns result dict."""
        # Security check
        if not is_path_allowed(fp, user):
            return {'error': 'Access denied'}

        if fp.startswith('mounts/'):
            source_path, _mount = resolve_mount_path(fp, user)
            if source_path is None:
                return {'error': 'Access denied'}
        else:
            source_path = Path(settings.MEDIA_ROOT) / fp

        if not source_path.exists():
            return {'error': 'Source file not found'}

        try:
            if target_app == 'anonymizer':
                return import_to_anonymizer(source_path, user)
            elif target_app == 'describer':
                return import_to_describer(source_path, user)
            elif target_app == 'enhancer':
                return import_to_enhancer(source_path, user)
            elif target_app == 'imager':
                return import_to_imager(source_path, user)
            elif target_app == 'synthesizer':
                return import_to_synthesizer(source_path, user)
            elif target_app == 'reader':
                return import_to_reader(source_path, user)
            elif target_app == 'transcriber':
                return import_to_transcriber(source_path, user)
            elif target_app == 'face_analyzer':
                return import_to_face_analyzer(source_path, user)
            elif target_app == 'cam_analyzer':
                return import_to_cam_analyzer(source_path, user)
            else:
                return {'error': 'App not supported'}
        except Exception as e:
            logger.error(f"Error importing {fp} to {target_app}: {e}")
            return {'error': str(e)}

    results = []
    errors = []

    for fp in file_paths:
        result = _import_single_file(fp)
        if 'error' in result:
            errors.append({'path': fp, 'error': result['error']})
        else:
            results.append(result)

    # Reader multi-file: consolidate into ONE batch (remove individual batch-of-1 wrappers)
    if target_app == 'reader' and len(results) > 1:
        try:
            from wama.reader.models import ReadingItem, BatchReadingItem, BatchReadingItemLink
            item_ids = [r['id'] for r in results if r.get('id')]
            if len(item_ids) > 1:
                # Delete the individual batch-of-1 wrappers created by import_to_reader
                links = BatchReadingItemLink.objects.filter(
                    reading_id__in=item_ids, batch__total=1
                ).select_related('batch')
                batch_ids_to_delete = list(links.values_list('batch_id', flat=True))
                links.delete()
                BatchReadingItem.objects.filter(id__in=batch_ids_to_delete, total=1).delete()
                # Create ONE batch for all items
                items = list(ReadingItem.objects.filter(id__in=item_ids))
                batch = BatchReadingItem.objects.create(user=user, total=len(items))
                for i, item in enumerate(items):
                    BatchReadingItemLink.objects.create(batch=batch, reading=item, row_index=i)
        except Exception as e:
            logger.warning(f"[filemanager] reader batch consolidation failed: {e}")

    if len(file_paths) == 1:
        # Backward compatibility: single path → return single result
        if results:
            return JsonResponse(results[0])
        return JsonResponse({'imported': False, 'error': errors[0]['error'] if errors else 'Unknown error'})
    else:
        return JsonResponse({
            'imported': len(results) > 0,
            'count': len(results),
            'results': results,
            'errors': errors,
        })


def import_to_describer(source_path, user):
    """Import a file to Describer app."""
    from wama.describer.models import Description
    from wama.common.utils.media_paths import get_app_media_path
    import shutil

    # Copy file to user-specific describer input folder
    dest_dir = get_app_media_path('describer', user.id, 'input')
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_path = dest_dir / source_path.name

    # Handle duplicate names
    if dest_path.exists():
        stem = dest_path.stem
        suffix = dest_path.suffix
        counter = 1
        while dest_path.exists():
            dest_path = dest_dir / f"{stem}_{counter}{suffix}"
            counter += 1

    shutil.copy2(source_path, dest_path)

    # Create Description record with user-specific path
    relative_path = f'describer/{user.id}/input/{dest_path.name}'

    description = Description.objects.create(user=user)
    description.input_file.name = relative_path
    description.filename = dest_path.name
    description.file_size = dest_path.stat().st_size
    description.save()

    return {
        'imported': True,
        'app': 'describer',
        'id': description.id,
        'filename': dest_path.name,
        'path': relative_path,
    }


def import_to_enhancer(source_path, user):
    """Import a file to Enhancer app (image, video, or audio)."""
    from wama.common.utils.media_paths import get_app_media_path
    import shutil

    image_extensions = {'.jpg', '.jpeg', '.png', '.bmp', '.tif', '.tiff', '.webp', '.heic'}
    video_extensions = {'.mp4', '.webm', '.mkv', '.flv', '.gif', '.avi', '.mov', '.mpg', '.qt', '.3gp'}
    audio_extensions = {'.mp3', '.wav', '.flac', '.ogg', '.m4a', '.aac', '.opus', '.wma'}

    ext = source_path.suffix.lower()

    if ext in audio_extensions:
        # ── Audio ─────────────────────────────────────────────────────────────
        from wama.enhancer.models import AudioEnhancement

        dest_dir = get_app_media_path('enhancer', user.id, 'input/audio')
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest_path = dest_dir / source_path.name
        if dest_path.exists():
            stem, suffix, counter = dest_path.stem, dest_path.suffix, 1
            while dest_path.exists():
                dest_path = dest_dir / f"{stem}_{counter}{suffix}"
                counter += 1
        shutil.copy2(source_path, dest_path)

        duration = 0.0
        file_size = dest_path.stat().st_size
        try:
            from wama.common.utils.video_utils import get_media_info
            info = get_media_info(str(dest_path))
            duration = info.get('duration', 0.0)
            file_size = info.get('file_size', file_size)
        except Exception:
            pass

        relative_path = f'enhancer/{user.id}/input/audio/{dest_path.name}'
        ae = AudioEnhancement.objects.create(user=user, duration=duration, file_size=file_size)
        ae.input_file.name = relative_path
        ae.save()
        return {
            'imported': True, 'app': 'enhancer', 'media_type': 'audio',
            'id': ae.id, 'filename': dest_path.name,
            'duration': duration, 'status': ae.status, 'progress': ae.progress,
            'path': relative_path,
        }

    elif ext in image_extensions or ext in video_extensions:
        # ── Image / Video ─────────────────────────────────────────────────────
        from wama.enhancer.models import Enhancement
        from wama.common.utils.video_utils import get_media_info

        media_type = 'image' if ext in image_extensions else 'video'
        dest_dir = get_app_media_path('enhancer', user.id, 'input/media')
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest_path = dest_dir / source_path.name
        if dest_path.exists():
            stem, suffix, counter = dest_path.stem, dest_path.suffix, 1
            while dest_path.exists():
                dest_path = dest_dir / f"{stem}_{counter}{suffix}"
                counter += 1
        shutil.copy2(source_path, dest_path)

        media_info = get_media_info(str(dest_path))
        relative_path = f'enhancer/{user.id}/input/media/{dest_path.name}'
        enhancement = Enhancement.objects.create(
            user=user, media_type=media_type,
            width=media_info['width'], height=media_info['height'],
            duration=media_info['duration'], file_size=media_info['file_size'],
        )
        enhancement.input_file.name = relative_path
        enhancement.save()
        return {
            'imported': True, 'app': 'enhancer', 'media_type': media_type,
            'id': enhancement.id, 'filename': dest_path.name,
            'path': relative_path,
            'width': media_info['width'], 'height': media_info['height'],
        }

    else:
        raise ValueError(f"Unsupported file format: {ext}")


def import_to_imager(source_path, user):
    """
    Import a file to Imager app.
    Supports:
    - Text files (.txt, .json, .yaml, .yml) -> batch prompts
    - Image files -> reference images for img2img/style/describe modes
    """
    from wama.imager.models import ImageGeneration
    from wama.common.utils.media_paths import get_app_media_path
    import shutil

    ext = source_path.suffix.lower()

    # Determine file type and destination (user-specific paths)
    if ext in ('.txt', '.json', '.yaml', '.yml'):
        # Prompt file for batch generation
        dest_dir = get_app_media_path('imager', user.id, 'input/prompts')
        file_type = 'prompt_file'
        generation_mode = 'file2img'
        subfolder = 'input/prompts'
    elif ext in ('.jpg', '.jpeg', '.png', '.webp', '.gif', '.bmp'):
        # Reference image for img2img/style/describe
        dest_dir = get_app_media_path('imager', user.id, 'input/references')
        file_type = 'reference_image'
        generation_mode = 'describe2img'  # Default, user can change mode
        subfolder = 'input/references'
    else:
        raise ValueError(f"Format not supported for Imager: {ext}")

    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_path = dest_dir / source_path.name

    # Handle duplicate names
    if dest_path.exists():
        stem = dest_path.stem
        suffix = dest_path.suffix
        counter = 1
        while dest_path.exists():
            dest_path = dest_dir / f"{stem}_{counter}{suffix}"
            counter += 1

    shutil.copy2(source_path, dest_path)

    # Create ImageGeneration record with user-specific path
    relative_path = f'imager/{user.id}/{subfolder}/{dest_path.name}'

    if file_type == 'prompt_file':
        # For prompt files, we just save the file reference
        # The actual batch will be created when user opens Imager
        generation = ImageGeneration.objects.create(
            user=user,
            generation_mode=generation_mode,
            prompt=f'Batch from {dest_path.name} (pending)',
            status='PENDING',
        )
        generation.prompt_file.name = relative_path
        generation.save()
    else:
        # For reference images, create a describe2img generation
        generation = ImageGeneration.objects.create(
            user=user,
            generation_mode=generation_mode,
            prompt='[Awaiting prompt generation]',
            status='PENDING',
        )
        generation.reference_image.name = relative_path
        generation.save()

    return {
        'imported': True,
        'app': 'imager',
        'id': generation.id,
        'type': file_type,
        'mode': generation_mode,
        'filename': dest_path.name,
        'path': relative_path,
    }


def import_to_anonymizer(source_path, user):
    """Import a file to Anonymizer app."""
    from wama.anonymizer.models import Media
    from wama.anonymizer.views import add_media_to_db
    from wama.common.utils.media_paths import get_app_media_path
    from django.core.files import File
    import shutil
    import mimetypes

    # Copy file to user-specific anonymizer input folder
    dest_dir = get_app_media_path('anonymizer', user.id, 'input')
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_path = dest_dir / source_path.name

    # Handle duplicate names
    if dest_path.exists():
        stem = dest_path.stem
        suffix = dest_path.suffix
        counter = 1
        while dest_path.exists():
            dest_path = dest_dir / f"{stem}_{counter}{suffix}"
            counter += 1

    shutil.copy2(source_path, dest_path)

    # Get file extension and determine media type
    file_ext = dest_path.suffix.lower()
    mime_type, _ = mimetypes.guess_type(str(dest_path))

    # Determine initial media type based on mime
    if mime_type and mime_type.startswith('image/'):
        media_type = 'image'
    elif mime_type and mime_type.startswith('video/'):
        media_type = 'video'
    else:
        media_type = 'video'  # Default

    # Create Media record with user-specific path
    relative_path = f'anonymizer/{user.id}/input/{dest_path.name}'

    media = Media.objects.create(
        user=user,
        file=relative_path,
        file_ext=file_ext,
        media_type=media_type,
    )

    # Add metadata (dimensions, fps, duration, etc.)
    try:
        add_media_to_db(media, str(dest_path))
    except Exception as e:
        logger.warning(f"Could not add metadata for {dest_path.name}: {e}")

    return {
        'imported': True,
        'app': 'anonymizer',
        'id': media.id,
        'filename': dest_path.name,
        'path': relative_path,
    }


def import_to_synthesizer(source_path, user):
    """Import a text file to Synthesizer app."""
    from wama.synthesizer.models import VoiceSynthesis
    from wama.common.utils.media_paths import get_app_media_path
    import shutil

    # Validate file extension
    allowed_extensions = ['txt', 'pdf', 'docx', 'csv', 'md']
    ext = source_path.suffix[1:].lower() if source_path.suffix else ''
    if ext not in allowed_extensions:
        raise ValueError(f"Format non supporté. Formats acceptés: {', '.join(allowed_extensions)}")

    # Copy file to user-specific synthesizer input folder
    dest_dir = get_app_media_path('synthesizer', user.id, 'input')
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_path = dest_dir / source_path.name

    # Handle duplicate names
    if dest_path.exists():
        stem = dest_path.stem
        suffix = dest_path.suffix
        counter = 1
        while dest_path.exists():
            dest_path = dest_dir / f"{stem}_{counter}{suffix}"
            counter += 1

    shutil.copy2(source_path, dest_path)

    relative_path = f'synthesizer/{user.id}/input/{dest_path.name}'

    # Batch detection — try to parse as a pipe-separated batch file first
    try:
        from wama.synthesizer.utils.batch_parser import parse_batch_file
        tasks, warnings = parse_batch_file(str(dest_path), default_voice='default', default_speed=1.0)
        if tasks:
            return {
                'imported': True,
                'is_batch': True,
                'app': 'synthesizer',
                'filename': dest_path.name,
                'server_path': relative_path,
                'tasks': tasks,
                'warnings': warnings,
            }
    except Exception:
        pass  # Not a batch file — fall through to normal import

    # Create VoiceSynthesis record with user-specific path
    synthesis = VoiceSynthesis.objects.create(
        user=user,
        tts_model='xtts_v2',
        language='fr',
        voice_preset='default',
        speed=1.0,
        pitch=1.0,
        emotion_intensity=1.0,
    )
    # Set file path directly
    synthesis.text_file.name = relative_path
    synthesis.save()

    # Extract text and update metadata
    try:
        from wama.synthesizer.utils.text_extractor import extract_text_from_file, clean_text_for_tts
        text_content = extract_text_from_file(str(dest_path))
        synthesis.text_content = clean_text_for_tts(text_content)
        synthesis.update_metadata()
    except Exception as e:
        logger.warning(f"Could not extract text from {dest_path}: {e}")
        synthesis.text_content = ""
        synthesis.word_count = 0
        synthesis.save()

    return {
        'imported': True,
        'app': 'synthesizer',
        'filename': dest_path.name,
        'path': relative_path,
        'synthesis_id': synthesis.id,
    }


def import_to_reader(source_path, user):
    """Import a document/image file to Reader (OCR) app."""
    from wama.reader.models import ReadingItem
    from wama.common.utils.media_paths import get_app_media_path
    import shutil

    reader_extensions = {'.pdf', '.jpg', '.jpeg', '.png', '.tiff', '.tif', '.webp', '.bmp'}
    ext = source_path.suffix.lower()
    if ext not in reader_extensions:
        raise ValueError(f"Format non supporté par Reader : {ext}")

    dest_dir = get_app_media_path('reader', user.id, 'input')
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_path = dest_dir / source_path.name

    if dest_path.exists():
        stem, suffix, counter = dest_path.stem, dest_path.suffix, 1
        while dest_path.exists():
            dest_path = dest_dir / f"{stem}_{counter}{suffix}"
            counter += 1

    shutil.copy2(source_path, dest_path)

    relative_path = f'reader/{user.id}/input/{dest_path.name}'
    item = ReadingItem(user=user, original_filename=dest_path.name, status='PENDING')
    item.input_file.name = relative_path
    item.save()

    from wama.reader.views import _wrap_reading_in_batch
    _wrap_reading_in_batch(item)

    return {
        'imported': True,
        'app': 'reader',
        'id': item.id,
        'filename': dest_path.name,
        'path': relative_path,
    }


def import_to_transcriber(source_path, user):
    """Import a file to Transcriber app."""
    from wama.transcriber.models import Transcript
    from wama.common.utils.media_paths import get_app_media_path
    import shutil

    # Copy file to user-specific transcriber input folder
    dest_dir = get_app_media_path('transcriber', user.id, 'input')
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_path = dest_dir / source_path.name

    # Handle duplicate names
    if dest_path.exists():
        stem = dest_path.stem
        suffix = dest_path.suffix
        counter = 1
        while dest_path.exists():
            dest_path = dest_dir / f"{stem}_{counter}{suffix}"
            counter += 1

    shutil.copy2(source_path, dest_path)

    # Create Transcript record with user-specific path
    relative_path = f'transcriber/{user.id}/input/{dest_path.name}'

    transcript = Transcript.objects.create(user=user)
    transcript.audio.name = relative_path
    transcript.save()

    return {
        'imported': True,
        'app': 'transcriber',
        'id': transcript.id,
        'filename': dest_path.name,
        'path': relative_path,
    }


def import_to_face_analyzer(source_path, user):
    """Import a video file to Face Analyzer app."""
    from wama_lab.face_analyzer.models import AnalysisSession
    import shutil

    # Copy file to face_analyzer per-user input folder
    user_id = user.id
    dest_dir = Path(settings.MEDIA_ROOT) / 'face_analyzer' / str(user_id) / 'input'
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_path = dest_dir / source_path.name

    # Handle duplicate names
    if dest_path.exists():
        stem = dest_path.stem
        suffix = dest_path.suffix
        counter = 1
        while dest_path.exists():
            dest_path = dest_dir / f"{stem}_{counter}{suffix}"
            counter += 1

    shutil.copy2(source_path, dest_path)

    # Create AnalysisSession record
    relative_path = f'face_analyzer/{user_id}/input/{dest_path.name}'

    session = AnalysisSession.objects.create(
        user=user,
        mode=AnalysisSession.AnalysisMode.VIDEO,
        status=AnalysisSession.Status.PENDING
    )
    session.input_file.name = relative_path
    session.save()

    return {
        'imported': True,
        'app': 'face_analyzer',
        'id': str(session.id),
        'filename': dest_path.name,
        'path': relative_path,
    }


def import_to_cam_analyzer(source_path, user):
    """Import a video file to Cam Analyzer app (copies to input folder)."""
    import shutil

    user_id = user.id
    dest_dir = Path(settings.MEDIA_ROOT) / 'cam_analyzer' / str(user_id) / 'input'
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_path = dest_dir / source_path.name

    # Handle duplicate names
    if dest_path.exists():
        stem = dest_path.stem
        suffix = dest_path.suffix
        counter = 1
        while dest_path.exists():
            dest_path = dest_dir / f"{stem}_{counter}{suffix}"
            counter += 1

    shutil.copy2(source_path, dest_path)

    relative_path = f'cam_analyzer/{user_id}/input/{dest_path.name}'

    return {
        'imported': True,
        'app': 'cam_analyzer',
        'filename': dest_path.name,
        'path': relative_path,
    }


# ── Mounted Folders API ────────────────────────────────────────────────────────

def _parse_unc_path(path_str):
    """
    Detect and parse a UNC path (\\server\share\sub or //server/share/sub).
    Returns {'server', 'share', 'subpath'} or None if not UNC.
    """
    import re
    p = path_str.strip().replace('\\', '/')
    m = re.match(r'^//([^/]+)/([^/]+)(/.*)?$', p)
    if not m:
        return None
    return {
        'server':  m.group(1),
        'share':   m.group(2),
        'subpath': (m.group(3) or '').lstrip('/'),
    }


def _try_cifs_mount(server, share, subpath='', username=None, password=None, domain=None):
    """
    Mount an SMB/CIFS share on Linux/WSL2 under /mnt/wama_mounts/<server>_<share>/.
    Tries guest access when no credentials are provided.

    Returns (success: bool, linux_path: str | None, error: str | None)
    Special error value 'AUTH_REQUIRED' means credentials are needed.
    """
    import subprocess, os, re, sys

    if not sys.platform.startswith('linux'):
        return False, None, 'CIFS auto-mount uniquement sur Linux/WSL2.'

    # Sanitise mount point name
    safe = re.sub(r'[^\w_-]', '_', f'{server}_{share}')
    mount_base = Path('/mnt/wama_mounts')
    mount_point = mount_base / safe

    try:
        mount_point.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        return False, None, f'Impossible de créer le point de montage : {e}'

    # Already mounted?
    check = subprocess.run(['mountpoint', '-q', str(mount_point)], capture_output=True)
    if check.returncode == 0:
        linux_path = str(mount_point / subpath) if subpath else str(mount_point)
        return True, linux_path, None

    # Build CIFS options
    uid = os.getuid()
    gid = os.getgid()
    opts = [f'uid={uid}', f'gid={gid}', 'vers=3.0', 'nounix']
    if username:
        opts.append(f'username={username}')
        opts.append(f'password={password or ""}')
        if domain:
            opts.append(f'domain={domain}')
    else:
        opts.append('guest')

    cmd = ['sudo', 'mount', '-t', 'cifs',
           f'//{server}/{share}', str(mount_point),
           '-o', ','.join(opts)]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
        if result.returncode == 0:
            linux_path = str(mount_point / subpath) if subpath else str(mount_point)
            return True, linux_path, None
        err = (result.stderr.strip() or result.stdout.strip() or 'Erreur de montage inconnue')
        # Detect authentication failures
        if any(k in err for k in ('Permission denied', 'NT_STATUS_LOGON_FAILURE',
                                   'NT_STATUS_ACCESS_DENIED', 'ERRDOS', 'Invalid argument')):
            return False, None, 'AUTH_REQUIRED'
        return False, None, err
    except subprocess.TimeoutExpired:
        return False, None, 'Timeout lors du montage CIFS (20 s).'
    except FileNotFoundError:
        return False, None, (
            'mount.cifs introuvable. Installez cifs-utils : sudo apt install cifs-utils\n'
            'Et autorisez le montage sans mot de passe :\n'
            '  echo "$(whoami) ALL=(ALL) NOPASSWD: /bin/mount -t cifs *" | sudo tee /etc/sudoers.d/wama-cifs'
        )
    except Exception as e:
        return False, None, str(e)


def _resolve_path(path_str):
    """Convert any path format (Windows absolute, UNC, Linux) to a server-accessible path.
    Handles WSL environment transparently via wslpath when available.
    """
    import sys
    import subprocess

    p = path_str.strip()
    if not p:
        return p

    # Normalise backslashes for analysis
    p_fwd = p.replace('\\', '/')

    if sys.platform.startswith('linux'):
        # Running in WSL2 — Windows/UNC paths must be converted via wslpath.
        # Check BEFORE the `startswith('/')` guard: a UNC path like \\server\share
        # becomes //server/share after normalisation, which starts with '/' but is
        # NOT a native Linux path.
        is_windows_drive = len(p_fwd) >= 3 and p_fwd[1] == ':'
        # UNC: original had backslashes OR normalised to //server/... (but not ///...)
        is_unc = '\\' in p or (p_fwd.startswith('//') and len(p_fwd) > 2 and p_fwd[2] not in ('/', ' '))

        if is_windows_drive or is_unc:
            # Try wslpath first (handles both drive letters and UNC shares)
            try:
                result = subprocess.run(
                    ['wslpath', p],
                    capture_output=True, text=True, timeout=5
                )
                if result.returncode == 0 and result.stdout.strip():
                    return result.stdout.strip()
            except Exception:
                pass

            # Manual fallback: drive letter C:\... → /mnt/c/...
            if is_windows_drive:
                drive = p_fwd[0].lower()
                rest = p_fwd[3:]
                return f'/mnt/{drive}/{rest}'

            # UNC path with no wslpath result — return as-is (will fail isdir;
            # user must mount the CIFS share in WSL2 first)
            return p_fwd

        # Already a native Linux absolute path
        if p_fwd.startswith('/'):
            return p_fwd

    else:
        # Native Windows: //server/share is a valid UNC representation
        if p_fwd.startswith('/'):
            return p_fwd

    # Fallback: normalise to forward slashes
    return p_fwd


@require_GET
def api_find_folder(request):
    """Find a server-side folder path by name + file fingerprint.
    Called after the browser folder-picker gives us the folder name and a few file names/sizes.
    Query params:
      name  : folder name (e.g. "MEDIAS")
      files : comma-separated "filename:size" pairs for fingerprinting
    Returns: {path, found}
    """
    import threading

    folder_name = request.GET.get('name', '').strip()
    files_param = request.GET.get('files', '').strip()

    if not folder_name:
        return JsonResponse({'path': None, 'found': False})

    # Parse fingerprint: {"filename": size_in_bytes, ...}
    fingerprint = {}
    for item in files_param.split(','):
        item = item.strip()
        if ':' in item:
            fname, _, fsize = item.rpartition(':')
            try:
                fingerprint[fname.strip()] = int(fsize)
            except ValueError:
                pass

    # Roots to search (WSL mounts, home, project area)
    candidate_roots = ['/mnt', '/home', '/data', str(Path(settings.BASE_DIR).parent)]
    search_roots = [r for r in candidate_roots if Path(r).is_dir()]

    def folder_matches(dirpath):
        if not fingerprint:
            return True
        needed = min(2, len(fingerprint))
        matched = 0
        for fname, fsize in list(fingerprint.items())[:5]:
            try:
                fp = Path(dirpath) / fname
                if fp.is_file() and fp.stat().st_size == fsize:
                    matched += 1
                    if matched >= needed:
                        return True
            except OSError:
                pass
        return False

    found_path = None

    def search(root, depth=0):
        nonlocal found_path
        if found_path or depth > 7:
            return
        try:
            with os.scandir(root) as entries:
                for entry in entries:
                    if found_path:
                        return
                    if not entry.is_dir(follow_symlinks=False):
                        continue
                    if entry.name.startswith('.'):
                        continue
                    if entry.name == folder_name and folder_matches(entry.path):
                        found_path = entry.path
                        return
                    try:
                        search(entry.path, depth + 1)
                    except (PermissionError, OSError):
                        pass
        except (PermissionError, OSError):
            pass

    def run():
        for root in search_roots:
            if found_path:
                return
            search(root)

    t = threading.Thread(target=run, daemon=True)
    t.start()
    t.join(timeout=8)

    if found_path:
        return JsonResponse({'path': found_path, 'found': True})
    return JsonResponse({'path': None, 'found': False})


@require_GET
def api_validate_path(request):
    """Validate and resolve a user-provided path (Windows/UNC/Linux).
    Returns: {resolved, accessible, name, is_smb?, smb_server?, smb_share?, smb_subpath?, smb_hint?}
    """
    import os, sys
    path_str = request.GET.get('path', '').strip()
    if not path_str:
        return JsonResponse({'resolved': '', 'accessible': False, 'name': ''})

    resolved = _resolve_path(path_str)
    try:
        accessible = os.path.isdir(resolved)
    except Exception:
        accessible = False

    last = path_str.replace('\\', '/').rstrip('/').rsplit('/', 1)[-1]
    response = {'resolved': resolved, 'accessible': accessible, 'name': last}

    # Detect SMB/UNC network path
    unc = _parse_unc_path(path_str)
    if unc:
        response.update({
            'is_smb':      True,
            'smb_server':  unc['server'],
            'smb_share':   unc['share'],
            'smb_subpath': unc['subpath'],
        })
        if not accessible and sys.platform.startswith('linux'):
            response['smb_hint'] = (
                'Partage réseau détecté. Entrez vos identifiants AD pour le monter automatiquement '
                '(laissez vide pour tenter un accès invité).'
            )

    return JsonResponse(response)


@require_GET
def api_browse_fs(request):
    """Return subdirectories of a server path for the in-browser folder picker.
    Query param: ?path=<absolute_path>  (defaults to a sensible root)
    Returns: {path, parent, parts (breadcrumb), dirs}
    """
    import sys

    raw = request.GET.get('path', '').strip()

    # Default starting point
    if not raw:
        if sys.platform.startswith('linux'):
            raw = '/mnt'
        else:
            import os
            raw = os.path.expanduser('~')

    target = Path(raw).resolve()

    # Safety: never expose root dirs on Linux that expose system internals
    # Only allow if the user is admin, or the path is under known safe roots
    user = get_user(request)
    from wama.accounts.views import is_admin
    SAFE_PREFIXES = [
        Path('/mnt'),
        Path('/home'),
        Path('/tmp'),
        Path(settings.MEDIA_ROOT),
        Path(settings.BASE_DIR),
    ]
    if not is_admin(user):
        if not any(str(target).startswith(str(p)) for p in SAFE_PREFIXES):
            return JsonResponse({'error': 'Accès refusé'}, status=403)

    if not target.exists() or not target.is_dir():
        return JsonResponse({'error': f'Dossier introuvable : {target}'}, status=404)

    # List subdirectories (non-hidden, sorted)
    try:
        dirs = sorted(
            [d.name for d in target.iterdir()
             if d.is_dir() and not d.name.startswith('.')]
        )
    except PermissionError:
        dirs = []

    # Breadcrumb parts: list of {name, path}
    parts = [{'name': p or '/', 'path': str(Path(*target.parts[:i+1]))}
             for i, p in enumerate(target.parts)]

    parent = str(target.parent) if target != target.parent else None

    return JsonResponse({
        'path': str(target),
        'parent': parent,
        'parts': parts,
        'dirs': dirs,
    })


@require_http_methods(["GET", "POST"])
def api_mounts(request):
    """GET: list user's mounted folders. POST: add a new mount."""
    user = get_user(request)

    if request.method == 'GET':
        mounts = list(
            MountedFolder.objects.filter(user=user).values('id', 'name', 'local_path', 'created_at')
        )
        return JsonResponse({'mounts': mounts})

    # POST — add a new mount
    try:
        data = json.loads(request.body)
        name = data.get('name', '').strip()
        local_path = data.get('local_path', '').strip()
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'error': 'JSON invalide'}, status=400)

    if not name or not local_path:
        return JsonResponse({'error': 'Nom et chemin requis'}, status=400)

    smb_username = data.get('smb_username', '').strip()
    smb_password = data.get('smb_password', '').strip()
    smb_domain   = data.get('smb_domain',   '').strip()

    import sys, os
    unc = _parse_unc_path(local_path)
    smb_config = None

    if unc and sys.platform.startswith('linux'):
        # Auto-mount the CIFS share, then store the Linux path
        success, linux_path, error = _try_cifs_mount(
            unc['server'], unc['share'], unc['subpath'],
            username=smb_username or None,
            password=smb_password or None,
            domain=smb_domain or None,
        )
        if not success:
            if error == 'AUTH_REQUIRED':
                return JsonResponse(
                    {'error': 'Authentification requise pour ce partage.', 'needs_auth': True},
                    status=401,
                )
            return JsonResponse({'error': error or 'Impossible de monter le partage.'}, status=400)

        resolved = linux_path
        smb_config = {
            'server':   unc['server'],
            'share':    unc['share'],
            'subpath':  unc['subpath'],
            'username': smb_username or None,
            'domain':   smb_domain or None,
            'guest':    not smb_username,
        }
    else:
        resolved = _resolve_path(local_path)
        resolved_path = Path(resolved)
        # Allow saving even if temporarily offline
        if resolved_path.exists() and not resolved_path.is_dir():
            return JsonResponse({'error': 'Le chemin doit pointer vers un dossier.'}, status=400)

    mount = MountedFolder.objects.create(
        user=user, name=name, local_path=resolved, smb_config=smb_config
    )
    return JsonResponse({'success': True, 'id': mount.id, 'name': mount.name})


@require_GET
def api_remount_shares(request):
    """
    Re-mount all WAMA-managed CIFS shares (called from start_wama_prod.sh via localhost).
    Only accessible from 127.0.0.1 or by superusers.
    """
    import sys
    addr = request.META.get('REMOTE_ADDR', '')
    if not (request.user.is_superuser or addr in ('127.0.0.1', '::1')):
        return JsonResponse({'error': 'Forbidden'}, status=403)

    if not sys.platform.startswith('linux'):
        return JsonResponse({'remounted': 0, 'skipped': 0, 'errors': []})

    remounted, skipped, errors = 0, 0, []
    for mount in MountedFolder.objects.exclude(smb_config=None):
        cfg = mount.smb_config or {}
        server  = cfg.get('server', '')
        share   = cfg.get('share', '')
        subpath = cfg.get('subpath', '')
        if not server or not share:
            skipped += 1
            continue
        # Only auto-remount guest mounts (no stored password)
        if not cfg.get('guest', True):
            errors.append({'mount': mount.name, 'info': 'Credentials requis — reconnectez depuis l\'interface.'})
            skipped += 1
            continue
        success, linux_path, error = _try_cifs_mount(server, share, subpath)
        if success:
            remounted += 1
            # Update stored path in case mount point changed
            if linux_path and linux_path != mount.local_path:
                mount.local_path = linux_path
                mount.save(update_fields=['local_path'])
        else:
            skipped += 1
            errors.append({'mount': mount.name, 'error': error})

    logger.warning(f'[Filemanager] api_remount_shares: remounted={remounted} skipped={skipped}')
    return JsonResponse({'remounted': remounted, 'skipped': skipped, 'errors': errors})


@require_POST
def api_mount_delete(request, pk):
    """Remove a mounted folder."""
    user = get_user(request)
    try:
        mount = MountedFolder.objects.get(pk=pk, user=user)
        mount.delete()
        return JsonResponse({'success': True})
    except MountedFolder.DoesNotExist:
        return JsonResponse({'error': 'Non trouvé'}, status=404)


@require_GET
def api_mount_serve(request, pk, path):
    """Serve a file from a mounted folder inline (for preview)."""
    user = get_user(request)
    try:
        mount = MountedFolder.objects.get(pk=pk, user=user)
    except MountedFolder.DoesNotExist:
        return JsonResponse({'error': 'Access denied'}, status=403)

    base = Path(mount.local_path)
    if path:
        if '..' in Path(path).parts:
            return JsonResponse({'error': 'Invalid path'}, status=400)
        target = base / path
    else:
        return JsonResponse({'error': 'No file specified'}, status=400)

    if not target.exists() or not target.is_file():
        return JsonResponse({'error': 'File not found'}, status=404)

    try:
        mime_type = mimetypes.guess_type(target.name)[0] or 'application/octet-stream'
        response = FileResponse(open(target, 'rb'), content_type=mime_type)
        response['Content-Disposition'] = f'inline; filename="{target.name}"'
        return response
    except Exception as e:
        logger.error(f"Error serving mount file {target}: {e}")
        return JsonResponse({'error': str(e)}, status=500)
