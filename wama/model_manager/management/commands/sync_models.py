"""
Django management command to sync AI models with the database.

Usage:
    python manage.py sync_models              # Full sync
    python manage.py sync_models --status     # Show status
    python manage.py sync_models --clean      # Remove missing models
    python manage.py sync_models --source=imager  # Sync specific source only
"""

from django.core.management.base import BaseCommand
from django.utils import timezone


class Command(BaseCommand):
    help = 'Synchronize AI models catalog with database'

    def add_arguments(self, parser):
        parser.add_argument(
            '--status',
            action='store_true',
            help='Show current models status'
        )
        parser.add_argument(
            '--clean',
            action='store_true',
            help='Mark models not found in sources as unavailable'
        )
        parser.add_argument(
            '--source',
            type=str,
            help='Sync only specific source (imager, enhancer, anonymizer, etc.)'
        )
        parser.add_argument(
            '--verbose',
            action='store_true',
            help='Show detailed output'
        )

    def handle(self, *args, **options):
        if options['status']:
            self.show_status(verbose=options['verbose'])
        else:
            self.sync_models(
                clean=options['clean'],
                source_filter=options.get('source'),
                verbose=options['verbose']
            )

    def show_status(self, verbose=False):
        """Display current models status."""
        from wama.model_manager.models import AIModel, ModelSyncLog, ModelSource, ModelType

        self.stdout.write(self.style.SUCCESS('\n' + '=' * 50))
        self.stdout.write(self.style.SUCCESS('  AI Models Catalog Status'))
        self.stdout.write(self.style.SUCCESS('=' * 50))

        total = AIModel.objects.filter(is_available=True).count()
        downloaded = AIModel.objects.filter(is_available=True, is_downloaded=True).count()
        loaded = AIModel.objects.filter(is_available=True, is_loaded=True).count()
        unavailable = AIModel.objects.filter(is_available=False).count()

        self.stdout.write(f"\nTotal models in catalog: {self.style.WARNING(str(total))}")
        self.stdout.write(f"  Downloaded: {self.style.SUCCESS(str(downloaded))}")
        self.stdout.write(f"  Loaded: {self.style.SUCCESS(str(loaded))}")
        if unavailable:
            self.stdout.write(f"  Unavailable: {self.style.ERROR(str(unavailable))}")

        # By source
        self.stdout.write("\n" + "-" * 30)
        self.stdout.write("By Source:")
        for source in ModelSource.choices:
            source_value = source[0]
            source_label = source[1]
            count = AIModel.objects.filter(source=source_value, is_available=True).count()
            dl_count = AIModel.objects.filter(
                source=source_value, is_available=True, is_downloaded=True
            ).count()
            if count > 0:
                self.stdout.write(f"  {source_label}: {dl_count}/{count}")

        # By type
        self.stdout.write("\n" + "-" * 30)
        self.stdout.write("By Type:")
        for mtype in ModelType.choices:
            type_value = mtype[0]
            type_label = mtype[1]
            count = AIModel.objects.filter(model_type=type_value, is_available=True).count()
            if count > 0:
                self.stdout.write(f"  {type_label}: {count}")

        # By format
        self.stdout.write("\n" + "-" * 30)
        self.stdout.write("By Format:")
        formats = AIModel.objects.filter(is_available=True).exclude(
            format=''
        ).values_list('format', flat=True).distinct()
        for fmt in formats:
            count = AIModel.objects.filter(format=fmt, is_available=True).count()
            self.stdout.write(f"  {fmt}: {count}")

        # Recent syncs
        self.stdout.write("\n" + "-" * 30)
        self.stdout.write("Recent Sync Logs:")
        recent_logs = ModelSyncLog.objects.order_by('-started_at')[:5]
        if recent_logs:
            for log in recent_logs:
                if log.status == 'completed':
                    status_style = self.style.SUCCESS
                elif log.status == 'failed':
                    status_style = self.style.ERROR
                else:
                    status_style = self.style.WARNING

                duration = ""
                if log.duration_seconds:
                    duration = f" ({log.duration_seconds:.1f}s)"

                self.stdout.write(
                    f"  {log.started_at.strftime('%Y-%m-%d %H:%M')} - "
                    f"{log.sync_type:12} - {status_style(log.status):10}{duration} "
                    f"(+{log.models_added}, ~{log.models_updated}, -{log.models_removed})"
                )
        else:
            self.stdout.write("  No sync logs yet")

        # Verbose: list all models
        if verbose:
            self.stdout.write("\n" + "-" * 30)
            self.stdout.write("All Models:")
            for model in AIModel.objects.filter(is_available=True).order_by('source', 'name'):
                status = self.style.SUCCESS("Downloaded") if model.is_downloaded else "---"
                self.stdout.write(f"  [{model.source:12}] {model.name[:40]:40} {status}")

        self.stdout.write("")

    def sync_models(self, clean=False, source_filter=None, verbose=False):
        """Perform model sync."""
        from wama.model_manager.models import AIModel
        from wama.model_manager.services.model_sync import get_sync_service

        self.stdout.write(self.style.WARNING('\nStarting model sync...'))
        self.stdout.write(f"  Clean missing: {clean}")
        if source_filter:
            self.stdout.write(f"  Source filter: {source_filter}")

        sync_service = get_sync_service()

        start_time = timezone.now()
        result = sync_service.full_sync(remove_missing=clean)
        duration = (timezone.now() - start_time).total_seconds()

        if result.success:
            self.stdout.write(self.style.SUCCESS(f'\n=== Sync Completed ({duration:.2f}s) ==='))
            self.stdout.write(f"  Models added: {self.style.SUCCESS(str(result.added))}")
            self.stdout.write(f"  Models updated: {self.style.WARNING(str(result.updated))}")
            self.stdout.write(f"  Models removed: {self.style.ERROR(str(result.removed))}")

            if result.errors:
                self.stdout.write(self.style.WARNING(f"\n  Warnings ({len(result.errors)}):"))
                for err in result.errors[:10]:
                    self.stdout.write(f"    - {err}")
                if len(result.errors) > 10:
                    self.stdout.write(f"    ... and {len(result.errors) - 10} more")
        else:
            self.stdout.write(self.style.ERROR('\n=== Sync Failed ==='))
            for err in result.errors:
                self.stdout.write(self.style.ERROR(f"  {err}"))

        # Show final status
        total = AIModel.objects.filter(is_available=True).count()
        downloaded = AIModel.objects.filter(is_available=True, is_downloaded=True).count()
        self.stdout.write(
            f"\nCatalog now contains {self.style.WARNING(str(total))} models "
            f"({self.style.SUCCESS(str(downloaded))} downloaded)"
        )
        self.stdout.write("")
