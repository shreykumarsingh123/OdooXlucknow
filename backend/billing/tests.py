from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import patch

from django.core import mail
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import User
from billing import notify, revenue, services
from billing.models import Invoice, Payment, PaymentRequest, SalesTarget, Subscription
from catalog.models import Discount, PaymentTerm, Plan, Product, ProductVariant, Tax
from config.api import Conflict

PASSWORD = "Strong@Pass1"


class Base(TestCase):
    def setUp(self):
        cache.clear()  # request throttles are counted in the cache, and must not carry over between tests
        self.today = timezone.localdate()
        self.admin = User.objects.create_user("admin@x.example", PASSWORD, role="admin")
        self.staff = User.objects.create_user("staff@x.example", PASSWORD, role="staff")
        self.cust = User.objects.create_user("c1@x.example", PASSWORD, company="C1")
        self.other = User.objects.create_user("c2@x.example", PASSWORD, company="C2")
        self.tax = Tax.objects.create(name="GST", rate=Decimal("18"))
        self.term = PaymentTerm.objects.create(name="Net 15", due_days=15)
        self.product = Product.objects.create(name="Seat", sales_price=Decimal("100"))
        self.product.taxes.add(self.tax)
        self.variant = ProductVariant.objects.create(product=self.product, value="Odoo", extra_price=Decimal("560"))
        self.addon = Product.objects.create(name="Backup", sales_price=Decimal("50"), type="addon")
        self.plan = Plan.objects.create(
            name="Monthly", price=Decimal("0"), billing_period="monthly", min_quantity=2,
            start_date=self.today - timedelta(days=800), pausable=True,
        )

    def api(self, user=None):
        client = APIClient()
        if user:
            client.force_authenticate(user)
        return client

    def sub(self, months_ago=0, quantity=2, state="active", plan=None, customer=None, rows=None, months_long=12):
        start = services.add_months(self.today, -months_ago)
        sub = services.save_subscription(
            {"customer": customer or self.cust, "plan": plan or self.plan, "payment_term": self.term,
             "start_date": start, "expiry_date": services.add_months(start, months_long)},
            rows or [{"product": self.product, "quantity": quantity}],
        )
        if state in ("quotation", "confirmed", "active"):
            services.send_quotation(sub.pk)
        if state in ("confirmed", "active"):
            services.confirm(sub.pk)
        if state == "active":
            services.activate(sub.pk)
        return Subscription.objects.get(pk=sub.pk)


class AuthTests(Base):
    def signup(self, email="new@x.example", password=PASSWORD):
        return self.api().post("/api/auth/signup/", {"email": email, "password": password}, format="json")

    def test_signup_creates_customer(self):
        self.assertEqual(self.signup().status_code, 201)
        self.assertEqual(User.objects.get(email="new@x.example").role, "customer")

    def test_duplicate_email_refused_in_any_case(self):
        self.assertEqual(self.signup("C1@X.example").status_code, 400)

    def test_password_rules(self):
        for weak in ["Short@1a", "alllower@123", "ALLUPPER@123", "NoSpecial123", "Exactly@8"[:8]]:
            self.assertEqual(self.signup(password=weak).status_code, 400, weak)

    def test_signup_cannot_choose_role(self):
        self.api().post("/api/auth/signup/", {"email": "h@x.example", "password": PASSWORD, "role": "admin"}, format="json")
        self.assertEqual(User.objects.get(email="h@x.example").role, "customer")

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_reset_flow_single_use(self):
        client = self.api()
        unknown = client.post("/api/auth/forgot-password/", {"email": "nobody@x.example"}, format="json")
        known = client.post("/api/auth/forgot-password/", {"email": "c1@x.example"}, format="json")
        self.assertEqual(unknown.data, known.data)
        self.assertEqual(len(mail.outbox), 1)
        query = mail.outbox[0].body.split("reset-password?")[1].split()[0]
        uid, token = [part.split("=")[1] for part in query.split("&")]
        body = {"uid": uid, "token": token, "password": "Another@Pass2"}
        self.assertEqual(client.post("/api/auth/reset-password/", body, format="json").status_code, 200)
        self.assertEqual(client.post("/api/auth/reset-password/", body, format="json").status_code, 400)
        self.cust.refresh_from_db()
        self.assertTrue(self.cust.check_password("Another@Pass2"))


class AccessTests(Base):
    def test_only_admin_adds_staff(self):
        body = {"email": "s2@x.example"}
        self.assertEqual(self.api(self.staff).post("/api/staff/", body, format="json").status_code, 403)
        self.assertEqual(self.api(self.cust).post("/api/staff/", body, format="json").status_code, 403)
        self.assertEqual(self.api(self.admin).post("/api/staff/", body, format="json").status_code, 201)

    def test_catalog_write_is_admin_only(self):
        body = {"name": "New", "sales_price": "10"}
        self.assertEqual(self.api(self.staff).post("/api/products/", body, format="json").status_code, 403)
        self.assertEqual(self.api(self.admin).post("/api/products/", body, format="json").status_code, 201)
        self.assertEqual(self.api(self.staff).get("/api/products/").status_code, 200)
        self.assertEqual(self.api(self.cust).get("/api/products/").status_code, 403)

    def test_discount_create_is_admin_only(self):
        body = {"name": "D", "kind": "percent", "value": "5", "scope": "products", "products": [self.product.pk], "start_date": str(self.today)}
        self.assertEqual(self.api(self.staff).post("/api/discounts/", body, format="json").status_code, 403)
        self.assertEqual(self.api(self.admin).post("/api/discounts/", body, format="json").status_code, 201)

    def test_customer_sees_only_own_records(self):
        mine, theirs = self.sub(), self.sub(customer=self.other)
        services.run_billing()
        client = self.api(self.cust)
        self.assertEqual(client.get(f"/api/subscriptions/{mine.pk}/").status_code, 200)
        self.assertEqual(client.get(f"/api/subscriptions/{theirs.pk}/").status_code, 404)
        self.assertEqual(client.post(f"/api/subscriptions/{theirs.pk}/pause/").status_code, 404)
        invoice = Invoice.objects.get(subscription=theirs)
        services.confirm_invoice(invoice.pk)
        self.assertEqual(client.get(f"/api/invoices/{invoice.pk}/").status_code, 404)

    def test_customer_cannot_run_team_actions(self):
        sub = self.sub(state="quotation")
        client = self.api(self.cust)
        self.assertEqual(client.post(f"/api/subscriptions/{sub.pk}/confirm/").status_code, 403)
        self.assertEqual(client.post("/api/billing/run/").status_code, 403)
        self.assertEqual(client.get("/api/reports/summary/").status_code, 403)
        self.assertEqual(client.get("/api/payments/").status_code, 403)

    def test_customer_never_sees_drafts(self):
        draft = self.sub(state="draft")
        self.assertEqual(self.api(self.cust).get(f"/api/subscriptions/{draft.pk}/").status_code, 404)


