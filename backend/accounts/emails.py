from django.conf import settings
from django.contrib.auth.tokens import default_token_generator
from django.core.mail import send_mail
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode


def password_link(user):
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    token = default_token_generator.make_token(user)
    return f"{settings.FRONTEND_URL}/reset-password?uid={uid}&token={token}"


def send_reset_email(user):
    send_mail(
        "Reset your Brightloop password",
        f"Hello,\n\nUse this link to set a new password. It expires in 2 hours.\n\n{password_link(user)}\n\n"
        "If you did not ask for this, you can ignore this email.",
        settings.DEFAULT_FROM_EMAIL,
        [user.email],
    )


def send_invite_email(user):
    send_mail(
        "Your Brightloop account is ready",
        f"Hello,\n\nAn account was created for you. Use this link to choose your password. "
        f"It expires in 2 hours, and you can request a new one from the sign-in page.\n\n{password_link(user)}",
        settings.DEFAULT_FROM_EMAIL,
        [user.email],
    )
