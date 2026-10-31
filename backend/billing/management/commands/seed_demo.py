import os
import random
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from accounts.models import Business, User
from billing import services
from billing.models import Invoice, Payment, PaymentRequest, SalesTarget, Subscription, SubscriptionLine
from catalog.models import Discount, PaymentTerm, Plan, Product, ProductVariant, QuotationTemplate, QuotationTemplateLine, Tax
from support.models import AdminMessage, TeamMessage, Ticket, TicketMessage

DEMO_PASSWORD = "Brightloop@123"  # for local development only; a live site must set SEED_PASSWORD


class Command(BaseCommand):
    help = "Load starting data following the business scheme. Use --volume N to add N subscriptions to Manbhwan for speed checks."

    def add_arguments(self, parser):
        parser.add_argument("--volume", type=int, default=0)
        parser.add_argument("--if-empty", action="store_true", help="Do nothing when data already exists, so this can run at every start.")

    def handle(self, *args, **options):
        if options["if_empty"] and Business.objects.exists():
            return
        # The default password is in this public repository, so it must never open a live site.
        self.password = os.environ.get("SEED_PASSWORD") or (DEMO_PASSWORD if settings.DEBUG else None)
        if self.password is None:
            raise CommandError("Set SEED_PASSWORD when DEBUG is false.")
        # Demo logins get shared with judges and teammates. That must never hand over the administrator too.
        self.admin_password = os.environ.get("ADMIN_PASSWORD") or (self.password if settings.DEBUG else None)
        if not settings.DEBUG:
            if not self.admin_password or self.admin_password == self.password:
                raise CommandError("Set an ADMIN_PASSWORD different from SEED_PASSWORD when DEBUG is false.")
            for name, value in (("SEED_PASSWORD", self.password), ("ADMIN_PASSWORD", self.admin_password)):
                if value == DEMO_PASSWORD:
                    raise CommandError(f"Choose a {name} other than the one in the repository.")
                try:
                    validate_password(value)
                except ValidationError as exc:
                    raise CommandError(f"{name} is too weak: {' '.join(exc.messages)}")
        self.today = timezone.localdate()
        self.start = self.today - timedelta(days=400)
        if Business.objects.exists():
            raise CommandError("Data already exists. Empty the database first.")
        self.brightloop()
        manbhwan = self.manbhwan()
        self.sunrise()
        if options["volume"]:
            self.volume(manbhwan, options["volume"])
        self.stdout.write(self.style.SUCCESS("Seeded."))

    def person(self, email, role, business, **extra):
        # No recovery address here. Each person enters their own real one at first login.
        return User.objects.create_user(email, self.password, role=role, business=business, **extra)

    def basics(self, business):
        gst = Tax.objects.create(business=business, name="GST 18%", rate=Decimal("18"))
        terms = {
            "now": PaymentTerm.objects.create(business=business, name="Immediate", due_days=0),
            "net15": PaymentTerm.objects.create(business=business, name="Net 15", due_days=15),
            "net30": PaymentTerm.objects.create(business=business, name="Net 30", due_days=30),
        }
        return gst, terms

    def plan(self, business, gst, name, price, period="monthly", **extra):
        extra.setdefault("min_quantity", 0)  # a plan fee alone is enough, with no product lines needed
        plan = Plan.objects.create(business=business, name=name, price=Decimal(price), billing_period=period, start_date=self.start, is_public=True, **extra)
        plan.taxes.add(gst)
        return plan

    def make(self, customer, plan, months_ago, rows, term, state="active", salesperson=None):
        start = services.add_months(self.today, -months_ago)
        sub = services.save_subscription(
            {"customer": customer, "plan": plan, "payment_term": term, "start_date": start, "expiry_date": services.add_months(start, 12), "salesperson": salesperson},
            rows,
        )
        if state != "draft":
            services.send_quotation(sub.pk)
        if state in ("confirmed", "active"):
            services.confirm(sub.pk)
        if state == "active":
            services.activate(sub.pk)
            Subscription.objects.filter(pk=sub.pk).update(activated_on=start)
        return sub

    def bill_history(self, sub, months, admin, paid_first=True):
        for back in range(months, -1, -1):
            services.bill_subscription(sub.pk, services.add_months(self.today, -back))
        invoices = list(Invoice.objects.filter(subscription=sub).order_by("period_start"))
        for invoice in invoices:
            services.confirm_invoice(invoice.pk)
        if paid_first and invoices:
            services.record_payment(invoices[0].pk, "upi", invoices[0].total, invoices[0].due_date, "Paid in full", admin)
        return invoices

    def ticket(self, business, customer, subject, body, **extra):
        ticket = Ticket.objects.create(business=business, customer=customer, subject=subject, **extra)
        ticket.number = f"TCK-{ticket.pk:06d}"
        ticket.save(update_fields=["number"])
        TicketMessage.objects.create(ticket=ticket, author=customer, body=body)
        return ticket

    def brightloop(self):
        """Brightloop is a business too. Its plans are what other businesses pay for."""
        self.platform = Business.objects.create(name="Brightloop", is_platform=True, code="brloop")
        self.asha = User.objects.create_superuser("asha@admin.com", self.admin_password, first_name="Asha", last_name="Admin")
        self.person("ravi@adminsale.com", User.Role.STAFF, self.platform, department="sales", first_name="Ravi", last_name="Rao")
        self.person("neha@support.com", User.Role.STAFF, self.platform, department="support", first_name="Neha", last_name="Nair")
        gst, terms = self.basics(self.platform)
        self.pterm = terms["net15"]
        self.pplans = {
            "starter": self.plan(self.platform, gst, "Starter", "999", pausable=True),
            "growth": self.plan(self.platform, gst, "Growth", "2499", pausable=True, trial_days=14),
            "scale": self.plan(self.platform, gst, "Scale", "49999", "yearly", renewable=True),
        }
        Discount.objects.create(business=self.platform, name="Launch offer", kind="percent", value=Decimal("20"), scope="subscriptions", start_date=self.start, code="WELCOME20")

    def owner_on_brightloop(self, owner, plan, months_ago):
        sub = self.make(owner, plan, months_ago, [], self.pterm)
        self.bill_history(sub, months_ago, self.asha)

    def manbhwan(self):
        business = Business.objects.create(name="Manbhwan Foods", code="mb7k2q")
        owner = self.person("manbhwan@gmail.com", User.Role.ADMIN, business, first_name="Manbhwan", last_name="Singh", company="Manbhwan Foods")
        sales = self.person(f"rohan{business.code}@sale.com", User.Role.STAFF, business, department="sales", first_name="Rohan", last_name="Gupta")
        care = self.person(f"pooja.{business.code}@support.com", User.Role.STAFF, business, department="support", first_name="Pooja", last_name="Sharma")
        priya = self.person("priya@gmail.com", User.Role.CUSTOMER, business, first_name="Priya", last_name="Verma", company="Verma Household", address="12 Hazratganj, Lucknow")
        rahul = self.person("rahul@gmail.com", User.Role.CUSTOMER, business, first_name="Rahul", last_name="Khan", company="Khan Traders", address="88 Gomti Nagar, Lucknow")
        self.owner_on_brightloop(owner, self.pplans["growth"], 2)

        gst, terms = self.basics(business)
        tiffin = Product.objects.create(business=business, name="Tiffin Meal", sales_price=Decimal("120"), cost_price=Decimal("70"), type="software", notes="Per meal plan seat.")
        tiffin.taxes.add(gst)
        premium = ProductVariant.objects.create(product=tiffin, attribute="Brand", value="Odoo", extra_price=Decimal("560"))
        ProductVariant.objects.create(product=tiffin, attribute="Brand", value="Standard", extra_price=0)
        dessert = Product.objects.create(business=business, name="Dessert Add-on", sales_price=Decimal("450"), cost_price=Decimal("150"), type="addon")
        dessert.taxes.add(gst)
        monthly = self.plan(business, gst, "Monthly Tiffin", "999", pausable=True)
        self.plan(business, gst, "Family Tiffin", "2499", pausable=True, trial_days=7)
        self.plan(business, gst, "Weekly Tiffin", "299", "weekly", auto_close=True, renewable=False)
        yearly = self.plan(business, gst, "Office Yearly", "49999", "yearly", min_quantity=10, closable=False)
        template = QuotationTemplate.objects.create(business=business, name="Office 25 seats", plan=yearly, validity_days=30)
        QuotationTemplateLine.objects.create(template=template, product=tiffin, variant=premium, quantity=25)
        seats = Discount.objects.create(business=business, name="10% off for 20+ seats", kind="percent", value=Decimal("10"), scope="products", min_quantity=20, start_date=self.start)
        seats.products.add(tiffin)
        for values in [
            {"name": "Welcome offer", "kind": "percent", "value": Decimal("20"), "code": "WELCOME20"},
            {"name": "500 account credit", "reward": "credit", "value": Decimal("500"), "code": "GIFT500"},
            {"name": "One month free", "reward": "free_days", "value": Decimal("30"), "code": "FREEMONTH"},
            {"name": "Free tasting", "reward": "perk", "perk_text": "A free tasting box", "code": "TASTE"},
        ]:
            Discount.objects.create(business=business, scope="subscriptions", start_date=self.start, **values)

        main = self.make(priya, monthly, 3, [{"product": tiffin, "quantity": 3}, {"product": dessert, "quantity": 1}], terms["net15"], salesperson=sales)
        self.make(rahul, yearly, 2, [{"product": tiffin, "variant": premium, "quantity": 25}], terms["net30"], salesperson=sales)
        self.make(priya, monthly, 0, [{"product": tiffin, "quantity": 2}], terms["net15"], state="quotation", salesperson=sales)
        self.make(rahul, monthly, 0, [{"product": dessert, "quantity": 1}], terms["now"], state="draft")
        invoices = self.bill_history(main, 3, owner)
        services.run_billing(business_id=business.pk)
        if len(invoices) > 1:
            services.record_payment(invoices[1].pk, "bank_transfer", Decimal("1000"), self.today, "Part payment", owner)
        if len(invoices) > 2:
            PaymentRequest.objects.create(invoice=invoices[2], customer=priya, method="upi", amount=invoices[2].amount_due, reference="UPI ref 4471920")
        for back in range(0, 6):
            SalesTarget.objects.create(salesperson=sales, month=services.add_months(self.today.replace(day=1), -back), amount=Decimal("6000"))

        self.ticket(business, priya, "Cannot find my last invoice", "Hello, I cannot find last month's invoice. Can you help?")
        urgent = self.ticket(business, rahul, "Charged for too many seats", "We have 20 seats, but the quote says 25.", priority="high", escalated=True)
        TicketMessage.objects.create(ticket=urgent, author=care, body="Owner, can you check this contract?", is_internal=True)
        TeamMessage.objects.create(business=business, author=care, body="Khan Traders asked about their seat count. I escalated the ticket.")
        AdminMessage.objects.create(business=business, author=owner, body="Hello Brightloop, how do I move my customers from a spreadsheet?")
        AdminMessage.objects.create(business=business, author=self.asha, body="Use Import subscribers. Load the sample first to see the format.")
        return business

    def sunrise(self):
        """A second business, to show that neither can see the other."""
        business = Business.objects.create(name="Sunrise Fitness", code="sr4n9x")
        owner = self.person("sunrise@gmail.com", User.Role.ADMIN, business, first_name="Sunny", last_name="Rawat", company="Sunrise Fitness")
        self.owner_on_brightloop(owner, self.pplans["starter"], 1)
        gst, terms = self.basics(business)
        plan = self.plan(business, gst, "Gym Monthly", "1500", pausable=True)
        member = self.person("meera@gmail.com", User.Role.CUSTOMER, business, first_name="Meera", last_name="Joshi")
        sub = self.make(member, plan, 1, [], terms["now"])
        self.bill_history(sub, 1, owner)

    def volume(self, business, count):
        """Bulk insert for speed. These rows skip the workflow on purpose and only exist to test page load times."""
        User.objects.bulk_create(
            [User(email=f"load{i}.volume@gmail.com", role=User.Role.CUSTOMER, business=business, first_name="Load", last_name=str(i), company=f"Load Co {i}", password="!") for i in range(max(count // 10, 1))],
            ignore_conflicts=True,
        )
        customers = list(User.objects.filter(email__endswith=".volume@gmail.com"))
        plans = list(Plan.objects.filter(business=business))
        terms = list(PaymentTerm.objects.filter(business=business))
        owner = User.objects.get(business=business, role=User.Role.ADMIN)
        rng = random.Random(7)
        base = Subscription.objects.order_by("-id").values_list("id", flat=True).first() or 0
        subs = []
        for i in range(count):
            start = self.today - timedelta(days=rng.randint(30, 360))
            subs.append(Subscription(
                business=business, number=f"VOL-{base + i + 1:07d}", customer=rng.choice(customers), plan=rng.choice(plans), payment_term=rng.choice(terms),
                start_date=start, expiry_date=start + timedelta(days=720), state="active",
                next_invoice_date=self.today + timedelta(days=rng.randint(1, 28)), recurring_total=Decimal(rng.randint(999, 90000)),
            ))
        Subscription.objects.bulk_create(subs, batch_size=1000)
        subs = list(Subscription.objects.filter(number__startswith="VOL-").select_related("customer"))
        SubscriptionLine.objects.bulk_create(
            [SubscriptionLine(subscription=s, description="Volume line", quantity=1, unit_price=s.recurring_total) for s in subs], batch_size=1000,
        )
        invoices = []
        for index, s in enumerate(subs):
            day = self.today - timedelta(days=rng.randint(0, 300))
            state = rng.choice(["confirmed", "paid"])
            invoices.append(Invoice(
                business=business, number=f"VOL-{s.pk}-{index}", subscription=s, customer=s.customer, customer_name=s.customer.display_name,
                customer_email=s.customer.email, state=state, invoice_date=day, due_date=day + timedelta(days=15),
                period_start=day, period_end=day + timedelta(days=29), billing_key=f"vol:{s.pk}", subtotal=s.recurring_total,
                total=s.recurring_total, amount_paid=s.recurring_total if state == "paid" else 0,
            ))
        Invoice.objects.bulk_create(invoices, batch_size=1000)
        paid = Invoice.objects.filter(number__startswith="VOL-", state="paid")
        Payment.objects.bulk_create(
            [Payment(business=business, invoice=i, method=rng.choice(Payment.Method.values), amount=i.total, date=i.invoice_date, recorded_by=owner) for i in paid],
            batch_size=1000,
        )
