"""
Context processors for the accounts app.
"""


def user_role(request):
    """Add user role and preferences to template context."""
    from .views import is_admin, is_dev, get_user_role

    user = request.user

    # Preferred language (defaults to 'fr' for unauthenticated users)
    preferred_language = 'fr'
    if user.is_authenticated:
        try:
            preferred_language = user.profile.preferred_language
        except Exception:
            pass

    return {
        'is_admin': is_admin(user),
        'is_dev': is_dev(user),
        'user_role': get_user_role(user),
        'preferred_language': preferred_language,
    }
