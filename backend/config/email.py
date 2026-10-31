"""Sends mail over HTTPS through Brevo, for hosts whose free plans block SMTP ports."""
from email.utils import parseaddr

import requests
from django.conf import settings
from django.core.mail.backends.base import BaseEmailBackend

BREVO_URL = "https://api.brevo.com/v3/smtp/email"


class BrevoEmailBackend(BaseEmailBackend):
    def send_messages(self, email_messages):
        sent = 0
        for message in email_messages:
            name, address = parseaddr(message.from_email)
            payload = {
                "sender": {"email": address, **({"name": name} if name else {})},
                "to": [{"email": recipient} for recipient in message.recipients()],
                "subject": message.subject,
                "textContent": message.body,
            }
            try:
                response = requests.post(BREVO_URL, json=payload, headers={"api-key": settings.BREVO_API_KEY}, timeout=10)
                response.raise_for_status()
                sent += 1
            except requests.RequestException:
                if not self.fail_silently:
                    raise
        return sent
