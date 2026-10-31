"""Bring in subscribers a business already has, from a CSV of what they bought. Past periods are not billed again."""
import csv
import io
from datetime import timedelta

from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_date

from accounts.identity import classify
from accounts.models import User
from catalog.models import PaymentTerm, Plan, Product

from . import services
from .models import Subscription

S = Subscription.State
COLUMNS = ["email", "first_name", "last_name", "company", "phone", "plan", "product", "quantity", "start_date", "expiry_date"]
MAX_ROWS = 2000
MAX_CHARS = 400_000


def sample_csv(business_id):
    """Sample purchases using this business's own plans, with addresses that can never receive mail."""
    today = timezone.localdate()
    plans = list(Plan.objects.filter(business_id=business_id, is_active=True).order_by("price"))
    product = Product.objects.filter(business_id=business_id, is_active=True).order_by("name").first()
    people = [
        ("Anika", "Rao", "Rao Bakery"), ("Dev", "Mehta", "Mehta Traders"), ("Sara", "Iqbal", "Iqbal Design"),
        ("Tom", "Reed", "Reed Logistics"), ("Mei", "Lin", "Lin Studio"), ("Omar", "Haddad", "Haddad Foods"),
        ("Isha", "Nair", "Nair Clinic"), ("Luis", "Gomez", "Gomez Print"),
    ]
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(COLUMNS)
    for index, (first, last, company) in enumerate(people):
        plan = plans[index % len(plans)] if plans else None
        start = today - timedelta(days=20 + index * 37)
        writer.writerow([
            f"{first.lower()}.{last.lower()}.sample@gmail.com", first, last, company, "", plan.name if plan else "",
            product.name if product and index % 2 else "", 1 + index % 3 if product and index % 2 else "", start, "",
        ])
    return out.getvalue()


def _parse_row(raw, plans, products):
    errors = []
    email = (raw.get("email") or "").strip().lower()
    if classify(email)["kind"] != "user":
        errors.append("Subscribers use a name@gmail.com address.")
    plan = plans.get((raw.get("plan") or "").strip().lower())
    if plan is None:
        errors.append(f"No plan is named \"{(raw.get('plan') or '').strip()}\".")
    product, quantity = None, 1
    if (raw.get("product") or "").strip():
        product = products.get(raw["product"].strip().lower())
        if product is None:
            errors.append(f"No product is named \"{raw['product'].strip()}\".")
    if (raw.get("quantity") or "").strip():
        text = raw["quantity"].strip()
        if text.isdigit() and 0 < int(text) <= 100000:
            quantity = int(text)
        else:
            errors.append("Quantity must be a whole number above zero.")
    today = timezone.localdate()
    start, expiry = today, None
    try:
        if (raw.get("start_date") or "").strip():
            start = parse_date(raw["start_date"].strip()) or errors.append("Use YYYY-MM-DD for the start date.") or today
        if (raw.get("expiry_date") or "").strip():
            expiry = parse_date(raw["expiry_date"].strip()) or errors.append("Use YYYY-MM-DD for the expiry date.")
    except ValueError:
        errors.append("A date in this row does not exist.")
    expiry = expiry or services.add_months(start, 12)
    if expiry < start:
        errors.append("Expiry date cannot be before the start date.")
    return {
        "email": email, "plan": plan, "product": product, "quantity": quantity, "start": start, "expiry": expiry, "errors": errors,
        "first_name": (raw.get("first_name") or "").strip()[:150], "last_name": (raw.get("last_name") or "").strip()[:150],
        "company": (raw.get("company") or "").strip()[:150], "phone": (raw.get("phone") or "").strip()[:30],
    }


def plan_business(row):
    return row["plan"].business_id


