import json

from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User, Group
from django.http import HttpResponseRedirect, JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.utils.decorators import method_decorator
from django.views.generic import ListView, View, DetailView, TemplateView
from django.views.generic.edit import CreateView, UpdateView
from django.views.decorators.http import require_POST
from functools import wraps

from .models import LoginForm, UserRegistrationForm, UserProfile
from ..anonymizer.forms import UserSettingsEdit
from ..anonymizer.models import UserSettings


def admin_required(view_func):
    """Decorator that checks if user is in admin group."""
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            messages.error(request, "Vous devez être connecté.")
            return redirect('accounts:login')
        if not is_admin(request.user):
            messages.error(request, "Accès réservé aux administrateurs.")
            return redirect('home')
        return view_func(request, *args, **kwargs)
    return wrapper


def is_admin(user):
    """Check if user is an admin."""
    if not user.is_authenticated:
        return False
    return user.is_superuser or user.groups.filter(name='admin').exists()


def is_dev(user):
    """Check if user is a developer."""
    if not user.is_authenticated:
        return False
    return user.groups.filter(name='dev').exists() or is_admin(user)


def get_user_role(user):
    """Get the primary role of a user."""
    if not user.is_authenticated or user.username == 'anonymous':
        return 'anonymous'
    if user.is_superuser or user.groups.filter(name='admin').exists():
        return 'admin'
    if user.groups.filter(name='dev').exists():
        return 'dev'
    if user.groups.filter(name='user').exists():
        return 'user'
    return 'user'  # Default to user if authenticated but no group


def login_view(request):
    if request.user.is_authenticated:
        return redirect('anonymizer:upload')

    form = LoginForm(data=request.POST or None)

    if request.method == 'POST':
        if form.is_valid():
            user = form.get_user()
            login(request, user)
            messages.success(request, "Successfully logged in!")
            next_url = request.POST.get('next') or 'anonymizer:upload'
            return redirect(next_url)
        else:
            messages.error(request, "Invalid credentials.")

    return render(request, 'accounts/login_v2.html', {'form': form, 'type_of_view': 'login'})


def signup_view(request):
    form = UserRegistrationForm(request.POST or None)

    if request.method == 'POST':
        if form.is_valid():
            user = form.save()
            # Crée les UserSettings liés
            UserSettings.objects.get_or_create(user=user)
            return render(request, 'accounts/signup_validation.html')

    return render(request, 'accounts/login.html', {'form': form, 'type_of_view': 'register'})


def logout_view(request):
    logout(request)
    return redirect('accounts:login')


class IndexView(ListView):
    template_name = 'anonymizer/index.html'
    queryset = User.objects.all()
    context_object_name = 'user_list'


class UserPage(DetailView):
    template_name = 'accounts/user_settings.html'
    queryset = User.objects.all()
    context_object_name = 'selected_user'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['can_edit'] = (self.request.user.pk == self.object.pk)
        return context


@method_decorator(login_required, name='dispatch')
class UserEdit(UpdateView):
    template_name = 'accounts/user_form.html'
    model = User
    fields = ["first_name", "last_name", "email"]

    def get_success_url(self):
        return reverse('anonymizer:upload')

    def get_object(self):
        return self.request.user

    def get_form(self, form_class=None):
        form = super().get_form(form_class)
        # Apply dark theme styling to all form fields
        for field_name, field in form.fields.items():
            field.widget.attrs.update({
                'class': 'form-control bg-dark text-white border-secondary'
            })
            # Update labels to French
            if field_name == 'first_name':
                field.label = 'Prénom'
            elif field_name == 'last_name':
                field.label = 'Nom'
            elif field_name == 'email':
                field.label = 'Email'
        return form

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.object
        context['title'] = f'{user.first_name} {user.last_name}' if user.first_name else user.username
        context['subtitle'] = 'Modifier les informations du profil'
        return context


@method_decorator(login_required, name='dispatch')
class UserSettingsUpdate(UpdateView):
    template_name = 'accounts/user_settings_form.html'
    form_class = UserSettingsEdit

    def get_success_url(self):
        return reverse('anonymizer:upload')

    def get_object(self):
        return get_object_or_404(UserSettings, user=self.request.user)

    def get_form(self, form_class=None):
        form = super().get_form(form_class)
        # Apply dark theme styling to all form fields
        for field_name, field in form.fields.items():
            widget_class = 'form-control bg-dark text-white border-secondary'
            if hasattr(field.widget, 'input_type') and field.widget.input_type == 'checkbox':
                widget_class = 'form-check-input'
            elif hasattr(field.widget, 'template_name') and 'select' in field.widget.template_name:
                widget_class = 'form-select bg-dark text-white border-secondary'
            field.widget.attrs.update({'class': widget_class})
        return form

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = 'Paramètres utilisateur'
        return context

    def form_valid(self, form):
        form.instance.user = self.request.user
        return super().form_valid(form)


