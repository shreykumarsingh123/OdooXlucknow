from datetime import timedelta
from decimal import Decimal

from django.core import mail
from django.core.cache import cache
from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.identity import classify, staff_email
from accounts.models import Business, PasswordOTP, User
from billing import services
from billing.models import Invoice, Subscription
from catalog.models import Discount, PaymentTerm, Plan, Product, Tax

PASSWORD = "Strong@Pass1"


class Setup(TestCase):
    def setUp(self):
        cache.clear()
        self.platform = Business.objects.create(name="Brightloop", is_platform=True, code="brloop")
        self.root = User.objects.create_superuser("asha@admin.com", PASSWORD)
        self.a = Business.objects.create(name="Alpha", code="aaa111")
        self.b = Business.objects.create(name="Beta", code="bbb222")
        self.owner_a = User.objects.create_user("alpha@gmail.com", PASSWORD, role="admin", business=self.a)
        self.owner_b = User.objects.create_user("beta@gmail.com", PASSWORD, role="admin", business=self.b)
        self.cust_a = User.objects.create_user("custa@gmail.com", PASSWORD, business=self.a)
        self.cust_b = User.objects.create_user("custb@gmail.com", PASSWORD, business=self.b)
        self.today = timezone.localdate()
        self.term_a = PaymentTerm.objects.create(business=self.a, name="Now", due_days=0)
        self.term_b = PaymentTerm.objects.create(business=self.b, name="Now", due_days=0)
        self.plan_a = Plan.objects.create(business=self.a, name="Monthly", price=Decimal("100"), start_date=self.today - timedelta(days=9), is_public=True)
        self.plan_b = Plan.objects.create(business=self.b, name="Monthly", price=Decimal("200"), start_date=self.today - timedelta(days=9), is_public=True)

    def api(self, user=None):
        client = APIClient()
        if user:
            client.force_authenticate(user)
        return client

    def running(self, customer, plan):
        return services.provision(customer, plan, None, "Test")


class IdentityTests(TestCase):
    def test_address_decides_the_person(self):
        self.assertEqual(classify("a@gmail.com")["kind"], "user")
        self.assertEqual(classify("asha@admin.com")["kind"], "root")
        self.assertEqual(classify("ravi@adminsale.com"), {"kind": "platform_staff", "department": "sales", "code": None})
        self.assertEqual(classify("neha@support.com"), {"kind": "platform_staff", "department": "support", "code": None})
        self.assertEqual(classify("rohanaaa111@sale.com"), {"kind": "business_staff", "department": "sales", "code": "aaa111"})
        self.assertEqual(classify("pooja.aaa111@support.com"), {"kind": "business_staff", "department": "support", "code": "aaa111"})

    def test_other_formats_are_refused(self):
        for email in ["a@yahoo.com", "short@sale.com", "a.b.c@adminsale.com", "x@", "1abc@support.com"]:
            self.assertIsNone(classify(email)["kind"], email)


