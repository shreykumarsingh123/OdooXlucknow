import random
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from accounts.models import User
from billing import services
from billing.models import Invoice, Payment, Subscription, SubscriptionLine
from catalog.models import Discount, PaymentTerm, Plan, Product, ProductVariant, QuotationTemplate, QuotationTemplateLine, Tax

DEMO_PASSWORD = "Brightloop@123"  # demo accounts only; the command refuses to run outside DEBUG


class Command(BaseCommand):
    help = "Load demo data. Use --volume N to add N extra subscriptions for performance checks."

    def add_arguments(self, parser):
        parser.add_argument("--volume", type=int, default=0)

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError("seed_demo only runs when DEBUG is true.")
        self.today = timezone.localdate()
        self.catalog()
        self.people()
        self.stories()
        if options["volume"]:
            self.volume(options["volume"])
        self.stdout.write(self.style.SUCCESS(f"Seeded. Demo logins use the password {DEMO_PASSWORD}"))

    def person(self, email, role, **extra):
        user, created = User.objects.get_or_create(email=email, defaults={"role": role, **extra})
        if created:
            user.set_password(DEMO_PASSWORD)
            user.save(update_fields=["password"])
        return user

    def catalog(self):
        self.gst, _ = Tax.objects.get_or_create(name="GST 18%", defaults={"rate": Decimal("18")})
        self.net0, _ = PaymentTerm.objects.get_or_create(name="Immediate", defaults={"due_days": 0})
        self.net15, _ = PaymentTerm.objects.get_or_create(name="Net 15", defaults={"due_days": 15})
        self.net30, _ = PaymentTerm.objects.get_or_create(name="Net 30", defaults={"due_days": 30})
        self.erp, _ = Product.objects.get_or_create(
            name="Brightloop ERP Seat",
            defaults={"sales_price": Decimal("1200"), "cost_price": Decimal("300"), "type": "software", "notes": "Per user, per billing period."},
        )
        self.erp.taxes.add(self.gst)
        self.odoo, _ = ProductVariant.objects.get_or_create(
            product=self.erp, attribute="Brand", value="Odoo", defaults={"extra_price": Decimal("560")}
        )
        ProductVariant.objects.get_or_create(product=self.erp, attribute="Brand", value="Standard", defaults={"extra_price": 0})
        self.backup, _ = Product.objects.get_or_create(
            name="Cloud Backup Add-on", defaults={"sales_price": Decimal("450"), "cost_price": Decimal("90"), "type": "addon"}
        )
        self.backup.taxes.add(self.gst)
        start = self.today - timedelta(days=400)
        self.monthly, _ = Plan.objects.get_or_create(
            name="Business Monthly",
            defaults={"price": Decimal("999"), "billing_period": "monthly", "min_quantity": 1, "start_date": start, "pausable": True, "is_public": True},
        )
        self.monthly.taxes.add(self.gst)
        growth, _ = Plan.objects.get_or_create(
            name="Growth Monthly",
            defaults={"price": Decimal("2499"), "billing_period": "monthly", "min_quantity": 1, "start_date": start, "pausable": True, "trial_days": 14, "is_public": True},
        )
        growth.taxes.add(self.gst)
        self.yearly, _ = Plan.objects.get_or_create(
            name="Enterprise Yearly",
            defaults={"price": Decimal("49999"), "billing_period": "yearly", "min_quantity": 10, "start_date": start, "closable": False, "is_public": True},
        )
        self.yearly.taxes.add(self.gst)
        self.trial, _ = Plan.objects.get_or_create(
            name="Starter Weekly (ends on its own)",
            defaults={"price": Decimal("199"), "billing_period": "weekly", "min_quantity": 1, "start_date": start, "auto_close": True, "renewable": False, "is_public": True},
        )
        template, created = QuotationTemplate.objects.get_or_create(
            name="Enterprise 25 seats", defaults={"plan": self.yearly, "validity_days": 30}
        )
        if created:
            QuotationTemplateLine.objects.create(template=template, product=self.erp, variant=self.odoo, quantity=25)
        seats, created = Discount.objects.get_or_create(
            name="10% off for 20+ seats",
            defaults={"kind": "percent", "value": Decimal("10"), "scope": "products", "min_quantity": 20, "start_date": start},
        )
        if created:
            seats.products.add(self.erp)
        Discount.objects.get_or_create(
            name="Welcome offer", defaults={"kind": "percent", "value": Decimal("20"), "scope": "subscriptions", "start_date": start, "code": "WELCOME20"}
        )

    def people(self):
        self.person("admin@brightloop.example", User.Role.ADMIN, first_name="Asha", last_name="Admin", is_staff=True, is_superuser=True)
        self.person("staff@brightloop.example", User.Role.STAFF, first_name="Sam", last_name="Sales")
        self.acme = self.person("customer@acme.example", User.Role.CUSTOMER, first_name="Priya", last_name="Verma", company="Acme Retail", address="12 Hazratganj, Lucknow")
        self.globex = self.person("finance@globex.example", User.Role.CUSTOMER, first_name="Rahul", last_name="Khan", company="Globex Industries", address="88 Gomti Nagar, Lucknow")

    def make(self, customer, plan, months_ago, rows, term, state="active", months_long=12):
        start = services.add_months(self.today, -months_ago)
        sub = services.save_subscription(
            {"customer": customer, "plan": plan, "payment_term": term, "start_date": start,
             "expiry_date": services.add_months(start, months_long)},
            rows,
        )
        if state != "draft":
            services.send_quotation(sub.pk)
        if state in ("confirmed", "active"):
            services.confirm(sub.pk)
        if state == "active":
            services.activate(sub.pk)
        return sub

    def stories(self):
        if Subscription.objects.filter(customer=self.acme).exists():
            return
        admin = User.objects.get(email="admin@brightloop.example")
        acme_rows = [{"product": self.erp, "quantity": 3}, {"product": self.backup, "quantity": 1}]
        acme = self.make(self.acme, self.monthly, 3, acme_rows, self.net15)
        globex_rows = [{"product": self.erp, "variant": self.odoo, "quantity": 25}]
        self.make(self.globex, self.yearly, 2, globex_rows, self.net30)
        self.make(self.acme, self.monthly, 0, [{"product": self.erp, "quantity": 2}], self.net15, state="quotation")
        self.make(self.globex, self.monthly, 0, [{"product": self.backup, "quantity": 1}], self.net0, state="draft")
        # Bill Acme month by month so its invoices carry real past dates and some are overdue.
        for months_ago in (3, 2, 1, 0):
            services.bill_subscription(acme.pk, services.add_months(self.today, -months_ago))
        services.run_billing()
        # The oldest Acme invoice is paid, the next is part paid, and the rest stay open.
        invoices = list(Invoice.objects.filter(subscription=acme).order_by("period_start"))
        for invoice in invoices:
            services.confirm_invoice(invoice.pk)
        if invoices:
            services.record_payment(invoices[0].pk, "upi", invoices[0].total, invoices[0].due_date, "Paid in full", admin)
        if len(invoices) > 1:
            services.record_payment(invoices[1].pk, "bank_transfer", Decimal("1000"), self.today, "Part payment", admin)

    def volume(self, count):
        """Bulk insert for speed. These rows skip the workflow on purpose and only exist to test page load times."""
        customers = [
            User(email=f"load{i}@volume.example", role=User.Role.CUSTOMER, first_name="Load", last_name=str(i), company=f"Load Co {i}", password="!")
            for i in range(max(count // 10, 1))
        ]
        User.objects.bulk_create(customers, ignore_conflicts=True)
        customers = list(User.objects.filter(email__endswith="@volume.example"))
        plans = [self.monthly, self.yearly, self.trial]
        terms = [self.net0, self.net15, self.net30]
        admin = User.objects.get(email="admin@brightloop.example")
        rng = random.Random(7)
        base = Subscription.objects.order_by("-id").values_list("id", flat=True).first() or 0
        subs = []
        for i in range(count):
            start = self.today - timedelta(days=rng.randint(30, 360))
            subs.append(Subscription(
                number=f"VOL-{base + i + 1:07d}", customer=rng.choice(customers), plan=rng.choice(plans), payment_term=rng.choice(terms),
                start_date=start, expiry_date=start + timedelta(days=720), state="active",
                next_invoice_date=self.today + timedelta(days=rng.randint(1, 28)), recurring_total=Decimal(rng.randint(999, 90000)),
            ))
        Subscription.objects.bulk_create(subs, batch_size=1000)
        subs = list(Subscription.objects.filter(number__startswith="VOL-").select_related("customer"))
        SubscriptionLine.objects.bulk_create(
            [SubscriptionLine(subscription=s, description="Volume line", quantity=1, unit_price=s.recurring_total) for s in subs],
            batch_size=1000,
        )
        invoices = []
        for index, s in enumerate(subs):
            day = self.today - timedelta(days=rng.randint(0, 300))
            invoices.append(Invoice(
                number=f"VOL-{s.pk}-{index}", subscription=s, customer=s.customer, customer_name=s.customer.display_name,
                customer_email=s.customer.email, state=rng.choice(["confirmed", "paid"]), invoice_date=day, due_date=day + timedelta(days=15),
                period_start=day, period_end=day + timedelta(days=29), billing_key=f"vol:{s.pk}", subtotal=s.recurring_total,
                total=s.recurring_total,
            ))
        Invoice.objects.bulk_create(invoices, batch_size=1000)
        paid = list(Invoice.objects.filter(number__startswith="VOL-", state="paid"))
        Invoice.objects.filter(pk__in=[i.pk for i in paid]).update(amount_paid=0)
        for invoice in paid:
            invoice.amount_paid = invoice.total
        Invoice.objects.bulk_update(paid, ["amount_paid"], batch_size=1000)
        Payment.objects.bulk_create(
            [Payment(invoice=i, method=rng.choice(Payment.Method.values), amount=i.total, date=i.invoice_date, recorded_by=admin) for i in paid],
            batch_size=1000,
        )
