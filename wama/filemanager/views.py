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
            'id': 'anonymizer',
            'text': 'Anonymizer',
            'icon': 'fa fa-user-secret text-danger',
            'children': [
                {'id': 'anonymizer_input', 'text': 'Input', 'path': 'anonymizer/input', 'icon': 'fa fa-folder text-secondary'},
                {'id': 'anonymizer_output', 'text': 'Output', 'path': 'anonymizer/output', 'icon': 'fa fa-folder text-success'},
            ]
        },
        {
            'id': 'describer',
            'text': 'Describer',
            'icon': 'fa fa-search-plus text-info',
            'children': [
                {'id': 'describer_input', 'text': 'Input', 'path': 'describer/input', 'icon': 'fa fa-folder text-secondary'},
                {'id': 'describer_output', 'text': 'Output', 'path': 'describer/output', 'icon': 'fa fa-folder text-success'},
            ]
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
            'id': 'imager',
            'text': 'Imager',
            'icon': 'fa fa-image text-success',
            'children': [
                {'id': 'imager_prompts', 'text': 'Prompts', 'path': 'imager/input/prompts', 'icon': 'fa fa-file-alt text-secondary'},
                {'id': 'imager_references', 'text': 'References', 'path': 'imager/input/references', 'icon': 'fa fa-image text-secondary'},
                {'id': 'imager_output_image', 'text': 'Images', 'path': f'imager/output/image/{user_id}', 'icon': 'fa fa-image text-success'},
                {'id': 'imager_output_video', 'text': 'Vidéos', 'path': f'imager/output/video/{user_id}', 'icon': 'fa fa-film text-success'},
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
        # WAMA Lab applications
        {
            'id': 'face_analyzer',
            'text': 'Face Analyzer',
            'icon': 'fa fa-smile text-info',
            'children': [
                {'id': 'face_analyzer_input', 'text': 'Input', 'path': 'face_analyzer/input', 'icon': 'fa fa-folder text-secondary'},
                {'id': 'face_analyzer_output', 'text': 'Output', 'path': 'face_analyzer/output', 'icon': 'fa fa-folder text-success'},
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
        'anonymizer/input',
        'anonymizer/output',
        'describer/input',
        'describer/output',
        'enhancer/input',
        'enhancer/output',
        f'imager/output/image/{user.id}',
        f'imager/output/video/{user.id}',
        'synthesizer/input',
        'synthesizer/output',
        'transcriber/input',
        'transcriber/output',
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
    ext = full_path.suffix.lower()

    # For images, videos and audio, return the media URL
    if mime_type.startswith(('image/', 'video/', 'audio/')):
        media_url = f"{settings.MEDIA_URL}{file_path}"
        return JsonResponse({
            'preview_url': media_url,
            'mime': mime_type,
            'name': full_path.name,
        })

    # For text files, extract and return the content
    text_extensions = ['.txt', '.md', '.csv', '.pdf', '.docx']
    if ext in text_extensions:
        try:
            from wama.synthesizer.utils.text_extractor import extract_text_from_file
            text_content = extract_text_from_file(str(full_path))
            # Limit preview to first 10000 characters
            if len(text_content) > 10000:
                text_content = text_content[:10000] + '\n\n... [Contenu tronqué]'
            return JsonResponse({
                'preview_url': None,
                'mime': 'text/plain',
                'name': full_path.name,
                'text_content': text_content,
                'original_mime': mime_type,
            })
        except Exception as e:
            logger.error(f"Error extracting text from {full_path}: {e}")
            return JsonResponse({
                'preview_url': None,
                'mime': mime_type,
                'name': full_path.name,
                'error': f'Erreur lors de la lecture: {str(e)}'
            })

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
        'anonymizer/',
        'describer/',
        'enhancer/',
        'imager/',
        'synthesizer/',
        'transcriber/',
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
    # All apps accept file imports:
    # - Imager: accepts prompt files (.txt/.json/.yaml) and reference images
    valid_apps = ['anonymizer', 'describer', 'enhancer', 'imager', 'synthesizer', 'transcriber']
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
        if target_app == 'anonymizer':
            result = import_to_anonymizer(source_path, user)
        elif target_app == 'describer':
            result = import_to_describer(source_path, user)
        elif target_app == 'enhancer':
            result = import_to_enhancer(source_path, user)
        elif target_app == 'imager':
            result = import_to_imager(source_path, user)
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


def import_to_describer(source_path, user):
    """Import a file to Describer app."""
    from wama.describer.models import Description
    import shutil

    # Copy file to describer input folder
    dest_dir = Path(settings.MEDIA_ROOT) / 'describer' / 'input'
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

    # Create Description record
    relative_path = f'describer/input/{dest_path.name}'

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
    """Import a file to Enhancer app."""
    from wama.enhancer.models import Enhancement
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

    # Create Enhancement record - set path directly to avoid duplicate upload
    relative_path = f'enhancer/input/{dest_path.name}'

    enhancement = Enhancement.objects.create(user=user)
    enhancement.input_file.name = relative_path
    enhancement.save()

    return {
        'imported': True,
        'app': 'enhancer',
        'id': enhancement.id,
        'filename': dest_path.name,
        'path': relative_path,
    }


def import_to_imager(source_path, user):
    """
    Import a file to Imager app.
    Supports:
    - Text files (.txt, .json, .yaml, .yml) -> batch prompts
    - Image files -> reference images for img2img/style/describe modes
    """
    from wama.imager.models import ImageGeneration
    import shutil

    ext = source_path.suffix.lower()

    # Determine file type and destination
    if ext in ('.txt', '.json', '.yaml', '.yml'):
        # Prompt file for batch generation
        dest_dir = Path(settings.MEDIA_ROOT) / 'imager' / 'input' / 'prompts'
        file_type = 'prompt_file'
        generation_mode = 'file2img'
    elif ext in ('.jpg', '.jpeg', '.png', '.webp', '.gif', '.bmp'):
        # Reference image for img2img/style/describe
        dest_dir = Path(settings.MEDIA_ROOT) / 'imager' / 'input' / 'references'
        file_type = 'reference_image'
        generation_mode = 'describe2img'  # Default, user can change mode
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

    # Create ImageGeneration record
    if file_type == 'prompt_file':
        # For prompt files, we just save the file reference
        # The actual batch will be created when user opens Imager
        generation = ImageGeneration.objects.create(
            user=user,
            generation_mode=generation_mode,
            prompt=f'Batch from {dest_path.name} (pending)',
            status='PENDING',
        )
        relative_path = f'imager/input/prompts/{dest_path.name}'
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
        relative_path = f'imager/input/references/{dest_path.name}'
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
    """Import a text file to Synthesizer app."""
    from wama.synthesizer.models import VoiceSynthesis
    from django.core.files import File
    import shutil

    # Validate file extension
    allowed_extensions = ['txt', 'pdf', 'docx', 'csv', 'md']
    ext = source_path.suffix[1:].lower() if source_path.suffix else ''
    if ext not in allowed_extensions:
        raise ValueError(f"Format non supporté. Formats acceptés: {', '.join(allowed_extensions)}")

    # Create destination directory
    dest_dir = Path(settings.MEDIA_ROOT) / 'synthesizer' / 'input'
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

    # Create VoiceSynthesis record
    relative_path = str(dest_path.relative_to(settings.MEDIA_ROOT))

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


def import_to_transcriber(source_path, user):
    """Import a file to Transcriber app."""
    from wama.transcriber.models import Transcript
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
