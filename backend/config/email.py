"""Sends mail through Twilio Email, using the same API key as SMS."""
from email.utils import parseaddr

import requests
from django.conf import settings
from django.core.mail.backends.base import BaseEmailBackend
from django.utils.html import escape, linebreaks

TWILIO_EMAIL_URL = "https://comms.twilio.com/v1/Emails"


class TwilioEmailBackend(BaseEmailBackend):
    def send_messages(self, email_messages):
        sent = 0
        for message in email_messages:
            name, address = parseaddr(message.from_email)
            payload = {
                "from": {"address": address, **({"name": name} if name else {})},
                "to": [{"address": recipient} for recipient in message.recipients()],
                "content": {"subject": message.subject, "text": message.body, "html": linebreaks(escape(message.body))},
            }
            try:
                response = requests.post(
                    TWILIO_EMAIL_URL, json=payload, auth=(settings.TWILIO_API_KEY_SID, settings.TWILIO_API_KEY_SECRET), timeout=10
                )
                response.raise_for_status()  # 202 means queued, and delivery itself is not confirmed here
                sent += 1
            except requests.RequestException:
                if not self.fail_silently:
                    raise
        return sent
