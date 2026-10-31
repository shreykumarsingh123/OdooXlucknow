"""Business rules for subscriptions, invoices and payments. Views stay thin and call these."""
import calendar
import logging
import uuid
from datetime import timedelta
from decimal import Decimal

import stripe
from django.conf import settings
from django.core.mail import send_mail
from django.db import IntegrityError, transaction
from django.db.models import F, Q
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from catalog.models import Discount, PaymentTerm, Plan, money
from config.api import Conflict

from .models import Invoice, InvoiceDiscount, InvoiceLine, Payment, Subscription, SubscriptionEvent, SubscriptionLine
from .notify import send_sms

logger = logging.getLogger(__name__)
S = Subscription.State
I = Invoice.State
ZERO = Decimal("0.00")


# ---------------------------------------------------------------- dates


def add_months(day, months):
    index = day.month - 1 + months
    year, month = day.year + index // 12, index % 12 + 1
    return day.replace(year=year, month=month, day=min(day.day, calendar.monthrange(year, month)[1]))


def next_period_start(day, period, anchor=None):
    """Next billing date. `anchor` keeps a 31st start on month ends instead of drifting to the 30th, then the 28th."""
    if period == Plan.Period.DAILY:
        return day + timedelta(days=1)
    if period == Plan.Period.WEEKLY:
        return day + timedelta(weeks=1)
    following = add_months(day, 1 if period == Plan.Period.MONTHLY else 12)
    if anchor:
        last = calendar.monthrange(following.year, following.month)[1]
        following = following.replace(day=min(anchor.day, last))
    return following


# ---------------------------------------------------------------- subscription building


def log_event(subscription_id, message, actor=None):
    SubscriptionEvent.objects.create(subscription_id=subscription_id, message=message[:255], actor=actor)


def refresh_totals(subscription):
    total = sum((line.amount for line in subscription.lines.all() if line.is_enabled), ZERO)
    subscription.recurring_total = money(total)
    subscription.save(update_fields=["recurring_total", "updated_at"])


def validate_terms(plan, start_date, expiry_date, product_quantity):
    errors = {}
    if not plan.available_on(start_date):
        errors["plan"] = ["This plan is not available on the start date."]
    if expiry_date < start_date:
        errors["expiry_date"] = ["Expiry date cannot be before the start date."]
    if product_quantity < plan.min_quantity:
        errors["lines"] = [f"This plan needs a minimum quantity of {plan.min_quantity}."]
    if errors:
        raise ValidationError(errors)


def default_unit_price(product, variant):
    return product.sales_price + (variant.extra_price if variant else ZERO)


def _add_plan_fee(subscription, plan):
    if plan.price > 0:
        fee = SubscriptionLine.objects.create(
            subscription=subscription, description=f"{plan.name} plan fee", quantity=1, unit_price=plan.price
        )
        fee.taxes.set(plan.taxes.all())


def write_lines(subscription, rows):
    """Replace all lines. The plan price is always added as its own line (assumption A-01)."""
    subscription.lines.all().delete()
    _add_plan_fee(subscription, subscription.plan)
    for row in rows:
        product, variant = row["product"], row.get("variant")
        label = f"{product.name} ({variant.value})" if variant else product.name
        unit_price = row.get("unit_price")
        line = SubscriptionLine.objects.create(
            subscription=subscription,
            product=product,
            variant=variant,
            description=label,
            quantity=row["quantity"],
            unit_price=default_unit_price(product, variant) if unit_price is None else unit_price,
        )
        taxes = row.get("taxes")
        line.taxes.set(product.taxes.all() if taxes is None else taxes)
    refresh_totals(subscription)


