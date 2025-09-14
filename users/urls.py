from django.urls import path
from django.views.generic import TemplateView

from .decorators import unauthenticated_user

from .views import (
    register_user,
    EmailActivation,
    ConfirmationEmail,
    PassowrdRisetConfirm,
    login_view,
    login_validation, 
    logout_view,
)

urlpatterns = [
    path('register/', register_user, name="register"),
    path('account/riset-password/', unauthenticated_user(TemplateView.as_view(template_name="account/riset_password.html")), name="riset_password"),
    path('account/confirm-riset-password/', unauthenticated_user(TemplateView.as_view(template_name="account/confirm_riset_password.html")), name="confirm_riset_password"),
    path('account/confirmation-email/<str:username>/', ConfirmationEmail, name="confirmation_email"),
    path('activate/<str:uidb64>/<str:token>/', EmailActivation, name="email_activation"),
    path('password/reset/confirm/<str:uidb64>/<str:token>/', PassowrdRisetConfirm, name="pass_riset_confirm"),
    path('login/', login_view, name="login"),
    path('account/login-validation/', login_validation, name="login_validation"),
    path('logout/', logout_view, name="logout"),
]