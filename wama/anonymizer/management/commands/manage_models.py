"""
Django management command for managing YOLO models.

Usage:
    python manage.py manage_models list              # List all available models
    python manage.py manage_models installed          # List installed models
    python manage.py manage_models download-defaults  # Download default models
    python manage.py manage_models download <type> <name>  # Download specific model
    python manage.py manage_models info <type> <name>      # Show model info
"""

from django.core.management.base import BaseCommand, CommandError
from wama.anonymizer.utils.model_manager import (
    list_downloadable_models,
    get_installed_models,
    download_default_models,
    download_model,
    get_model_info,
    OFFICIAL_MODELS,
)


class Command(BaseCommand):
    help = 'Manage YOLO models: list, download, and get information'

    def add_arguments(self, parser):
        parser.add_argument(
            'action',
            type=str,
            choices=['list', 'installed', 'download-defaults', 'download', 'info'],
            help='Action to perform',
        )
        parser.add_argument(
            'model_type',
            type=str,
            nargs='?',
            help='Model type (detect, segment, pose, classify, obb)',
        )
        parser.add_argument(
            'model_name',
            type=str,
            nargs='?',
            help='Model name (e.g., yolo11n.pt)',
        )
        parser.add_argument(
            '--force',
            action='store_true',
            help='Force re-download even if model exists',
        )

    def handle(self, *args, **options):
        action = options['action']

        if action == 'list':
            self.list_models()
        elif action == 'installed':
            self.list_installed()
        elif action == 'download-defaults':
            self.download_defaults()
        elif action == 'download':
            if not options['model_type'] or not options['model_name']:
                raise CommandError('download requires model_type and model_name')
            self.download_specific(
                options['model_type'],
                options['model_name'],
                options['force']
            )
        elif action == 'info':
            if not options['model_type'] or not options['model_name']:
                raise CommandError('info requires model_type and model_name')
            self.show_info(options['model_type'], options['model_name'])

    def list_models(self):
        """List all downloadable models."""
        self.stdout.write(self.style.SUCCESS('\n=== Available Models for Download ===\n'))

        downloadable = list_downloadable_models()

        for model_type, models in sorted(downloadable.items()):
            self.stdout.write(self.style.HTTP_INFO(f'\n{model_type.upper()}:'))

            for model_name in sorted(models):
                # Check if installed
                info = get_model_info(model_type, model_name)
                status = '✓ installed' if info and info['exists'] else '✗ not installed'
                status_style = self.style.SUCCESS if info and info['exists'] else self.style.WARNING

                self.stdout.write(f'  • {model_name:<25} {status_style(status)}')

        self.stdout.write('\n')

    def list_installed(self):
        """List all installed models."""
        self.stdout.write(self.style.SUCCESS('\n=== Installed Models ===\n'))

        installed = get_installed_models()

        if not installed:
            self.stdout.write(self.style.WARNING('No models installed.'))
            self.stdout.write('\nRun: python manage.py manage_models download-defaults')
            return

        total_size = 0

        for model_type, models in sorted(installed.items()):
            self.stdout.write(self.style.HTTP_INFO(f'\n{model_type.upper()}:'))

            for model_info in models:
                size_mb = model_info['size'] / (1024 * 1024)
                total_size += model_info['size']

                official_mark = '★' if model_info['official'] else '·'
                self.stdout.write(
                    f'  {official_mark} {model_info["name"]:<30} '
                    f'{size_mb:>7.1f} MB'
                )

        total_mb = total_size / (1024 * 1024)
        self.stdout.write(f'\n{self.style.SUCCESS("Total:")} {total_mb:.1f} MB\n')

    def download_defaults(self):
        """Download default models."""
        self.stdout.write(self.style.SUCCESS('\n=== Downloading Default Models ===\n'))
        self.stdout.write('This will download:')
        self.stdout.write('  • yolo11n.pt (detection, nano)')
        self.stdout.write('  • yolo11s.pt (detection, small)')
        self.stdout.write('  • yolo11n-seg.pt (segmentation, nano)')
        self.stdout.write('  • yolo11n-pose.pt (pose estimation, nano)\n')

        results = download_default_models()

        self.stdout.write('\n' + self.style.SUCCESS('=== Download Results ===\n'))

        success_count = 0
        for model_id, success in results.items():
            if success:
                self.stdout.write(self.style.SUCCESS(f'✓ {model_id}'))
                success_count += 1
            else:
                self.stdout.write(self.style.ERROR(f'✗ {model_id}'))

        self.stdout.write(
            f'\n{self.style.SUCCESS(f"Successfully downloaded {success_count}/{len(results)} models")}\n'
        )

    def download_specific(self, model_type: str, model_name: str, force: bool = False):
        """Download a specific model."""
        if model_type not in OFFICIAL_MODELS:
            raise CommandError(
                f'Unknown model type: {model_type}\n'
                f'Available types: {", ".join(OFFICIAL_MODELS.keys())}'
            )

        if model_name not in OFFICIAL_MODELS[model_type]:
            raise CommandError(
                f'Unknown model: {model_name} for type {model_type}\n'
                f'Available models: {", ".join(OFFICIAL_MODELS[model_type].keys())}'
            )

        self.stdout.write(f'\nDownloading {model_type}/{model_name}...\n')

        success = download_model(model_type, model_name, force=force)

        if success:
            self.stdout.write(self.style.SUCCESS(f'\n✓ Successfully downloaded {model_name}\n'))
        else:
            raise CommandError(f'Failed to download {model_name}')

    def show_info(self, model_type: str, model_name: str):
        """Show information about a model."""
        info = get_model_info(model_type, model_name)

        if not info:
            raise CommandError(f'Model not found: {model_type}/{model_name}')

        self.stdout.write(self.style.SUCCESS(f'\n=== Model Information ===\n'))
        self.stdout.write(f'Name:      {info["name"]}')
        self.stdout.write(f'Type:      {info["type"]}')
        self.stdout.write(f'Version:   {info["version"]}')
        self.stdout.write(f'Installed: {"Yes" if info["exists"] else "No"}')

        if info['exists']:
            size_mb = info['size'] / (1024 * 1024)
            self.stdout.write(f'Size:      {size_mb:.1f} MB')
            self.stdout.write(f'Path:      {info["path"]}')

        self.stdout.write(f'URL:       {info["url"]}\n')
