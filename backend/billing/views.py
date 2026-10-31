import logging
from datetime import timedelta
from decimal import Decimal

import stripe
from django.conf import settings
from django.db.models import Case, Count, DecimalField, ExpressionWrapper, F, Sum, Value, When
from django.db.models.functions import TruncMonth
from django.utils import timezone
from django.utils.dateparse import parse_date
from django_filters import rest_framework as filters
from rest_framework import mixins, serializers, viewsets
from rest_framework.decorators import action, api_view, authentication_classes, permission_classes
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from accounts.permissions import IsTeam
from catalog.models import Plan, money
from config.api import Conflict

from . import services
from .models import Invoice, Payment, Subscription
from .serializers import (
    FromTemplateSerializer,
    InvoiceDetailSerializer,
    InvoiceListSerializer,
    PaymentSerializer,
    SubscriptionDetailSerializer,
    SubscriptionListSerializer,
    SubscriptionWriteSerializer,
)

logger = logging.getLogger(__name__)
S = Subscription.State
I = Invoice.State


class SubscriptionFilter(filters.FilterSet):
    expiring_within = filters.NumberFilter(method="filter_expiring")

    class Meta:
        model = Subscription
        fields = ["state", "plan", "customer"]

    def filter_expiring(self, queryset, name, value):
        today = timezone.localdate()
        return queryset.filter(state=S.ACTIVE, expiry_date__range=(today, today + timedelta(days=int(value))))


class SubscriptionViewSet(viewsets.ModelViewSet):
    filterset_class = SubscriptionFilter
    search_fields = ["number", "customer__email", "customer__company", "customer__first_name", "plan__name"]
    ordering_fields = ["id", "number", "start_date", "expiry_date", "next_invoice_date", "recurring_total"]

    def get_queryset(self):
        qs = Subscription.objects.select_related("customer", "plan", "payment_term")
        if self.action != "list":
            qs = qs.prefetch_related("lines__taxes", "lines__product")
        user = self.request.user
        if not user.is_team:
            qs = qs.filter(customer=user).exclude(state=S.DRAFT)
        return qs

    def get_serializer_class(self):
        return SubscriptionListSerializer if self.action == "list" else SubscriptionDetailSerializer

    def _team_only(self):
        if not self.request.user.is_team:
            raise PermissionDenied("Only the Brightloop team can do this.")

    def _render(self, pk, code=200):
        sub = self.get_queryset().get(pk=pk)
        return Response(SubscriptionDetailSerializer(sub, context=self.get_serializer_context()).data, status=code)

    def create(self, request, *args, **kwargs):
        self._team_only()
        write = SubscriptionWriteSerializer(data=request.data)
        write.is_valid(raise_exception=True)
        data = dict(write.validated_data)
        rows = data.pop("lines", [])
        return self._render(services.save_subscription(data, rows).pk, 201)

    def update(self, request, *args, **kwargs):
        self._team_only()
        instance = self.get_object()
        write = SubscriptionWriteSerializer(instance, data=request.data, partial=kwargs.get("partial", False))
        write.is_valid(raise_exception=True)
        data = dict(write.validated_data)
        rows = data.pop("lines", None)
        return self._render(services.save_subscription(data, rows, instance).pk)

    def destroy(self, request, *args, **kwargs):
        self._team_only()
        instance = self.get_object()
        if instance.state != S.DRAFT:
            raise Conflict("Only draft subscriptions can be deleted.")
        instance.delete()
        return Response(status=204)

    @action(detail=False, methods=["post"])
    def from_template(self, request):
        self._team_only()
        form = FromTemplateSerializer(data=request.data)
        form.is_valid(raise_exception=True)
        return self._render(services.subscription_from_template(**form.validated_data).pk, 201)

    def _team_transition(self, func):
        self._team_only()
        func(self.get_object().pk)
        return self._render(self.kwargs["pk"])

    @action(detail=True, methods=["post"])
    def quote(self, request, pk=None):
        return self._team_transition(services.send_quotation)

    @action(detail=True, methods=["post"])
    def confirm(self, request, pk=None):
        return self._team_transition(services.confirm)

    @action(detail=True, methods=["post"])
    def activate(self, request, pk=None):
        return self._team_transition(services.activate)

    # Customers may run these on their own subscriptions. get_object() applies the ownership scope.
    def _owner_transition(self, func):
        func(self.get_object().pk)
        return self._render(self.kwargs["pk"])

    @action(detail=True, methods=["post"])
    def pause(self, request, pk=None):
        return self._owner_transition(services.pause)

    @action(detail=True, methods=["post"])
    def resume(self, request, pk=None):
        return self._owner_transition(services.resume)

    @action(detail=True, methods=["post"])
    def close(self, request, pk=None):
        return self._owner_transition(services.close)

    @action(detail=True, methods=["post"])
    def renew(self, request, pk=None):
        return self._owner_transition(services.renew)

    @action(detail=True, methods=["post"])
    def toggle_addon(self, request, pk=None):
        sub = self.get_object()
        services.toggle_addon(sub.pk, request.data.get("line"), request.data.get("enabled"))
        return self._render(sub.pk)

    @action(detail=True, methods=["post"])
    def generate_invoice(self, request, pk=None):
        self._team_only()
        created = services.bill_subscription(self.get_object().pk)
        return Response({"invoices_created": len(created), "invoices": [i.pk for i in created]})


