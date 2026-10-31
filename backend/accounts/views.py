import logging

from django.conf import settings
from django.contrib.auth.password_validation import validate_password
from django.contrib.auth.tokens import default_token_generator
from django.core.exceptions import ValidationError
from django.utils.encoding import force_str
from django.utils.http import urlsafe_base64_decode
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token
from rest_framework import generics, mixins, serializers, viewsets
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView

from .emails import send_invite_email, send_reset_email
from .models import User
from .permissions import IsAdmin, IsTeam
from .serializers import MeSerializer, PersonSerializer, SignupSerializer

logger = logging.getLogger(__name__)


class PublicAuth:
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "auth"
    permission_classes = [AllowAny]
    authentication_classes = []


class LoginView(PublicAuth, TokenObtainPairView):
    pass


class SignupView(PublicAuth, generics.CreateAPIView):
    serializer_class = SignupSerializer


class AuthConfigView(PublicAuth, APIView):
    """Public settings for the sign-in page. A client ID is not a secret."""

    throttle_classes = []

    def get(self, request):
        return Response({"google_client_id": settings.GOOGLE_CLIENT_ID})


class GoogleLoginView(PublicAuth, APIView):
    def post(self, request):
        if not settings.GOOGLE_CLIENT_ID:
            raise serializers.ValidationError({"credential": ["Google sign-in is not set up."]})
        try:
            claims = id_token.verify_oauth2_token(
                str(request.data.get("credential", "")), google_requests.Request(), settings.GOOGLE_CLIENT_ID
            )
        except ValueError:
            raise serializers.ValidationError({"credential": ["Google sign-in failed. Please try again."]})
        email = str(claims.get("email", "")).strip().lower()
        # Only a Google-verified address may claim an account with that email.
        if not email or not claims.get("email_verified"):
            raise serializers.ValidationError({"credential": ["Your Google email is not verified."]})
        user = User.objects.filter(email__iexact=email).first()
        if user is None:
            user = User.objects.create_user(
                email, None, first_name=claims.get("given_name", "")[:150], last_name=claims.get("family_name", "")[:150],
                email_verified=True,
            )
        elif not user.email_verified:
            # Anyone can sign up with someone else's email. Linking now would let that person keep a password on this account.
            if user.has_usable_password():
                raise serializers.ValidationError(
                    {"credential": ["This email already has a password. Sign in with it, or use Forgot password, then try Google again."]}
                )
            user.email_verified = True
            user.save(update_fields=["email_verified"])
        if not user.is_active:
            raise serializers.ValidationError({"credential": ["This account is deactivated."]})
        refresh = RefreshToken.for_user(user)
        return Response({"access": str(refresh.access_token), "refresh": str(refresh)})


class ForgotPasswordView(PublicAuth, APIView):
    def post(self, request):
        email = str(request.data.get("email", "")).strip().lower()
        user = User.objects.filter(email__iexact=email, is_active=True).first()
        if user:
            try:
                send_reset_email(user)
            except Exception:  # the response must not reveal whether the account exists
                logger.exception("Could not send password reset email")
        return Response({"message": "If this email has an account, a reset link is on its way."})


class ResetPasswordView(PublicAuth, APIView):
    def post(self, request):
        invalid = serializers.ValidationError({"token": ["This reset link is invalid or has expired."]})
        try:
            pk = force_str(urlsafe_base64_decode(str(request.data.get("uid", ""))))
            user = User.objects.get(pk=pk, is_active=True)
        except (User.DoesNotExist, ValueError, TypeError, OverflowError):
            raise invalid
        if not default_token_generator.check_token(user, str(request.data.get("token", ""))):
            raise invalid
        password = str(request.data.get("password", ""))
        try:
            validate_password(password, user)
        except ValidationError as exc:
            raise serializers.ValidationError({"password": list(exc.messages)})
        user.set_password(password)
        user.email_verified = True
        user.save(update_fields=["password", "email_verified"])
        return Response({"message": "Password updated. You can sign in now."})


class MeView(generics.RetrieveUpdateAPIView):
    serializer_class = MeSerializer
    permission_classes = [IsAuthenticated]
    http_method_names = ["get", "patch"]

    def get_object(self):
        return self.request.user


class PersonViewSet(
    mixins.ListModelMixin, mixins.CreateModelMixin, mixins.RetrieveModelMixin, mixins.UpdateModelMixin, viewsets.GenericViewSet
):
    serializer_class = PersonSerializer
    search_fields = ["email", "first_name", "last_name", "company"]
    filterset_fields = ["is_active"]
    ordering_fields = ["email", "first_name", "company", "date_joined"]
    role = None

    def get_queryset(self):
        return User.objects.filter(role=self.role)

    def perform_create(self, serializer):
        user = serializer.save(role=self.role)
        user.set_unusable_password()
        user.save(update_fields=["password"])
        try:
            send_invite_email(user)
        except Exception:
            logger.exception("Could not send invite email")


class CustomerViewSet(PersonViewSet):
    permission_classes = [IsTeam]
    role = User.Role.CUSTOMER


class StaffViewSet(PersonViewSet):
    permission_classes = [IsAdmin]
    role = User.Role.STAFF
