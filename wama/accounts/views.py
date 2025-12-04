from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.http import HttpResponseRedirect, JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.utils.decorators import method_decorator
from django.views.generic import ListView, View, DetailView, TemplateView
from django.views.generic.edit import CreateView, UpdateView

from .models import LoginForm, UserRegistrationForm
from ..anonymizer.forms import UserSettingsEdit
from ..anonymizer.models import UserSettings


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

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = f'{self.object.first_name} {self.object.last_name}'
        context['subtitle'] = 'Edit user information'
        return context


@method_decorator(login_required, name='dispatch')
class UserSettingsUpdate(UpdateView):
    template_name = 'accounts/user_settings_form.html'
    form_class = UserSettingsEdit

    def get_success_url(self):
        return reverse('anonymizer:upload')

    def get_object(self):
        return get_object_or_404(UserSettings, user=self.request.user)

    def form_valid(self, form):
        form.instance.user = self.request.user
        return super().form_valid(form)


def login_form(request):
    """ Context processor ou fragment HTML selon usage """
    if not request.user.is_authenticated:
        return {"login_form": LoginForm()}
    return {}


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
