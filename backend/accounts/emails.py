from django.conf import settings
from django.core.mail import send_mail


def send_password_otp(user, code, minutes):
    """Goes to the recovery address when there is one, since work addresses have no real mailbox."""
    send_mail(
        "Your Brightloop password reset code",
        f"Hello {user.display_name},\n\n"
        "We received a request to reset the password for your Brightloop account.\n\n"
        f"Your one-time code is: {code}\n\n"
        f"Enter it on the Forgot password page, then choose a new password. The code expires in {minutes} minutes and works once.\n\n"
        "If you did not ask for this, you can ignore this email. Your password has not changed, and nobody can change it without this code.\n\n"
        "Brightloop Software",
        settings.DEFAULT_FROM_EMAIL,
        [user.recovery_email or user.email],
    )
