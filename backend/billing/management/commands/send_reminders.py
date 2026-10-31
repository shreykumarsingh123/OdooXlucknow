from django.core.management.base import BaseCommand

from billing.services import send_reminders


class Command(BaseCommand):
    help = "Remind customers about overdue invoices. Schedule this daily."

    def handle(self, *args, **options):
        self.stdout.write(str(send_reminders()))
