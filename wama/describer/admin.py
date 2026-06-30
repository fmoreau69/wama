from django.contrib import admin
from .models import Description


@admin.register(Description)
class DescriptionAdmin(admin.ModelAdmin):
    list_display = ['id', 'user', 'filename', 'detected_type', 'output_style', 'status', 'created_at']
    list_filter = ['status', 'detected_type', 'output_style', 'output_language']
    search_fields = ['filename', 'result_text']
    readonly_fields = ['created_at', 'updated_at', 'task_id']
    ordering = ['-created_at']
