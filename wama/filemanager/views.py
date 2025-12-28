"""
FileManager views - API for file browsing and management.
"""
import os
import json
import mimetypes
import logging
from pathlib import Path

from django.conf import settings
from django.http import JsonResponse, FileResponse, HttpResponseBadRequest
from django.views.decorators.http import require_POST, require_GET
from django.core.files.storage import default_storage

from .models import UserFile
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
    Build a file tree structure for jstree.
    Includes files from:
    - users/{user_id}/temp/ (filemanager uploads)
    - enhancer/input/, enhancer/output/
    - anonymizer/input/, anonymizer/output/
    - synthesizer/, transcriber/, etc.
    """
    tree = []
    media_root = Path(settings.MEDIA_ROOT)
    user_id = user.id

    # Define folders to scan (user-specific paths)
    folders_config = [
        {
            'id': 'temp',
            'text': 'Mes fichiers temporaires',
            'icon': 'fa fa-folder text-warning',
            'path': f'users/{user_id}/temp',
            'type': 'folder'
        },
        {
            'id': 'enhancer',
            'text': 'Enhancer',
            'icon': 'fa fa-magic text-info',
            'children': [
                {'id': 'enhancer_input', 'text': 'Input', 'path': 'enhancer/input', 'icon': 'fa fa-folder text-secondary'},
                {'id': 'enhancer_output', 'text': 'Output', 'path': 'enhancer/output', 'icon': 'fa fa-folder text-success'},
            ]
        },
        {
            'id': 'anonymizer',
            'text': 'Anonymizer',
            'icon': 'fa fa-user-secret text-danger',
            'children': [
                {'id': 'anonymizer_input', 'text': 'Input', 'path': 'anonymizer/input', 'icon': 'fa fa-folder text-secondary'},
                {'id': 'anonymizer_output', 'text': 'Output', 'path': 'anonymizer/output', 'icon': 'fa fa-folder text-success'},
            ]
        },
        {
            'id': 'synthesizer',
            'text': 'Synthesizer',
            'icon': 'fa fa-microphone text-primary',
            'children': [
                {'id': 'synthesizer_input', 'text': 'Input', 'path': 'synthesizer/input', 'icon': 'fa fa-folder text-secondary'},
                {'id': 'synthesizer_output', 'text': 'Output', 'path': 'synthesizer/output', 'icon': 'fa fa-folder text-success'},
            ]
        },
        {
            'id': 'transcriber',
            'text': 'Transcriber',
            'icon': 'fa fa-file-alt text-warning',
            'children': [
                {'id': 'transcriber_input', 'text': 'Input', 'path': 'transcriber/input', 'icon': 'fa fa-folder text-secondary'},
                {'id': 'transcriber_output', 'text': 'Output', 'path': 'transcriber/output', 'icon': 'fa fa-folder text-success'},
            ]
        },
        {
            'id': 'imager',
            'text': 'Imager',
            'icon': 'fa fa-image text-success',
            'children': [
                {'id': 'imager_output', 'text': 'Output', 'path': f'imager/outputs/{user_id}', 'icon': 'fa fa-folder text-success'},
            ]
        },
    ]

    for folder_config in folders_config:
        node = build_folder_node(folder_config, media_root, user_id)
        if node:
            tree.append(node)

    return tree


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
        # This is a leaf folder - scan for files
        folder_path = media_root / config['path']
        if folder_path.exists():
            node['data'] = {'path': config['path']}
            node['children'] = scan_folder_files(folder_path, config['path'], user_id)
    elif 'children' in config:
        # This is a parent folder with sub-folders
        for child_config in config['children']:
            child_node = build_folder_node(child_config, media_root, user_id)
            if child_node:
                node['children'].append(child_node)

    return node


def scan_folder_files(folder_path, relative_path, user_id):
    """Scan a folder for files and return jstree nodes."""
    files = []
    try:
        for item in sorted(folder_path.iterdir()):
            if item.is_file():
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

                files.append({
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

    return files


@require_GET
def api_tree(request):
    """Get file tree for jstree."""
    user = get_user(request)
    tree = build_file_tree(user)
    return JsonResponse(tree, safe=False)


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
        'enhancer/input',
        'enhancer/output',
        'anonymizer/input',
        'anonymizer/output',
        'synthesizer/input',
        'synthesizer/output',
        'transcriber/input',
        'transcriber/output',
        f'imager/outputs/{user.id}',
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
    """Upload file(s) to user's temp folder."""
    user = get_user(request)
    files = request.FILES.getlist('files')

    if not files:
        return HttpResponseBadRequest('No files provided')

    uploaded = []
    for file in files:
        try:
            # Create UserFile record
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

    return JsonResponse({'uploaded': uploaded, 'count': len(uploaded)})


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