@transaction.atomic
def save_subscription(data, rows, instance=None):
    plan = data.get("plan", getattr(instance, "plan", None))
    start = data.get("start_date", getattr(instance, "start_date", None))
    expiry = data.get("expiry_date", getattr(instance, "expiry_date", None))
    if rows is None:
        quantity = sum(l.quantity for l in instance.lines.all() if not l.is_plan_fee)
    else:
        quantity = sum(row["quantity"] for row in rows)
    validate_terms(plan, start, expiry, quantity)
    if instance is None:
        instance = Subscription.objects.create(**data)
        instance.number = f"SUB-{instance.pk:06d}"
        instance.save(update_fields=["number"])
    else:
        if instance.state not in (S.DRAFT, S.QUOTATION):
            raise Conflict("Only draft or quotation subscriptions can be edited.")
        for key, value in data.items():
            setattr(instance, key, value)
        instance.save()
    if rows is not None:
        write_lines(instance, rows)
    return instance


@transaction.atomic
def subscription_from_template(template, customer, start_date, expiry_date, payment_term):
    rows = [{"product": l.product, "variant": l.variant, "quantity": l.quantity} for l in template.lines.select_related("product", "variant")]
    subscription = save_subscription(
        {
            "customer": customer,
            "plan": template.plan,
            "payment_term": payment_term,
            "start_date": start_date,
            "expiry_date": expiry_date,
            "quotation_valid_until": timezone.localdate() + timedelta(days=template.validity_days),
        },
        rows,
    )
    return subscription


# ---------------------------------------------------------------- subscription lifecycle


def _locked(subscription_id):
    return Subscription.objects.select_for_update().select_related("plan").get(pk=subscription_id)


def _require(subscription, *states):
    if subscription.state not in states:
        names = " or ".join(str(S(state).label) for state in states)
        raise Conflict(f"This subscription must be {names} for this action. It is {subscription.get_state_display()}.")


@transaction.atomic
def send_quotation(subscription_id):
    sub = _locked(subscription_id)
    _require(sub, S.DRAFT)
    if not sub.lines.exists():
        raise Conflict("Add at least one line before quoting.")
    sub.state = S.QUOTATION
    sub.save(update_fields=["state", "updated_at"])
    return sub


@transaction.atomic
def confirm(subscription_id):
    sub = _locked(subscription_id)
    _require(sub, S.QUOTATION)
    if sub.quotation_valid_until and sub.quotation_valid_until < timezone.localdate():
        raise Conflict("This quotation has expired.")
    sub.state = S.CONFIRMED
    sub.save(update_fields=["state", "updated_at"])
    return sub


@transaction.atomic
def activate(subscription_id):
    sub = _locked(subscription_id)
    _require(sub, S.CONFIRMED)
    _start_billing(sub)
    return sub


def _start_billing(sub):
    """Go active. A plan's free trial delays the first invoice, once per customer per plan."""
    used_before = Subscription.objects.filter(
        Q(plan_id=sub.plan_id) | Q(trial_plan_id=sub.plan_id), customer_id=sub.customer_id, state__in=[S.ACTIVE, S.PAUSED, S.CLOSED]
    ).exclude(pk=sub.pk).exists()
    trial = 0 if used_before else sub.plan.trial_days
    sub.state = S.ACTIVE
    sub.trial_ends = sub.start_date + timedelta(days=trial) if trial else None
    sub.trial_plan = sub.plan if trial else None
    sub.next_invoice_date = sub.trial_ends or sub.start_date
    sub.save(update_fields=["state", "trial_ends", "trial_plan", "next_invoice_date", "updated_at"])


@transaction.atomic
def start_plan(user, plan_id):
    """A customer starts a public plan online. The team's quotation steps do not apply (assumption A-12)."""
    today = timezone.localdate()
    plan = Plan.objects.filter(pk=plan_id, is_public=True).first()
    if plan is None or not plan.available_on(today) or plan.min_quantity > 1 or plan.price <= 0:
        raise Conflict("This plan cannot be started online. Please contact Brightloop.")
    type(user).objects.select_for_update().get(pk=user.pk)  # one at a time per customer, so a double click makes one
    if Subscription.objects.filter(customer=user, plan=plan, state__in=[S.ACTIVE, S.PAUSED]).exists():
        raise Conflict("You already have this plan.")
    term = PaymentTerm.objects.filter(is_active=True).first()
    if term is None:
        raise Conflict("This plan cannot be started online. Please contact Brightloop.")
    sub = Subscription.objects.create(customer=user, plan=plan, payment_term=term, start_date=today, expiry_date=add_months(today, 12))
    sub.number = f"SUB-{sub.pk:06d}"
    sub.save(update_fields=["number"])
    write_lines(sub, [])
    _start_billing(sub)
    log_event(sub.pk, "Started online" + (f", free trial until {sub.trial_ends}" if sub.trial_ends else ""), user)
    return sub


