"""Brightloop's own view over every business, and the public site each business gets."""
from decimal import Decimal

from django.db import transaction
from django.db.models import Case, Count, DecimalField, ExpressionWrapper, F, Q, Sum, Value, When
from django.utils import timezone
from rest_framework import serializers
from rest_framework.decorators import api_view, authentication_classes, permission_classes, throttle_classes
from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle

from accounts.identity import classify
from accounts.models import Business, User
from accounts.permissions import IsPlatform, IsTeam
from catalog.models import Plan, money
from config.api import Conflict

from . import services
from .models import Invoice, Payment, Subscription

S = Subscription.State
I = Invoice.State
FACTOR = {"daily": Decimal("30"), "weekly": Decimal("4.33"), "monthly": Decimal("1"), "yearly": Decimal("0.0833")}
MONEY = DecimalField(max_digits=16, decimal_places=2)


def _business_figures():
    """One grouped query per measure, joined in a dictionary by business id. Time grows with businesses, not with invoices."""
    today = timezone.localdate()
    monthly = Sum(Case(*[When(plan__billing_period=p, then=F("recurring_total") * Value(f)) for p, f in FACTOR.items()], output_field=MONEY))
    due = ExpressionWrapper(F("total") - F("amount_paid"), output_field=MONEY)
    figures = {}

    def merge(rows):
        for row in rows:
            figures.setdefault(row.pop("business"), {}).update(row)

    merge(Subscription.objects.order_by().values("business").annotate(
        subscriptions=Count("id"),
        active=Count("id", filter=Q(state=S.ACTIVE)),
        mrr=monthly,
    ))
    merge(Invoice.objects.filter(state=I.CONFIRMED).order_by().values("business").annotate(
        owed=Sum(due), overdue=Sum(due, filter=Q(due_date__lt=today)), overdue_count=Count("id", filter=Q(due_date__lt=today)),
    ))
    merge(Payment.objects.order_by().values("business").annotate(collected=Sum("amount")))
    merge(User.objects.exclude(business=None).order_by().values("business").annotate(
        team=Count("id", filter=Q(role=User.Role.STAFF)), customers=Count("id", filter=Q(role=User.Role.CUSTOMER)),
    ))
    return figures


def _row(business, figures):
    row = figures.get(business.pk, {})
    return {
        "id": business.pk, "code": business.code, "name": business.name, "is_active": business.is_active, "is_platform": business.is_platform,
        "created_at": business.created_at,
        "active": row.get("active", 0), "subscriptions": row.get("subscriptions", 0), "mrr": money(row.get("mrr") or 0),
        "owed": row.get("owed") or 0, "overdue": row.get("overdue") or 0, "overdue_count": row.get("overdue_count", 0),
        "collected": row.get("collected") or 0, "team": row.get("team", 0), "customers": row.get("customers", 0),
    }


@api_view(["GET"])
@permission_classes([IsPlatform])
def overview(request):
    figures = _business_figures()
    rows = [_row(b, figures) for b in Business.objects.all()]
    tenants = [r for r in rows if not r["is_platform"]]
    return Response({
        "totals": {
            "businesses": len(tenants),
            "active_businesses": sum(1 for r in tenants if r["is_active"]),
            "users": User.objects.count(),
            "active_subscriptions": sum(r["active"] for r in tenants),
            "tracked_mrr": sum((r["mrr"] for r in tenants), Decimal("0")),
            "collected": sum((r["collected"] for r in tenants), Decimal("0")),
            "owed": sum((r["owed"] for r in tenants), Decimal("0")),
            "overdue": sum((r["overdue"] for r in tenants), Decimal("0")),
        },
        "businesses": sorted(tenants, key=lambda r: -r["mrr"]),
    })


@api_view(["POST"])
@permission_classes([IsPlatform])
def set_business_active(request, pk):
    business = Business.objects.filter(pk=pk, is_platform=False).first()
    if business is None:
        raise NotFound()
    business.is_active = request.data.get("is_active") is True
    business.save(update_fields=["is_active"])
    return Response({"id": business.pk, "is_active": business.is_active})


@api_view(["GET"])
@permission_classes([IsPlatform])
def users(request):
    rows = User.objects.select_related("business").order_by("-id")
    search = str(request.query_params.get("search", "")).strip()
    if search:
        rows = rows.filter(Q(email__icontains=search) | Q(first_name__icontains=search) | Q(business__name__icontains=search))
    role = request.query_params.get("role")
    if role:
        rows = rows.filter(role=role)
    page = max(int(request.query_params.get("page", 1)) if str(request.query_params.get("page", 1)).isdigit() else 1, 1)
    return Response({
        "count": rows.count(),
        "results": [
            {
                "id": u.pk, "name": u.display_name, "email": u.email, "role": u.role, "role_label": u.role_label, "is_active": u.is_active,
                "business": u.business.name if u.business else None, "is_root": bool(u.root_marker),
            }
            for u in rows[(page - 1) * 25:page * 25]
        ],
    })