def api_download(request, path):
    """Download a file."""
    user = get_user(request)

    # Security check
    if not is_path_allowed(path, user):
        return JsonResponse({'error': 'Access denied'}, status=403)

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

    full_path = Path(settings.MEDIA_ROOT) / file_path

    if not full_path.exists():
        return JsonResponse({'error': 'File not found'}, status=404)

    mime_type = mimetypes.guess_type(full_path.name)[0] or ''

    # For images and videos, return the media URL
    if mime_type.startswith(('image/', 'video/', 'audio/')):
        media_url = f"{settings.MEDIA_URL}{file_path}"
        return JsonResponse({
            'preview_url': media_url,
            'mime': mime_type,
            'name': full_path.name,
        })
    else:
        return JsonResponse({
            'preview_url': None,
            'mime': mime_type,
            'name': full_path.name,
            'message': 'Preview not available for this file type'
        })


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
        'enhancer/',
        'anonymizer/',
        'synthesizer/',
        'transcriber/',
        'imager/',
    ]

    for prefix in allowed_prefixes:
        if path.startswith(prefix):
            return True

    return False


@require_POST
def api_import_to_app(request):
    """
    Import a file from FileManager to an app's input folder.
    This copies the file and creates the app-specific record.
    """
    import shutil
    from django.core.files import File

    user = get_user(request)

    try:
        data = json.loads(request.body)
        file_path = data.get('path', '')
        target_app = data.get('app', '')
    except (json.JSONDecodeError, ValueError):
        return HttpResponseBadRequest('Invalid JSON')

    if not file_path or not target_app:
        return HttpResponseBadRequest('Missing path or app parameter')

    # Validate app name
    valid_apps = ['enhancer', 'anonymizer', 'synthesizer', 'transcriber']
    if target_app not in valid_apps:
        return JsonResponse({'error': f'Invalid app: {target_app}'}, status=400)

    # Security check
    if not is_path_allowed(file_path, user):
        return JsonResponse({'error': 'Access denied'}, status=403)

    source_path = Path(settings.MEDIA_ROOT) / file_path

    if not source_path.exists():
        return JsonResponse({'error': 'Source file not found'}, status=404)

    try:
        # Import based on target app
        if target_app == 'enhancer':
            result = import_to_enhancer(source_path, user)
        elif target_app == 'anonymizer':
            result = import_to_anonymizer(source_path, user)
        elif target_app == 'synthesizer':
            result = import_to_synthesizer(source_path, user)
        elif target_app == 'transcriber':
            result = import_to_transcriber(source_path, user)
        else:
            return JsonResponse({'error': 'App not supported'}, status=400)

        return JsonResponse(result)
    except Exception as e:
        logger.error(f"Error importing {file_path} to {target_app}: {e}")
        return JsonResponse({'error': str(e)}, status=500)


def import_to_enhancer(source_path, user):
    """Import a file to Enhancer app."""
    from wama.enhancer.models import Enhancement
    from django.core.files import File
    import shutil

    # Copy file to enhancer input folder
    dest_dir = Path(settings.MEDIA_ROOT) / 'enhancer' / 'input'
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

    # Create Enhancement record
    relative_path = f'enhancer/input/{dest_path.name}'

    with open(dest_path, 'rb') as f:
        enhancement = Enhancement.objects.create(
            user=user,
            input_file=File(f, name=dest_path.name),
        )

    return {
        'imported': True,
        'app': 'enhancer',
        'id': enhancement.id,
        'filename': dest_path.name,
        'path': relative_path,
    }


def import_to_anonymizer(source_path, user):
    """Import a file to Anonymizer app."""
    from wama.anonymizer.models import Media
    from wama.anonymizer.views import add_media_to_db
    from django.core.files import File
    import shutil
    import mimetypes

    # Copy file to anonymizer input folder
    dest_dir = Path(settings.MEDIA_ROOT) / 'anonymizer' / 'input'
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

    # Create Media record with proper fields
    relative_path = f'anonymizer/input/{dest_path.name}'

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
    """Import a file to Synthesizer app (for voice samples)."""
    # Synthesizer may handle this differently - just copy for now
    import shutil

    dest_dir = Path(settings.MEDIA_ROOT) / 'synthesizer' / 'input'
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_path = dest_dir / source_path.name

    if dest_path.exists():
        stem = dest_path.stem
        suffix = dest_path.suffix
        counter = 1
        while dest_path.exists():
            dest_path = dest_dir / f"{stem}_{counter}{suffix}"
            counter += 1

    shutil.copy2(source_path, dest_path)

    return {
        'imported': True,
        'app': 'synthesizer',
        'filename': dest_path.name,
        'path': f'synthesizer/input/{dest_path.name}',
    }


def import_to_transcriber(source_path, user):
    """Import a file to Transcriber app."""
    from wama.transcriber.models import Transcript
    from django.core.files import File
    import shutil

    # Copy file to transcriber input folder
    dest_dir = Path(settings.MEDIA_ROOT) / 'transcriber' / 'input'
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

    # Create Transcript record
    relative_path = f'transcriber/input/{dest_path.name}'

    with open(dest_path, 'rb') as f:
        transcript = Transcript.objects.create(
            user=user,
            audio_file=File(f, name=dest_path.name),
        )

    return {
        'imported': True,
        'app': 'transcriber',
        'id': transcript.id,
        'filename': dest_path.name,
        'path': relative_path,
    }
