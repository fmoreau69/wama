from django.contrib import admin

from wama.accounts.models import UserProfile, AppAccessPolicy


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'account_tier', 'preferred_language', 'ui_mode',
                    'notify_email', 'notify_on', 'media_retention_days')
    list_filter = ('account_tier', 'preferred_language', 'notify_email', 'notify_on')
    search_fields = ('user__username', 'user__email')


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
