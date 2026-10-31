from django.urls import path
from rest_framework.routers import SimpleRouter

from . import views

router = SimpleRouter()
router.register("subscriptions", views.SubscriptionViewSet, basename="subscription")
router.register("invoices", views.InvoiceViewSet, basename="invoice")
router.register("payments", views.PaymentViewSet, basename="payment")
router.register("payment-requests", views.PaymentRequestViewSet, basename="payment-request")
router.register("sales-targets", views.SalesTargetViewSet, basename="sales-target")
urlpatterns = router.urls + [
    path("billing/run/", views.billing_run),
    path("billing/reminders/", views.send_reminders),
    path("webhooks/stripe/", views.stripe_webhook),
    path("reports/summary/", views.report_summary),
    path("reports/revenue/", views.revenue_summary),
    path("reports/export/<str:kind>/", views.report_export),
    path("public/plans/", views.public_plans),
    path("reports/sales/", views.sales_report),
    path("customers/<int:pk>/overview/", views.customer_overview),
    path("customers/<int:pk>/assign_plan/", views.assign_plan),
    path("imports/sample/", views.import_sample),
    path("imports/subscribers/", views.import_subscribers),
]
