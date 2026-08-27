from django.contrib import admin

from .models import OrgUnit, UserFunction, Project, ProjectMembership, Manifest


class ProjectMembershipInline(admin.TabularInline):
    model = ProjectMembership
    extra = 1
    autocomplete_fields = ('user', 'org')


@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = ('name', 'code', 'owner_org', 'lead')
    list_filter = ('owner_org',)
    search_fields = ('name', 'code')
    autocomplete_fields = ('owner_org', 'lead')
    inlines = [ProjectMembershipInline]


@admin.register(OrgUnit)
class OrgUnitAdmin(admin.ModelAdmin):
    # `authority` visible ET filtrable : deux unités homonymes ne se distinguent QUE par elle
    # (§8.6). Une colonne « code » seule redeviendrait ambiguë à l'œil dès le 2ᵉ établissement.
    list_display = ('name', 'code', 'authority', 'unit_type', 'parent', 'source')
    list_filter = ('unit_type', 'source', 'authority')
    search_fields = ('name', 'code')
    autocomplete_fields = ('parent',)


@admin.register(UserFunction)
class UserFunctionAdmin(admin.ModelAdmin):
    list_display = ('name', 'key', 'category', 'owner', 'visibility', 'scope_org_unit')
    list_filter = ('category', 'visibility')
    search_fields = ('name', 'key', 'description')


@admin.register(Manifest)
class ManifestAdmin(admin.ModelAdmin):
    list_display = ('manifest_kind', 'key', 'name', 'world', 'visibility', 'is_valid', 'updated_at')
    list_filter = ('manifest_kind', 'world', 'visibility')
    search_fields = ('key', 'name', 'description')
    readonly_fields = ('created_at', 'updated_at', 'errors')
