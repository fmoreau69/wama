from django.contrib import admin
from .models import ReadingItem


@admin.register(ReadingItem)
class ReadingItemAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'original_filename', 'backend', 'mode', 'status', 'created_at')
    list_filter = ('status', 'backend', 'mode')
    search_fields = ('user__username', 'original_filename')
    readonly_fields = ('created_at', 'task_id', 'used_backend')