class SignupTests(Setup):
    def signup(self, email, **extra):
        return self.api().post("/api/auth/signup/", {"email": email, "password": PASSWORD, **extra}, format="json")

    def test_gmail_becomes_owner_with_a_unique_id(self):
        response = self.signup("new@gmail.com", business_name="New Co")
        self.assertEqual(response.status_code, 201)
        user = User.objects.get(email="new@gmail.com")
        self.assertEqual((user.role, user.business.name), ("admin", "New Co"))
        self.assertEqual(len(user.business.code), 6)

    def test_gmail_with_business_id_becomes_its_customer(self):
        self.assertEqual(self.signup("sub@gmail.com", business_id="AAA111").status_code, 201)
        user = User.objects.get(email="sub@gmail.com")
        self.assertEqual((user.role, user.business), ("customer", self.a))

    def test_team_joins_by_id_but_waits_for_approval(self):
        response = self.signup("rohanaaa111@sale.com")
        self.assertEqual(response.status_code, 201)
        self.assertTrue(response.data["pending"])
        user = User.objects.get(email="rohanaaa111@sale.com")
        self.assertEqual((user.role, user.department, user.business, user.is_active), ("staff", "sales", self.a, False))
        self.assertEqual(self.api().post("/api/auth/login/", {"email": user.email, "password": PASSWORD}, format="json").status_code, 401)

    def test_unknown_business_id_refused(self):
        self.assertEqual(self.signup("rohanzzz999@sale.com").status_code, 400)
        self.assertEqual(self.signup("x@gmail.com", business_id="zzz999").status_code, 400)

    def test_nobody_can_sign_up_as_brightloop(self):
        for email in ["eve@admin.com", "eve@adminsale.com", "eve@support.com", "evebrloop@sale.com", "eve.brloop@support.com"]:
            self.assertEqual(self.signup(email).status_code, 400, email)
        self.assertEqual(User.objects.filter(business=self.platform).count(), 1)

    def test_other_addresses_and_weak_passwords_refused(self):
        self.assertEqual(self.signup("a@yahoo.com").status_code, 400)
        self.assertEqual(self.signup("ALPHA@gmail.com").status_code, 400)
        for weak in ["Short@1a", "alllower@123", "ALLUPPER@123", "NoSpecial123"]:
            response = self.api().post("/api/auth/signup/", {"email": "w@gmail.com", "password": weak}, format="json")
            self.assertEqual(response.status_code, 400, weak)

    def test_signup_cannot_choose_role(self):
        self.signup("h@gmail.com", role="staff", department="sales", root_marker=True)
        user = User.objects.get(email="h@gmail.com")
        self.assertEqual((user.role, user.department, user.root_marker), ("admin", "", None))


