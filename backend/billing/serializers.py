from decimal import Decimal

from django.conf import settings
from rest_framework import serializers

from accounts.models import User
from catalog.models import PaymentTerm, Product, ProductVariant, QuotationTemplate, Tax

from .models import Invoice, InvoiceDiscount, InvoiceLine, Payment, Subscription, SubscriptionEvent, SubscriptionLine

S = Subscription.State
I = Invoice.State


def subscription_actions(sub, user):
    plan = sub.plan
    actions = []
    if user.is_team:
        if sub.state == S.DRAFT:
            actions += ["edit", "quote", "delete"]
        elif sub.state == S.QUOTATION:
            actions += ["edit", "confirm"]
        elif sub.state == S.CONFIRMED:
            actions.append("activate")
    if sub.state == S.ACTIVE:
        actions.append("change_plan")
        if plan.pausable:
            actions.append("pause")
        if plan.renewable:
            actions.append("renew")
    if sub.state == S.PAUSED:
        actions.append("resume")
    if sub.state in (S.ACTIVE, S.PAUSED):
        actions.append("redeem")
        if user.is_admin:
            actions.append("adjust")
        if plan.closable:
            actions.append("close")
    return actions


def invoice_actions(invoice, user):
    actions = ["print"]
    if user.is_team:
        if invoice.state == I.DRAFT:
            actions.append("confirm")
        if invoice.state in (I.CONFIRMED, I.PAID):
            actions.append("send")
        if invoice.state == I.CONFIRMED:
            actions.append("pay")
        if invoice.state in (I.DRAFT, I.CONFIRMED) and invoice.amount_paid == 0:
            actions.append("cancel")
    elif invoice.state == I.CONFIRMED and settings.STRIPE_SECRET_KEY:
        actions.append("pay_online")
    return actions


class SubscriptionListSerializer(serializers.ModelSerializer):
    customer_name = serializers.CharField(source="customer.display_name", read_only=True)
    plan_name = serializers.CharField(source="plan.name", read_only=True)

    class Meta:
        model = Subscription
        fields = [
            "id", "number", "customer", "customer_name", "plan", "plan_name", "start_date", "expiry_date",
            "state", "next_invoice_date", "recurring_total", "trial_ends",
        ]


class LineInSerializer(serializers.Serializer):
    product = serializers.PrimaryKeyRelatedField(queryset=Product.objects.filter(is_active=True))
    variant = serializers.PrimaryKeyRelatedField(queryset=ProductVariant.objects.all(), required=False, allow_null=True)
    quantity = serializers.IntegerField(min_value=1)
    unit_price = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=0, required=False, allow_null=True)
    taxes = serializers.PrimaryKeyRelatedField(queryset=Tax.objects.filter(is_active=True), many=True, required=False)

    def validate(self, attrs):
        variant = attrs.get("variant")
        if variant and variant.product_id != attrs["product"].pk:
            raise serializers.ValidationError({"variant": ["This variant belongs to another product."]})
        return attrs


class LineOutSerializer(serializers.ModelSerializer):
    taxes = serializers.SlugRelatedField(slug_field="name", many=True, read_only=True)
    tax_ids = serializers.PrimaryKeyRelatedField(source="taxes", many=True, read_only=True)
    amount = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)
    is_addon = serializers.SerializerMethodField()

    class Meta:
        model = SubscriptionLine
        fields = [
            "id", "product", "variant", "description", "quantity", "unit_price", "taxes", "tax_ids", "amount",
            "is_enabled", "is_plan_fee", "is_addon",
        ]

    def get_is_addon(self, line):
        return bool(line.product_id and line.product.type == "addon")


class EventSerializer(serializers.ModelSerializer):
    actor_name = serializers.SerializerMethodField()

    class Meta:
        model = SubscriptionEvent
        fields = ["id", "message", "actor_name", "created_at"]

    def get_actor_name(self, event):
        return event.actor.display_name if event.actor else "Brightloop"