def login_form(request):
    """ Context processor ou fragment HTML selon usage """
    if not request.user.is_authenticated:
        return {"login_form": LoginForm()}
    return {}


# =============================================================================
# Profile Views
# =============================================================================

def _is_ldap_user(request):
    """Return True if the current session was authenticated via LDAPBackend."""
    backend = request.session.get('_auth_user_backend', '')
    return 'LDAPBackend' in backend


@login_required
def profile_view(request):
    """Unified profile page: user info + preferred language + API token."""
    from rest_framework.authtoken.models import Token
    from wama.common.tts.constants import LANGUAGE_CHOICES

    token_obj, _ = Token.objects.get_or_create(user=request.user)
    profile, _ = UserProfile.objects.get_or_create(user=request.user)

    return render(request, 'accounts/profile.html', {
        'token': token_obj.key,
        'profile': profile,
        'languages': LANGUAGE_CHOICES,
        'is_ldap': _is_ldap_user(request),
    })


@login_required
@require_POST
def change_password(request):
    """AJAX: change password for local (non-LDAP) accounts only."""
    from django.contrib.auth.forms import PasswordChangeForm
    from django.contrib.auth import update_session_auth_hash

    if _is_ldap_user(request):
        return JsonResponse(
            {'error': 'Modification du mot de passe non disponible pour les comptes LDAP.'},
            status=400,
        )

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'JSON invalide'}, status=400)

    form = PasswordChangeForm(request.user, data)
    if form.is_valid():
        user = form.save()
        update_session_auth_hash(request, user)
        return JsonResponse({'success': True})

    errors = {field: [str(e) for e in errs] for field, errs in form.errors.items()}
    # Surface the first human-readable error
    first_error = next(
        (e for errs in errors.values() for e in errs), 'Validation échouée'
    )
    return JsonResponse({'error': first_error, 'fields': errors}, status=400)


@login_required
@require_POST
def language_update(request):
    """AJAX: save preferred language to UserProfile."""
    from wama.common.tts.constants import LANGUAGE_CHOICES

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'JSON invalide'}, status=400)

    lang = data.get('language', 'fr')
    valid_codes = [c[0] for c in LANGUAGE_CHOICES]
    if lang not in valid_codes:
        return JsonResponse({'error': f"Langue invalide : '{lang}'"}, status=400)

    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    profile.preferred_language = lang
    profile.save(update_fields=['preferred_language'])
    return JsonResponse({'success': True, 'language': lang})


@login_required
@require_POST
def notifications_update(request):
    """AJAX: enregistre les préférences de notification email."""
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'JSON invalide'}, status=400)

    valid_on = {'both', 'completion', 'failure', 'none'}
    notify_on = data.get('notify_on', 'both')
    if notify_on not in valid_on:
        return JsonResponse({'error': f"Valeur invalide : '{notify_on}'"}, status=400)

    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    profile.notify_email = bool(data.get('notify_email', True))
    profile.notify_on = notify_on
    profile.save(update_fields=['notify_email', 'notify_on'])
    return JsonResponse({'success': True, 'notify_email': profile.notify_email, 'notify_on': profile.notify_on})


@login_required
@require_POST
def layout_update(request):
    """AJAX: enregistre la disposition des cards (list = ligne, grid = mosaïque)."""
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'JSON invalide'}, status=400)
    layout = data.get('card_layout', 'list')
    if layout not in ('list', 'grid'):
        return JsonResponse({'error': f"Valeur invalide : '{layout}'"}, status=400)
    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    profile.card_layout = layout
    profile.save(update_fields=['card_layout'])
    return JsonResponse({'success': True, 'card_layout': layout})


@login_required
@require_POST
def retention_update(request):
    """AJAX: enregistre la durée de conservation des médias (0 = illimité)."""
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'JSON invalide'}, status=400)
    try:
        days = max(0, int(data.get('media_retention_days', 0)))
    except (TypeError, ValueError):
        return JsonResponse({'error': 'Valeur invalide'}, status=400)

    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    profile.media_retention_days = days
    profile.save(update_fields=['media_retention_days'])
    return JsonResponse({'success': True, 'media_retention_days': days,
                         'effective': profile.effective_retention_days()})


@login_required
@require_POST
def token_regenerate(request):
    """AJAX: delete existing DRF token and create a new one."""
    from rest_framework.authtoken.models import Token

    Token.objects.filter(user=request.user).delete()
    token = Token.objects.create(user=request.user)
    return JsonResponse({'success': True, 'token': token.key})


