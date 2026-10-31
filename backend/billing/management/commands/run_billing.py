from django.core.management.base import BaseCommand

from billing.services import run_billing


class Command(BaseCommand):
    help = "Bill everything due and close ended subscriptions. Schedule this daily."

    def handle(self, *args, **options):
        result = run_billing()
        self.stdout.write(str(result))
        if result["failed"]:
            raise SystemExit(1)
