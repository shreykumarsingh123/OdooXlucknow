import csv
import logging
from datetime import timedelta
from decimal import Decimal

import stripe
from django.conf import settings
from django.db.models import Case, Count, DecimalField, ExpressionWrapper, F, Q, Sum, Value, When
from django.db.models.functions import TruncMonth
from django.http import StreamingHttpResponse
from django.utils import timezone
from django.utils.dateparse import parse_date
from django_filters import rest_framework as filters
from rest_framework import mixins, serializers, viewsets
from rest_framework.decorators import action, api_view, authentication_classes, permission_classes
from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle

from accounts.identity import customers_of
from accounts.models import User
from accounts.permissions import IsAdmin, IsBackOffice, IsTeam
from catalog.models import Plan, money
from config.api import Conflict

from . import imports, revenue, services
from .models import Invoice, Payment, PaymentRequest, SalesTarget, Subscription
from .serializers import (
    AdjustSerializer,
    FromTemplateSerializer,
    InvoiceDetailSerializer,
    InvoiceListSerializer,
    PaymentRequestInSerializer,
    PaymentRequestSerializer,
    PaymentSerializer,
    SalesTargetSerializer,
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
    throttle_scope = "auth"  # used only by actions that opt in to ScopedRateThrottle
    search_fields = ["number", "customer__email", "customer__company", "customer__first_name", "plan__name"]
    ordering_fields = ["id", "number", "start_date", "expiry_date", "next_invoice_date", "recurring_total"]

    def get_queryset(self):
        qs = Subscription.objects.select_related("customer", "plan", "payment_term")
        if self.action != "list":
            qs = qs.prefetch_related("lines__taxes", "lines__product")
        user = self.request.user
        if not user.is_team:
            return qs.filter(customer=user).exclude(state=S.DRAFT)
        qs = qs.filter(business_id=user.business_id)
        return qs.filter(salesperson=user) if user.is_sales else qs

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
        write = SubscriptionWriteSerializer(data=request.data, context=self.get_serializer_context())
        write.is_valid(raise_exception=True)
        data = dict(write.validated_data)
        rows = data.pop("lines", [])
        if request.user.is_sales:
            data["salesperson"] = request.user
        return self._render(services.save_subscription(data, rows).pk, 201)

    def update(self, request, *args, **kwargs):
        self._team_only()
        instance = self.get_object()
        write = SubscriptionWriteSerializer(instance, data=request.data, partial=kwargs.get("partial", False), context=self.get_serializer_context())
        write.is_valid(raise_exception=True)
        data = dict(write.validated_data)
        rows = data.pop("lines", None)
        if request.user.is_sales:
            data.pop("salesperson", None)
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
        form = FromTemplateSerializer(data=request.data, context=self.get_serializer_context())
        form.is_valid(raise_exception=True)
        salesperson = request.user if request.user.is_sales else None
        return self._render(services.subscription_from_template(**form.validated_data, salesperson=salesperson).pk, 201)

    def _team_transition(self, func, message):
        self._team_only()
        pk = self.get_object().pk
        func(pk)
        services.log_event(pk, message, self.request.user)
        return self._render(pk)

    @action(detail=True, methods=["post"])
    def quote(self, request, pk=None):
        return self._team_transition(services.send_quotation, "Quotation sent")

    @action(detail=True, methods=["post"])
    def confirm(self, request, pk=None):
        return self._team_transition(services.confirm, "Confirmed")

    @action(detail=True, methods=["post"])
    def activate(self, request, pk=None):
        return self._team_transition(services.activate, "Activated")

    # Customers may run these on their own subscriptions. get_object() applies the ownership scope.
    def _owner_transition(self, func, message):
        pk = self.get_object().pk
        func(pk)
        services.log_event(pk, message, self.request.user)
        return self._render(pk)

    @action(detail=True, methods=["post"])
    def pause(self, request, pk=None):
        return self._owner_transition(services.pause, "Paused")

    @action(detail=True, methods=["post"])
    def resume(self, request, pk=None):
        return self._owner_transition(services.resume, "Resumed")

    @action(detail=True, methods=["post"])
    def close(self, request, pk=None):
        reason, note = str(request.data.get("reason", "")), request.data.get("note", "")
        return self._owner_transition(lambda pk: services.close(pk, reason, note), "Closed" + (f": {Subscription.CloseReason(reason).label}" if reason in Subscription.CloseReason.values else ""))

    @action(detail=False, methods=["post"])
    def start(self, request):
        if request.user.is_team:
            raise PermissionDenied("Only customers can start a plan online.")
        return self._render(services.start_plan(request.user, request.data.get("plan"), request.user.business_id).pk, 201)

    @action(detail=True, methods=["post"])
    def change_plan(self, request, pk=None):
        sub = self.get_object()
        # A team-arranged or fixed-term plan is a commitment, so a customer cannot switch out of it.
        if not request.user.is_team and not (sub.plan.is_public and sub.plan.closable):
            raise PermissionDenied("Please contact Brightloop to change this plan.")
        plans = Plan.objects.filter(business_id=sub.business_id)
        if not request.user.is_team:
            plans = plans.filter(is_public=True)
        plan = plans.filter(pk=request.data.get("plan")).first() if str(request.data.get("plan", "")).isdigit() else None
        if plan is None:
            raise serializers.ValidationError({"plan": ["Choose a plan."]})
        services.change_plan(sub.pk, plan, request.user)
        return self._render(sub.pk)

    @action(detail=True, methods=["post"], throttle_classes=[ScopedRateThrottle])
    def redeem(self, request, pk=None):
        sub = self.get_object()
        services.redeem_code(sub.pk, request.data.get("code", ""), request.user)
        return self._render(sub.pk)

    @action(detail=True, methods=["post"])
    def adjust(self, request, pk=None):
        if not request.user.is_admin:
            raise PermissionDenied("Only the admin can do this.")
        form = AdjustSerializer(data=request.data)
        form.is_valid(raise_exception=True)
        sub = self.get_object()
        services.adjust_balance(sub.pk, actor=request.user, **form.validated_data)
        return self._render(sub.pk)

    @action(detail=True, methods=["post"])
    def renew(self, request, pk=None):
        return self._team_transition(services.renew, "Renewed by the team")

    # Opting out takes effect at expiry, so even a fixed-term plan can turn it off.
    @action(detail=True, methods=["post"])
    def auto_renew(self, request, pk=None):
        sub = self.get_object()
        services.set_auto_renew(sub.pk, request.data.get("enabled"), request.user)
        return self._render(sub.pk)

    @action(detail=True, methods=["post"])
    def toggle_addon(self, request, pk=None):
        sub = self.get_object()
        services.toggle_addon(sub.pk, request.data.get("line"), request.data.get("enabled"))
        return self._render(sub.pk)

    @action(detail=True, methods=["post"])
    def generate_invoice(self, request, pk=None):
        self._team_only()
        if request.user.is_sales:
            raise PermissionDenied("Only the billing team can do this.")
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
            return qs.filter(customer=user).exclude(state=I.DRAFT)
        qs = qs.filter(business_id=user.business_id)
        return qs.filter(subscription__salesperson=user) if user.is_sales else qs

    def get_serializer_class(self):
        return InvoiceListSerializer if self.action == "list" else InvoiceDetailSerializer

    def get_serializer_context(self):
        return {**super().get_serializer_context(), "today": timezone.localdate()}

    def _team_action(self, func, **kwargs):
        if not self.request.user.is_team or self.request.user.is_sales:
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

    @action(detail=True, methods=["post"])
    def request_payment(self, request, pk=None):
        invoice = self.get_object()
        if request.user.is_team:
            raise PermissionDenied("Record the payment on the invoice instead.")
        form = PaymentRequestInSerializer(data=request.data)
        form.is_valid(raise_exception=True)
        data = form.validated_data
        services.request_payment(invoice.pk, request.user, data["method"], data["amount"], data.get("reference", ""))
        fresh = self.get_queryset().get(pk=invoice.pk)
        return Response(InvoiceDetailSerializer(fresh, context=self.get_serializer_context()).data, status=201)

    @action(detail=True, methods=["get"], permission_classes=[IsTeam])
    def recognition(self, request, pk=None):
        return Response(revenue.invoice_schedule(self.get_object()))

    @action(detail=False, methods=["post"], permission_classes=[IsBackOffice])
    def bulk(self, request):
        kind = request.data.get("action")
        func = {"confirm": services.confirm_invoice, "send": services.send_invoice}.get(kind)
        ids = request.data.get("ids") or []
        if func is None or not isinstance(ids, list) or not ids:
            raise serializers.ValidationError({"action": ["Choose confirm or send, and at least one invoice."]})
        done, failed = 0, []
        mine = set(self.get_queryset().filter(pk__in=[pk for pk in ids[:500] if isinstance(pk, int)]).values_list("pk", flat=True))
        for pk in ids[:500]:
            try:
                if pk not in mine:
                    raise Invoice.DoesNotExist
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


class PaymentRequestViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    permission_classes = [IsAdmin]
    serializer_class = PaymentRequestSerializer
    filterset_fields = ["status"]

    def get_queryset(self):
        return PaymentRequest.objects.select_related("invoice", "customer").filter(invoice__business_id=self.request.user.business_id)

    def _decide(self, request, approve):
        row = services.decide_payment(self.get_object().pk, approve, request.data.get("note", ""), request.user)
        return Response(self.get_serializer(self.get_queryset().get(pk=row.pk)).data)

    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        return self._decide(request, True)

    @action(detail=True, methods=["post"])
    def reject(self, request, pk=None):
        return self._decide(request, False)


class SalesTargetViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAdmin]
    serializer_class = SalesTargetSerializer
    filterset_fields = ["salesperson", "month"]

    def get_queryset(self):
        return SalesTarget.objects.select_related("salesperson").filter(salesperson__business_id=self.request.user.business_id)


