"""
Context processors for the accounts app.
"""


def user_role(request):
    """Add user role information to template context."""
    from .views import is_admin, is_dev, get_user_role

    user = request.user

    return {
        'is_admin': is_admin(user),
        'is_dev': is_dev(user),
        'user_role': get_user_role(user),
    }
