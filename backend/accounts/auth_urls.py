from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView

from . import views

urlpatterns = [
    path("signup/", views.SignupView.as_view()),
    path("login/", views.LoginView.as_view()),
    path("refresh/", TokenRefreshView.as_view()),
    path("forgot-password/", views.ForgotPasswordView.as_view()),
    path("reset-password/", views.ResetPasswordView.as_view()),
    path("me/", views.MeView.as_view()),
    path("config/", views.AuthConfigView.as_view()),
    path("google/", views.GoogleLoginView.as_view()),
]