class CatalogRuleTests(Base):
    def test_variant_adds_to_price(self):
        sub = self.sub(rows=[{"product": self.product, "variant": self.variant, "quantity": 2}])
        line = sub.lines.get()
        self.assertEqual(line.unit_price, Decimal("660"))
        self.assertEqual(line.amount, Decimal("1320"))

    def test_minimum_quantity_enforced(self):
        body = {"customer": self.cust.pk, "plan": self.plan.pk, "payment_term": self.term.pk, "start_date": str(self.today),
                "expiry_date": str(self.today + timedelta(days=30)), "lines": [{"product": self.product.pk, "quantity": 1}]}
        response = self.api(self.staff).post("/api/subscriptions/", body, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("lines", response.data["fields"])

    def test_plan_dates_enforced(self):
        self.plan.end_date = self.today - timedelta(days=1)
        self.plan.save()
        body = {"customer": self.cust.pk, "plan": self.plan.pk, "payment_term": self.term.pk, "start_date": str(self.today),
                "expiry_date": str(self.today + timedelta(days=30)), "lines": [{"product": self.product.pk, "quantity": 2}]}
        self.assertEqual(self.api(self.staff).post("/api/subscriptions/", body, format="json").status_code, 400)

    def test_plan_price_becomes_a_line(self):
        self.plan.price = Decimal("999")
        self.plan.save()
        self.assertEqual(self.sub(state="draft").recurring_total, Decimal("1199.00"))


class LifecycleTests(Base):
    def test_states_cannot_be_skipped(self):
        sub = self.sub(state="draft")
        client = self.api(self.staff)
        self.assertEqual(client.post(f"/api/subscriptions/{sub.pk}/activate/").status_code, 409)
        self.assertEqual(client.post(f"/api/subscriptions/{sub.pk}/confirm/").status_code, 409)
        for step in ["quote", "confirm", "activate", "close"]:
            self.assertEqual(client.post(f"/api/subscriptions/{sub.pk}/{step}/").status_code, 200, step)
        sub.refresh_from_db()
        self.assertEqual(sub.state, "closed")

    def test_numbers_are_unique(self):
        self.assertNotEqual(self.sub(state="draft").number, self.sub(state="draft").number)

    def test_plan_options_respected(self):
        locked = Plan.objects.create(
            name="Locked", start_date=self.plan.start_date, min_quantity=1, closable=False, pausable=False, renewable=False
        )
        sub = self.sub(plan=locked)
        client = self.api(self.cust)
        for step in ["pause", "close"]:
            self.assertEqual(client.post(f"/api/subscriptions/{sub.pk}/{step}/").status_code, 409, step)
        self.assertEqual(self.api(self.staff).post(f"/api/subscriptions/{sub.pk}/renew/").status_code, 409)

    def test_customer_can_pause_and_resume_own(self):
        sub = self.sub()
        client = self.api(self.cust)
        self.assertEqual(client.post(f"/api/subscriptions/{sub.pk}/pause/").data["state"], "paused")
        self.assertEqual(client.post(f"/api/subscriptions/{sub.pk}/resume/").data["state"], "active")

    def test_auto_close_only_when_plan_says_so(self):
        auto = Plan.objects.create(name="Auto", start_date=self.plan.start_date, min_quantity=1, auto_close=True)
        ended = self.sub(plan=auto, months_ago=13)
        manual = self.sub(months_ago=13)
        services.close_ended()
        ended.refresh_from_db()
        manual.refresh_from_db()
        self.assertEqual(ended.state, "closed")
        self.assertEqual(manual.state, "active")

    def test_template_builds_quote_and_validity_applies(self):
        template = self.api(self.admin).post(
            "/api/templates/", {"name": "T", "plan": self.plan.pk, "validity_days": 7, "lines": [{"product": self.product.pk, "quantity": 3}]}, format="json"
        ).data["id"]
        response = self.api(self.staff).post("/api/subscriptions/from_template/", {
            "template": template, "customer": self.cust.pk, "payment_term": self.term.pk,
            "start_date": str(self.today), "expiry_date": str(self.today + timedelta(days=90)),
        }, format="json")
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["lines"][0]["quantity"], 3)
        sub = Subscription.objects.get(pk=response.data["id"])
        services.send_quotation(sub.pk)
        Subscription.objects.filter(pk=sub.pk).update(quotation_valid_until=self.today - timedelta(days=1))
        self.assertEqual(self.api(self.staff).post(f"/api/subscriptions/{sub.pk}/confirm/").status_code, 409)

    def test_addon_cannot_dodge_billing_by_toggling(self):
        sub = self.sub(rows=[{"product": self.product, "quantity": 2}, {"product": self.addon, "quantity": 1}])
        line = sub.lines.get(product=self.addon)
        services.toggle_addon(sub.pk, line.pk, False)
        services.run_billing()
        self.assertEqual(Invoice.objects.get(subscription=sub).subtotal, Decimal("200.00"))
        # On after billing, off again before the next run: that period is still charged, once.
        services.toggle_addon(sub.pk, line.pk, True)
        services.toggle_addon(sub.pk, line.pk, False)
        first = services.next_period_start(sub.start_date, "monthly", sub.start_date)
        second = services.next_period_start(first, "monthly", sub.start_date)
        created = services.bill_subscription(sub.pk, first)
        self.assertEqual(created[0].subtotal, Decimal("250.00"))
        self.assertEqual(services.bill_subscription(sub.pk, second)[0].subtotal, Decimal("200.00"))

    def test_addon_toggle_changes_next_invoice(self):
        sub = self.sub(rows=[{"product": self.product, "quantity": 2}, {"product": self.addon, "quantity": 1}])
        addon_line = sub.lines.get(product=self.addon)
        seat_line = sub.lines.get(product=self.product)
        client = self.api(self.cust)
        url = f"/api/subscriptions/{sub.pk}/toggle_addon/"
        self.assertEqual(client.post(url, {"line": seat_line.pk, "enabled": False}, format="json").status_code, 409)
        self.assertEqual(client.post(url, {"line": addon_line.pk, "enabled": False}, format="json").status_code, 200)
        services.run_billing()
        self.assertEqual(Invoice.objects.get(subscription=sub).subtotal, Decimal("200.00"))


class BillingTests(Base):
    def test_month_end_start_does_not_drift(self):
        start = date(2026, 1, 31)
        feb = services.next_period_start(start, "monthly", start)
        self.assertEqual(feb, date(2026, 2, 28))
        self.assertEqual(services.next_period_start(feb, "monthly", start), date(2026, 3, 31))

    def test_invoice_filled_from_subscription(self):
        sub = self.sub(quantity=3)
        services.run_billing()
        invoice = Invoice.objects.get(subscription=sub)
        self.assertEqual(invoice.state, "draft")
        self.assertEqual(invoice.customer_email, "c1@x.example")
        self.assertEqual(invoice.subtotal, Decimal("300.00"))
        self.assertEqual(invoice.tax_total, Decimal("54.00"))
        self.assertEqual(invoice.total, Decimal("354.00"))
        self.assertEqual(invoice.due_date, self.today + timedelta(days=15))
        self.assertEqual(invoice.lines.count(), 1)

    def test_repeat_run_never_double_bills(self):
        self.sub()
        self.assertEqual(services.run_billing()["invoices_created"], 1)
        self.assertEqual(services.run_billing()["invoices_created"], 0)
        self.assertEqual(Invoice.objects.count(), 1)

    def test_missed_periods_are_caught_up(self):
        sub = self.sub(months_ago=3)
        self.assertEqual(services.run_billing()["invoices_created"], 4)
        starts = sorted(Invoice.objects.filter(subscription=sub).values_list("period_start", flat=True))
        self.assertEqual(starts[0], sub.start_date)
        self.assertEqual(len(set(starts)), 4)

    def test_rewound_date_cannot_double_bill(self):
        sub = self.sub()
        services.run_billing()
        Subscription.objects.filter(pk=sub.pk).update(next_invoice_date=sub.start_date)
        services.run_billing()
        self.assertEqual(Invoice.objects.filter(subscription=sub).count(), 1)

    def test_paused_and_not_active_are_not_billed(self):
        services.pause(self.sub().pk)
        self.sub(state="confirmed")
        self.assertEqual(services.run_billing()["invoices_created"], 0)

    def test_no_billing_past_expiry(self):
        sub = self.sub(months_ago=6, months_long=2)
        Subscription.objects.filter(pk=sub.pk).update(auto_renew=False)
        self.assertEqual(services.run_billing()["invoices_created"], 3)
        sub.refresh_from_db()
        self.assertEqual(sub.state, "closed")

    def test_invoice_state_machine(self):
        self.sub()
        services.run_billing()
        invoice = Invoice.objects.get()
        client = self.api(self.staff)
        self.assertEqual(client.post(f"/api/invoices/{invoice.pk}/send/").status_code, 409)
        self.assertEqual(client.post(f"/api/invoices/{invoice.pk}/confirm/").data["state"], "confirmed")
        self.assertEqual(client.post(f"/api/invoices/{invoice.pk}/confirm/").status_code, 409)

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_send_emails_customer(self):
        self.sub()
        services.run_billing()
        invoice = Invoice.objects.get()
        services.confirm_invoice(invoice.pk)
        response = self.api(self.staff).post(f"/api/invoices/{invoice.pk}/send/")
        self.assertIsNotNone(response.data["sent_at"])
        self.assertEqual(mail.outbox[0].to, ["c1@x.example"])

    def test_cancel_and_rebill(self):
        sub = self.sub()
        services.run_billing()
        invoice = Invoice.objects.get()
        client = self.api(self.staff)
        self.assertEqual(client.post(f"/api/invoices/{invoice.pk}/cancel/", {"rebill": True}, format="json").data["state"], "cancelled")
        self.assertEqual(services.run_billing()["invoices_created"], 1)
        self.assertEqual(Invoice.objects.filter(subscription=sub, state="draft").count(), 1)

    def test_cancel_without_rebill_stays_cancelled(self):
        self.sub()
        services.run_billing()
        services.cancel_invoice(Invoice.objects.get().pk)
        self.assertEqual(services.run_billing()["invoices_created"], 0)


