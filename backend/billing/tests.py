from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import patch

from django.core import mail
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import User
from billing import notify, services
from billing.models import Invoice, Payment, Subscription
from catalog.models import Discount, PaymentTerm, Plan, Product, ProductVariant, Tax

PASSWORD = "Strong@Pass1"


class Base(TestCase):
    def setUp(self):
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
        for step in ["pause", "close", "renew"]:
            self.assertEqual(client.post(f"/api/subscriptions/{sub.pk}/{step}/").status_code, 409, step)

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
        self.sub(months_ago=6, months_long=2)
        self.assertEqual(services.run_billing()["invoices_created"], 3)

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
