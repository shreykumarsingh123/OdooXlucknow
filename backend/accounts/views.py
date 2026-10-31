import logging
import secrets
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import ProtectedError
from django.utils import timezone
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token
from rest_framework import generics, mixins, serializers, viewsets
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView

from .emails import send_password_otp
from .identity import WORK_DOMAINS, classify, customers_of
from .models import Business, PasswordOTP, User
from .permissions import IsAdmin, IsTeam
from .serializers import MeSerializer, PersonSerializer, SignupSerializer, StaffSerializer

logger = logging.getLogger(__name__)
OTP_MINUTES = 10
OTP_ATTEMPTS = 5
OTP_CODES_PER_HOUR = 3


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
            if classify(email)["kind"] != "user":
                raise serializers.ValidationError({"credential": ["Sign in with a name@gmail.com account."]})
            first = claims.get("given_name", "")[:150]
            user = User.objects.create_user(
                email, None, first_name=first, last_name=claims.get("family_name", "")[:150], email_verified=True,
                role=User.Role.ADMIN, business=Business.objects.create(name=first or email.partition("@")[0]),
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
        body = {"message": "If this email has an account, a 6-digit code is on its way."}
        # A work address such as name@sale.com may be a stranger's mailbox, so it never receives a code.
        if user and (user.recovery_email or user.email.rpartition("@")[2] not in WORK_DOMAINS):
            code = self._issue(user)
            if code:
                try:
                    send_password_otp(user, code, OTP_MINUTES)
                except Exception:  # the response must not reveal whether the account exists
                    logger.exception("Could not send password reset code")
                # With no mail server, the code would reach nobody. Local development only.
                if settings.DEBUG and settings.EMAIL_BACKEND.endswith("filebased.EmailBackend"):
                    body["dev_otp"] = code
        return Response(body)

    @transaction.atomic
    def _issue(self, user):
        """A new code, or None once this account has had its codes for the hour. The answer to the caller stays the same."""
        now = timezone.now()
        code = f"{secrets.randbelow(1000000):06d}"
        fresh = {"expires_at": now + timedelta(minutes=OTP_MINUTES), "code_hash": make_password(code)}
        row = PasswordOTP.objects.select_for_update().filter(user=user).first()
        if row is None:
            PasswordOTP.objects.create(user=user, window_start=now, codes_sent=1, **fresh)
            return code
        if row.window_start < now - timedelta(hours=1):
            row.window_start, row.codes_sent, row.attempts = now, 0, 0
        if row.codes_sent >= OTP_CODES_PER_HOUR:
            row.save(update_fields=["window_start", "codes_sent", "attempts"])
            return None
        row.codes_sent += 1
        row.code_hash, row.expires_at = fresh["code_hash"], fresh["expires_at"]
        row.save()
        return code


class ResetPasswordView(PublicAuth, APIView):
    def post(self, request):
        invalid = serializers.ValidationError({"otp": ["This code is wrong or has expired. Request a new one."]})
        email = str(request.data.get("email", "")).strip().lower()
        with transaction.atomic():
            row = PasswordOTP.objects.select_for_update().select_related("user").filter(user__email__iexact=email, user__is_active=True).first()
            if row is None:
                raise invalid
            # The row stays, so that its hourly limits still count after a code runs out.
            if row.expires_at < timezone.now() or row.attempts >= OTP_ATTEMPTS:
                raise invalid
            if not check_password(str(request.data.get("otp", "")).strip(), row.code_hash):
                row.attempts += 1
                row.save(update_fields=["attempts"])
                ok = False
            else:
                ok = True
        if not ok:
            raise invalid
        user = row.user
        password = str(request.data.get("password", ""))
        try:
            validate_password(password, user)
        except ValidationError as exc:
            raise serializers.ValidationError({"password": list(exc.messages)})
        user.set_password(password)
        # A code sent to a recovery address proves nothing about the sign-in address, and Google trusts this flag.
        if not user.recovery_email:
            user.email_verified = True
        user.save(update_fields=["password", "email_verified"])
        row.delete()
        return Response({"message": "Password updated. You can sign in now."})


class MeView(generics.RetrieveUpdateAPIView):
    serializer_class = MeSerializer
    permission_classes = [IsAuthenticated]
    http_method_names = ["get", "patch"]

    def get_object(self):
        return self.request.user


class CustomerViewSet(mixins.ListModelMixin, mixins.CreateModelMixin, mixins.RetrieveModelMixin, mixins.UpdateModelMixin, viewsets.GenericViewSet):
    permission_classes = [IsTeam]
    serializer_class = PersonSerializer
    search_fields = ["email", "first_name", "last_name", "company"]
    filterset_fields = ["is_active"]
    ordering_fields = ["email", "first_name", "company", "date_joined"]

    def get_queryset(self):
        user = self.request.user
        return customers_of(user.business_id, user.is_platform)

    def perform_create(self, serializer):
        user = self.request.user
        if user.is_platform:
            # Brightloop's customer is a business, so a new customer brings a new business with it.
            data = serializer.validated_data
            business = Business.objects.create(name=data.get("company") or data.get("first_name") or data["email"].partition("@")[0])
            created = serializer.save(role=User.Role.ADMIN, business=business)
        else:
            created = serializer.save(role=User.Role.CUSTOMER, business=user.business)
        created.set_unusable_password()
        created.save(update_fields=["password"])


class StaffViewSet(viewsets.ModelViewSet):
    """Only an owner, or the administrator for Brightloop's own staff, manages a team."""

    permission_classes = [IsAdmin]
    serializer_class = StaffSerializer
    search_fields = ["email", "first_name", "last_name"]
    filterset_fields = ["is_active", "department"]
    http_method_names = ["get", "post", "put", "patch", "delete"]

    def get_queryset(self):
        return User.objects.filter(role=User.Role.STAFF, business_id=self.request.user.business_id)

    def destroy(self, request, *args, **kwargs):
        person = self.get_object()
        try:
            person.delete()
        except ProtectedError:
            # They wrote messages or recorded payments, and those records must stay. Their access ends all the same.
            person.is_active = False
            person.save(update_fields=["is_active"])
        return Response(status=204)