@transaction.atomic
def pause(subscription_id):
    sub = _locked(subscription_id)
    _require(sub, S.ACTIVE)
    if not sub.plan.pausable:
        raise Conflict("This plan cannot be paused.")
    sub.state = S.PAUSED
    sub.save(update_fields=["state", "updated_at"])
    return sub


@transaction.atomic
def resume(subscription_id):
    sub = _locked(subscription_id)
    _require(sub, S.PAUSED)
    sub.state = S.ACTIVE
    # Paused time is not back-billed (assumption A-04).
    today = timezone.localdate()
    if sub.next_invoice_date and sub.next_invoice_date < today:
        sub.next_invoice_date = today
    sub.save(update_fields=["state", "next_invoice_date", "updated_at"])
    return sub


@transaction.atomic
def close(subscription_id, reason="", note=""):
    sub = _locked(subscription_id)
    _require(sub, S.ACTIVE, S.PAUSED)
    if not sub.plan.closable:
        raise Conflict("This plan cannot be closed early.")
    if reason and reason not in Subscription.CloseReason.values:
        raise ValidationError({"reason": ["Choose one of the listed reasons."]})
    sub.state = S.CLOSED
    sub.closed_at = timezone.localdate()
    sub.close_reason = reason
    sub.close_note = str(note)[:255]
    sub.save(update_fields=["state", "closed_at", "close_reason", "close_note", "updated_at"])
    return sub


@transaction.atomic
def renew(subscription_id):
    sub = _locked(subscription_id)
    _require(sub, S.ACTIVE)
    if not sub.plan.renewable:
        raise Conflict("This plan cannot be renewed.")
    # Extends by the original term (assumption A-07).
    term = max(sub.expiry_date - sub.start_date, timedelta(days=1))
    sub.expiry_date += term
    sub.save(update_fields=["expiry_date", "updated_at"])
    return sub


@transaction.atomic
def toggle_addon(subscription_id, line_id, enabled):
    sub = _locked(subscription_id)
    _require(sub, S.ACTIVE, S.PAUSED)
    line = sub.lines.select_related("product").filter(pk=line_id).first()
    if line is None or line.is_plan_fee or line.product.type != "addon":
        raise Conflict("Only add-on lines can be switched on or off.")
    enabled = enabled is True
    if enabled and not line.is_enabled:
        line.billable_pending = True
    line.is_enabled = enabled
    line.save(update_fields=["is_enabled", "billable_pending"])
    refresh_totals(sub)
    return sub


def _fee_gross(amount, taxes):
    return amount + sum((tax.compute(amount, 1) for tax in taxes), ZERO)


