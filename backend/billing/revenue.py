"""Revenue recognition. An invoice is earned evenly per day over the period it covers, not when it is billed or paid.

Worked out in whole paise so that the months of an invoice always add up to exactly what was billed.
"""
import calendar
from collections import defaultdict
from datetime import timedelta
from decimal import Decimal

from django.db.models import Sum
from django.db.models.functions import TruncMonth
from django.utils import timezone

from .models import Invoice, Payment

I = Invoice.State
ISSUED = [I.CONFIRMED, I.PAID]


def month_start(day):
    return day.replace(day=1)


def month_end(day):
    return day.replace(day=calendar.monthrange(day.year, day.month)[1])


def next_month(day):
    return month_end(day) + timedelta(days=1)


def to_money(paise):
    return (Decimal(paise) / 100).quantize(Decimal("0.01"))


def net_paise(subtotal, discount, tax, total):
    """Revenue excludes tax. Credit used on the invoice lowers revenue in proportion, since part of it was tax."""
    net = subtotal - discount
    gross = net + tax
    return int(net * total / gross * 100) if gross > 0 else 0


def spread(paise, start, end, today):
    """Yield (month, earned so far, still scheduled) for each month from start to end."""
    days = (end - start).days + 1
    earned = paise * min(max((today - start).days + 1, 0), days) // days
    cursor, elapsed, done = start, 0, 0
    while cursor <= end:
        last = min(month_end(cursor), end)
        elapsed += (last - cursor).days + 1
        upto = paise * elapsed // days
        recognized = min(upto, earned) - min(done, earned)
        yield month_start(cursor), recognized, upto - done - recognized
        done = upto
        cursor = last + timedelta(days=1)


def invoice_schedule(invoice, today=None):
    if invoice.state not in ISSUED:
        return []
    today = today or timezone.localdate()
    paise = net_paise(invoice.subtotal, invoice.discount_total, invoice.tax_total, invoice.total)
    if paise <= 0:
        return []
    return [
        {"month": month.isoformat(), "recognized": to_money(recognized), "scheduled": to_money(scheduled)}
        for month, recognized, scheduled in spread(paise, invoice.period_start, invoice.period_end, today)
    ]


def revenue_report(business_id, start=None, end=None, plan=None, period=None, today=None):
    today = today or timezone.localdate()
    this_month = month_start(today)
    first = month_start(start) if start else month_start(this_month - timedelta(days=330))
    last = month_start(end) if end else month_start(this_month + timedelta(days=190))

    invoices = Invoice.objects.filter(business_id=business_id, state__in=ISSUED)
    payments = Payment.objects.filter(business_id=business_id)
    if plan:
        invoices = invoices.filter(subscription__plan_id=plan)
        payments = payments.filter(invoice__subscription__plan_id=plan)
    if period:
        invoices = invoices.filter(subscription__plan__billing_period=period)
        payments = payments.filter(invoice__subscription__plan__billing_period=period)

    recognized, scheduled, billed, closing = defaultdict(int), defaultdict(int), defaultdict(int), defaultdict(int)
    by_plan, by_period, by_customer = defaultdict(int), defaultdict(int), defaultdict(int)
    earned_total, billed_total = 0, 0
    rows = invoices.order_by().values_list(
        "subtotal", "discount_total", "tax_total", "total", "period_start", "period_end", "invoice_date",
        "subscription__plan__name", "subscription__plan__billing_period", "customer_name",
    )
    for subtotal, discount, tax, total, begin, finish, issued, plan_name, plan_period, customer in rows.iterator(chunk_size=2000):
        paise = net_paise(subtotal, discount, tax, total)
        if paise <= 0:
            continue
        issued_month = month_start(issued)
        billed[issued_month] += paise
        billed_total += paise
        running = 0
        for month, earned, later in spread(paise, begin, finish, today):
            recognized[month] += earned
            scheduled[month] += later
            earned_total += earned
            if first <= month <= last and earned:
                by_plan[plan_name] += earned
                by_period[plan_period] += earned
                by_customer[customer] += earned
            running += earned + later
            # What was billed but not yet earned at each month end, from the month it was billed.
            if month >= issued_month and paise > running:
                closing[month] += paise - running

    collected = {
        row["month"]: row["amount"]
        for row in payments.filter(date__gte=first, date__lte=month_end(last)).order_by().annotate(month=TruncMonth("date")).values("month").annotate(amount=Sum("amount"))
    }
    history, cursor = [], first
    previous = recognized.get(month_start(first - timedelta(days=1)), 0) + scheduled.get(month_start(first - timedelta(days=1)), 0)
    while cursor <= last:
        amount = recognized.get(cursor, 0) + scheduled.get(cursor, 0)
        status = "scheduled" if cursor > this_month else "current" if cursor == this_month else "closed"
        history.append({
            "month": cursor.isoformat(),
            "status": status,
            "recognized": to_money(recognized.get(cursor, 0)),
            "scheduled": to_money(scheduled.get(cursor, 0)),
            "billed": to_money(billed.get(cursor, 0)),
            "collected": collected.get(cursor, Decimal("0.00")),
            "deferred_end": to_money(closing.get(cursor, 0)),
            # Whole months only, so a part-finished month is not compared with a full one.
            "change": round(100 * (amount - previous) / previous, 1) if previous and status == "closed" else None,
        })
        previous = amount
        cursor = next_month(cursor)

    def ranked(values, limit=None):
        window = sum(values.values())
        ordered = sorted(values.items(), key=lambda item: -item[1])
        return [
            {"name": name, "amount": to_money(amount), "share": round(100 * amount / window, 1) if window else 0}
            for name, amount in ordered[:limit]
        ]

    last_month = month_start(this_month - timedelta(days=1))
    return {
        "as_of": today,
        "summary": {
            "recognized_to_date": to_money(earned_total),
            "deferred": to_money(billed_total - earned_total),
            "billed_to_date": to_money(billed_total),
            "recognized_this_month": to_money(recognized.get(this_month, 0)),
            "recognized_last_month": to_money(recognized.get(last_month, 0)),
            "scheduled_this_month": to_money(scheduled.get(this_month, 0)),
        },
        "history": history,
        "by_plan": ranked(by_plan),
        "by_period": ranked(by_period),
        "top_customers": ranked(by_customer, 10),
    }