class InvoiceFilter(filters.FilterSet):
    payment_status = filters.CharFilter(method="filter_payment")
    invoice_date_from = filters.DateFilter(field_name="invoice_date", lookup_expr="gte")
    invoice_date_to = filters.DateFilter(field_name="invoice_date", lookup_expr="lte")

    class Meta:
        model = Invoice
        fields = ["state", "customer", "subscription"]

    def filter_payment(self, queryset, name, value):
        if value == "paid":
            return queryset.filter(state=I.PAID)
        if value == "outstanding":
            return queryset.filter(state=I.CONFIRMED)
        if value == "overdue":
            return queryset.filter(state=I.CONFIRMED, due_date__lt=timezone.localdate())
        return queryset


class InvoiceViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    filterset_class = InvoiceFilter
    search_fields = ["number", "customer_name", "customer_email", "subscription__number"]
    ordering_fields = ["id", "number", "invoice_date", "due_date", "total"]

    def get_queryset(self):
        qs = Invoice.objects.select_related("subscription")
        if self.action != "list":
            qs = qs.prefetch_related("lines", "discounts", "payments__invoice")
        user = self.request.user
        if not user.is_team:
            qs = qs.filter(customer=user).exclude(state=I.DRAFT)
        return qs

    def get_serializer_class(self):
        return InvoiceListSerializer if self.action == "list" else InvoiceDetailSerializer

    def get_serializer_context(self):
        return {**super().get_serializer_context(), "today": timezone.localdate()}

    def _team_action(self, func, **kwargs):
        if not self.request.user.is_team:
            raise PermissionDenied("Only the Brightloop team can do this.")
        func(self.get_object().pk, **kwargs)
        invoice = self.get_queryset().get(pk=self.kwargs["pk"])
        return Response(InvoiceDetailSerializer(invoice, context=self.get_serializer_context()).data)

    @action(detail=True, methods=["post"])
    def confirm(self, request, pk=None):
        return self._team_action(services.confirm_invoice)

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        return self._team_action(services.cancel_invoice, rebill=bool(request.data.get("rebill")))

    @action(detail=True, methods=["post"])
    def send(self, request, pk=None):
        return self._team_action(services.send_invoice)

    # Customers pay their own invoices. get_object() applies the ownership scope.
    @action(detail=True, methods=["post"])
    def checkout(self, request, pk=None):
        return Response({"url": services.create_checkout(self.get_object())})

    @action(detail=True, methods=["post"])
    def checkout_complete(self, request, pk=None):
        invoice = self.get_object()
        services.confirm_checkout(str(request.data.get("session_id", "")), invoice.pk)
        fresh = self.get_queryset().get(pk=invoice.pk)
        return Response(InvoiceDetailSerializer(fresh, context=self.get_serializer_context()).data)

    @action(detail=False, methods=["post"], permission_classes=[IsTeam])
    def bulk(self, request):
        kind = request.data.get("action")
        func = {"confirm": services.confirm_invoice, "send": services.send_invoice}.get(kind)
        ids = request.data.get("ids") or []
        if func is None or not isinstance(ids, list) or not ids:
            raise serializers.ValidationError({"action": ["Choose confirm or send, and at least one invoice."]})
        done, failed = 0, []
        for pk in ids[:500]:
            try:
                func(pk)
                done += 1
            except Invoice.DoesNotExist:
                failed.append({"invoice": pk, "error": "Not found."})
            except Conflict as exc:
                failed.append({"invoice": pk, "error": str(exc.detail)})
        return Response({"done": done, "failed": failed})


class PaymentFilter(filters.FilterSet):
    date_from = filters.DateFilter(field_name="date", lookup_expr="gte")
    date_to = filters.DateFilter(field_name="date", lookup_expr="lte")

    class Meta:
        model = Payment
        fields = ["method", "invoice"]