@transaction.atomic
def change_plan(subscription_id, new_plan, actor=None, today=None):
    """Swap the plan now. The unused part of the billed period is charged or credited (assumption A-13)."""
    today = today or timezone.localdate()
    sub = Subscription.objects.select_for_update().select_related("plan", "customer", "payment_term").get(pk=subscription_id)
    _require(sub, S.ACTIVE)
    old = sub.plan
    if new_plan.pk == old.pk:
        raise Conflict("This subscription is already on that plan.")
    if new_plan.billing_period != old.billing_period:
        raise Conflict("You can only change to a plan with the same billing period.")
    if not new_plan.available_on(today):
        raise Conflict("That plan is not available right now.")
    if sub.trial_ends and sub.trial_ends > today:
        raise Conflict("You can change plan when your free trial ends.")
    # Otherwise upgrading and downgrading in a loop would pile up credit against charges nobody has paid.
    if sub.invoices.filter(is_adjustment=True, state__in=[I.DRAFT, I.CONFIRMED]).exists():
        raise Conflict("Please pay the outstanding plan change invoice first.")
    quantity = sum(line.quantity for line in sub.lines.all() if not line.is_plan_fee)
    if quantity < new_plan.min_quantity and new_plan.min_quantity > 1:
        raise Conflict(f"That plan needs a minimum quantity of {new_plan.min_quantity}.")

    fee = sub.lines.filter(product__isnull=True).prefetch_related("taxes").first()
    billed = sub.invoices.exclude(state=I.CANCELLED).filter(
        is_adjustment=False, period_end=sub.next_invoice_date - timedelta(days=1)
    ).first()
    difference, tax_part = ZERO, ZERO
    if billed and billed.subtotal:
        length = (billed.period_end - billed.period_start).days + 1
        left = max(min((billed.period_end - today).days + 1, length), 0)
        share = Decimal(left) / Decimal(length)
        # What the old fee really cost after discounts, so a credit never exceeds what was charged.
        paid_share = (billed.subtotal - billed.discount_total) / billed.subtotal
        old_net = money((fee.unit_price if fee else ZERO) * share * paid_share)
        new_net = money(new_plan.price * share)
        old_gross = _fee_gross(old_net, fee.taxes.all()) if fee else ZERO
        new_gross = _fee_gross(new_net, new_plan.taxes.all())
        difference = new_gross - old_gross
        tax_part = max((new_gross - new_net) - (old_gross - old_net), ZERO)

    if fee:
        fee.delete()
    _add_plan_fee(sub, new_plan)
    sub.plan = new_plan
    sub.save(update_fields=["plan", "updated_at"])
    refresh_totals(sub)

    message = f"Plan changed from {old.name} to {new_plan.name}"
    if difference > 0:
        _adjustment_invoice(sub, f"{new_plan.name}: prorated change from {old.name}", difference - tax_part, tax_part, today)
        message += f", {difference} charged for the rest of the period"
    elif difference < 0 and billed.state == I.PAID:
        sub.credit_balance += -difference
        sub.save(update_fields=["credit_balance", "updated_at"])
        message += f", {-difference} credited"
    elif difference < 0:
        message += ", no credit because the invoice for this period is not paid"
    log_event(sub.pk, message, actor)
    return sub


def _adjustment_invoice(sub, description, subtotal, tax, today):
    """A one-off invoice. It is ready to pay at once, and its unique key is outside the billing periods."""
    last = sub.next_invoice_date - timedelta(days=1) if sub.next_invoice_date else today
    customer = sub.customer
    invoice = Invoice.objects.create(
        subscription=sub, customer=customer, customer_name=customer.display_name, customer_email=customer.email,
        customer_address=customer.address, state=I.CONFIRMED, invoice_date=today,
        due_date=today + timedelta(days=sub.payment_term.due_days), period_start=today, period_end=max(last, today),
        billing_key=f"adj:{uuid.uuid4().hex[:32]}", subtotal=subtotal, tax_total=tax, total=subtotal + tax, is_adjustment=True,
    )
    invoice.number = f"INV-{invoice.pk:06d}"
    invoice.save(update_fields=["number"])
    InvoiceLine.objects.create(
        invoice=invoice, description=description[:255], quantity=1, unit_price=subtotal, tax_amount=tax, amount=subtotal
    )
    return invoice


@transaction.atomic
def adjust_balance(subscription_id, kind, amount, note, actor):
    """An admin charges a one-off amount, or gives credit towards the next invoices."""
    sub = Subscription.objects.select_for_update().select_related("customer", "payment_term").get(pk=subscription_id)
    _require(sub, S.ACTIVE, S.PAUSED)
    if kind == "credit":
        sub.credit_balance += amount
        sub.save(update_fields=["credit_balance", "updated_at"])
        log_event(sub.pk, f"{amount} credit added: {note}", actor)
        return None
    invoice = _adjustment_invoice(sub, note, amount, ZERO, timezone.localdate())
    log_event(sub.pk, f"{amount} charged on {invoice.number}: {note}", actor)
    return invoice


