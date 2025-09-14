from django.shortcuts import render,redirect
from django.http import JsonResponse
from django.contrib.auth import login, authenticate, logout
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ObjectDoesNotExist
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_http_methods

from django.contrib.auth import get_user_model

from .forms import AccountAuthenticationForm
from .decorators import unauthenticated_user, autenticated_user

User = get_user_model()



@unauthenticated_user
def register_user(request):

    return render(request, 'account/register.html')


@unauthenticated_user
def ConfirmationEmail(request, username):
    user_is_exists = User.objects.filter(username=username).exists()
    if user_is_exists:
        try:
            get_username = User.objects.get(username=username)

            request.session['email'] = get_username.email

        except Exception as e:
            print(str(e))

        context = {
            'user' : get_username
        }
        return render(request, 'account/comfirmation_email.html', context)
    else:
        return redirect('register')



@unauthenticated_user
def EmailActivation(request, uidb64, token):
    user_uid = uidb64
    user_token = token

    context = {
        'uid': user_uid,
        'token': user_token,
    }

    return render(request, 'account/activation_email.html', context)



def get_redirect_if_exists(request):
    redirect = None
    if request.GET:
        if request.GET.get("next"):
            redirect = str(request.GET.get("next"))
    return redirect


@unauthenticated_user
def login_view(request, *args, **kwargs):
    context = {}

    user = request.user
    if user.is_authenticated:
        return redirect("dashboard")

    destination = get_redirect_if_exists(request)

    if request.POST:
        form = AccountAuthenticationForm(request.POST)
        if form.is_valid():
            email = request.POST['email']
            password = request.POST['password']
            user = authenticate(email=email, password=password)

            if user:
                login(request, user)
                if destination:
                    return redirect(destination)
                return redirect("dashboard")

    else:
        form = AccountAuthenticationForm()

    context['login_form'] = form

    return render(request, "account/login.html", context)



@ensure_csrf_cookie
@require_http_methods(["POST"])
def login_validation(request):
    # Check if request is AJAX by looking at the HTTP_X_REQUESTED_WITH header
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        input_email = request.POST.get('email')
        input_password = request.POST.get('password')
        try:
            account = authenticate(email=input_email, password=input_password)
            if account is not None:
                return JsonResponse({'data': 'Valid'})
            else:
                return JsonResponse({'data': 'NotValid'})

        except ObjectDoesNotExist:
            return JsonResponse({'data': 'NotValid'})
    else:
        return JsonResponse({'error': 'Invalid request'}, status=400)



@unauthenticated_user
def PassowrdRisetConfirm(request, uidb64, token):
    user_uid = uidb64
    user_token = token

    context = {
        'uid': user_uid,
        'token': user_token
    }

    return render(request, 'account/riset_password_confirm.html', context)



@autenticated_user
@login_required(login_url='login')
def logout_view(request):
    logout(request)
    return redirect("login")