class SingleAdministratorTests(Setup):
    def test_database_allows_only_one(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            User.objects.create_superuser("second@admin.com", PASSWORD)


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class OtpTests(Setup):
    def ask(self, email="custa@gmail.com"):
        return self.api().post("/api/auth/forgot-password/", {"email": email}, format="json")

    def code(self):
        return mail.outbox[-1].body.split("code is: ")[1][:6]

    def reset(self, otp, email="custa@gmail.com", password="Another@Pass2"):
        return self.api().post("/api/auth/reset-password/", {"email": email, "otp": otp, "password": password}, format="json")

    def test_flow_works_once(self):
        self.ask()
        code = self.code()
        self.assertIn("reset the password", mail.outbox[-1].body)
        self.assertEqual(self.reset(code).status_code, 200)
        self.cust_a.refresh_from_db()
        self.assertTrue(self.cust_a.check_password("Another@Pass2"))
        self.assertEqual(self.reset(code).status_code, 400)

    def test_unknown_email_gets_the_same_answer_and_no_mail(self):
        self.assertEqual(self.ask("nobody@gmail.com").data, self.ask("custa@gmail.com").data)
        self.assertEqual(len(mail.outbox), 1)

    def test_code_goes_to_the_recovery_address(self):
        User.objects.filter(pk=self.cust_a.pk).update(recovery_email="safe@example.com")
        self.ask()
        self.assertEqual(mail.outbox[-1].to, ["safe@example.com"])

    def test_code_is_stored_hashed(self):
        self.ask()
        self.assertNotIn(self.code(), PasswordOTP.objects.get(user=self.cust_a).code_hash)

    def test_wrong_guesses_burn_the_code(self):
        self.ask()
        code = self.code()
        wrong = "000000" if code != "000000" else "111111"
        for _ in range(5):
            self.assertEqual(self.reset(wrong).status_code, 400)
        self.assertEqual(self.reset(code).status_code, 400)

    def test_new_code_does_not_buy_more_guesses(self):
        self.ask()
        wrong = "000000" if self.code() != "000000" else "111111"
        for _ in range(5):
            self.reset(wrong)
        self.ask()
        self.assertEqual(self.reset(self.code()).status_code, 400)

    def test_codes_per_hour_are_capped_with_the_same_answer(self):
        answers = [self.ask().data for _ in range(5)]
        self.assertEqual(len(mail.outbox), 3)
        self.assertEqual(answers[0], answers[4])

    def test_limits_clear_after_an_hour(self):
        self.ask()
        wrong = "000000" if self.code() != "000000" else "111111"
        for _ in range(5):
            self.reset(wrong)
        PasswordOTP.objects.filter(user=self.cust_a).update(window_start=timezone.now() - timedelta(hours=2))
        self.ask()
        self.assertEqual(self.reset(self.code()).status_code, 200)

    def test_expired_code_refused(self):
        self.ask()
        PasswordOTP.objects.filter(user=self.cust_a).update(expires_at=timezone.now() - timedelta(minutes=1))
        self.assertEqual(self.reset(self.code()).status_code, 400)

    def test_weak_password_keeps_the_code(self):
        self.ask()
        code = self.code()
        self.assertEqual(self.reset(code, password="weak").status_code, 400)
        self.assertEqual(self.reset(code).status_code, 200)

    @override_settings(DEBUG=False, EMAIL_BACKEND="django.core.mail.backends.filebased.EmailBackend", EMAIL_FILE_PATH="/tmp/never")
    def test_code_is_never_shown_outside_debug(self):
        self.assertNotIn("dev_otp", self.ask().data)


class RecoveryEmailTests(Setup):
    def patch(self, value):
        return self.api(self.cust_a).patch("/api/auth/me/", {"recovery_email": value}, format="json")

    def test_saved_on_the_profile(self):
        self.assertEqual(self.patch("Me@Example.com").status_code, 200)
        self.cust_a.refresh_from_db()
        self.assertEqual(self.cust_a.recovery_email, "me@example.com")

    def test_needs_a_real_different_mailbox(self):
        self.assertEqual(self.patch("x@sale.com").status_code, 400)
        self.assertEqual(self.patch("custa@gmail.com").status_code, 400)


class StaffTests(Setup):
    def add(self, user=None, **extra):
        body = {"first_name": "Rohan", "department": "sales", "password": PASSWORD, **extra}
        return self.api(user or self.owner_a).post("/api/staff/", body, format="json")

    def test_owner_adds_staff_and_address_follows_the_scheme(self):
        self.assertEqual(self.add().data["email"], "rohanaaa111@sale.com")
        self.assertEqual(self.add(first_name="Pooja", department="support").data["email"], "pooja.aaa111@support.com")

    def test_administrator_adds_brightloop_staff(self):
        self.assertEqual(self.add(self.root).data["email"], "rohan@adminsale.com")
        self.assertEqual(self.add(self.root, first_name="Neha", department="support").data["email"], "neha@support.com")
        self.assertEqual(staff_email("9x", "sales", self.a), f"x{self.a.code}@sale.com")

    def test_customer_and_staff_cannot_add_staff(self):
        self.assertEqual(self.add(self.cust_a).status_code, 403)
        worker = User.objects.get(pk=self.add().data["id"])
        self.assertEqual(self.add(worker, first_name="Eve").status_code, 403)

    def test_owner_sees_only_their_staff_and_can_delete(self):
        pk = self.add().data["id"]
        self.assertEqual(self.api(self.owner_b).get("/api/staff/").data["count"], 0)
        self.assertEqual(self.api(self.owner_b).delete(f"/api/staff/{pk}/").status_code, 404)
        self.assertEqual(self.api(self.owner_a).delete(f"/api/staff/{pk}/").status_code, 204)
        self.assertFalse(User.objects.filter(pk=pk).exists())

    def test_owner_approves_someone_who_joined(self):
        self.api().post("/api/auth/signup/", {"email": "newaaa111@sale.com", "password": PASSWORD}, format="json")
        person = User.objects.get(email="newaaa111@sale.com")
        self.assertEqual(self.api(self.owner_a).patch(f"/api/staff/{person.pk}/", {"is_active": True}, format="json").status_code, 200)
        self.assertEqual(self.api().post("/api/auth/login/", {"email": person.email, "password": PASSWORD}, format="json").status_code, 200)
        person.refresh_from_db()
        self.assertEqual(person.email, "newaaa111@sale.com")


class IsolationTests(Setup):
    """One business must never read or touch another's records, whatever id it sends."""

    def test_lists_show_only_own_records(self):
        self.running(self.cust_b, self.plan_b)
        Tax.objects.create(business=self.b, name="Secret tax", rate=1)
        client = self.api(self.owner_a)
        for path in ["/api/subscriptions/", "/api/invoices/", "/api/taxes/", "/api/customers/?search=custb"]:
            self.assertEqual(client.get(path).data["count"], 0, path)
        self.assertEqual([p["id"] for p in client.get("/api/plans/").data["results"]], [self.plan_a.pk])

    def test_details_of_another_business_are_not_found(self):
        sub = self.running(self.cust_b, self.plan_b)
        invoice = Invoice.objects.get(subscription=sub)
        client = self.api(self.owner_a)
        self.assertEqual(client.get(f"/api/subscriptions/{sub.pk}/").status_code, 404)
        self.assertEqual(client.get(f"/api/invoices/{invoice.pk}/").status_code, 404)
        self.assertEqual(client.post(f"/api/invoices/{invoice.pk}/send/").status_code, 404)
        self.assertEqual(client.get(f"/api/plans/{self.plan_b.pk}/").status_code, 404)
        self.assertEqual(client.get(f"/api/customers/{self.cust_b.pk}/overview/").status_code, 404)

    def test_cannot_build_on_another_business_records(self):
        client = self.api(self.owner_a)
        body = {
            "customer": self.cust_a.pk, "plan": self.plan_b.pk, "payment_term": self.term_a.pk,
            "start_date": str(self.today), "expiry_date": str(self.today + timedelta(days=30)),
        }
        self.assertEqual(client.post("/api/subscriptions/", body, format="json").status_code, 400)
        body.update(plan=self.plan_a.pk, customer=self.cust_b.pk)
        self.assertEqual(client.post("/api/subscriptions/", body, format="json").status_code, 400)
        body.update(customer=self.cust_a.pk, payment_term=self.term_b.pk)
        self.assertEqual(client.post("/api/subscriptions/", body, format="json").status_code, 400)
        tax = Tax.objects.create(business=self.b, name="Other", rate=1)
        product = {"name": "P", "sales_price": "1", "taxes": [tax.pk]}
        self.assertEqual(client.post("/api/products/", product, format="json").status_code, 400)

    def test_payment_cannot_land_on_another_business_invoice(self):
        invoice = Invoice.objects.get(subscription=self.running(self.cust_b, self.plan_b))
        body = {"invoice": invoice.pk, "method": "cash", "amount": "1", "date": str(self.today)}
        self.assertEqual(self.api(self.owner_a).post("/api/payments/", body, format="json").status_code, 400)

    def test_same_names_and_codes_in_two_businesses(self):
        client = self.api(self.owner_a)
        self.assertEqual(client.post("/api/plans/", {"name": "Monthly", "start_date": str(self.today)}, format="json").status_code, 400)
        body = {"name": "D", "code": "SAME", "reward": "credit", "value": "5", "start_date": str(self.today)}
        self.assertEqual(client.post("/api/discounts/", body, format="json").status_code, 201)
        self.assertEqual(self.api(self.owner_b).post("/api/discounts/", body, format="json").status_code, 201)

    def test_code_from_another_business_does_not_redeem(self):
        Discount.objects.create(business=self.b, name="B", scope="subscriptions", value=5, start_date=self.today, code="BONLY", reward="credit")
        sub = self.running(self.cust_a, self.plan_a)
        self.assertEqual(self.api(self.cust_a).post(f"/api/subscriptions/{sub.pk}/redeem/", {"code": "BONLY"}, format="json").status_code, 400)

    def test_billing_button_covers_only_own_business(self):
        sub = services.provision(self.cust_b, self.plan_b, None, "Test", bill=False)
        result = self.api(self.owner_a).post("/api/billing/run/").data
        self.assertEqual(result["invoices_created"], 0)
        self.assertFalse(Invoice.objects.filter(subscription=sub).exists())

    def test_reports_cover_only_own_business(self):
        self.running(self.cust_b, self.plan_b)
        self.running(self.cust_a, self.plan_a)
        data = self.api(self.owner_a).get("/api/reports/summary/").data
        self.assertEqual(data["monthly_recurring_revenue"], Decimal("100.00"))
        self.assertEqual(self.api(self.owner_a).get("/api/reports/revenue/").data["summary"]["billed_to_date"], Decimal("100.00"))

    def test_bulk_skips_other_business_invoices(self):
        invoice = Invoice.objects.get(subscription=self.running(self.cust_b, self.plan_b))
        response = self.api(self.owner_a).post("/api/invoices/bulk/", {"action": "send", "ids": [invoice.pk]}, format="json")
        self.assertEqual(response.data["done"], 0)

    def test_chats_are_private_to_a_business(self):
        self.api(self.owner_a).post("/api/team-chat/", {"body": "Private"}, format="json")
        self.api(self.owner_a).post("/api/admin-chat/", {"body": "Help"}, format="json")
        self.assertEqual(self.api(self.owner_b).get("/api/team-chat/").data["count"], 0)
        self.assertEqual(self.api(self.owner_b).get("/api/admin-chat/").data["count"], 0)
        self.assertEqual(self.api(self.cust_a).get("/api/team-chat/").status_code, 403)
        self.assertEqual(self.api(self.cust_a).get("/api/admin-chat/").status_code, 403)

    def test_owner_cannot_post_admin_chat_as_another_business(self):
        self.api(self.owner_a).post("/api/admin-chat/?business=%d" % self.b.pk, {"body": "Spoof", "business": self.b.pk}, format="json")
        self.assertEqual(self.api(self.root).get(f"/api/admin-chat/?business={self.b.pk}").data["count"], 0)


class PlatformTests(Setup):
    def test_only_brightloop_sees_everything(self):
        self.running(self.cust_a, self.plan_a)
        self.running(self.cust_b, self.plan_b)
        for user in (self.owner_a, self.cust_a):
            self.assertEqual(self.api(user).get("/api/platform/overview/").status_code, 403)
            self.assertEqual(self.api(user).get("/api/platform/users/").status_code, 403)
        data = self.api(self.root).get("/api/platform/overview/").data
        self.assertEqual(data["totals"]["businesses"], 2)
        self.assertEqual(data["totals"]["active_subscriptions"], 2)
        self.assertEqual(data["totals"]["tracked_mrr"], Decimal("300.00"))
        self.assertEqual(data["businesses"][0]["name"], "Beta")

    def test_brightloop_staff_see_metrics_and_manage_users(self):
        staff = User.objects.create_user("ravi@adminsale.com", PASSWORD, role="staff", department="sales", business=self.platform)
        client = self.api(staff)
        self.assertEqual(client.get("/api/platform/overview/").status_code, 200)
        self.assertEqual(client.post(f"/api/platform/users/{self.cust_a.pk}/active/", {"is_active": False}, format="json").status_code, 200)
        self.cust_a.refresh_from_db()
        self.assertFalse(self.cust_a.is_active)
        self.assertEqual(client.post(f"/api/platform/users/{self.root.pk}/active/", {"is_active": False}, format="json").status_code, 403)

    def test_suspended_business_is_locked_out(self):
        token = self.api().post("/api/auth/login/", {"email": "alpha@gmail.com", "password": PASSWORD}, format="json").data["access"]
        client = self.api()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        self.assertEqual(client.get("/api/auth/me/").status_code, 200)
        self.api(self.root).post(f"/api/platform/businesses/{self.a.pk}/active/", {"is_active": False}, format="json")
        self.assertEqual(client.get("/api/auth/me/").status_code, 401)

    def test_brightloop_answers_a_business_in_admin_chat(self):
        self.api(self.owner_a).post("/api/admin-chat/", {"body": "Help"}, format="json")
        client = self.api(self.root)
        self.assertEqual(client.get("/api/admin-chat/threads/").data[0]["name"], "Alpha")
        self.assertEqual(client.get("/api/admin-chat/").status_code, 400)
        self.assertEqual(client.post(f"/api/admin-chat/?business={self.a.pk}", {"body": "Sure"}, format="json").status_code, 201)
        self.assertEqual(self.api(self.owner_a).get("/api/admin-chat/").data["count"], 2)
        self.assertEqual(self.api(self.owner_a).get("/api/admin-chat/threads/").status_code, 403)

    def test_owner_is_brightloop_customer_without_mixing_records(self):
        term = PaymentTerm.objects.create(business=self.platform, name="Now", due_days=0)
        plan = Plan.objects.create(business=self.platform, name="Growth", price=Decimal("500"), start_date=self.today, is_public=True)
        self.assertTrue(term.pk)
        response = self.api(self.owner_a).post("/api/my-plan/", {"plan": plan.pk}, format="json")
        self.assertEqual(response.status_code, 201)
        self.assertEqual(self.api(self.owner_a).get("/api/my-plan/").data["subscriptions"][0]["plan_name"], "Growth")
        self.assertEqual(self.api(self.owner_a).get("/api/subscriptions/").data["count"], 0)
        self.assertEqual(self.api(self.root).get("/api/subscriptions/").data["count"], 1)
        self.assertEqual(self.api(self.root).get("/api/customers/").data["count"], 2)

    def test_owner_cannot_start_another_business_plan_as_brightloop_plan(self):
        self.assertEqual(self.api(self.owner_a).post("/api/my-plan/", {"plan": self.plan_b.pk}, format="json").status_code, 409)


class SiteTests(Setup):
    def subscribe(self, code="aaa111", **extra):
        body = {"email": "buyer@gmail.com", "name": "Buyer", "plan": self.plan_a.pk, **extra}
        return self.api().post(f"/api/public/sites/{code}/subscribe/", body, format="json")

    def test_site_shows_only_that_business(self):
        data = self.api().get("/api/public/sites/aaa111/").data
        self.assertEqual(data["name"], "Alpha")
        self.assertEqual([p["id"] for p in data["plans"]], [self.plan_a.pk])
        self.assertEqual(self.api().get("/api/public/sites/nope00/").status_code, 404)
        self.assertEqual(self.api().get("/api/public/sites/brloop/").status_code, 404)

    def test_subscription_on_the_site_is_tracked_under_the_business(self):
        response = self.subscribe()
        self.assertEqual(response.status_code, 201)
        sub = Subscription.objects.get(number=response.data["number"])
        self.assertEqual((sub.business, sub.customer.email, sub.customer.role, sub.state), (self.a, "buyer@gmail.com", "customer", "active"))
        self.assertEqual(Invoice.objects.get(subscription=sub).state, "confirmed")
        self.assertEqual(self.api(self.owner_a).get("/api/subscriptions/").data["count"], 1)
        self.assertEqual(self.api(self.owner_b).get("/api/subscriptions/").data["count"], 0)

    def test_site_rules(self):
        self.assertEqual(self.subscribe(email="a@yahoo.com").status_code, 400)
        self.assertEqual(self.subscribe(plan=self.plan_b.pk).status_code, 400)
        self.assertEqual(self.subscribe().status_code, 201)
        self.assertEqual(self.subscribe().status_code, 409)

    def test_site_cannot_charge_an_existing_account(self):
        for email in ["custa@gmail.com", "custb@gmail.com", "alpha@gmail.com"]:
            self.assertEqual(self.subscribe(email=email).status_code, 409, email)
        self.assertFalse(Subscription.objects.filter(customer=self.cust_a).exists())
        Product.objects.create(business=self.a, name="Keep", sales_price=1)