def _import_row(row, term, actor):
    customer = User.objects.filter(email__iexact=row["email"]).first()
    if customer is None:
        customer = User.objects.create_user(
            row["email"], None, first_name=row["first_name"], last_name=row["last_name"], company=row["company"], phone=row["phone"],
            role=User.Role.CUSTOMER, business_id=plan_business(row),
        )
    plan = row["plan"]
    sub = Subscription.objects.create(business_id=plan.business_id, customer=customer, plan=plan, payment_term=term, start_date=row["start"], expiry_date=row["expiry"])
    sub.number = f"SUB-{sub.pk:06d}"
    sub.save(update_fields=["number"])
    services.write_lines(sub, [{"product": row["product"], "quantity": row["quantity"]}] if row["product"] else [])
    today = timezone.localdate()
    # Earlier periods were billed wherever the subscriber came from, so billing starts from the next date due.
    next_date = row["start"]
    while next_date < today:
        next_date = services.next_period_start(next_date, plan.billing_period, row["start"])
    sub.state = S.ACTIVE
    sub.activated_on = row["start"]
    sub.term_days = (row["expiry"] - row["start"]).days or None
    sub.next_invoice_date = next_date
    sub.save(update_fields=["state", "activated_on", "term_days", "next_invoice_date", "updated_at"])
    services.log_event(sub.pk, "Imported from a CSV file", actor)


def run_import(text, commit, actor):
    text = str(text or "").lstrip("﻿")
    if not text.strip():
        return {"error": "Paste a CSV or load the sample first."}
    if len(text) > MAX_CHARS:
        return {"error": "This file is too large. Split it into smaller files."}
    try:
        rows = list(csv.DictReader(io.StringIO(text)))
    except csv.Error:
        return {"error": "This does not look like a CSV file."}
    if not rows:
        return {"error": "This file has a header but no rows."}
    if len(rows) > MAX_ROWS:
        return {"error": f"Import at most {MAX_ROWS} rows at a time."}
    missing = {"email", "plan"} - {str(name).strip().lower() for name in rows[0]}
    if missing:
        return {"error": f"Add these columns: {', '.join(sorted(missing))}."}
    rows = [{str(k).strip().lower(): v for k, v in row.items() if k} for row in rows]

    # Hash maps give each row a constant-time lookup, so a large file does not mean thousands of queries.
    business_id = actor.business_id
    plans = {p.name.lower(): p for p in Plan.objects.filter(business_id=business_id, is_active=True)}
    products = {p.name.lower(): p for p in Product.objects.filter(business_id=business_id, is_active=True)}
    term = PaymentTerm.objects.filter(business_id=business_id, is_active=True).first()
    emails = {str(raw.get("email") or "").strip().lower() for raw in rows}
    existing = {email.lower(): (role, owner) for email, role, owner in User.objects.filter(email__in=emails).values_list("email", "role", "business_id")}
    running = set(
        Subscription.objects.filter(business_id=business_id, customer__email__in=emails, state__in=[S.ACTIVE, S.PAUSED])
        .values_list("customer__email", "plan_id")
    )
    seen, results, imported = set(), [], 0
    for line, raw in enumerate(rows, start=2):
        row = _parse_row(raw, plans, products)
        errors, status = row["errors"], "new"
        if term is None:
            errors.append("Add a payment term first.")
        role, owner = existing.get(row["email"], (None, None))
        if role and (role != User.Role.CUSTOMER or owner != business_id):
            errors.append("This address already has an account elsewhere.")
        key = (row["email"], row["plan"].pk if row["plan"] else None)
        if not errors:
            if key in seen or key in running:
                status = "skipped"
            elif commit:
                try:
                    with transaction.atomic():
                        _import_row(row, term, actor)
                    imported += 1
                    status = "imported"
                except Exception as exc:
                    errors.append(f"Could not import this row: {exc}")
        seen.add(key)
        results.append({
            "line": line, "email": row["email"], "customer": row["company"] or f"{row['first_name']} {row['last_name']}".strip(),
            "plan": row["plan"].name if row["plan"] else (raw.get("plan") or ""), "product": row["product"].name if row["product"] else "",
            "quantity": row["quantity"], "start_date": row["start"], "status": "error" if errors else status, "errors": errors,
            "existing_customer": bool(role),
        })
    return {
        "rows": results, "imported": imported, "total": len(results),
        "errors": sum(1 for r in results if r["status"] == "error"), "skipped": sum(1 for r in results if r["status"] == "skipped"),
        "ready": sum(1 for r in results if r["status"] == "new"),
    }
