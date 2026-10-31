from django.core import mail
from django.core.cache import cache
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from accounts.models import User
from support.models import Ticket

PASSWORD = "Strong@Pass1"


class SupportTests(TestCase):
    def setUp(self):
        cache.clear()
        self.admin = User.objects.create_user("admin@x.example", PASSWORD, role="admin")
        self.care = User.objects.create_user("care@x.example", PASSWORD, role="staff", department="support")
        self.seller = User.objects.create_user("sell@x.example", PASSWORD, role="staff", department="sales")
        self.cust = User.objects.create_user("c1@x.example", PASSWORD, company="C1")
        self.other = User.objects.create_user("c2@x.example", PASSWORD, company="C2")

    def api(self, user):
        client = APIClient()
        client.force_authenticate(user)
        return client

    def raise_ticket(self, user=None, **extra):
        body = {"subject": "Help", "body": "My invoice is wrong", **extra}
        return self.api(user or self.cust).post("/api/tickets/", body, format="json")

    def test_customer_raises_and_sees_only_own_tickets(self):
        created = self.raise_ticket()
        self.assertEqual(created.status_code, 201)
        self.assertTrue(created.data["number"].startswith("TCK-"))
        self.assertEqual(created.data["customer"], self.cust.pk)
        self.raise_ticket(self.other)
        rows = self.api(self.cust).get("/api/tickets/").data["results"]
        self.assertEqual([r["id"] for r in rows], [created.data["id"]])
        self.assertEqual(self.api(self.other).get(f"/api/tickets/{created.data['id']}/").status_code, 404)

    def test_customer_cannot_raise_for_someone_else(self):
        created = self.raise_ticket(customer=self.other.pk)
        self.assertEqual(created.data["customer"], self.cust.pk)

    def test_care_sees_all_and_sales_sees_none(self):
        self.raise_ticket()
        self.raise_ticket(self.other)
        self.assertEqual(self.api(self.care).get("/api/tickets/").data["count"], 2)
        self.assertEqual(self.api(self.admin).get("/api/tickets/").data["count"], 2)
        self.assertEqual(self.api(self.seller).get("/api/tickets/").status_code, 403)

    def test_internal_notes_never_reach_the_customer(self):
        pk = self.raise_ticket().data["id"]
        self.api(self.care).post(f"/api/tickets/{pk}/reply/", {"body": "Secret note", "internal": True}, format="json")
        self.assertEqual(len(self.api(self.care).get(f"/api/tickets/{pk}/").data["messages"]), 2)
        seen = self.api(self.cust).get(f"/api/tickets/{pk}/").data["messages"]
        self.assertEqual([m["body"] for m in seen], ["My invoice is wrong"])
        # A customer cannot mark their own message internal either.
        reply = self.api(self.cust).post(f"/api/tickets/{pk}/reply/", {"body": "Hello?", "internal": True}, format="json")
        self.assertEqual(reply.data["messages"][-1]["is_internal"], False)

    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_reply_moves_status_and_emails_customer(self):
        pk = self.raise_ticket().data["id"]
        response = self.api(self.care).post(f"/api/tickets/{pk}/reply/", {"body": "On it"}, format="json")
        self.assertEqual(response.data["status"], "in_progress")
        self.assertEqual(len(mail.outbox), 1)
        self.api(self.care).post(f"/api/tickets/{pk}/manage/", {"status": "resolved"}, format="json")
        reopened = self.api(self.cust).post(f"/api/tickets/{pk}/reply/", {"body": "Still broken"}, format="json")
        self.assertEqual(reopened.data["status"], "open")

    def test_only_team_manages_and_can_escalate(self):
        pk = self.raise_ticket().data["id"]
        self.assertEqual(self.api(self.cust).post(f"/api/tickets/{pk}/manage/", {"status": "resolved"}, format="json").status_code, 403)
        response = self.api(self.care).post(f"/api/tickets/{pk}/manage/", {"escalated": True, "assigned_to": self.admin.pk}, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(Ticket.objects.get(pk=pk).escalated)
        self.assertEqual(self.api(self.care).post(f"/api/tickets/{pk}/manage/", {"assigned_to": self.cust.pk}, format="json").status_code, 400)

    def test_empty_reply_refused(self):
        pk = self.raise_ticket().data["id"]
        self.assertEqual(self.api(self.cust).post(f"/api/tickets/{pk}/reply/", {"body": "  "}, format="json").status_code, 400)

    def test_team_chat_is_team_only(self):
        self.assertEqual(self.api(self.care).post("/api/team-chat/", {"body": "Admin, please look"}, format="json").status_code, 201)
        self.assertEqual(self.api(self.admin).get("/api/team-chat/").data["results"][0]["author_role"], "Customer care")
        self.assertEqual(self.api(self.cust).get("/api/team-chat/").status_code, 403)
        self.assertEqual(self.api(self.cust).post("/api/team-chat/", {"body": "x"}, format="json").status_code, 403)