@transaction.atomic
def redeem_code(subscription_id, code, actor=None):
    sub = _locked(subscription_id)
    _require(sub, S.ACTIVE, S.PAUSED)
    discount = Discount.objects.select_for_update().filter(code__iexact=str(code).strip()).first() if str(code).strip() else None
    if discount is None or not discount.is_live():
        raise ValidationError({"code": ["This code is not valid, or has expired."]})
    if discount.subscriptions.filter(pk=sub.pk).exists():
        raise Conflict("This code is already on this subscription.")
    discount.subscriptions.add(sub)
    log_event(sub.pk, f"Code {discount.code} added: {discount.name}", actor)
    return sub


def close_ended(today=None):
    """Close subscriptions whose plan closes on its own, once they have ended."""
    today = today or timezone.localdate()
    ended = Subscription.objects.filter(state__in=[S.ACTIVE, S.PAUSED], plan__auto_close=True).filter(
        Q(expiry_date__lt=today) | Q(plan__end_date__lt=today)
    )
    ids = list(ended.values_list("pk", flat=True))
    SubscriptionEvent.objects.bulk_create(SubscriptionEvent(subscription_id=pk, message="Closed on its own at the end of its term") for pk in ids)
    return Subscription.objects.filter(pk__in=ids).update(state=S.CLOSED, closed_at=today, updated_at=timezone.now())


# ---------------------------------------------------------------- invoicing


def _qualifies(discount, purchase, quantity):
    return purchase >= discount.min_purchase and quantity >= discount.min_quantity


def _applicable_discounts(sub, day):
    live = Discount.objects.select_for_update().filter(is_active=True, start_date__lte=day).filter(
        Q(end_date__isnull=True) | Q(end_date__gte=day)
    ).filter(Q(usage_limit__isnull=True) | Q(times_used__lt=F("usage_limit")))
    product_ids = [line.product_id for line in sub.lines.all() if line.product_id]
    by_product = live.filter(scope=Discount.Scope.PRODUCTS, products__in=product_ids).filter(
        Q(code__isnull=True) | Q(subscriptions=sub)
    ).distinct().prefetch_related("products")
    whole = live.filter(scope=Discount.Scope.SUBSCRIPTIONS, subscriptions=sub)
    return list(by_product), list(whole)


def _price_lines(sub, day):
    """Work out each line, then apply discounts and tax. Returns (rows, applied discounts)."""
    rows = []
    for line in sub.lines.select_related("product").prefetch_related("taxes"):
        if line.is_enabled or line.billable_pending:
            rows.append({"line": line, "base": money(line.amount), "discount": ZERO})
    if not rows:
        return [], []
    by_product, whole = _applicable_discounts(sub, day)
    applied = []

    for discount in by_product:
        ids = {p.pk for p in discount.products.all()}
        targets = [r for r in rows if r["line"].product_id in ids]
        purchase = sum((r["base"] for r in targets), ZERO)
        quantity = sum(r["line"].quantity for r in targets)
        if not targets or not _qualifies(discount, purchase, quantity):
            continue
        applied.append((discount, _spread(discount, targets)))

    purchase = sum((r["base"] for r in rows), ZERO)
    quantity = sum(r["line"].quantity for r in rows if r["line"].product_id)
    for discount in whole:
        if _qualifies(discount, purchase, quantity):
            applied.append((discount, _spread(discount, rows)))

    applied = [(d, amount) for d, amount in applied if amount > 0]
    for row in rows:
        net = row["base"] - row["discount"]
        row["net"] = net
        taxes = list(row["line"].taxes.all())
        row["tax"] = sum((tax.compute(net, row["line"].quantity) for tax in taxes), ZERO)
        row["tax_names"] = ", ".join(tax.name for tax in taxes)
    return rows, applied


