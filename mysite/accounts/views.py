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
from ..medias.models import UserLink
from ..medias.forms import UserDetailsEdit


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
            return redirect(request.POST.get('next'))
            # return redirect('common:index')
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
    template_name = 'community/index.html'
    queryset = User.objects.all()
    context_object_name = 'user_list'


class UserPage(DetailView):
    template_name = 'community/user_details.html'
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
    template_name = 'community/user_form.html'
    model = User
    fields = ["first_name", "last_name", "email"]

    def get_success_url(self):
        from django.urls import reverse
        return reverse('community:user-page', args=[self.get_object().pk])

    def get_object(self):
        return self.model.objects.get(pk=self.request.user.id)

    def get_context_data(self, **kwargs):
        context = super(UserEdit, self).get_context_data(**kwargs)
        context['title'] = f'{self.get_object().first_name} {self.get_object().last_name}'
        context['subtitle'] = 'Edit user information'
        return context


# Query views : Details

@method_decorator(login_required, name='dispatch')
class UserDetailsUpdate(UpdateView):
    template_name = 'community/userdetails_form.html'
    form_class = UserDetailsEdit

    def get_success_url(self):
        from django.urls import reverse
        return reverse('community:user-page', args=[self.get_object().user.pk])

    def get_object(self):
        return self.form_class._meta.model.objects.get(user__pk=self.request.user.id)

    def form_valid(self, form):
        form.instance.user = self.request.user
        return super().form_valid(form)


# Query views : Links

@method_decorator(login_required, name='dispatch')
class UserLinkUpdate(UpdateView):
    model = UserLink

    def get_success_url(self):
        from django.urls import reverse
        return reverse('community:user-page', args=[self.get_object().added_by.pk])

    def get_context_data(self, **kwargs):
        context = super(UserLinkUpdate, self).get_context_data(**kwargs)
        context['title'] = f'{self.request.user.first_name} {self.request.user.last_name}'
        context['subtitle'] = 'Edit link'
        return context


@method_decorator(login_required, name='dispatch')
class UserLinkInsert(CreateView):
    model = UserLink
    fields = ['name', 'details', 'url']

    def get_success_url(self):
        from django.urls import reverse
        return reverse('community:user-page', args=[self.request.user.pk])

    def form_valid(self, form):
        form.instance.added_by = self.request.user
        return super().form_valid(form)

    def get_context_data(self, **kwargs):
        context = super(UserLinkInsert, self).get_context_data(**kwargs)
        context['title'] = f'{self.request.user.first_name} {self.request.user.last_name}'
        context['subtitle'] = 'New link'
        return context


@method_decorator(login_required, name='dispatch')
class UserLinkDelete(DeleteView):
    model = UserLink

    def get_success_url(self):
        from django.urls import reverse
        return reverse('community:user-page', args=[self.get_object().added_by.pk])