class SubscriptionDetailSerializer(serializers.ModelSerializer):
    customer_name = serializers.CharField(source="customer.display_name", read_only=True)
    plan_name = serializers.CharField(source="plan.name", read_only=True)
    billing_period = serializers.CharField(source="plan.billing_period", read_only=True)
    payment_term_name = serializers.CharField(source="payment_term.name", read_only=True)
    lines = LineOutSerializer(many=True, read_only=True)
    allowed_actions = serializers.SerializerMethodField()
    promotions = serializers.SlugRelatedField(source="discounts", slug_field="name", many=True, read_only=True)
    events = serializers.SerializerMethodField()

    class Meta:
        model = Subscription
        fields = [
            "id", "number", "customer", "customer_name", "plan", "plan_name", "billing_period", "payment_term",
            "payment_term_name", "start_date", "expiry_date", "state", "quotation_valid_until", "next_invoice_date",
            "recurring_total", "closed_at", "close_reason", "trial_ends", "credit_balance", "promotions", "events", "lines", "allowed_actions",
        ]

    def get_allowed_actions(self, sub):
        return subscription_actions(sub, self.context["request"].user)

    def get_events(self, sub):
        return EventSerializer(sub.events.select_related("actor")[:30], many=True).data


class AdjustSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(choices=["credit", "charge"])
    amount = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal("0.01"))
    note = serializers.CharField(max_length=200)


class SubscriptionWriteSerializer(serializers.ModelSerializer):
    customer = serializers.PrimaryKeyRelatedField(queryset=User.objects.filter(role=User.Role.CUSTOMER, is_active=True))
    lines = LineInSerializer(many=True, required=False)

    class Meta:
        model = Subscription
        fields = ["customer", "plan", "payment_term", "start_date", "expiry_date", "lines"]


class FromTemplateSerializer(serializers.Serializer):
    template = serializers.PrimaryKeyRelatedField(queryset=QuotationTemplate.objects.filter(is_active=True))
    customer = serializers.PrimaryKeyRelatedField(queryset=User.objects.filter(role=User.Role.CUSTOMER, is_active=True))
    payment_term = serializers.PrimaryKeyRelatedField(queryset=PaymentTerm.objects.filter(is_active=True))
    start_date = serializers.DateField()
    expiry_date = serializers.DateField()


class InvoiceListSerializer(serializers.ModelSerializer):
    amount_due = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)
    subscription_number = serializers.CharField(source="subscription.number", read_only=True)
    is_overdue = serializers.SerializerMethodField()

    class Meta:
        model = Invoice
        fields = [
            "id", "number", "subscription", "subscription_number", "customer", "customer_name", "state", "invoice_date",
            "due_date", "total", "amount_paid", "amount_due", "is_overdue", "sent_at",
        ]

    def get_is_overdue(self, invoice):
        return invoice.state == I.CONFIRMED and invoice.due_date < self.context["today"]


class InvoiceLineSerializer(serializers.ModelSerializer):
    class Meta:
        model = InvoiceLine
        fields = ["id", "description", "quantity", "unit_price", "discount_amount", "tax_names", "tax_amount", "amount"]


class InvoiceDiscountSerializer(serializers.ModelSerializer):
    class Meta:
        model = InvoiceDiscount
        fields = ["name", "amount"]


class PaymentSerializer(serializers.ModelSerializer):
    invoice_number = serializers.CharField(source="invoice.number", read_only=True)
    customer_name = serializers.CharField(source="invoice.customer_name", read_only=True)

    class Meta:
        model = Payment
        fields = ["id", "invoice", "invoice_number", "customer_name", "method", "amount", "date", "note", "created_at"]
        read_only_fields = ["created_at"]
        extra_kwargs = {"amount": {"min_value": Decimal("0.01")}}


class InvoiceDetailSerializer(InvoiceListSerializer):
    lines = InvoiceLineSerializer(many=True, read_only=True)
    discounts = InvoiceDiscountSerializer(many=True, read_only=True)
    payments = PaymentSerializer(many=True, read_only=True)
    allowed_actions = serializers.SerializerMethodField()

    class Meta(InvoiceListSerializer.Meta):
        fields = InvoiceListSerializer.Meta.fields + [
            "reminder_count", "last_reminder_at", "customer_email", "customer_address", "period_start", "period_end", "subtotal", "discount_total", "tax_total", "credit_applied", "is_adjustment",
            "lines", "discounts", "payments", "allowed_actions",
        ]

    def get_allowed_actions(self, invoice):
        return invoice_actions(invoice, self.context["request"].user)
