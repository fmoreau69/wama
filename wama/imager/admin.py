"""
WAMA Imager - Admin
"""

from django.contrib import admin
from .models import ImageGeneration, UserSettings


@admin.register(ImageGeneration)
class ImageGenerationAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'prompt_preview', 'model', 'status', 'progress', 'created_at', 'duration_display')
    list_filter = ('status', 'model', 'created_at')
    search_fields = ('prompt', 'user__username')
    readonly_fields = ('created_at', 'updated_at', 'completed_at', 'duration_display')

    fieldsets = (
        ('User', {
            'fields': ('user',)
        }),
        ('Prompt', {
            'fields': ('prompt', 'negative_prompt')
        }),
        ('Model Settings', {
            'fields': ('model', 'width', 'height')
        }),
        ('Generation Parameters', {
            'fields': ('steps', 'guidance_scale', 'seed', 'num_images', 'upscale')
        }),
        ('Output', {
            'fields': ('generated_images',)
        }),
        ('Status', {
            'fields': ('status', 'progress', 'error_message')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at', 'completed_at', 'duration_display')
        }),
    )

    def prompt_preview(self, obj):
        return obj.prompt[:50] + '...' if len(obj.prompt) > 50 else obj.prompt
    prompt_preview.short_description = 'Prompt'


@admin.register(UserSettings)
class UserSettingsAdmin(admin.ModelAdmin):
    list_display = ('user', 'default_model', 'default_width', 'default_height', 'default_steps')
    search_fields = ('user__username',)
    readonly_fields = ('created_at', 'updated_at')