def add_user(username, first_name, last_name, email):
    """ Crée un utilisateur si inexistant """
    if not User.objects.filter(username=username).exists():
        user = User.objects.create_user(
            username=username,
            first_name=first_name,
            last_name=last_name,
            email=email
        )
        user.set_unusable_password()
        user.save()
        print(f"The user {username} has been created successfully.")
    else:
        print(f"The user {username} already exists.")


def get_or_create_anonymous_user():
    """
    Récupère ou crée un utilisateur anonyme désactivé.
    """
    user, created = User.objects.get_or_create(
        username='anonymous',
        defaults={
            'first_name': 'Anonymous',
            'last_name': 'User',
            'email': 'anonymous@univ-eiffel.fr',
            'is_active': False,
        }
    )
    if created:
        user.set_unusable_password()
        user.save()
        print("Anonymous user created.")
    return user


# =============================================================================
# User Management Views (Admin only)
# =============================================================================

@admin_required
def user_management(request):
    """Display the user management page."""
    users = User.objects.all().order_by('username')
    groups = Group.objects.all().order_by('name')

    # Add role info to each user
    users_with_roles = []
    for user in users:
        users_with_roles.append({
            'user': user,
            'role': get_user_role(user),
            'groups': list(user.groups.values_list('name', flat=True)),
        })

    context = {
        'users': users_with_roles,
        'groups': groups,
        'available_roles': ['admin', 'dev', 'user'],
    }
    return render(request, 'accounts/user_management.html', context)


@admin_required
def app_access_matrix(request):
    """Tableau d'accès app×rôle éditable (cases à cocher)."""
    from wama.accounts.models import AppAccessPolicy
    from wama.accounts.permissions import (ROLES, ROLE_DESCRIPTIONS, GROUP_PREFIX,
                                           TIER_CHOICES, APP_DESCRIPTIONS_FALLBACK,
                                           APP_GROUP_ORDER, app_group)
    try:
        from wama.common.app_registry import APP_CATALOG
    except Exception:
        APP_CATALOG = {}

    # [(key, label, help)] pour les en-têtes de colonnes (tooltip).
    role_keys = [(k, label, ROLE_DESCRIPTIONS.get(k, '')) for k, label in ROLES.items()]

    def _app_desc(app_id):
        meta = APP_CATALOG.get(app_id, {})
        return meta.get('description') or APP_DESCRIPTIONS_FALLBACK.get(app_id, '')

    by_group = {}
    for pol in AppAccessPolicy.objects.prefetch_related('roles').order_by('app_id'):
        active = {g.name[len(GROUP_PREFIX):] for g in pol.roles.all() if g.name.startswith(GROUP_PREFIX)}
        by_group.setdefault(app_group(pol.app_id), []).append({
            'app_id': pol.app_id,
            'description': _app_desc(pol.app_id),
            'public': pol.public,
            'min_tier': pol.min_tier,
            'cells': [{'role': k, 'active': (k in active)} for k, _ in ROLES.items()],
        })
    # Sections ordonnées (puis tout groupe non prévu).
    ordered = APP_GROUP_ORDER + [g for g in by_group if g not in APP_GROUP_ORDER]
    groups = [{'name': g, 'rows': by_group[g]} for g in ordered if by_group.get(g)]

    context = {
        'groups': groups,
        'role_keys': role_keys,
        'ncols': len(role_keys) + 3,  # nom + rôles + anonyme + tier
        # 'anonymous' est le plancher → inutile comme tier MINIMAL (équivalent à « aucun »).
        'tier_choices': [(v, l) for v, l in TIER_CHOICES if v != 'anonymous'],
    }
    return render(request, 'accounts/app_access_matrix.html', context)


@admin_required
@require_POST
def app_access_toggle(request):
    """AJAX: modifie une cellule du tableau d'accès (role/public/min_tier d'une app)."""
    from wama.accounts.models import AppAccessPolicy
    from wama.accounts.permissions import ROLES, GROUP_PREFIX
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'JSON invalide'}, status=400)

    app_id = data.get('app_id')
    if not app_id:
        return JsonResponse({'error': 'app_id manquant'}, status=400)
    pol, _ = AppAccessPolicy.objects.get_or_create(app_id=app_id)

    field = data.get('field')
    if field == 'role':
        role = data.get('role')
        if role not in ROLES:
            return JsonResponse({'error': f"Rôle inconnu : {role}"}, status=400)
        group, _ = Group.objects.get_or_create(name=GROUP_PREFIX + role)
        if data.get('enabled'):
            pol.roles.add(group)
        else:
            pol.roles.remove(group)
    elif field == 'public':
        pol.public = bool(data.get('enabled'))
        pol.save(update_fields=['public'])
    elif field == 'min_tier':
        pol.min_tier = data.get('value', '') or ''
        pol.save(update_fields=['min_tier'])
    else:
        return JsonResponse({'error': 'champ invalide'}, status=400)

    return JsonResponse({'success': True})


