from django.contrib import admin

from wama.accounts.models import UserProfile, AppAccessPolicy


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'account_tier', 'preferred_language', 'ui_mode',
                    'notify_email', 'notify_on', 'notify_sound', 'media_retention_days',
                    'temp_retention_days')
    list_filter = ('account_tier', 'preferred_language', 'notify_email', 'notify_on',
                   'notify_sound')
    search_fields = ('user__username', 'user__email')

    def save_model(self, request, obj, form, change):
        """Le niveau édité ici entraîne ses drapeaux Django (`set_account_tier`, 2026-10-21) :
        sans quoi un compte passé administrateur par ce formulaire n'ouvrirait pas ce site, et un
        compte rétrogradé y garderait l'accès."""
        super().save_model(request, obj, form, change)
        from wama.accounts.permissions import set_account_tier
        set_account_tier(obj.user, obj.account_tier)


@admin.register(AppAccessPolicy)
class AppAccessPolicyAdmin(admin.ModelAdmin):
    """Tableau d'accès app→rôles, éditable (MVP avant l'UI matrice dans la gestion utilisateurs)."""
    list_display = ('app_id', 'roles_list', 'public', 'min_tier')
    list_filter = ('public', 'min_tier', 'roles')
    search_fields = ('app_id',)
    filter_horizontal = ('roles',)

    @admin.display(description='Rôles')
    def roles_list(self, obj):
        return ', '.join(g.name.replace('role:', '') for g in obj.roles.all()) or '— commun —'


from .models import AccessLog


@admin.register(AccessLog)
class AccessLogAdmin(admin.ModelAdmin):
    list_display = ('timestamp', 'username', 'event', 'kind', 'reason', 'auth_backend', 'ip')
    list_filter = ('kind', 'event', 'reason', 'timestamp')
    search_fields = ('username', 'ip')
    date_hierarchy = 'timestamp'
    readonly_fields = ('user', 'username', 'event', 'kind', 'reason', 'auth_backend', 'ip',
                       'user_agent', 'timestamp')

    def has_add_permission(self, request):
        return False   # journal en lecture seule