class DiscountTests(Base):
    def discount(self, **extra):
        products = extra.pop("products", [self.product])
        subs = extra.pop("subscriptions", [])
        defaults = {"name": "D", "kind": "percent", "value": Decimal("10"), "start_date": self.today - timedelta(days=5)}
        discount = Discount.objects.create(**{**defaults, **extra})
        discount.products.set(products)
        discount.subscriptions.set(subs)
        return discount

    def test_percent_applied_automatically_before_tax(self):
        self.discount()
        self.sub(quantity=10)
        services.run_billing()
        invoice = Invoice.objects.get()
        self.assertEqual(invoice.subtotal, Decimal("1000.00"))
        self.assertEqual(invoice.discount_total, Decimal("100.00"))
        self.assertEqual(invoice.tax_total, Decimal("162.00"))
        self.assertEqual(invoice.total, Decimal("1062.00"))
        self.assertEqual(invoice.discounts.get().name, "D")

    def test_fixed_amount_on_whole_subscription(self):
        sub = self.sub(quantity=2)
        self.discount(kind="fixed", value=Decimal("50"), scope="subscriptions", products=[], subscriptions=[sub])
        services.run_billing()
        self.assertEqual(Invoice.objects.get().discount_total, Decimal("50.00"))

    def test_minimum_quantity_and_purchase(self):
        self.discount(min_quantity=5)
        self.discount(name="E", min_purchase=Decimal("9999"))
        self.sub(quantity=2)
        services.run_billing()
        self.assertEqual(Invoice.objects.get().discount_total, 0)

    def test_stops_when_expired(self):
        self.discount(end_date=self.today - timedelta(days=1))
        self.sub()
        services.run_billing()
        self.assertEqual(Invoice.objects.get().discount_total, 0)

    def test_stops_when_used_up_and_cancel_returns_use(self):
        discount = self.discount(usage_limit=1)
        self.sub()
        self.sub()
        services.run_billing()
        totals = sorted(Invoice.objects.values_list("discount_total", flat=True))
        self.assertEqual(totals, [Decimal("0.00"), Decimal("20.00")])
        discount.refresh_from_db()
        self.assertEqual(discount.times_used, 1)
        services.cancel_invoice(Invoice.objects.get(discount_total=20).pk)
        discount.refresh_from_db()
        self.assertEqual(discount.times_used, 0)

    def test_discount_never_goes_below_zero(self):
        self.discount(kind="fixed", value=Decimal("100000"))
        self.sub()
        services.run_billing()
        self.assertEqual(Invoice.objects.get().total, Decimal("0.00"))


class PaymentTests(Base):
    def invoice(self):
        self.sub()
        services.run_billing()
        invoice = Invoice.objects.get()
        services.confirm_invoice(invoice.pk)
        return Invoice.objects.get(pk=invoice.pk)

    def pay(self, invoice, amount, user=None):
        return self.api(user or self.staff).post("/api/payments/", {
            "invoice": invoice.pk, "method": "upi", "amount": str(amount), "date": str(self.today), "note": "n",
        }, format="json")

    def test_partial_then_full_marks_paid(self):
        invoice = self.invoice()
        self.assertEqual(self.pay(invoice, "100").status_code, 201)
        invoice.refresh_from_db()
        self.assertEqual(invoice.state, "confirmed")
        self.assertEqual(self.pay(invoice, invoice.amount_due).status_code, 201)
        invoice.refresh_from_db()
        self.assertEqual(invoice.state, "paid")

    def test_overpayment_refused(self):
        invoice = self.invoice()
        self.assertEqual(self.pay(invoice, invoice.total + 1).status_code, 400)

    def test_zero_or_negative_refused(self):
        invoice = self.invoice()
        self.assertEqual(self.pay(invoice, "0").status_code, 400)
        self.assertEqual(self.pay(invoice, "-5").status_code, 400)

    def test_draft_cannot_be_paid(self):
        self.sub()
        services.run_billing()
        self.assertEqual(self.pay(Invoice.objects.get(), "1").status_code, 409)

    def test_part_paid_cannot_be_cancelled(self):
        invoice = self.invoice()
        self.pay(invoice, "1")
        self.assertEqual(self.api(self.staff).post(f"/api/invoices/{invoice.pk}/cancel/").status_code, 409)

    def test_customer_cannot_record_payment(self):
        self.assertEqual(self.pay(self.invoice(), "1", self.cust).status_code, 403)

    def test_status_filters_and_report_totals(self):
        invoice = self.invoice()
        Invoice.objects.filter(pk=invoice.pk).update(due_date=self.today - timedelta(days=1))
        client = self.api(self.staff)
        self.assertEqual(client.get("/api/invoices/?payment_status=overdue").data["count"], 1)
        self.assertEqual(client.get("/api/invoices/?payment_status=paid").data["count"], 0)
        self.pay(invoice, "36")
        report = client.get("/api/reports/summary/").data
        self.assertEqual(report["active_subscriptions"], 1)
        self.assertEqual(report["revenue_collected"], Decimal("36.00"))
        self.assertEqual(report["outstanding_amount"], Decimal("200.00"))
        self.assertEqual(report["overdue_count"], 1)
        self.assertEqual(report["monthly_recurring_revenue"], Decimal("200.00"))


@override_settings(STRIPE_SECRET_KEY="sk_test_fake")
class OnlinePaymentTests(Base):
    def invoice(self, customer=None):
        self.sub(customer=customer)
        services.run_billing()
        invoice = Invoice.objects.order_by("-id").first()
        services.confirm_invoice(invoice.pk)
        return Invoice.objects.get(pk=invoice.pk)

    def session(self, invoice, status="paid"):
        return {"id": "cs_test_1", "payment_status": status, "metadata": {"invoice_id": str(invoice.pk)}, "amount_total": int(invoice.total * 100)}

    def test_checkout_amount_and_ownership(self):
        invoice = self.invoice()
        with patch("stripe.checkout.Session.create") as create:
            create.return_value.url = "https://checkout.example/x"
            response = self.api(self.cust).post(f"/api/invoices/{invoice.pk}/checkout/")
            self.assertEqual(response.data["url"], "https://checkout.example/x")
            self.assertEqual(create.call_args.kwargs["line_items"][0]["price_data"]["unit_amount"], 23600)
            self.assertEqual(self.api(self.other).post(f"/api/invoices/{invoice.pk}/checkout/").status_code, 404)

    def test_paid_session_recorded_once(self):
        invoice = self.invoice()
        with patch("stripe.checkout.Session.retrieve", return_value=self.session(invoice)):
            url = f"/api/invoices/{invoice.pk}/checkout_complete/"
            self.assertEqual(self.api(self.cust).post(url, {"session_id": "cs_test_1"}, format="json").data["state"], "paid")
            self.assertEqual(self.api(self.cust).post(url, {"session_id": "cs_test_1"}, format="json").status_code, 200)
        self.assertEqual(invoice.payments.count(), 1)

    def test_unpaid_session_records_nothing(self):
        invoice = self.invoice()
        with patch("stripe.checkout.Session.retrieve", return_value=self.session(invoice, "unpaid")):
            services.confirm_checkout("cs_test_1", invoice.pk)
        self.assertEqual(invoice.payments.count(), 0)

    def test_session_for_other_invoice_refused(self):
        invoice = self.invoice()
        other = self.invoice(customer=self.other)
        with patch("stripe.checkout.Session.retrieve", return_value=self.session(other)):
            response = self.api(self.cust).post(f"/api/invoices/{invoice.pk}/checkout_complete/", {"session_id": "x"}, format="json")
        self.assertEqual(response.status_code, 409)

    @override_settings(STRIPE_WEBHOOK_SECRET="whsec_test")
    def test_webhook_rejects_bad_signature(self):
        response = self.api().post("/api/webhooks/stripe/", {"id": "evt"}, format="json", HTTP_STRIPE_SIGNATURE="bad")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(Payment.objects.count(), 0)


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend", REMINDER_INTERVAL_DAYS=3, REMINDER_MAX_COUNT=2)
class ReminderTests(Base):
    def overdue(self):
        self.sub()
        services.run_billing()
        invoice = Invoice.objects.get()
        services.confirm_invoice(invoice.pk)
        Invoice.objects.filter(pk=invoice.pk).update(due_date=self.today - timedelta(days=5))
        return invoice

    def test_spacing_and_limit(self):
        self.overdue()
        with patch("billing.services.send_sms", return_value=False):
            self.assertEqual(services.send_reminders()["reminded"], 1)
            self.assertEqual(services.send_reminders()["reminded"], 0)
            self.assertEqual(services.send_reminders(self.today + timedelta(days=3))["reminded"], 1)
            self.assertEqual(services.send_reminders(self.today + timedelta(days=9))["reminded"], 0)
        self.assertEqual(len(mail.outbox), 2)

    def test_not_due_or_paid_not_chased(self):
        self.sub()
        services.run_billing()
        services.confirm_invoice(Invoice.objects.get().pk)
        self.assertEqual(services.send_reminders()["reminded"], 0)

    def test_sms_goes_to_customer_phone(self):
        User.objects.filter(pk=self.cust.pk).update(phone="+15550001111")
        self.overdue()
        with patch("billing.services.send_sms", return_value=True) as sms:
            self.assertEqual(services.send_reminders()["sms_sent"], 1)
        self.assertEqual(sms.call_args.args[0], "+15550001111")

    def test_sms_inactive_without_settings(self):
        with override_settings(TWILIO_FROM_NUMBER=""), patch("requests.post") as post:
            self.assertFalse(notify.send_sms("+15550001111", "x"))
        post.assert_not_called()

    def test_customer_cannot_trigger(self):
        self.assertEqual(self.api(self.cust).post("/api/billing/reminders/").status_code, 403)