@admin_required
def user_add(request):
    """Add a new user."""
    if request.method == 'POST':
        username = request.POST.get('username', '').strip()
        email = request.POST.get('email', '').strip()
        first_name = request.POST.get('first_name', '').strip()
        last_name = request.POST.get('last_name', '').strip()
        password = request.POST.get('password', '')
        role = request.POST.get('role', 'user')

        # Validation
        if not username:
            return JsonResponse({'success': False, 'error': 'Le nom d\'utilisateur est requis'})

        if User.objects.filter(username=username).exists():
            return JsonResponse({'success': False, 'error': 'Ce nom d\'utilisateur existe déjà'})

        if email and User.objects.filter(email=email).exists():
            return JsonResponse({'success': False, 'error': 'Cet email est déjà utilisé'})

        try:
            # Create user
            user = User.objects.create_user(
                username=username,
                email=email,
                password=password if password else None,
                first_name=first_name,
                last_name=last_name,
            )

            if not password:
                user.set_unusable_password()
                user.save()

            # Assign role
            if role in ['admin', 'dev', 'user']:
                group, _ = Group.objects.get_or_create(name=role)
                user.groups.add(group)

                if role == 'admin':
                    user.is_staff = True
                    user.is_superuser = True
                    user.save()

            # Create UserSettings
            UserSettings.objects.get_or_create(user=user)

            return JsonResponse({
                'success': True,
                'message': f'Utilisateur {username} créé avec succès',
                'user_id': user.id
            })

        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)})

    return JsonResponse({'success': False, 'error': 'Méthode non autorisée'})


@admin_required
def user_delete(request, user_id):
    """Delete a user."""
    if request.method == 'POST':
        try:
            user = get_object_or_404(User, id=user_id)

            # Prevent deleting yourself
            if user == request.user:
                return JsonResponse({'success': False, 'error': 'Vous ne pouvez pas vous supprimer vous-même'})

            # Prevent deleting anonymous user
            if user.username == 'anonymous':
                return JsonResponse({'success': False, 'error': 'L\'utilisateur anonymous ne peut pas être supprimé'})

            username = user.username
            user.delete()

            return JsonResponse({
                'success': True,
                'message': f'Utilisateur {username} supprimé'
            })

        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)})

    return JsonResponse({'success': False, 'error': 'Méthode non autorisée'})


@admin_required
def user_update_role(request, user_id):
    """Update a user's role."""
    if request.method == 'POST':
        try:
            user = get_object_or_404(User, id=user_id)
            new_role = request.POST.get('role', 'user')

            # Prevent changing anonymous user role
            if user.username == 'anonymous':
                return JsonResponse({'success': False, 'error': 'Le rôle de l\'utilisateur anonymous ne peut pas être modifié'})

            # Prevent removing your own admin role
            if user == request.user and new_role != 'admin':
                return JsonResponse({'success': False, 'error': 'Vous ne pouvez pas retirer votre propre rôle admin'})

            # Clear existing groups
            user.groups.clear()

            # Assign new role
            if new_role in ['admin', 'dev', 'user']:
                group, _ = Group.objects.get_or_create(name=new_role)
                user.groups.add(group)

            # Update staff/superuser status
            if new_role == 'admin':
                user.is_staff = True
                user.is_superuser = True
            else:
                user.is_staff = False
                user.is_superuser = False

            user.save()

            return JsonResponse({
                'success': True,
                'message': f'Rôle de {user.username} mis à jour vers {new_role}'
            })

        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)})

    return JsonResponse({'success': False, 'error': 'Méthode non autorisée'})


@admin_required
def user_toggle_active(request, user_id):
    """Toggle user active status."""
    if request.method == 'POST':
        try:
            user = get_object_or_404(User, id=user_id)

            # Prevent deactivating yourself
            if user == request.user:
                return JsonResponse({'success': False, 'error': 'Vous ne pouvez pas vous désactiver vous-même'})

            # Prevent changing anonymous status
            if user.username == 'anonymous':
                return JsonResponse({'success': False, 'error': 'L\'utilisateur anonymous ne peut pas être modifié'})

            user.is_active = not user.is_active
            user.save()

            status = 'activé' if user.is_active else 'désactivé'
            return JsonResponse({
                'success': True,
                'message': f'Utilisateur {user.username} {status}',
                'is_active': user.is_active
            })

        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)})

    return JsonResponse({'success': False, 'error': 'Méthode non autorisée'})
