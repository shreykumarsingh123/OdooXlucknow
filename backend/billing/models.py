from django.conf import settings
from django.db import models

from catalog.models import PaymentTerm, Plan, Product, ProductVariant, Tax


class Subscription(models.Model):
    class State(models.TextChoices):
        DRAFT = "draft", "Draft"
        QUOTATION = "quotation", "Quotation"
        CONFIRMED = "confirmed", "Confirmed"
        ACTIVE = "active", "Active"
        PAUSED = "paused", "Paused"
        CLOSED = "closed", "Closed"

    class CloseReason(models.TextChoices):
        TOO_EXPENSIVE = "too_expensive", "Too expensive"
        MISSING_FEATURES = "missing_features", "Missing features"
        NOT_USING = "not_using", "Not using it enough"
        SWITCHED = "switched", "Switched to another product"
        OTHER = "other", "Something else"

    number = models.CharField(max_length=20, unique=True, null=True, editable=False)
    customer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="subscriptions")
    plan = models.ForeignKey(Plan, on_delete=models.PROTECT, related_name="subscriptions")
    payment_term = models.ForeignKey(PaymentTerm, on_delete=models.PROTECT)
    start_date = models.DateField()
    expiry_date = models.DateField()
    state = models.CharField(max_length=10, choices=State.choices, default=State.DRAFT)
    quotation_valid_until = models.DateField(null=True, blank=True)
    next_invoice_date = models.DateField(null=True, blank=True)
    # Stored so that lists and reports need no per-row line queries.
    recurring_total = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    closed_at = models.DateField(null=True, blank=True)
    close_reason = models.CharField(max_length=20, choices=CloseReason.choices, blank=True)
    close_note = models.CharField(max_length=255, blank=True)
    trial_ends = models.DateField(null=True, blank=True)
    # The plan the free trial was given on. Kept after a plan change, so that trial cannot be taken again.
    trial_plan = models.ForeignKey(Plan, on_delete=models.PROTECT, null=True, blank=True, related_name="+")
    # Owed to the customer, for example after a downgrade. Taken off the next invoices.
    credit_balance = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-id"]
        indexes = [
            models.Index(fields=["state", "next_invoice_date"]),
            models.Index(fields=["state", "expiry_date"]),
            models.Index(fields=["customer", "state"]),
        ]
        constraints = [
            models.CheckConstraint(condition=models.Q(expiry_date__gte=models.F("start_date")), name="sub_dates_ordered")
        ]

    @property
    def billing_anchor(self):
        """The day of the month invoices fall on. A trial moves it to the day the trial ends."""
        return self.trial_ends or self.start_date

    def __str__(self):
        return self.number or f"Subscription {self.pk}"


class SubscriptionEvent(models.Model):
    subscription = models.ForeignKey(Subscription, on_delete=models.CASCADE, related_name="events")
    message = models.CharField(max_length=255)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-id"]


class SubscriptionLine(models.Model):
    subscription = models.ForeignKey(Subscription, on_delete=models.CASCADE, related_name="lines")
    product = models.ForeignKey(Product, on_delete=models.PROTECT, null=True, blank=True)  # empty for the plan fee line
    variant = models.ForeignKey(ProductVariant, on_delete=models.PROTECT, null=True, blank=True)
    description = models.CharField(max_length=255)
    quantity = models.PositiveIntegerField(default=1)
    unit_price = models.DecimalField(max_digits=12, decimal_places=2)
    taxes = models.ManyToManyField(Tax, blank=True)
    is_enabled = models.BooleanField(default=True)
    # Switched on since the last invoice, so it is billed even if switched off again before billing day.
    billable_pending = models.BooleanField(default=False)

    class Meta:
        ordering = ["id"]

    @property
    def is_plan_fee(self):
        return self.product_id is None

    @property
    def amount(self):
        return self.quantity * self.unit_price


class Invoice(models.Model):
    class State(models.TextChoices):
        DRAFT = "draft", "Draft"
        CONFIRMED = "confirmed", "Confirmed"
        PAID = "paid", "Paid"
        CANCELLED = "cancelled", "Cancelled"

    number = models.CharField(max_length=20, unique=True, null=True, editable=False)
    subscription = models.ForeignKey(Subscription, on_delete=models.PROTECT, related_name="invoices")
    customer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="invoices")
    customer_name = models.CharField(max_length=200)
    customer_email = models.EmailField()
    customer_address = models.TextField(blank=True)
    state = models.CharField(max_length=10, choices=State.choices, default=State.DRAFT)
    invoice_date = models.DateField()
    due_date = models.DateField()
    period_start = models.DateField()
    period_end = models.DateField()
    # NULL once cancelled for rebilling. This unique index is what makes double billing impossible.
    billing_key = models.CharField(max_length=40, unique=True, null=True, editable=False)
    subtotal = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    discount_total = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    tax_total = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    credit_applied = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    total = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    # A one-off charge, such as a prorated upgrade, outside the regular billing periods.
    is_adjustment = models.BooleanField(default=False)
    amount_paid = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    sent_at = models.DateTimeField(null=True, blank=True)
    reminder_count = models.PositiveSmallIntegerField(default=0)
    last_reminder_at = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-id"]
        indexes = [
            models.Index(fields=["state", "due_date"]),
            models.Index(fields=["state", "invoice_date"]),
            models.Index(fields=["customer", "state"]),
        ]

    @property
    def amount_due(self):
        return self.total - self.amount_paid

    def __str__(self):
        return self.number or f"Invoice {self.pk}"


class InvoiceLine(models.Model):
    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name="lines")
    description = models.CharField(max_length=255)
    quantity = models.PositiveIntegerField()
    unit_price = models.DecimalField(max_digits=12, decimal_places=2)
    discount_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    tax_names = models.CharField(max_length=255, blank=True)
    tax_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    amount = models.DecimalField(max_digits=14, decimal_places=2)

    class Meta:
        ordering = ["id"]


class InvoiceDiscount(models.Model):
    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name="discounts")
    discount = models.ForeignKey("catalog.Discount", on_delete=models.PROTECT)
    name = models.CharField(max_length=120)
    amount = models.DecimalField(max_digits=14, decimal_places=2)


class Payment(models.Model):
    class Method(models.TextChoices):
        BANK_TRANSFER = "bank_transfer", "Bank transfer"
        CARD = "card", "Card"
        UPI = "upi", "UPI"
        CASH = "cash", "Cash"
        CHEQUE = "cheque", "Cheque"
        ONLINE = "online", "Online (Stripe)"

    invoice = models.ForeignKey(Invoice, on_delete=models.PROTECT, related_name="payments")
    method = models.CharField(max_length=15, choices=Method.choices)
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    date = models.DateField()
    note = models.CharField(max_length=255, blank=True)
    # Stripe Checkout session id. Unique, so one online payment can never be recorded twice.
    reference = models.CharField(max_length=255, unique=True, null=True, blank=True, editable=False)
    recorded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date", "-id"]
        indexes = [models.Index(fields=["date", "method"])]
        constraints = [models.CheckConstraint(condition=models.Q(amount__gt=0), name="payment_positive")]