@override_settings(GOOGLE_CLIENT_ID="client-id.example")
class GoogleLoginTests(Base):
    def login(self, claims=None, error=None):
        with patch("accounts.views.id_token.verify_oauth2_token", return_value=claims, side_effect=error):
            return self.api().post("/api/auth/google/", {"credential": "token"}, format="json")

    def test_new_user_becomes_customer(self):
        response = self.login({"email": "G@x.example", "email_verified": True, "given_name": "Gia"})
        self.assertEqual(response.status_code, 200)
        user = User.objects.get(email="g@x.example")
        self.assertEqual(user.role, "customer")
        self.assertFalse(user.has_usable_password())

    def test_unverified_password_account_is_not_linked(self):
        response = self.login({"email": "c1@x.example", "email_verified": True})
        self.assertEqual(response.status_code, 400)
        self.assertNotIn("access", response.data)

    def test_invited_account_without_password_is_linked(self):
        invited = User.objects.create_user("inv@x.example", None)
        self.assertEqual(self.login({"email": "inv@x.example", "email_verified": True}).status_code, 200)
        invited.refresh_from_db()
        self.assertTrue(invited.email_verified)

    def test_password_change_ends_old_sessions(self):
        client = self.api()
        token = client.post("/api/auth/login/", {"email": "c1@x.example", "password": PASSWORD}, format="json").data["access"]
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        self.assertEqual(client.get("/api/auth/me/").status_code, 200)
        self.cust.set_password("Another@Pass2")
        self.cust.save()
        self.assertEqual(client.get("/api/auth/me/").status_code, 401)

    def test_existing_user_keeps_role(self):
        User.objects.filter(email="staff@x.example").update(email_verified=True)
        self.assertEqual(self.login({"email": "staff@x.example", "email_verified": True}).status_code, 200)
        self.assertEqual(User.objects.filter(email="staff@x.example", role="staff").count(), 1)

    def test_unverified_email_refused(self):
        self.assertEqual(self.login({"email": "admin@x.example", "email_verified": False}).status_code, 400)

    def test_invalid_token_refused(self):
        self.assertEqual(self.login(error=ValueError("bad")).status_code, 400)

    def test_inactive_refused(self):
        User.objects.filter(pk=self.cust.pk).update(is_active=False)
        self.assertEqual(self.login({"email": "c1@x.example", "email_verified": True}).status_code, 400)

    @override_settings(GOOGLE_CLIENT_ID="")
    def test_not_configured(self):
        self.assertEqual(self.login({"email": "z@x.example", "email_verified": True}).status_code, 400)
        self.assertEqual(self.api().get("/api/auth/config/").data["google_client_id"], "")