@api_view(["POST"])
@permission_classes([IsPlatform])
def set_user_active(request, pk):
    user = User.objects.filter(pk=pk).first()
    if user is None:
        raise NotFound()
    if user.root_marker:
        raise PermissionDenied("The administrator cannot be turned off.")
    user.is_active = request.data.get("is_active") is True
    user.save(update_fields=["is_active"])
    return Response({"id": user.pk, "is_active": user.is_active})


@api_view(["GET", "POST"])
@permission_classes([IsTeam])
def my_plan(request):
    """A business owner is also Brightloop's customer. Read here, start a plan here, and nothing else."""
    user = request.user
    if not user.is_admin or user.is_platform:
        raise PermissionDenied("Only a business owner has a Brightloop plan.")
    platform = Business.objects.filter(is_platform=True).first()
    if request.method == "POST":
        if platform is None:
            raise Conflict("Plans are not available yet.")
        sub = services.start_plan(user, request.data.get("plan"), platform.pk)
        return Response({"id": sub.pk, "number": sub.number}, status=201)
    subs = Subscription.objects.filter(customer=user).select_related("plan").order_by("-id")
    invoices = Invoice.objects.filter(customer=user).exclude(state=I.DRAFT).order_by("-id")[:12]
    return Response({
        "subscriptions": [
            {"id": s.pk, "number": s.number, "plan_name": s.plan.name, "state": s.state, "recurring_total": s.recurring_total,
             "billing_period": s.plan.billing_period, "expiry_date": s.expiry_date, "trial_ends": s.trial_ends}
            for s in subs
        ],
        "invoices": [
            {"id": i.pk, "number": i.number, "state": i.state, "total": i.total, "amount_due": i.amount_due, "due_date": i.due_date}
            for i in invoices
        ],
    })


def _public_plans(business):
    today = timezone.localdate()
    plans = Plan.objects.filter(business=business, is_public=True, is_active=True, start_date__lte=today).filter(
        Q(end_date__isnull=True) | Q(end_date__gte=today)
    ).order_by("price")
    return [
        {
            "id": p.pk, "name": p.name, "price": p.price, "billing_period": p.billing_period, "trial_days": p.trial_days,
            "self_serve": p.min_quantity <= 1 and p.price > 0, "pausable": p.pausable, "min_quantity": p.min_quantity,
        }
        for p in plans
    ]


def _site(code):
    business = Business.objects.filter(code=str(code).lower(), is_active=True, is_platform=False).first()
    if business is None:
        raise NotFound()
    return business


@api_view(["GET"])
@authentication_classes([])
@permission_classes([AllowAny])
def public_plans(request):
    """Brightloop's own prices, for the landing page."""
    platform = Business.objects.filter(is_platform=True).first()
    return Response(_public_plans(platform) if platform else [])


@api_view(["GET"])
@authentication_classes([])
@permission_classes([AllowAny])
def site(request, code):
    business = _site(code)
    return Response({"name": business.name, "code": business.code, "plans": _public_plans(business)})


@api_view(["POST"])
@authentication_classes([])
@permission_classes([AllowAny])
@throttle_classes([ScopedRateThrottle])
def site_subscribe(request, code):
    """A subscription made on a business's own site. Brightloop tracks it under that business."""
    business = _site(code)
    email = str(request.data.get("email", "")).strip().lower()
    name = str(request.data.get("name", "")).strip()[:150]
    if classify(email)["kind"] != "user":
        raise serializers.ValidationError({"email": ["Use your name@gmail.com address."]})
    if not name:
        raise serializers.ValidationError({"name": ["Enter your name."]})
    raw = str(request.data.get("plan", ""))
    plan = Plan.objects.filter(pk=raw, business=business, is_public=True).first() if raw.isdigit() else None
    if plan is None or not plan.available_on(timezone.localdate()) or plan.min_quantity > 1 or plan.price <= 0:
        raise serializers.ValidationError({"plan": ["Choose one of the plans on this page."]})
    with transaction.atomic():
        # This page has no login, so it must never add charges to an account that already exists.
        if User.objects.filter(email__iexact=email).exists():
            raise Conflict("This address already has an account. Please sign in to subscribe.")
        customer = User.objects.create_user(email, None, first_name=name, role=User.Role.CUSTOMER, business=business)
        sub = services.provision(customer, plan, None, f"Subscribed on the {business.name} site")
    return Response({"number": sub.number, "plan": plan.name, "trial_ends": sub.trial_ends}, status=201)


site_subscribe.cls.throttle_scope = "auth"