class PaymentViewSet(mixins.ListModelMixin, mixins.CreateModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    permission_classes = [IsBackOffice]
    serializer_class = PaymentSerializer
    filterset_class = PaymentFilter
    search_fields = ["invoice__number", "invoice__customer_name", "note"]
    ordering_fields = ["date", "amount"]

    def get_queryset(self):
        return Payment.objects.select_related("invoice").filter(business_id=self.request.user.business_id)

    def perform_create(self, serializer):
        data = serializer.validated_data
        serializer.instance = services.record_payment(
            data["invoice"].pk, data["method"], data["amount"], data["date"], data.get("note", ""), self.request.user
        )


@api_view(["POST"])
@permission_classes([IsBackOffice])
def billing_run(request):
    return Response(services.run_billing(business_id=request.user.business_id))


@api_view(["POST"])
@permission_classes([IsBackOffice])
def send_reminders(request):
    return Response(services.send_reminders(business_id=request.user.business_id))


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
@permission_classes([IsBackOffice])
def report_summary(request):
    today = timezone.localdate()
    start, end = _date_param(request, "from"), _date_param(request, "to")
    money_field = DecimalField(max_digits=16, decimal_places=2)
    business_id = request.user.business_id
    subscriptions = Subscription.objects.filter(business_id=business_id)

    payments = Payment.objects.filter(business_id=business_id)
    invoices = Invoice.objects.filter(business_id=business_id).exclude(state__in=[I.DRAFT, I.CANCELLED])
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
    monthly_value = Sum(
        Case(
            *[When(plan__billing_period=p, then=F("recurring_total") * Value(f)) for p, f in MONTHLY_FACTOR.items()],
            output_field=money_field,
        )
    )
    # Subscriptions still in a free trial pay nothing yet, so they are not recurring revenue.
    paying = subscriptions.filter(state=S.ACTIVE).filter(Q(trial_ends__isnull=True) | Q(trial_ends__lte=today))
    mrr = paying.aggregate(value=monthly_value)["value"]
    customers = paying.order_by().values("customer").distinct().count()
    by_plan = paying.order_by().values("plan__name").annotate(count=Count("id"), mrr=monthly_value).order_by("-mrr")[:8]
    due = ExpressionWrapper(F("total") - F("amount_paid"), output_field=money_field)
    aging = overdue_qs.aggregate(
        d30=Sum(due, filter=Q(due_date__gte=today - timedelta(days=30))),
        d60=Sum(due, filter=Q(due_date__lt=today - timedelta(days=30), due_date__gte=today - timedelta(days=60))),
        d90=Sum(due, filter=Q(due_date__lt=today - timedelta(days=60), due_date__gte=today - timedelta(days=90))),
        older=Sum(due, filter=Q(due_date__lt=today - timedelta(days=90))),
    )
    window_start = start or today - timedelta(days=30)
    window_end = end or today
    closed = subscriptions.filter(state=S.CLOSED, closed_at__range=(window_start, window_end))
    churned = closed.count()
    reasons = closed.order_by().values("close_reason").annotate(count=Count("id")).order_by("-count")
    by_state = dict(subscriptions.order_by().values_list("state").annotate(n=Count("id")))
    by_method = payments.order_by().values("method").annotate(amount=Sum("amount"), count=Count("id")).order_by("-amount")
    monthly = (
        payments.order_by().annotate(month=TruncMonth("date")).values("month").annotate(amount=Sum("amount")).order_by("-month")[:12]
    )
    oldest = overdue_qs.order_by("due_date")[:10]

    return Response({
        "active_subscriptions": by_state.get(S.ACTIVE, 0),
        "subscriptions_by_state": by_state,
        "expiring_soon": subscriptions.filter(
            state=S.ACTIVE, expiry_date__range=(today, today + timedelta(days=30))
        ).count(),
        "monthly_recurring_revenue": money(mrr or 0),
        "annual_recurring_revenue": money((mrr or 0) * 12),
        "average_revenue_per_customer": money((mrr or 0) / max(customers, 1)),
        "in_trial": subscriptions.filter(state=S.ACTIVE, trial_ends__gt=today).count(),
        "mrr_by_plan": [{"plan": r["plan__name"], "count": r["count"], "mrr": money(r["mrr"] or 0)} for r in by_plan],
        "overdue_aging": [
            {"bucket": name, "amount": aging[key] or 0}
            for name, key in [("1-30 days", "d30"), ("31-60 days", "d60"), ("61-90 days", "d90"), ("Over 90 days", "older")]
        ],
        "churn_reasons": [
            {
                "reason": Subscription.CloseReason(r["close_reason"]).label if r["close_reason"] else "Not given or ended on its own",
                "count": r["count"],
            }
            for r in reasons
        ],
        "churned_subscriptions": churned,
        "churn_rate": round(100 * churned / max(by_state.get(S.ACTIVE, 0) + churned, 1), 1),
        "invoiced": invoices.aggregate(v=Sum("total"))["v"] or 0,
        "revenue_collected": payments.aggregate(v=Sum("amount"))["v"] or 0,
        "payments_count": payments.count(),
        "outstanding_count": outstanding["count"],
        "outstanding_amount": outstanding["amount"] or 0,
        "overdue_count": overdue["count"],
        "overdue_amount": overdue["amount"] or 0,
        "drafts_to_confirm": Invoice.objects.filter(business_id=business_id, state=I.DRAFT).count(),
        "payment_requests_pending": PaymentRequest.objects.filter(invoice__business_id=business_id, status=PaymentRequest.Status.PENDING).count(),
        "due_for_billing": subscriptions.filter(state=S.ACTIVE, next_invoice_date__lte=today).count(),
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


def _revenue_params(request):
    start, end = _date_param(request, "from"), _date_param(request, "to")
    if start and end and start > end:
        raise serializers.ValidationError({"to": ["The end month cannot be before the start month."]})
    if start and end and (end.year - start.year) * 12 + end.month - start.month > 60:
        raise serializers.ValidationError({"to": ["Choose at most five years."]})
    plan = request.query_params.get("plan") or None
    if plan and not plan.isdigit():
        raise serializers.ValidationError({"plan": ["Choose a plan."]})
    period = request.query_params.get("period") or None
    if period and period not in Plan.Period.values:
        raise serializers.ValidationError({"period": ["Choose a billing period."]})
    return {"start": start, "end": end, "plan": plan, "period": period}


@api_view(["GET"])
@permission_classes([IsBackOffice])
def revenue_summary(request):
    return Response(revenue.revenue_report(request.user.business_id, **_revenue_params(request)))


class _Echo:
    def write(self, value):
        return value


def _csv_safe(value):
    """A cell starting with one of these runs as a formula in a spreadsheet. Names come from customers."""
    text = "" if value is None else str(value)
    return f"'{text}" if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text


EXPORTS = {
    "subscriptions": (
        lambda: Subscription.objects.select_related("customer", "plan"), "start_date",
        ["Number", "Customer", "Plan", "Stage", "Start", "Expiry", "Per period", "Close reason"],
        lambda s: [s.number, s.customer.display_name, s.plan.name, s.get_state_display(), s.start_date, s.expiry_date, s.recurring_total, s.get_close_reason_display()],
    ),
    "invoices": (
        lambda: Invoice.objects.all(), "invoice_date",
        ["Number", "Customer", "Email", "Status", "Date", "Due", "Subtotal", "Discount", "Tax", "Credit", "Total", "Paid"],
        lambda i: [i.number, i.customer_name, i.customer_email, i.get_state_display(), i.invoice_date, i.due_date, i.subtotal, i.discount_total, i.tax_total, i.credit_applied, i.total, i.amount_paid],
    ),
    "payments": (
        lambda: Payment.objects.select_related("invoice"), "date",
        ["Date", "Invoice", "Customer", "Method", "Amount", "Note"],
        lambda p: [p.date, p.invoice.number, p.invoice.customer_name, p.get_method_display(), p.amount, p.note],
    ),
}


@api_view(["GET"])
@permission_classes([IsBackOffice])
def report_export(request, kind):
    if kind == "revenue":
        history = revenue.revenue_report(request.user.business_id, **_revenue_params(request))["history"]
        out = csv.writer(_Echo())
        lines = [out.writerow(["Month", "Status", "Recognized", "Scheduled", "Billed before tax", "Collected with tax", "Deferred at month end"])]
        lines += [out.writerow([r["month"][:7], r["status"], r["recognized"], r["scheduled"], r["billed"], r["collected"], r["deferred_end"]]) for r in history]
        response = StreamingHttpResponse(lines, content_type="text/csv")
        response["Content-Disposition"] = 'attachment; filename="brightloop-revenue.csv"'
        return response
    if kind not in EXPORTS:
        raise serializers.ValidationError({"kind": ["Choose subscriptions, invoices or payments."]})
    queryset, date_field, header, row = EXPORTS[kind]
    rows = queryset().filter(business_id=request.user.business_id)
    start, end = _date_param(request, "from"), _date_param(request, "to")
    if start:
        rows = rows.filter(**{f"{date_field}__gte": start})
    if end:
        rows = rows.filter(**{f"{date_field}__lte": end})
    writer = csv.writer(_Echo())

    def stream():
        yield writer.writerow(header)
        for item in rows.iterator(chunk_size=1000):
            yield writer.writerow([_csv_safe(cell) for cell in row(item)])

    response = StreamingHttpResponse(stream(), content_type="text/csv")
    response["Content-Disposition"] = f'attachment; filename="brightloop-{kind}.csv"'
    return response


def _monthly_value():
    return Sum(
        Case(
            *[When(plan__billing_period=p, then=F("recurring_total") * Value(f)) for p, f in MONTHLY_FACTOR.items()],
            output_field=DecimalField(max_digits=16, decimal_places=2),
        )
    )


def _sales_figures(person, today):
    """New monthly recurring revenue sold this month and in earlier months, against the admin's targets."""
    month = today.replace(day=1)
    sold = Subscription.objects.filter(salesperson=person).exclude(activated_on=None)
    months = [revenue.month_start(month - timedelta(days=30 * back)) for back in range(5, -1, -1)]
    by_month = {
        row["m"].replace(day=1): row
        for row in sold.filter(activated_on__gte=months[0]).order_by().annotate(m=TruncMonth("activated_on")).values("m").annotate(value=_monthly_value(), count=Count("id"))
    }
    targets = dict(SalesTarget.objects.filter(salesperson=person, month__gte=months[0]).values_list("month", "amount"))
    target = targets.get(month, Decimal("0"))
    current = by_month.get(month, {})
    value = current.get("value") or Decimal("0")
    won = sold.count()
    quotes = Subscription.objects.filter(salesperson=person, state__in=[S.QUOTATION, S.CONFIRMED]).count()
    return {
        "id": person.pk,
        "name": person.display_name,
        "target": target,
        "sold": money(value),
        "progress": round(100 * value / target, 1) if target else None,
        "new_subscriptions": current.get("count", 0),
        "active": sold.filter(state=S.ACTIVE).count(),
        "lost": sold.filter(state=S.CLOSED).count(),
        "open_quotes": quotes,
        "total_won": won,
        "conversion": round(100 * won / (won + quotes), 1) if won + quotes else None,
        "active_value": money(sold.filter(state=S.ACTIVE).aggregate(v=_monthly_value())["v"] or 0),
        "history": [
            {"month": m.isoformat(), "sold": money((by_month.get(m) or {}).get("value") or 0), "target": targets.get(m, Decimal("0"))}
            for m in months
        ],
    }


@api_view(["GET"])
@permission_classes([IsTeam])
def sales_report(request):
    user = request.user
    today = timezone.localdate()
    if user.is_support:
        raise PermissionDenied("Sales figures are for the sales team and the back office.")
    if user.is_sales:
        person = user
    elif request.query_params.get("salesperson"):
        person = User.objects.filter(pk=request.query_params["salesperson"] if request.query_params["salesperson"].isdigit() else None, business_id=user.business_id, role=User.Role.STAFF, department=User.Department.SALES).first()
        if person is None:
            raise serializers.ValidationError({"salesperson": ["Choose a salesperson."]})
    else:
        team = User.objects.filter(business_id=user.business_id, role=User.Role.STAFF, department=User.Department.SALES, is_active=True)
        return Response({"team": [_sales_figures(person, today) for person in team]})
    sold = Subscription.objects.filter(salesperson=person).select_related("customer", "plan").order_by("-activated_on", "-id")[:100]
    return Response({
        **_sales_figures(person, today),
        "customers": [
            {
                "id": s.pk, "number": s.number, "customer_name": s.customer.display_name, "plan_name": s.plan.name, "state": s.state,
                "activated_on": s.activated_on, "recurring_total": s.recurring_total, "billing_period": s.plan.billing_period,
            }
            for s in sold
        ],
    })


@api_view(["GET"])
@permission_classes([IsTeam])
def customer_overview(request, pk):
    if request.user.is_sales:
        raise PermissionDenied("Open the customer from your sales page.")
    me = request.user
    customer = customers_of(me.business_id, me.is_platform).filter(pk=pk).first()
    if customer is None:
        raise NotFound()
    subs = Subscription.objects.filter(customer=customer, business_id=me.business_id).select_related("plan").order_by("-id")
    invoices = Invoice.objects.filter(customer=customer, business_id=me.business_id).exclude(state__in=[I.DRAFT, I.CANCELLED])
    totals = invoices.aggregate(billed=Sum("total"), paid=Sum("amount_paid"))
    overdue = invoices.filter(state=I.CONFIRMED, due_date__lt=timezone.localdate()).count()
    running = [s for s in subs if s.state in (S.ACTIVE, S.PAUSED)]
    return Response({
        "id": customer.pk, "name": customer.display_name, "email": customer.email, "company": customer.company,
        "phone": customer.phone, "address": customer.address, "is_active": customer.is_active, "joined": customer.date_joined,
        "status": "active" if running else "no_active_plan",
        "billed": totals["billed"] or 0, "paid": totals["paid"] or 0, "owed": (totals["billed"] or 0) - (totals["paid"] or 0),
        "overdue_invoices": overdue,
        "credit": sum((s.credit_balance for s in subs), Decimal("0")),
        "subscriptions": [
            {
                "id": s.pk, "number": s.number, "plan_name": s.plan.name, "billing_period": s.plan.billing_period, "state": s.state,
                "expiry_date": s.expiry_date, "recurring_total": s.recurring_total, "trial_ends": s.trial_ends, "auto_renew": s.auto_renew,
            }
            for s in subs
        ],
        "open_tickets": list(customer.tickets.exclude(status="resolved").values("id", "number", "subject", "status")[:20]),
    })


@api_view(["POST"])
@permission_classes([IsAdmin])
def assign_plan(request, pk):
    me = request.user
    customer = customers_of(me.business_id, me.is_platform).filter(pk=pk).first()
    if customer is None:
        raise NotFound()
    raw = str(request.data.get("plan", ""))
    plan = Plan.objects.filter(pk=raw, business_id=me.business_id).first() if raw.isdigit() else None
    if plan is None:
        raise serializers.ValidationError({"plan": ["Choose a plan."]})
    replace = str(request.data.get("replace") or "")
    if replace and not replace.isdigit():
        raise serializers.ValidationError({"replace": ["Choose a subscription."]})
    sub = services.assign_plan(customer, plan, request.user, replace or None)
    return Response({"id": sub.pk, "number": sub.number}, status=201)


@api_view(["GET"])
@permission_classes([IsBackOffice])
def import_sample(request):
    return Response({"csv": imports.sample_csv(request.user.business_id), "columns": imports.COLUMNS})


@api_view(["POST"])
@permission_classes([IsBackOffice])
def import_subscribers(request):
    result = imports.run_import(request.data.get("csv", ""), request.data.get("commit") is True, request.user)
    if "error" in result:
        raise serializers.ValidationError({"csv": [result["error"]]})
    return Response(result)
