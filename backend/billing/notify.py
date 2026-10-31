import logging

import requests
from django.conf import settings

logger = logging.getLogger(__name__)


def send_sms(to, body):
    """Send one SMS through Twilio. Returns False, without raising, if it is not set up or fails."""
    sid, key, secret, sender = (
        settings.TWILIO_ACCOUNT_SID, settings.TWILIO_API_KEY_SID, settings.TWILIO_API_KEY_SECRET, settings.TWILIO_FROM_NUMBER,
    )
    if not (to and sid and key and secret and sender):
        return False
    try:
        response = requests.post(
            f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json",
            auth=(key, secret),
            data={"To": to, "From": sender, "Body": body},
            timeout=10,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        # The exception text is safe to log: credentials travel in the auth header, not the URL.
        logger.warning("SMS failed: %s", exc)
        return False
    return True
