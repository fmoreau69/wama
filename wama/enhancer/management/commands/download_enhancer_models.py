"""
Django management command to download AI models for Enhancer app.

Usage:
    python manage.py download_enhancer_models           # Download essential models only
    python manage.py download_enhancer_models --all     # Download all models
    python manage.py download_enhancer_models --status  # Show models status
"""

from django.core.management.base import BaseCommand
from wama.enhancer.utils.model_downloader import (
    download_models,
    get_models_status,
    MODEL_FILES,
)


class Command(BaseCommand):
    help = 'Download AI models for Enhancer app'

    def add_arguments(self, parser):
        parser.add_argument(
            '--all',
            action='store_true',
            help='Download all available models (~156 MB total)',
        )
        parser.add_argument(
            '--status',
            action='store_true',
            help='Show current status of models',
        )
        parser.add_argument(
            '--models',
            nargs='+',
            help='Specific models to download (e.g., RealESR_Gx4_fp16.onnx)',
        )

    def handle(self, *args, **options):
        if options['status']:
            self.show_status()
        else:
            self.download_models(
                download_all=options['all'],
                specific_models=options.get('models')
            )

    def show_status(self):
        """Display current models status."""
        status = get_models_status()

        self.stdout.write(self.style.SUCCESS('\n=== AI Models Status ==='))
        self.stdout.write(f"Directory: {status['models_dir']}")
        self.stdout.write(f"Exists: {status['models_dir_exists']}")

        summary = status['summary']
        self.stdout.write(f"\nAvailable: {summary['available']}/{summary['total']}")
        self.stdout.write(f"Missing: {summary['missing']}/{summary['total']}")

        self.stdout.write("\nModels:")
        for model_file, info in status['models'].items():
            if info['available']:
                size_mb = info['actual_size'] / (1024 * 1024)
                status_str = self.style.SUCCESS(f"✓ {model_file}")
                self.stdout.write(f"  {status_str} ({size_mb:.1f} MB) - {info['description']}")
            else:
                expected_mb = info['expected_size'] / (1024 * 1024)
                status_str = self.style.ERROR(f"✗ {model_file}")
                self.stdout.write(f"  {status_str} (missing, ~{expected_mb:.0f} MB) - {info['description']}")

        if summary['missing'] == 0:
            self.stdout.write(self.style.SUCCESS("\n✓ All models are available!"))
        else:
            self.stdout.write(self.style.WARNING(f"\n⚠ {summary['missing']} model(s) missing"))

    def download_models(self, download_all=False, specific_models=None):
        """Download models."""
        if specific_models:
            # Validate model names
            invalid = [m for m in specific_models if m not in MODEL_FILES]
            if invalid:
                self.stdout.write(self.style.ERROR(f"Invalid model names: {', '.join(invalid)}"))
                self.stdout.write(f"Available models: {', '.join(MODEL_FILES.keys())}")
                return

            self.stdout.write(f"Downloading specific models: {', '.join(specific_models)}")
        elif download_all:
            self.stdout.write(self.style.WARNING("Downloading ALL models (~156 MB total)..."))
        else:
            self.stdout.write("Downloading essential models only (RealESR_Gx4)...")

        self.stdout.write("This may take a few minutes depending on your connection...\n")

        try:
            results = download_models(
                models=specific_models,
                download_all=download_all
            )

            if not results:
                self.stdout.write(self.style.SUCCESS("✓ All requested models are already downloaded!"))
                return

            # Show results
            successful = sum(1 for v in results.values() if v)
            failed = len(results) - successful

            self.stdout.write(f"\n=== Download Results ===")
            for model, success in results.items():
                if success:
                    self.stdout.write(self.style.SUCCESS(f"✓ {model}"))
                else:
                    self.stdout.write(self.style.ERROR(f"✗ {model} - FAILED"))

            if successful > 0:
                self.stdout.write(self.style.SUCCESS(f"\n✓ Successfully downloaded {successful} model(s)"))

            if failed > 0:
                self.stdout.write(self.style.ERROR(f"✗ Failed to download {failed} model(s)"))
                self.stdout.write("\nYou can try again or download manually from:")
                self.stdout.write("https://github.com/Djdefrag/QualityScaler/releases")

        except Exception as e:
            self.stdout.write(self.style.ERROR(f"\n✗ Error during download: {e}"))
            self.stdout.write("\nPlease download models manually from:")
            self.stdout.write("https://github.com/Djdefrag/QualityScaler/releases")
