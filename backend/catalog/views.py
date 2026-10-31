from rest_framework import viewsets

from accounts.permissions import AdminWriteTeamRead

from .models import Discount, PaymentTerm, Plan, Product, QuotationTemplate, Tax
from .serializers import (
    DiscountSerializer,
    PaymentTermSerializer,
    PlanSerializer,
    ProductSerializer,
    QuotationTemplateSerializer,
    TaxSerializer,
)


class CatalogViewSet(viewsets.ModelViewSet):
    permission_classes = [AdminWriteTeamRead]
    search_fields = ["name"]
    filterset_fields = ["is_active"]


class TaxViewSet(CatalogViewSet):
    queryset = Tax.objects.all()
    serializer_class = TaxSerializer


class PaymentTermViewSet(CatalogViewSet):
    queryset = PaymentTerm.objects.all()
    serializer_class = PaymentTermSerializer


class ProductViewSet(CatalogViewSet):
    queryset = Product.objects.prefetch_related("variants", "taxes")
    serializer_class = ProductSerializer
    filterset_fields = ["is_active", "type"]


class PlanViewSet(CatalogViewSet):
    queryset = Plan.objects.prefetch_related("taxes")
    serializer_class = PlanSerializer
    filterset_fields = ["is_active", "billing_period"]


class DiscountViewSet(CatalogViewSet):
    queryset = Discount.objects.prefetch_related("products", "subscriptions")
    serializer_class = DiscountSerializer
    filterset_fields = ["is_active", "kind", "scope"]


class QuotationTemplateViewSet(CatalogViewSet):
    queryset = QuotationTemplate.objects.prefetch_related("lines").select_related("plan")
    serializer_class = QuotationTemplateSerializer