def _spread(discount, targets):
    """Apply one discount across lines in proportion to what is left on them. No line goes below zero."""
    remaining = sum((r["base"] - r["discount"] for r in targets), ZERO)
    amount = discount.compute(remaining)
    left = amount
    for index, row in enumerate(targets):
        balance = row["base"] - row["discount"]
        share = left if index == len(targets) - 1 else (money(amount * balance / remaining) if remaining else ZERO)
        share = min(share, balance, left)
        row["discount"] += share
        left -= share
    return amount - left


def _create_invoice(sub, period_start, day):
    period_end = next_period_start(period_start, sub.plan.billing_period, sub.billing_anchor) - timedelta(days=1)
    rows, applied = _price_lines(sub, day)
    if not rows:
        return None
    customer = sub.customer
    subtotal = sum((r["base"] for r in rows), ZERO)
    discount_total = sum((r["discount"] for r in rows), ZERO)
    tax_total = sum((r["tax"] for r in rows), ZERO)
    credit = min(sub.credit_balance, subtotal - discount_total + tax_total)
    if credit:
        sub.credit_balance -= credit
        sub.save(update_fields=["credit_balance"])
    invoice = Invoice.objects.create(
        subscription=sub,
        customer=customer,
        customer_name=customer.display_name,
        customer_email=customer.email,
        customer_address=customer.address,
        invoice_date=day,
        due_date=day + timedelta(days=sub.payment_term.due_days),
        period_start=period_start,
        period_end=period_end,
        billing_key=f"{sub.pk}:{period_start.isoformat()}",
        subtotal=subtotal,
        discount_total=discount_total,
        tax_total=tax_total,
        credit_applied=credit,
        total=subtotal - discount_total + tax_total - credit,
    )
    invoice.number = f"INV-{invoice.pk:06d}"
    invoice.save(update_fields=["number"])
    InvoiceLine.objects.bulk_create(
        InvoiceLine(
            invoice=invoice,
            description=r["line"].description,
            quantity=r["line"].quantity,
            unit_price=r["line"].unit_price,
            discount_amount=r["discount"],
            tax_names=r["tax_names"],
            tax_amount=r["tax"],
            amount=r["net"],
        )
        for r in rows
    )
    sub.lines.filter(billable_pending=True).update(billable_pending=False)
    for discount, amount in applied:
        InvoiceDiscount.objects.create(invoice=invoice, discount=discount, name=discount.name, amount=amount)
        Discount.objects.filter(pk=discount.pk).update(times_used=F("times_used") + 1)
    return invoice


def bill_subscription(subscription_id, today=None):
    """Create every invoice due for one subscription, catching up on missed periods."""
    today = today or timezone.localdate()
    created = []
    with transaction.atomic():
        sub = Subscription.objects.select_for_update().select_related("plan", "customer", "payment_term").get(pk=subscription_id)
        if sub.state != S.ACTIVE or sub.next_invoice_date is None:
            return created
        period = sub.next_invoice_date
        last_day = min(filter(None, [sub.expiry_date, sub.plan.end_date]))
        while period <= today and period <= last_day:
            key = f"{sub.pk}:{period.isoformat()}"
            if not Invoice.objects.filter(billing_key=key).exists():
                invoice = _create_invoice(sub, period, today)
                if invoice:
                    created.append(invoice)
                    log_event(sub.pk, f"Invoice {invoice.number} created for {invoice.period_start} to {invoice.period_end}")
            period = next_period_start(period, sub.plan.billing_period, sub.billing_anchor)
        sub.next_invoice_date = period
        sub.save(update_fields=["next_invoice_date", "updated_at"])
    return created


def run_billing(today=None):
    """Bill everything due. Each subscription has its own transaction, so one failure cannot block the rest."""
    today = today or timezone.localdate()
    closed = close_ended(today)
    due = Subscription.objects.filter(state=S.ACTIVE, next_invoice_date__lte=today).values_list("pk", flat=True)
    created, failed = 0, []
    for pk in list(due):
        try:
            created += len(bill_subscription(pk, today))
        except IntegrityError:  # another run won the race; the unique key kept it from double billing
            logger.warning("Subscription %s was billed by a concurrent run", pk)
        except Exception as exc:
            logger.exception("Billing failed for subscription %s", pk)
            failed.append({"subscription": pk, "error": str(exc)})
    return {"invoices_created": created, "subscriptions_closed": closed, "failed": failed}


