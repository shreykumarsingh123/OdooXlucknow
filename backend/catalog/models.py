from decimal import ROUND_HALF_UP, Decimal

from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone

CENT = Decimal("0.01")
NON_NEGATIVE = [MinValueValidator(Decimal("0"))]


def money(value):
    return Decimal(value).quantize(CENT, rounding=ROUND_HALF_UP)


class Tax(models.Model):
    class Computation(models.TextChoices):
        PERCENT = "percent", "Percentage"
        FIXED = "fixed", "Fixed per unit"

    name = models.CharField(max_length=80, unique=True)
    computation = models.CharField(max_length=10, choices=Computation.choices, default=Computation.PERCENT)
    rate = models.DecimalField(max_digits=10, decimal_places=2, validators=NON_NEGATIVE)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]
        verbose_name_plural = "taxes"

    def compute(self, base, quantity):
        if self.computation == self.Computation.PERCENT:
            return money(base * self.rate / 100)
        return money(self.rate * quantity)

    def __str__(self):
        return self.name


class PaymentTerm(models.Model):
    name = models.CharField(max_length=80, unique=True)
    due_days = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["due_days"]

    def __str__(self):
        return self.name


class Product(models.Model):
    class Type(models.TextChoices):
        SOFTWARE = "software", "Software"
        ADDON = "addon", "Add-on"
        SERVICE = "service", "Service"

    name = models.CharField(max_length=150, unique=True)
    type = models.CharField(max_length=10, choices=Type.choices, default=Type.SOFTWARE, db_index=True)
    sales_price = models.DecimalField(max_digits=12, decimal_places=2, validators=NON_NEGATIVE)
    cost_price = models.DecimalField(max_digits=12, decimal_places=2, default=0, validators=NON_NEGATIVE)
    notes = models.TextField(blank=True)
    taxes = models.ManyToManyField(Tax, blank=True, related_name="products")
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class ProductVariant(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="variants")
    attribute = models.CharField(max_length=60, default="Brand")
    value = models.CharField(max_length=80)
    extra_price = models.DecimalField(max_digits=12, decimal_places=2, default=0, validators=NON_NEGATIVE)

    class Meta:
        ordering = ["attribute", "value"]
        constraints = [models.UniqueConstraint(fields=["product", "attribute", "value"], name="uniq_variant")]

    def __str__(self):
        return f"{self.attribute}: {self.value}"


class Plan(models.Model):
    class Period(models.TextChoices):
        DAILY = "daily", "Daily"
        WEEKLY = "weekly", "Weekly"
        MONTHLY = "monthly", "Monthly"
        YEARLY = "yearly", "Yearly"

    name = models.CharField(max_length=150, unique=True)
    price = models.DecimalField(max_digits=12, decimal_places=2, default=0, validators=NON_NEGATIVE)
    billing_period = models.CharField(max_length=10, choices=Period.choices, default=Period.MONTHLY, db_index=True)
    min_quantity = models.PositiveIntegerField(default=1)
    start_date = models.DateField()
    end_date = models.DateField(null=True, blank=True)
    taxes = models.ManyToManyField(Tax, blank=True, related_name="plans")
    auto_close = models.BooleanField(default=False, help_text="Close subscriptions on their own when they end.")
    closable = models.BooleanField(default=True, help_text="Can be closed early.")
    pausable = models.BooleanField(default=False, help_text="Can be paused.")
    renewable = models.BooleanField(default=True, help_text="Can be renewed.")
    trial_days = models.PositiveIntegerField(default=0, help_text="Free days before the first invoice.")
    is_public = models.BooleanField(default=False, help_text="Shown on the pricing page and in the customer portal.")
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(end_date__isnull=True) | models.Q(end_date__gte=models.F("start_date")),
                name="plan_dates_ordered",
            )
        ]

    def available_on(self, day):
        return self.is_active and self.start_date <= day and (self.end_date is None or day <= self.end_date)

    def __str__(self):
        return self.name


class Discount(models.Model):
    class Kind(models.TextChoices):
        FIXED = "fixed", "Fixed amount"
        PERCENT = "percent", "Percentage"

    class Scope(models.TextChoices):
        PRODUCTS = "products", "Specific products"
        SUBSCRIPTIONS = "subscriptions", "Whole subscriptions"

    class Reward(models.TextChoices):
        DISCOUNT = "discount", "Discount on invoices"
        CREDIT = "credit", "Money added to the account"
        FREE_DAYS = "free_days", "Free days before the next invoice"
        PERK = "perk", "Other perk"

    name = models.CharField(max_length=120, unique=True)
    kind = models.CharField(max_length=10, choices=Kind.choices, default=Kind.PERCENT)
    value = models.DecimalField(max_digits=12, decimal_places=2, default=0, validators=NON_NEGATIVE)
    reward = models.CharField(max_length=10, choices=Reward.choices, default=Reward.DISCOUNT)
    perk_text = models.CharField(max_length=200, blank=True)
    scope = models.CharField(max_length=15, choices=Scope.choices, default=Scope.PRODUCTS)
    min_purchase = models.DecimalField(max_digits=12, decimal_places=2, default=0, validators=NON_NEGATIVE)
    min_quantity = models.PositiveIntegerField(default=0)
    start_date = models.DateField()
    end_date = models.DateField(null=True, blank=True)
    usage_limit = models.PositiveIntegerField(null=True, blank=True, help_text="Leave empty for no limit.")
    # A discount with a code applies only to subscriptions that have redeemed it.
    code = models.CharField(max_length=40, unique=True, null=True, blank=True)
    times_used = models.PositiveIntegerField(default=0, editable=False)
    products = models.ManyToManyField(Product, blank=True, related_name="discounts")
    subscriptions = models.ManyToManyField("billing.Subscription", blank=True, related_name="discounts")
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["-start_date", "name"]
        indexes = [models.Index(fields=["is_active", "start_date", "end_date"])]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(end_date__isnull=True) | models.Q(end_date__gte=models.F("start_date")),
                name="discount_dates_ordered",
            )
        ]

    def is_live(self, day=None):
        day = day or timezone.localdate()
        if not self.is_active or day < self.start_date or (self.end_date and day > self.end_date):
            return False
        return self.usage_limit is None or self.times_used < self.usage_limit

    def compute(self, base):
        if self.kind == self.Kind.PERCENT:
            return min(base, money(base * self.value / 100))
        return min(base, money(self.value))

    def __str__(self):
        return self.name


class QuotationTemplate(models.Model):
    name = models.CharField(max_length=150, unique=True)
    plan = models.ForeignKey(Plan, on_delete=models.PROTECT, related_name="templates")
    validity_days = models.PositiveIntegerField(default=30)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class QuotationTemplateLine(models.Model):
    template = models.ForeignKey(QuotationTemplate, on_delete=models.CASCADE, related_name="lines")
    product = models.ForeignKey(Product, on_delete=models.PROTECT)
    variant = models.ForeignKey(ProductVariant, on_delete=models.PROTECT, null=True, blank=True)
    quantity = models.PositiveIntegerField(default=1)