class PaymentViewSet(mixins.ListModelMixin, mixins.CreateModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    permission_classes = [IsTeam]
    queryset = Payment.objects.select_related("invoice")
    serializer_class = PaymentSerializer
    filterset_class = PaymentFilter
    search_fields = ["invoice__number", "invoice__customer_name", "note"]
    ordering_fields = ["date", "amount"]

    def perform_create(self, serializer):
        data = serializer.validated_data
        serializer.instance = services.record_payment(
            data["invoice"].pk, data["method"], data["amount"], data["date"], data.get("note", ""), self.request.user
        )


@api_view(["POST"])
@permission_classes([IsTeam])
def billing_run(request):
    return Response(services.run_billing())


@api_view(["POST"])
@permission_classes([IsTeam])
def send_reminders(request):
    return Response(services.send_reminders())


@api_view(["POST"])
@authentication_classes([])
@permission_classes([AllowAny])
def stripe_webhook(request):
    """Records payments even if the customer never returns to the site. Trusts only a verified signature."""
    if not settings.STRIPE_WEBHOOK_SECRET:
        return Response(status=400)
    try:
        event = stripe.Webhook.construct_event(
            request.body, request.headers.get("Stripe-Signature", ""), settings.STRIPE_WEBHOOK_SECRET
        )
    except (ValueError, stripe.SignatureVerificationError):
        return Response(status=400)
    if event["type"] in ("checkout.session.completed", "checkout.session.async_payment_succeeded"):
        try:
            services.settle_checkout(event["data"]["object"].to_dict())
        except Conflict:
            logger.exception("Stripe webhook could not settle a payment")
    return Response({"received": True})


# How many times each billing period fits into one month, to express recurring revenue monthly.
MONTHLY_FACTOR = {
    Plan.Period.DAILY: Decimal("30"),
    Plan.Period.WEEKLY: Decimal("4.33"),
    Plan.Period.MONTHLY: Decimal("1"),
    Plan.Period.YEARLY: Decimal("0.0833"),
}


def _date_param(request, name):
    raw = request.query_params.get(name)
    if not raw:
        return None
    value = parse_date(raw)
    if value is None:
        raise serializers.ValidationError({name: ["Use the format YYYY-MM-DD."]})
    return value


@api_view(["GET"])
@permission_classes([IsTeam])
def report_summary(request):
    today = timezone.localdate()
    start, end = _date_param(request, "from"), _date_param(request, "to")
    money_field = DecimalField(max_digits=16, decimal_places=2)

    payments = Payment.objects.all()
    invoices = Invoice.objects.exclude(state__in=[I.DRAFT, I.CANCELLED])
    if start:
        payments, invoices = payments.filter(date__gte=start), invoices.filter(invoice_date__gte=start)
    if end:
        payments, invoices = payments.filter(date__lte=end), invoices.filter(invoice_date__lte=end)

    outstanding = invoices.filter(state=I.CONFIRMED).aggregate(
        count=Count("id"), amount=Sum(ExpressionWrapper(F("total") - F("amount_paid"), output_field=money_field))
    )
    overdue_qs = invoices.filter(state=I.CONFIRMED, due_date__lt=today)
    overdue = overdue_qs.aggregate(
        count=Count("id"), amount=Sum(ExpressionWrapper(F("total") - F("amount_paid"), output_field=money_field))
    )
    mrr = Subscription.objects.filter(state=S.ACTIVE).aggregate(
        value=Sum(
            Case(
                *[When(plan__billing_period=p, then=F("recurring_total") * Value(f)) for p, f in MONTHLY_FACTOR.items()],
                output_field=money_field,
            )
        )
    )["value"]
    window_start = start or today - timedelta(days=30)
    window_end = end or today
    churned = Subscription.objects.filter(state=S.CLOSED, closed_at__range=(window_start, window_end)).count()
    by_state = dict(Subscription.objects.order_by().values_list("state").annotate(n=Count("id")))
    by_method = payments.order_by().values("method").annotate(amount=Sum("amount"), count=Count("id")).order_by("-amount")
    monthly = (
        payments.order_by().annotate(month=TruncMonth("date")).values("month").annotate(amount=Sum("amount")).order_by("-month")[:12]
    )
    oldest = overdue_qs.order_by("due_date")[:10]

    return Response({
        "active_subscriptions": by_state.get(S.ACTIVE, 0),
        "subscriptions_by_state": by_state,
        "expiring_soon": Subscription.objects.filter(
            state=S.ACTIVE, expiry_date__range=(today, today + timedelta(days=30))
        ).count(),
        "monthly_recurring_revenue": money(mrr or 0),
        "annual_recurring_revenue": money((mrr or 0) * 12),
        "churned_subscriptions": churned,
        "churn_rate": round(100 * churned / max(by_state.get(S.ACTIVE, 0) + churned, 1), 1),
        "invoiced": invoices.aggregate(v=Sum("total"))["v"] or 0,
        "revenue_collected": payments.aggregate(v=Sum("amount"))["v"] or 0,
        "payments_count": payments.count(),
        "outstanding_count": outstanding["count"],
        "outstanding_amount": outstanding["amount"] or 0,
        "overdue_count": overdue["count"],
        "overdue_amount": overdue["amount"] or 0,
        "drafts_to_confirm": Invoice.objects.filter(state=I.DRAFT).count(),
        "due_for_billing": Subscription.objects.filter(state=S.ACTIVE, next_invoice_date__lte=today).count(),
        "payments_by_method": [
            {"method": Payment.Method(r["method"]).label, "amount": r["amount"], "count": r["count"]} for r in by_method
        ],
        "revenue_by_month": [{"month": r["month"].strftime("%b %Y"), "amount": r["amount"]} for r in monthly],
        "oldest_overdue": [
            {
                "id": i.pk, "number": i.number, "customer_name": i.customer_name, "due_date": i.due_date,
                "amount_due": i.amount_due,
            }
            for i in oldest
        ],
    })