def _locked_invoice(invoice_id):
    return Invoice.objects.select_for_update().get(pk=invoice_id)


@transaction.atomic
def confirm_invoice(invoice_id):
    invoice = _locked_invoice(invoice_id)
    if invoice.state != I.DRAFT:
        raise Conflict("Only draft invoices can be confirmed.")
    invoice.state = I.PAID if invoice.total == 0 else I.CONFIRMED
    invoice.save(update_fields=["state"])
    return invoice


@transaction.atomic
def cancel_invoice(invoice_id, rebill=False):
    invoice = _locked_invoice(invoice_id)
    if invoice.state not in (I.DRAFT, I.CONFIRMED):
        raise Conflict("Paid or cancelled invoices cannot be cancelled.")
    if invoice.amount_paid > 0:
        raise Conflict("This invoice has payments recorded, so it cannot be cancelled.")
    invoice.state = I.CANCELLED
    fields = ["state"]
    if invoice.credit_applied:
        Subscription.objects.filter(pk=invoice.subscription_id).update(credit_balance=F("credit_balance") + invoice.credit_applied)
    if rebill and not invoice.is_adjustment:
        invoice.billing_key = None
        fields.append("billing_key")
        sub = Subscription.objects.select_for_update().get(pk=invoice.subscription_id)
        if sub.next_invoice_date is None or invoice.period_start < sub.next_invoice_date:
            sub.next_invoice_date = invoice.period_start
            sub.save(update_fields=["next_invoice_date", "updated_at"])
    invoice.save(update_fields=fields)
    # A cancelled invoice gives its discount uses back.
    for row in invoice.discounts.all():
        Discount.objects.filter(pk=row.discount_id, times_used__gt=0).update(times_used=F("times_used") - 1)
    return invoice


def send_invoice(invoice_id):
    invoice = Invoice.objects.select_related("subscription").get(pk=invoice_id)
    if invoice.state not in (I.CONFIRMED, I.PAID):
        raise Conflict("Confirm the invoice before sending it.")
    send_mail(
        f"Invoice {invoice.number} from Brightloop Software",
        f"Hello {invoice.customer_name},\n\n"
        f"Invoice {invoice.number} for subscription {invoice.subscription.number} is ready.\n"
        f"Period: {invoice.period_start} to {invoice.period_end}\n"
        f"Total: {invoice.total}\nAmount due: {invoice.amount_due}\nDue date: {invoice.due_date}\n\n"
        f"View or print it here: {settings.FRONTEND_URL}/invoices/{invoice.pk}\n",
        settings.DEFAULT_FROM_EMAIL,
        [invoice.customer_email],
    )
    invoice.sent_at = timezone.now()
    invoice.save(update_fields=["sent_at"])
    return invoice


@transaction.atomic
def record_payment(invoice_id, method, amount, date, note, user, reference=None):
    invoice = _locked_invoice(invoice_id)
    if invoice.state != I.CONFIRMED:
        raise Conflict("Payments can only be recorded against confirmed invoices.")
    if amount > invoice.amount_due:
        raise ValidationError({"amount": [f"This is more than the {invoice.amount_due} still due."]})
    payment = Payment.objects.create(invoice=invoice, method=method, amount=amount, date=date, note=note, recorded_by=user, reference=reference)
    invoice.amount_paid += amount
    if invoice.amount_due == 0:
        invoice.state = I.PAID
    invoice.save(update_fields=["amount_paid", "state"])
    return payment


# ---------------------------------------------------------------- online payment (Stripe Checkout)


