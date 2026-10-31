from django.urls import path
from rest_framework.routers import SimpleRouter

from . import views

router = SimpleRouter()
router.register("subscriptions", views.SubscriptionViewSet, basename="subscription")
router.register("invoices", views.InvoiceViewSet, basename="invoice")
router.register("payments", views.PaymentViewSet, basename="payment")
urlpatterns = router.urls + [
    path("billing/run/", views.billing_run),
    path("billing/reminders/", views.send_reminders),
    path("webhooks/stripe/", views.stripe_webhook),
    path("reports/summary/", views.report_summary),
]