class GrowthFeatureTests(Base):
    def setUp(self):
        super().setUp()
        start = self.today - timedelta(days=800)
        self.small = Plan.objects.create(name="Small", price=Decimal("300"), billing_period="monthly", start_date=start, is_public=True)
        self.big = Plan.objects.create(name="Big", price=Decimal("900"), billing_period="monthly", start_date=start, is_public=True)
        self.free = Plan.objects.create(name="Free try", price=Decimal("500"), billing_period="monthly", start_date=start, is_public=True, trial_days=14)
        self.hidden = Plan.objects.create(name="Hidden", price=Decimal("500"), billing_period="monthly", start_date=start)
        self.yearly = Plan.objects.create(name="Year", price=Decimal("500"), billing_period="yearly", start_date=start, is_public=True)

    def start(self, plan, user=None):
        return self.api(user or self.cust).post("/api/subscriptions/start/", {"plan": plan.pk}, format="json")

    def billed(self, plan=None):
        """Billed today for a month that runs from today, so the whole period is still unused."""
        sub = self.sub(quantity=1, plan=plan or self.small, rows=[{"product": self.addon, "quantity": 1}])
        services.bill_subscription(sub.pk)
        return Subscription.objects.get(pk=sub.pk)

    def test_public_plans_need_no_login_and_hide_private_ones(self):
        response = self.api().get("/api/public/plans/")
        self.assertEqual(response.status_code, 200)
        names = [row["name"] for row in response.data]
        self.assertIn("Small", names)
        self.assertNotIn("Hidden", names)
        self.assertNotIn("cost_price", response.data[0])

    def test_customer_starts_public_plan_once(self):
        response = self.start(self.small)
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["state"], "active")
        self.assertEqual(Decimal(response.data["recurring_total"]), Decimal("300"))
        self.assertEqual(self.start(self.small).status_code, 409)

    def test_private_plan_and_team_cannot_start_online(self):
        self.assertEqual(self.start(self.hidden).status_code, 409)
        self.assertEqual(self.start(self.small, self.staff).status_code, 403)

    def test_trial_delays_first_invoice_and_keeps_full_periods(self):
        sub = Subscription.objects.get(pk=self.start(self.free).data["id"])
        trial_end = self.today + timedelta(days=14)
        self.assertEqual(sub.next_invoice_date, trial_end)
        self.assertEqual(services.bill_subscription(sub.pk), [])
        invoice = services.bill_subscription(sub.pk, trial_end)[0]
        self.assertEqual(invoice.period_start, trial_end)
        self.assertEqual(invoice.period_end, services.next_period_start(trial_end, "monthly", trial_end) - timedelta(days=1))

    def test_trial_is_not_given_twice(self):
        first = self.start(self.free).data["id"]
        services.close(first)
        self.assertIsNone(Subscription.objects.get(pk=self.start(self.free).data["id"]).trial_ends)

    def test_trial_is_not_counted_in_mrr(self):
        self.start(self.free)
        data = self.api(self.admin).get("/api/reports/summary/").data
        self.assertEqual(data["monthly_recurring_revenue"], Decimal("0.00"))
        self.assertEqual(data["in_trial"], 1)

    def test_upgrade_charges_unused_difference_once(self):
        sub = self.billed()
        response = self.api(self.cust).post(f"/api/subscriptions/{sub.pk}/change_plan/", {"plan": self.big.pk}, format="json")
        self.assertEqual(response.status_code, 200)
        extra = Invoice.objects.get(subscription=sub, is_adjustment=True)
        self.assertEqual(extra.total, Decimal("600.00"))
        self.assertEqual(extra.state, "confirmed")
        sub.refresh_from_db()
        self.assertEqual(sub.plan, self.big)
        self.assertEqual(sub.recurring_total, Decimal("950.00"))

    def paid(self, plan=None):
        sub = self.billed(plan)
        for invoice in Invoice.objects.filter(subscription=sub):
            services.confirm_invoice(invoice.pk)
            services.record_payment(invoice.pk, "cash", invoice.total, self.today, "", self.admin)
        return sub

    def test_upgrade_downgrade_loop_cannot_mint_credit(self):
        sub = self.paid()
        services.change_plan(sub.pk, self.big)
        with self.assertRaises(Conflict):
            services.change_plan(sub.pk, self.small)
        sub.refresh_from_db()
        self.assertEqual(sub.credit_balance, Decimal("0.00"))

    def test_no_credit_on_an_unpaid_period(self):
        sub = self.billed(self.big)
        services.change_plan(sub.pk, self.small)
        sub.refresh_from_db()
        self.assertEqual(sub.plan, self.small)
        self.assertEqual(sub.credit_balance, Decimal("0.00"))

    def test_trial_cannot_be_retaken_after_a_plan_change(self):
        first = Subscription.objects.get(pk=self.start(self.free).data["id"])
        with self.assertRaises(Conflict):
            services.change_plan(first.pk, self.small)
        Subscription.objects.filter(pk=first.pk).update(trial_ends=self.today - timedelta(days=1), next_invoice_date=self.today)
        services.change_plan(first.pk, self.small)
        self.assertIsNone(Subscription.objects.get(pk=self.start(self.free).data["id"]).trial_ends)

    def test_customer_cannot_leave_a_committed_plan(self):
        fixed = Plan.objects.create(name="Fixed", price=Decimal("500"), billing_period="monthly", start_date=self.small.start_date, is_public=True, closable=False)
        team_plan = self.billed(self.hidden)
        locked = self.billed(fixed)
        body = {"plan": self.small.pk}
        self.assertEqual(self.api(self.cust).post(f"/api/subscriptions/{locked.pk}/change_plan/", body, format="json").status_code, 403)
        self.assertEqual(self.api(self.cust).post(f"/api/subscriptions/{team_plan.pk}/change_plan/", body, format="json").status_code, 403)
        self.assertNotIn("change_plan", self.api(self.cust).get(f"/api/subscriptions/{locked.pk}/").data["allowed_actions"])
        self.assertEqual(self.api(self.staff).post(f"/api/subscriptions/{locked.pk}/change_plan/", body, format="json").status_code, 200)

    def test_downgrade_gives_credit_used_on_next_invoice(self):
        sub = self.paid(self.big)
        services.change_plan(sub.pk, self.small)
        sub.refresh_from_db()
        self.assertEqual(sub.credit_balance, Decimal("600.00"))
        self.assertFalse(Invoice.objects.filter(subscription=sub, is_adjustment=True).exists())
        following = services.bill_subscription(sub.pk, sub.next_invoice_date)[0]
        self.assertEqual(following.credit_applied, Decimal("350.00"))
        self.assertEqual(following.total, Decimal("0.00"))
        sub.refresh_from_db()
        self.assertEqual(sub.credit_balance, Decimal("250.00"))

    def test_cancelling_invoice_returns_credit(self):
        sub = self.paid(self.big)
        services.change_plan(sub.pk, self.small)
        following = services.bill_subscription(sub.pk, Subscription.objects.get(pk=sub.pk).next_invoice_date)[0]
        services.cancel_invoice(following.pk)
        sub.refresh_from_db()
        self.assertEqual(sub.credit_balance, Decimal("600.00"))

    def test_cancelled_adjustment_cannot_rewind_billing(self):
        sub = self.billed()
        services.change_plan(sub.pk, self.big)
        before = Subscription.objects.get(pk=sub.pk).next_invoice_date
        services.cancel_invoice(Invoice.objects.get(subscription=sub, is_adjustment=True).pk, rebill=True)
        self.assertEqual(Subscription.objects.get(pk=sub.pk).next_invoice_date, before)

    def test_plan_change_rules(self):
        sub = self.billed()
        client = self.api(self.cust)
        url = f"/api/subscriptions/{sub.pk}/change_plan/"
        self.assertEqual(client.post(url, {"plan": self.yearly.pk}, format="json").status_code, 409)
        self.assertEqual(client.post(url, {"plan": self.hidden.pk}, format="json").status_code, 400)
        self.assertEqual(client.post(url, {"plan": "x"}, format="json").status_code, 400)
        self.assertEqual(self.api(self.other).post(url, {"plan": self.big.pk}, format="json").status_code, 404)

    def make_code(self, **extra):
        return Discount.objects.create(name="Promo", kind="percent", value=Decimal("50"), scope="subscriptions", start_date=self.today, code="SAVE50", **extra)

    def test_code_applies_only_after_redeeming(self):
        self.make_code()
        plain = self.sub(quantity=2)
        redeemed = self.sub(quantity=2, customer=self.other)
        response = self.api(self.other).post(f"/api/subscriptions/{redeemed.pk}/redeem/", {"code": "save50"}, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(services.bill_subscription(plain.pk)[0].discount_total, Decimal("0.00"))
        self.assertEqual(services.bill_subscription(redeemed.pk)[0].discount_total, Decimal("100.00"))

    def test_bad_expired_or_repeated_code_refused(self):
        sub = self.sub(quantity=2)
        client = self.api(self.cust)
        url = f"/api/subscriptions/{sub.pk}/redeem/"
        self.assertEqual(client.post(url, {"code": "NOPE"}, format="json").status_code, 400)
        code = self.make_code()
        self.assertEqual(client.post(url, {"code": "SAVE50"}, format="json").status_code, 200)
        self.assertEqual(client.post(url, {"code": "SAVE50"}, format="json").status_code, 409)
        code.end_date = self.today - timedelta(days=1)
        code.start_date = self.today - timedelta(days=2)
        code.save()
        other = self.sub(quantity=2)
        self.assertEqual(client.post(f"/api/subscriptions/{other.pk}/redeem/", {"code": "SAVE50"}, format="json").status_code, 400)

    def test_adjustment_is_admin_only(self):
        sub = self.sub(quantity=2)
        url = f"/api/subscriptions/{sub.pk}/adjust/"
        body = {"kind": "credit", "amount": "75", "note": "Goodwill"}
        self.assertEqual(self.api(self.staff).post(url, body, format="json").status_code, 403)
        self.assertEqual(self.api(self.cust).post(url, body, format="json").status_code, 403)
        self.assertEqual(self.api(self.admin).post(url, body, format="json").status_code, 200)
        sub.refresh_from_db()
        self.assertEqual(sub.credit_balance, Decimal("75.00"))
        self.assertEqual(self.api(self.admin).post(url, {"kind": "charge", "amount": "40", "note": "Setup"}, format="json").status_code, 200)
        self.assertEqual(Invoice.objects.get(subscription=sub, is_adjustment=True).total, Decimal("40.00"))
        self.assertEqual(self.api(self.admin).post(url, {"kind": "credit", "amount": "-5", "note": "x"}, format="json").status_code, 400)

    def test_close_reason_reaches_churn_report(self):
        sub = self.sub(quantity=2)
        client = self.api(self.cust)
        url = f"/api/subscriptions/{sub.pk}/close/"
        self.assertEqual(client.post(url, {"reason": "bogus"}, format="json").status_code, 400)
        self.assertEqual(client.post(url, {"reason": "too_expensive"}, format="json").status_code, 200)
        reasons = self.api(self.admin).get("/api/reports/summary/").data["churn_reasons"]
        self.assertEqual(reasons, [{"reason": "Too expensive", "count": 1}])

    def test_timeline_records_who_did_what(self):
        sub = self.sub(quantity=2)
        client = self.api(self.staff)
        client.post(f"/api/subscriptions/{sub.pk}/renew/", {}, format="json")
        event = client.get(f"/api/subscriptions/{sub.pk}/").data["events"][0]
        self.assertEqual(event["message"], "Renewed by the team")
        self.assertEqual(event["actor_name"], self.staff.display_name)

    def test_export_is_team_only_and_defuses_formulas(self):
        evil = User.objects.create_user("evil@x.example", PASSWORD, company="=HYPERLINK(1)")
        services.bill_subscription(self.sub(quantity=2, customer=evil).pk)
        self.assertEqual(self.api(self.cust).get("/api/reports/export/invoices/").status_code, 403)
        response = self.api(self.staff).get("/api/reports/export/invoices/")
        self.assertEqual(response.status_code, 200)
        body = b"".join(response.streaming_content).decode()
        self.assertIn("'=HYPERLINK(1)", body)
        self.assertEqual(self.api(self.staff).get("/api/reports/export/other/").status_code, 400)

    def test_finance_extras(self):
        sub = self.sub(quantity=2, months_ago=3)
        for invoice in services.bill_subscription(sub.pk, services.add_months(self.today, -2)):
            services.confirm_invoice(invoice.pk)
        data = self.api(self.admin).get("/api/reports/summary/").data
        self.assertEqual(data["mrr_by_plan"][0]["plan"], "Monthly")
        self.assertEqual(data["average_revenue_per_customer"], Decimal("200.00"))
        self.assertGreater(sum(row["amount"] for row in data["overdue_aging"]), 0)


class RevenueRecognitionTests(Base):
    def issued(self, start, end, subtotal="3100.00", discount="0.00", tax="558.00", total=None, state="confirmed"):
        sub = self.sub(quantity=2)
        subtotal, discount, tax = Decimal(subtotal), Decimal(discount), Decimal(tax)
        return Invoice.objects.create(
            subscription=sub, customer=self.cust, customer_name="C1", customer_email="c1@x.example", state=state,
            invoice_date=start, due_date=end, period_start=start, period_end=end, billing_key=f"t:{sub.pk}",
            subtotal=subtotal, discount_total=discount, tax_total=tax, total=total or subtotal - discount + tax,
        )

    def test_earned_evenly_per_day_across_months(self):
        invoice = self.issued(date(2026, 1, 17), date(2026, 2, 15))  # 15 days in January, 15 in February
        rows = revenue.invoice_schedule(invoice, today=date(2026, 3, 1))
        self.assertEqual([r["recognized"] for r in rows], [Decimal("1550.00"), Decimal("1550.00")])
        self.assertEqual([r["month"] for r in rows], ["2026-01-01", "2026-02-01"])

    def test_part_earned_invoice_splits_recognized_and_scheduled(self):
        invoice = self.issued(date(2026, 1, 1), date(2026, 1, 31))
        row = revenue.invoice_schedule(invoice, today=date(2026, 1, 10))[0]
        self.assertEqual(row["recognized"], Decimal("1000.00"))
        self.assertEqual(row["scheduled"], Decimal("2100.00"))

    def test_months_always_add_up_to_exactly_what_was_billed(self):
        invoice = self.issued(date(2026, 1, 31), date(2027, 1, 30), subtotal="1000.01", tax="0.00")
        rows = revenue.invoice_schedule(invoice, today=date(2026, 6, 15))
        self.assertEqual(len(rows), 13)
        self.assertEqual(sum(r["recognized"] + r["scheduled"] for r in rows), Decimal("1000.01"))

    def test_tax_is_left_out_and_discount_lowers_revenue(self):
        self.issued(date(2026, 1, 1), date(2026, 1, 31), subtotal="1000.00", discount="100.00", tax="162.00")
        report = revenue.revenue_report(today=date(2026, 2, 1))
        self.assertEqual(report["summary"]["recognized_to_date"], Decimal("900.00"))

    def test_credit_lowers_revenue_in_proportion(self):
        self.issued(date(2026, 1, 1), date(2026, 1, 31), subtotal="1000.00", tax="180.00", total=Decimal("590.00"))
        report = revenue.revenue_report(today=date(2026, 2, 1))
        self.assertEqual(report["summary"]["recognized_to_date"], Decimal("500.00"))

    def test_draft_and_cancelled_are_not_revenue(self):
        self.issued(date(2026, 1, 1), date(2026, 1, 31), state="draft")
        self.issued(date(2026, 1, 1), date(2026, 1, 31), state="cancelled")
        self.assertEqual(revenue.revenue_report(today=date(2026, 2, 1))["summary"]["billed_to_date"], Decimal("0.00"))

    def test_deferred_is_billed_but_not_yet_earned(self):
        self.issued(date(2026, 1, 1), date(2026, 3, 31), subtotal="9000.00", tax="0.00")  # 90 days
        report = revenue.revenue_report(start=date(2026, 1, 1), end=date(2026, 4, 1), today=date(2026, 1, 31))
        self.assertEqual(report["summary"]["recognized_to_date"], Decimal("3100.00"))
        self.assertEqual(report["summary"]["deferred"], Decimal("5900.00"))
        months = {row["month"]: row for row in report["history"]}
        self.assertEqual(months["2026-01-01"]["status"], "current")
        self.assertEqual(months["2026-01-01"]["deferred_end"], Decimal("5900.00"))
        self.assertEqual(months["2026-01-01"]["billed"], Decimal("9000.00"))
        self.assertEqual(months["2026-02-01"]["status"], "scheduled")
        self.assertEqual(months["2026-02-01"]["scheduled"], Decimal("2800.00"))
        self.assertEqual(months["2026-03-01"]["deferred_end"], Decimal("0.00"))

    def test_filters_and_breakdowns(self):
        invoice = self.issued(date(2026, 1, 1), date(2026, 1, 31), subtotal="1000.00", tax="0.00")
        other = Plan.objects.create(name="Other", price=Decimal("1"), billing_period="yearly", start_date=date(2020, 1, 1))
        window = {"start": date(2026, 1, 1), "end": date(2026, 2, 1), "today": date(2026, 3, 1)}
        report = revenue.revenue_report(**window)
        self.assertEqual(report["by_plan"], [{"name": "Monthly", "amount": Decimal("1000.00"), "share": 100.0}])
        self.assertEqual(report["by_period"][0]["name"], "monthly")
        self.assertEqual(report["top_customers"][0]["name"], invoice.customer_name)
        self.assertEqual(revenue.revenue_report(plan=other.pk, **window)["by_plan"], [])
        self.assertEqual(revenue.revenue_report(period="yearly", **window)["summary"]["billed_to_date"], Decimal("0.00"))

    def test_api_is_team_only_and_checks_input(self):
        self.assertEqual(self.api(self.cust).get("/api/reports/revenue/").status_code, 403)
        self.assertEqual(self.api(self.staff).get("/api/reports/revenue/").status_code, 200)
        client = self.api(self.admin)
        self.assertEqual(client.get("/api/reports/revenue/?from=2026-05-01&to=2026-01-01").status_code, 400)
        self.assertEqual(client.get("/api/reports/revenue/?period=hourly").status_code, 400)
        self.assertEqual(client.get("/api/reports/revenue/?plan=x").status_code, 400)
        self.assertEqual(self.api(self.cust).get("/api/reports/export/revenue/").status_code, 403)
        self.assertIn(b"Recognized", b"".join(client.get("/api/reports/export/revenue/").streaming_content))

    def test_invoice_schedule_is_team_only(self):
        invoice = self.issued(date(2026, 1, 1), date(2026, 1, 31))
        self.assertEqual(self.api(self.cust).get(f"/api/invoices/{invoice.pk}/recognition/").status_code, 403)
        self.assertEqual(len(self.api(self.staff).get(f"/api/invoices/{invoice.pk}/recognition/").data), 1)


class BusinessFeatureTests(Base):
    def setUp(self):
        super().setUp()
        self.care = User.objects.create_user("care@x.example", PASSWORD, role="staff", department="support")
        self.seller = User.objects.create_user("sell@x.example", PASSWORD, role="staff", department="sales")
        self.seller2 = User.objects.create_user("sell2@x.example", PASSWORD, role="staff", department="sales")
        self.fee = Plan.objects.create(name="Fee", price=Decimal("300"), billing_period="monthly", start_date=self.today - timedelta(days=9), is_public=True)

    # ---- automatic renewal
    def test_customer_has_no_renew_button_or_endpoint(self):
        sub = self.sub()
        client = self.api(self.cust)
        self.assertEqual(client.post(f"/api/subscriptions/{sub.pk}/renew/").status_code, 403)
        self.assertNotIn("renew", client.get(f"/api/subscriptions/{sub.pk}/").data["allowed_actions"])
        self.assertIn("auto_renew", client.get(f"/api/subscriptions/{sub.pk}/").data["allowed_actions"])

    def test_renews_by_itself_past_expiry_and_keeps_billing(self):
        sub = self.sub(quantity=2, months_ago=2, months_long=1)
        result = services.run_billing()
        sub.refresh_from_db()
        self.assertEqual(result["subscriptions_renewed"], 1)
        self.assertEqual(sub.state, "active")
        self.assertGreaterEqual(sub.expiry_date, self.today)
        self.assertEqual(Invoice.objects.filter(subscription=sub).count(), 3)

    def test_renewal_extends_by_one_term_not_a_growing_one(self):
        sub = self.sub(months_ago=1, months_long=1)
        days = sub.term_days
        Subscription.objects.filter(pk=sub.pk).update(expiry_date=self.today - timedelta(days=1), term_days=days)
        services.renew_due()
        sub.refresh_from_db()
        self.assertEqual(sub.expiry_date, self.today - timedelta(days=1) + timedelta(days=days))

    def test_opt_out_ends_at_expiry(self):
        sub = self.sub(months_ago=2, months_long=1)
        client = self.api(self.cust)
        self.assertEqual(client.post(f"/api/subscriptions/{sub.pk}/auto_renew/", {"enabled": False}, format="json").status_code, 200)
        services.run_billing()
        sub.refresh_from_db()
        self.assertEqual(sub.state, "closed")

    def test_other_customer_cannot_opt_out(self):
        sub = self.sub()
        self.assertEqual(self.api(self.other).post(f"/api/subscriptions/{sub.pk}/auto_renew/", {"enabled": False}, format="json").status_code, 404)

    # ---- promo codes
    def promo(self, **extra):
        body = {"name": "P", "code": "promo1", "start_date": str(self.today), **extra}
        return self.api(self.admin).post("/api/discounts/", body, format="json")

    def redeem(self, sub, code="PROMO1"):
        return self.api(self.cust).post(f"/api/subscriptions/{sub.pk}/redeem/", {"code": code}, format="json")

    def test_only_admin_creates_promo_codes(self):
        body = {"name": "P", "code": "X", "reward": "credit", "value": "5", "start_date": str(self.today)}
        self.assertEqual(self.api(self.staff).post("/api/discounts/", body, format="json").status_code, 403)
        self.assertEqual(self.api(self.care).post("/api/discounts/", body, format="json").status_code, 403)

    def test_promo_validation(self):
        self.assertEqual(self.promo(reward="credit").status_code, 400)
        self.assertEqual(self.promo(reward="free_days", value="2.5").status_code, 400)
        self.assertEqual(self.promo(reward="perk").status_code, 400)
        self.assertEqual(self.api(self.admin).post("/api/discounts/", {"name": "N", "reward": "credit", "value": "5", "start_date": str(self.today)}, format="json").status_code, 400)

    def test_list_filter_separates_codes_from_rules(self):
        self.assertEqual(self.promo(reward="credit", value="5").status_code, 201)
        Discount.objects.create(name="Plain", value=Decimal("5"), start_date=self.today)
        client = self.api(self.admin)
        self.assertEqual([r["name"] for r in client.get("/api/discounts/?has_code=true").data["results"]], ["P"])
        self.assertEqual([r["name"] for r in client.get("/api/discounts/?has_code=false").data["results"]], ["Plain"])

    def test_credit_code_gives_money_once(self):
        self.promo(reward="credit", value="150")
        sub = self.sub()
        self.assertEqual(self.redeem(sub).status_code, 200)
        self.assertEqual(self.redeem(sub).status_code, 409)
        sub.refresh_from_db()
        self.assertEqual(sub.credit_balance, Decimal("150.00"))
        self.assertEqual(services.bill_subscription(sub.pk)[0].credit_applied, Decimal("150.00"))

    def test_free_days_code_moves_next_invoice_and_keeps_periods_full(self):
        self.promo(reward="free_days", value="30")
        sub = self.sub(quantity=2)
        services.bill_subscription(sub.pk)
        before = Subscription.objects.get(pk=sub.pk).next_invoice_date
        self.redeem(sub)
        sub.refresh_from_db()
        self.assertEqual(sub.next_invoice_date, before + timedelta(days=30))

    def test_perk_code_is_recorded_and_changes_no_invoice(self):
        self.promo(reward="perk", perk_text="Free onboarding call")
        sub = self.sub(quantity=2)
        response = self.redeem(sub)
        self.assertEqual(response.data["promotions"], ["Free onboarding call"])
        self.assertEqual(services.bill_subscription(sub.pk)[0].discount_total, Decimal("0.00"))
        self.assertEqual(Discount.objects.get(code="PROMO1").times_used, 1)

    def test_usage_limit_stops_a_credit_code(self):
        self.promo(reward="credit", value="10", usage_limit=1)
        self.assertEqual(self.redeem(self.sub()).status_code, 200)
        self.assertEqual(self.redeem(self.sub()).status_code, 400)

    # ---- departments
    def test_care_and_sales_cannot_reach_finance(self):
        for user in (self.care, self.seller):
            client = self.api(user)
            for path in ["/api/reports/summary/", "/api/reports/revenue/", "/api/payments/", "/api/reports/export/invoices/", "/api/imports/sample/"]:
                self.assertEqual(client.get(path).status_code, 403, path)
            self.assertEqual(client.post("/api/billing/run/").status_code, 403)

    def test_sales_sees_only_what_they_sold(self):
        mine = self.sub()
        theirs = self.sub()
        Subscription.objects.filter(pk=mine.pk).update(salesperson=self.seller)
        Subscription.objects.filter(pk=theirs.pk).update(salesperson=self.seller2)
        invoice = services.bill_subscription(mine.pk)[0]
        other_invoice = services.bill_subscription(theirs.pk)[0]
        client = self.api(self.seller)
        self.assertEqual([r["id"] for r in client.get("/api/subscriptions/").data["results"]], [mine.pk])
        self.assertEqual(client.get(f"/api/subscriptions/{theirs.pk}/").status_code, 404)
        self.assertEqual(client.get(f"/api/invoices/{invoice.pk}/").status_code, 200)
        self.assertEqual(client.get(f"/api/invoices/{other_invoice.pk}/").status_code, 404)
        self.assertEqual(client.post(f"/api/invoices/{invoice.pk}/confirm/").status_code, 403)

    def test_quote_made_by_sales_is_credited_to_them(self):
        body = {
            "customer": self.cust.pk, "plan": self.plan.pk, "payment_term": self.term.pk, "start_date": str(self.today),
            "expiry_date": str(self.today + timedelta(days=30)), "salesperson": self.seller2.pk,
            "lines": [{"product": self.product.pk, "quantity": 2}],
        }
        response = self.api(self.seller).post("/api/subscriptions/", body, format="json")
        self.assertEqual(response.status_code, 201)
        self.assertEqual(Subscription.objects.get(pk=response.data["id"]).salesperson, self.seller)

    def test_sales_report_against_target(self):
        sub = self.sub(quantity=5)
        Subscription.objects.filter(pk=sub.pk).update(salesperson=self.seller)
        SalesTarget.objects.create(salesperson=self.seller, month=self.today.replace(day=1), amount=Decimal("1000"))
        data = self.api(self.seller).get("/api/reports/sales/").data
        self.assertEqual(data["target"], Decimal("1000.00"))
        self.assertEqual(data["sold"], Decimal("500.00"))
        self.assertEqual(data["progress"], 50.0)
        self.assertEqual(data["customers"][0]["number"], sub.number)
        self.assertEqual(len(data["history"]), 6)
        other = self.api(self.seller).get(f"/api/reports/sales/?salesperson={self.seller2.pk}").data
        self.assertEqual(other["name"], self.seller.display_name)
        self.assertEqual(self.api(self.care).get("/api/reports/sales/").status_code, 403)
        self.assertEqual(self.api(self.cust).get("/api/reports/sales/").status_code, 403)
        self.assertEqual(len(self.api(self.admin).get("/api/reports/sales/").data["team"]), 2)

    def test_only_admin_sets_targets_and_month_is_normalised(self):
        body = {"salesperson": self.seller.pk, "month": "2026-03-17", "amount": "100"}
        self.assertEqual(self.api(self.staff).post("/api/sales-targets/", body, format="json").status_code, 403)
        self.assertEqual(self.api(self.seller).post("/api/sales-targets/", body, format="json").status_code, 403)
        self.assertEqual(self.api(self.admin).post("/api/sales-targets/", body, format="json").data["month"], "2026-03-01")
        self.assertEqual(self.api(self.admin).post("/api/sales-targets/", body, format="json").status_code, 400)

    # ---- payment approval
    def confirmed(self):
        sub = self.sub(quantity=2)
        invoice = services.bill_subscription(sub.pk)[0]
        services.confirm_invoice(invoice.pk)
        return Invoice.objects.get(pk=invoice.pk)

    def ask(self, invoice, user=None, **extra):
        body = {"method": "upi", "amount": str(invoice.total), "reference": "ref 1", **extra}
        return self.api(user or self.cust).post(f"/api/invoices/{invoice.pk}/request_payment/", body, format="json")

    def test_payment_request_changes_nothing_until_approved(self):
        invoice = self.confirmed()
        self.assertEqual(self.ask(invoice).status_code, 201)
        self.assertEqual(self.ask(invoice).status_code, 409)
        invoice.refresh_from_db()
        self.assertEqual(invoice.state, "confirmed")
        self.assertEqual(invoice.amount_paid, 0)
        row = PaymentRequest.objects.get(invoice=invoice)
        self.assertEqual(self.api(self.staff).post(f"/api/payment-requests/{row.pk}/approve/").status_code, 403)
        self.assertEqual(self.api(self.cust).post(f"/api/payment-requests/{row.pk}/approve/").status_code, 403)
        self.assertEqual(self.api(self.admin).post(f"/api/payment-requests/{row.pk}/approve/").status_code, 200)
        invoice.refresh_from_db()
        self.assertEqual(invoice.state, "paid")
        self.assertEqual(self.api(self.admin).post(f"/api/payment-requests/{row.pk}/approve/").status_code, 409)
        self.assertEqual(Payment.objects.filter(invoice=invoice).count(), 1)

    def test_rejected_request_records_nothing(self):
        invoice = self.confirmed()
        self.ask(invoice)
        row = PaymentRequest.objects.get(invoice=invoice)
        self.assertEqual(self.api(self.admin).post(f"/api/payment-requests/{row.pk}/reject/", {"note": "No money received"}, format="json").status_code, 200)
        self.assertFalse(Payment.objects.filter(invoice=invoice).exists())

    def test_payment_request_limits(self):
        invoice = self.confirmed()
        self.assertEqual(self.ask(invoice, amount="999999").status_code, 400)
        self.assertEqual(self.ask(invoice, method="online").status_code, 400)
        self.assertEqual(self.ask(invoice, user=self.other).status_code, 404)
        self.assertEqual(self.ask(invoice, user=self.staff).status_code, 403)

    # ---- account view and assigned plans
    def test_customer_overview(self):
        self.sub(quantity=2)
        client = self.api(self.care)
        data = client.get(f"/api/customers/{self.cust.pk}/overview/").data
        self.assertEqual(data["status"], "active")
        self.assertEqual(data["subscriptions"][0]["plan_name"], "Monthly")
        self.assertEqual(self.api(self.cust).get(f"/api/customers/{self.cust.pk}/overview/").status_code, 403)
        self.assertEqual(self.api(self.seller).get(f"/api/customers/{self.cust.pk}/overview/").status_code, 403)
        self.assertEqual(client.get(f"/api/customers/{self.admin.pk}/overview/").status_code, 404)

    def test_only_admin_assigns_any_plan(self):
        url = f"/api/customers/{self.cust.pk}/assign_plan/"
        private = Plan.objects.create(name="Private", price=Decimal("50"), billing_period="yearly", start_date=self.today, min_quantity=9)
        self.assertEqual(self.api(self.staff).post(url, {"plan": private.pk}, format="json").status_code, 403)
        response = self.api(self.admin).post(url, {"plan": private.pk}, format="json")
        self.assertEqual(response.status_code, 201)
        sub = Subscription.objects.get(pk=response.data["id"])
        self.assertEqual((sub.state, sub.plan), ("active", private))
        self.assertEqual(sub.invoices.get().state, "confirmed")
        self.assertEqual(self.api(self.admin).post(url, {"plan": private.pk}, format="json").status_code, 409)

    def test_assign_can_replace_only_that_customers_subscription(self):
        old = self.sub()
        stranger = self.sub(customer=self.other)
        url = f"/api/customers/{self.cust.pk}/assign_plan/"
        client = self.api(self.admin)
        self.assertEqual(client.post(url, {"plan": self.fee.pk, "replace": stranger.pk}, format="json").status_code, 400)
        self.assertEqual(client.post(url, {"plan": self.fee.pk, "replace": old.pk}, format="json").status_code, 201)
        old.refresh_from_db()
        stranger.refresh_from_db()
        self.assertEqual((old.state, stranger.state), ("closed", "active"))

    def test_starting_a_plan_online_gives_an_invoice_to_pay(self):
        response = self.api(self.cust).post("/api/subscriptions/start/", {"plan": self.fee.pk}, format="json")
        invoice = Invoice.objects.get(subscription_id=response.data["id"])
        self.assertEqual(invoice.state, "confirmed")
        self.assertEqual(invoice.total, Decimal("300.00"))

    # ---- import
    CSV = "email,first_name,company,plan,product,quantity,start_date\nnew@buyer.example,Nia,Nia Co,Fee,Seat,3,{start}\n"

    def imported(self, text, commit=True, user=None):
        return self.api(user or self.admin).post("/api/imports/subscribers/", {"csv": text, "commit": commit}, format="json")

    def test_preview_writes_nothing(self):
        data = self.imported(self.CSV.format(start=self.today), commit=False).data
        self.assertEqual((data["ready"], data["errors"]), (1, 0))
        self.assertFalse(User.objects.filter(email="new@buyer.example").exists())

    def test_import_creates_subscriber_without_back_billing_and_only_once(self):
        start = self.today - timedelta(days=95)
        self.assertEqual(self.imported(self.CSV.format(start=start)).data["imported"], 1)
        sub = Subscription.objects.get(customer__email="new@buyer.example")
        self.assertEqual((sub.state, sub.recurring_total), ("active", Decimal("600.00")))
        self.assertGreaterEqual(sub.next_invoice_date, self.today)
        services.run_billing(self.today - timedelta(days=1))
        self.assertEqual(Invoice.objects.filter(subscription=sub).count(), 0)
        self.assertFalse(User.objects.get(email="new@buyer.example").has_usable_password())
        self.assertEqual(self.imported(self.CSV.format(start=start)).data["skipped"], 1)
        self.assertEqual(Subscription.objects.filter(customer__email="new@buyer.example").count(), 1)

    def test_bad_rows_are_reported_and_good_rows_still_import(self):
        text = "email,plan,start_date,quantity\nbad,Fee,,\na@b.example,Nope,,\nc@b.example,Fee,2026-13-99,\nd@b.example,Fee,,0\nstaff@x.example,Fee,,\ne@b.example,Fee,,\n"
        data = self.imported(text).data
        self.assertEqual((data["imported"], data["errors"]), (1, 5))

    def test_import_checks_shape_and_access(self):
        self.assertEqual(self.imported("").status_code, 400)
        self.assertEqual(self.imported("name,age\nx,1\n").status_code, 400)
        self.assertEqual(self.imported(self.CSV.format(start=self.today), user=self.care).status_code, 403)
        self.assertEqual(self.imported(self.CSV.format(start=self.today), user=self.cust).status_code, 403)

    def test_sample_data_imports_cleanly(self):
        sample = self.api(self.admin).get("/api/imports/sample/").data["csv"]
        data = self.imported(sample).data
        self.assertEqual(data["errors"], 0)
        self.assertEqual(data["imported"], 8)

