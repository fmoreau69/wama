from django.contrib import admin

from .models import OrgUnit, UserFunction


@admin.register(OrgUnit)
class OrgUnitAdmin(admin.ModelAdmin):
    list_display = ('name', 'code', 'unit_type', 'parent', 'source')
    list_filter = ('unit_type', 'source')
    search_fields = ('name', 'code')
    autocomplete_fields = ('parent',)


@admin.register(UserFunction)
class UserFunctionAdmin(admin.ModelAdmin):
    list_display = ('name', 'key', 'category', 'owner', 'visibility', 'scope_org_unit')
    list_filter = ('category', 'visibility')
    search_fields = ('name', 'key', 'description')