def create_checkout(invoice):
    if not settings.STRIPE_SECRET_KEY:
        raise Conflict("Online payment is not set up.")
    if invoice.state != I.CONFIRMED:
        raise Conflict("Only confirmed invoices can be paid online.")
    base = f"{settings.FRONTEND_URL}/invoices/{invoice.pk}"
    try:
        session = stripe.checkout.Session.create(
            api_key=settings.STRIPE_SECRET_KEY,
            mode="payment",
            customer_email=invoice.customer_email,
            metadata={"invoice_id": str(invoice.pk)},
            line_items=[{
                "quantity": 1,
                "price_data": {
                    "currency": settings.STRIPE_CURRENCY,
                    "unit_amount": int(invoice.amount_due * 100),
                    "product_data": {"name": f"Invoice {invoice.number}"},
                },
            }],
            success_url=f"{base}?session_id={{CHECKOUT_SESSION_ID}}",
            cancel_url=base,
        )
    except stripe.StripeError:
        logger.exception("Could not create a Stripe Checkout session for %s", invoice.number)
        raise Conflict("Online payment is unavailable right now. Please try again later.")
    return session.url


def settle_checkout(session, invoice_id=None):
    """Record a paid Checkout session once. The return page and the webhook can both call this safely."""
    if session.get("payment_status") != "paid":
        return None
    session_invoice = int((session.get("metadata") or {}).get("invoice_id", 0))
    if invoice_id is not None and session_invoice != int(invoice_id):
        raise Conflict("This payment belongs to another invoice.")
    with transaction.atomic():
        invoice = _locked_invoice(session_invoice)
        existing = Payment.objects.filter(reference=session["id"]).first()
        if existing:
            return existing
        amount = Decimal(session["amount_total"]) / 100
        try:
            return record_payment(
                invoice.pk, Payment.Method.ONLINE, amount, timezone.localdate(), "Paid online by card",
                invoice.customer, reference=session["id"],
            )
        except (Conflict, ValidationError):
            # Money was taken, but the invoice changed meanwhile. The team must resolve it in Stripe.
            logger.error("Stripe session %s paid but invoice %s cannot accept it", session["id"], invoice.number)
            raise Conflict("Your payment went through, but this invoice has changed. Please contact Brightloop.")


def confirm_checkout(session_id, invoice_id):
    if not settings.STRIPE_SECRET_KEY:
        raise Conflict("Online payment is not set up.")
    try:
        session = stripe.checkout.Session.retrieve(session_id, api_key=settings.STRIPE_SECRET_KEY)
    except stripe.StripeError:
        logger.exception("Could not read Stripe Checkout session")
        raise Conflict("We could not check this payment. Please refresh in a moment.")
    return settle_checkout(session, invoice_id)


# ---------------------------------------------------------------- overdue reminders


def send_reminders(today=None, limit=200):
    """Chase overdue invoices by email, and by SMS where possible, up to the configured count and spacing."""
    today = today or timezone.localdate()
    cutoff = today - timedelta(days=settings.REMINDER_INTERVAL_DAYS)
    due = Invoice.objects.select_related("customer").filter(
        state=I.CONFIRMED, due_date__lt=today, reminder_count__lt=settings.REMINDER_MAX_COUNT
    ).filter(Q(last_reminder_at__isnull=True) | Q(last_reminder_at__lte=cutoff)).order_by("due_date")[:limit]
    reminded, texted, failed = 0, 0, 0
    for invoice in due:
        link = f"{settings.FRONTEND_URL}/invoices/{invoice.pk}"
        try:
            send_mail(
                f"Payment reminder: invoice {invoice.number} is overdue",
                f"Hello {invoice.customer_name},\n\nInvoice {invoice.number} was due on {invoice.due_date}, "
                f"and {invoice.amount_due} is still owed.\n\nView it here: {link}\n",
                settings.DEFAULT_FROM_EMAIL,
                [invoice.customer_email],
            )
        except Exception:
            logger.exception("Could not send reminder for %s", invoice.number)
            failed += 1
            continue
        if send_sms(invoice.customer.phone, f"Brightloop: invoice {invoice.number} is overdue. {invoice.amount_due} is due. {link}"):
            texted += 1
        Invoice.objects.filter(pk=invoice.pk).update(reminder_count=F("reminder_count") + 1, last_reminder_at=today)
        reminded += 1
    return {"reminded": reminded, "sms_sent": texted, "failed": failed}
