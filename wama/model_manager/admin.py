"""
WAMA Model Manager - Django Admin Configuration
"""

from django.contrib import admin
from django.utils.html import format_html
from .models import AIModel, ModelSyncLog


@admin.register(AIModel)
class AIModelAdmin(admin.ModelAdmin):
    list_display = [
        'name', 'source', 'model_type', 'status_badge',
        'format_badge', 'size_display', 'updated_at'
    ]
    list_filter = [
        'source', 'model_type', 'is_downloaded',
        'is_loaded', 'is_available', 'format'
    ]
    search_fields = ['name', 'model_key', 'hf_id', 'description']
    readonly_fields = ['model_key', 'created_at', 'updated_at', 'last_synced_at']
    ordering = ['-updated_at']

    fieldsets = (
        ('Identity', {
            'fields': ('model_key', 'name', 'description')
        }),
        ('Classification', {
            'fields': ('model_type', 'source', 'backend_ref')
        }),
        ('External References', {
            'fields': ('hf_id', 'local_path')
        }),
        ('Resource Requirements', {
            'fields': ('vram_gb', 'ram_gb', 'disk_gb')
        }),
        ('Format', {
            'fields': ('format', 'preferred_format', 'can_convert_to')
        }),
        ('Status', {
            'fields': ('is_downloaded', 'is_loaded', 'is_available')
        }),
        ('Metadata', {
            'fields': ('extra_info',),
            'classes': ('collapse',)
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at', 'last_synced_at', 'last_used_at')
        }),
    )

    def status_badge(self, obj):
        if obj.is_loaded:
            return format_html(
                '<span style="background: #28a745; color: white; padding: 3px 8px; '
                'border-radius: 4px; font-size: 11px;">Loaded</span>'
            )
        elif obj.is_downloaded:
            return format_html(
                '<span style="background: #17a2b8; color: white; padding: 3px 8px; '
                'border-radius: 4px; font-size: 11px;">Ready</span>'
            )
        else:
            return format_html(
                '<span style="background: #6c757d; color: white; padding: 3px 8px; '
                'border-radius: 4px; font-size: 11px;">Not Downloaded</span>'
            )
    status_badge.short_description = 'Status'

    def format_badge(self, obj):
        if not obj.format:
            return '-'

        colors = {
            'safetensors': '#28a745',
            'onnx': '#fd7e14',
            'pt': '#6c757d',
            'pth': '#6c757d',
            'bin': '#495057',
            'gguf': '#6f42c1',
        }
        color = colors.get(obj.format.lower(), '#343a40')

        return format_html(
            '<span style="background: {}; color: white; padding: 2px 6px; '
            'border-radius: 3px; font-size: 10px; text-transform: uppercase;">{}</span>',
            color, obj.format
        )
    format_badge.short_description = 'Format'

    actions = ['mark_as_downloaded', 'mark_as_not_downloaded', 'trigger_sync']

    @admin.action(description="Mark selected models as downloaded")
    def mark_as_downloaded(self, request, queryset):
        updated = queryset.update(is_downloaded=True)
        self.message_user(request, f"{updated} model(s) marked as downloaded.")

    @admin.action(description="Mark selected models as not downloaded")
    def mark_as_not_downloaded(self, request, queryset):
        updated = queryset.update(is_downloaded=False, is_loaded=False)
        self.message_user(request, f"{updated} model(s) marked as not downloaded.")

    @admin.action(description="Trigger model sync")
    def trigger_sync(self, request, queryset):
        from .services.model_sync import get_sync_service
        sync_service = get_sync_service()
        result = sync_service.full_sync()
        self.message_user(
            request,
            f"Sync completed: +{result.added}, ~{result.updated}, -{result.removed}"
        )


@admin.register(ModelSyncLog)
class ModelSyncLogAdmin(admin.ModelAdmin):
    list_display = [
        'sync_type', 'status_badge', 'models_added', 'models_updated',
        'models_removed', 'duration', 'started_at'
    ]
    list_filter = ['sync_type', 'status', 'started_at']
    readonly_fields = [
        'sync_type', 'status', 'models_added', 'models_updated',
        'models_removed', 'started_at', 'completed_at', 'error_message', 'details'
    ]
    ordering = ['-started_at']

    def status_badge(self, obj):
        colors = {
            'started': '#ffc107',
            'completed': '#28a745',
            'failed': '#dc3545',
        }
        color = colors.get(obj.status, '#6c757d')

        return format_html(
            '<span style="background: {}; color: white; padding: 2px 6px; '
            'border-radius: 3px; font-size: 10px;">{}</span>',
            color, obj.status.upper()
        )
    status_badge.short_description = 'Status'

    def duration(self, obj):
        if obj.duration_seconds:
            return f"{obj.duration_seconds:.1f}s"
        return '-'
    duration.short_description = 'Duration'

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
