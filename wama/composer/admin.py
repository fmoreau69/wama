from django.contrib import admin
from .models import ComposerGeneration


@admin.register(ComposerGeneration)
class ComposerGenerationAdmin(admin.ModelAdmin):
    list_display = ['id', 'user', 'generation_type', 'model', 'status', 'duration', 'created_at']
    list_filter = ['generation_type', 'status', 'model']
    search_fields = ['prompt', 'user__username']
    readonly_fields = ['task_id', 'progress', 'created_at']
