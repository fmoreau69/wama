from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.contrib.auth import login, logout
from django.utils.decorators import method_decorator
from django.views.generic import ListView, View, DetailView, TemplateView, RedirectView
from django.views.generic.edit import CreateView, UpdateView, DeleteView
from django.http import HttpResponseRedirect
from django.shortcuts import render, redirect
from django.contrib import messages

from .models import LoginForm, UserRegistrationForm
from ..medias.forms import UserSettingsEdit


def login_view(request):
    if request.user.is_authenticated:
        return redirect('medias:upload')

    if request.method == 'POST':
        # Create form with POST request
        form = LoginForm(data=request.POST)
        # Verify form validity
        if form.is_valid():
            # get the user
            user = form.get_user()
            # log in the user
            login(request, user)
            # Return home page
            messages.success(request, "Successfully logged in !")
            # return redirect(request.POST.get('next'))
            return redirect('medias:upload')
        else:
            messages.error(request, "Wrong login ID or password.")
            return redirect(request.POST.get('next'))
    else:
        # Return blank form
        form = LoginForm()
    return render(request, 'accounts/login_v2.html', {'form': form, 'type_of_view': 'login'})


def signup_view(request):
    # Determine if it is POST or GET request
    if request.method == 'POST':
        # Create form with POST request
        form = UserRegistrationForm(request.POST)
        # Verify form validity
        if form.is_valid():
            # Save and get the user
            form.save()
            return render(request, 'accounts/signup_validation.html')
    else:
        # Return blank form
        form = UserRegistrationForm()
    # Return page with the right form (blank or filled)
    return render(request, 'accounts/login.html', {'form': form, 'type_of_view': 'register'})


def logout_view(request):
    # If POST method (POST == good practice to logout) => a voir si ça marche
    # if request.method == "POST":
    # Logout current user
    logout(request)
    return HttpResponseRedirect('/')


class IndexView(ListView):
    template_name = 'upload/index.html'
    queryset = User.objects.all()
    context_object_name = 'user_list'


class UserPage(DetailView):
    template_name = 'accounts/user_settings.html'
    queryset = User.objects.all()
    context_object_name = 'selected_user'
    can_edit = False

    def dispatch(self, request, *args, **kwargs):
        if kwargs['pk'] == request.user.pk:
            self.can_edit = True
        return super(UserPage, self).dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super(UserPage, self).get_context_data(**kwargs)
        context['can_edit'] = self.can_edit
        return context


@method_decorator(login_required, name='dispatch')
class UserEdit(UpdateView):
    template_name = 'accounts/user_form.html'
    model = User
    fields = ["first_name", "last_name", "email"]

    def get_success_url(self):
        from django.urls import reverse
        return reverse('medias:upload')

    def get_object(self):
        return self.model.objects.get(pk=self.request.user.id)

    def get_context_data(self, **kwargs):
        context = super(UserEdit, self).get_context_data(**kwargs)
        context['title'] = f'{self.get_object().first_name} {self.get_object().last_name}'
        context['subtitle'] = 'Edit user information'
        return context


# Query views : settings

@method_decorator(login_required, name='dispatch')
class UserSettingsUpdate(UpdateView):
    template_name = 'accounts/user_settings_form.html'
    form_class = UserSettingsEdit

    def get_success_url(self):
        from django.urls import reverse
        return reverse('medias:upload')

    def get_object(self):
        return self.form_class._meta.model.objects.get(user__pk=self.request.user.id)

    def form_valid(self, form):
        form.instance.user = self.request.user
        return super().form_valid(form)


def login_form(request):
    form = LoginForm()
    out = {}
    if request.user.is_authenticated is False:
        out = {"login_form": form}
    return out
