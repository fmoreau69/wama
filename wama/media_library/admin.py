from django.contrib import admin
from .models import UserAsset, SystemAsset


@admin.register(UserAsset)
class UserAssetAdmin(admin.ModelAdmin):
    list_display = ['name', 'asset_type', 'user', 'file_size', 'created_at']
    list_filter  = ['asset_type', 'created_at']
    search_fields = ['name', 'user__username', 'tags']
    readonly_fields = ['mime_type', 'file_size', 'created_at', 'updated_at']


@admin.register(SystemAsset)
class SystemAssetAdmin(admin.ModelAdmin):
    list_display = ['name', 'asset_type', 'file_size', 'license', 'is_active', 'created_at']
    list_filter  = ['asset_type', 'is_active']
    search_fields = ['name', 'tags', 'description']
    readonly_fields = ['mime_type', 'file_size', 'created_at']
