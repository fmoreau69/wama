from django.contrib.auth import login, logout
from django.http import HttpResponseRedirect
from django.shortcuts import render, redirect
from django.contrib import messages

from .models import LoginForm, UserRegistrationForm


def login_view(request):
    if request.user.is_authenticated:
        return redirect('upload:index')

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
