from django.db import transaction
from rest_framework import serializers
from rest_framework.validators import UniqueValidator

from .models import Discount, PaymentTerm, Plan, Product, ProductVariant, QuotationTemplate, QuotationTemplateLine, Tax


class TaxSerializer(serializers.ModelSerializer):
    class Meta:
        model = Tax
        fields = ["id", "name", "computation", "rate", "is_active"]


class PaymentTermSerializer(serializers.ModelSerializer):
    class Meta:
        model = PaymentTerm
        fields = ["id", "name", "due_days", "is_active"]


class VariantSerializer(serializers.ModelSerializer):
    id = serializers.IntegerField(required=False)

    class Meta:
        model = ProductVariant
        fields = ["id", "attribute", "value", "extra_price"]


class ProductSerializer(serializers.ModelSerializer):
    variants = VariantSerializer(many=True, required=False)

    class Meta:
        model = Product
        fields = ["id", "name", "type", "sales_price", "cost_price", "notes", "taxes", "is_active", "variants"]

    @transaction.atomic
    def create(self, validated_data):
        variants = validated_data.pop("variants", [])
        product = super().create(validated_data)
        self._sync(product, variants)
        return product

    @transaction.atomic
    def update(self, instance, validated_data):
        variants = validated_data.pop("variants", None)
        product = super().update(instance, validated_data)
        if variants is not None:
            self._sync(product, variants)
        return product

    def _sync(self, product, variants):
        keep = []
        for row in variants:
            pk = row.pop("id", None)
            obj = product.variants.filter(pk=pk).first() if pk else None
            if obj:
                for key, value in row.items():
                    setattr(obj, key, value)
                obj.save()
            else:
                obj = product.variants.create(**row)
            keep.append(obj.pk)
        # Variants already sold stay on record; unused ones can go.
        stale = product.variants.exclude(pk__in=keep)
        stale.filter(subscriptionline__isnull=True, quotationtemplateline__isnull=True).delete()


class PlanSerializer(serializers.ModelSerializer):
    class Meta:
        model = Plan
        fields = [
            "id", "name", "price", "billing_period", "min_quantity", "start_date", "end_date", "taxes",
            "auto_close", "closable", "pausable", "renewable", "trial_days", "is_public", "is_active",
        ]

    def validate(self, attrs):
        start = attrs.get("start_date", getattr(self.instance, "start_date", None))
        end = attrs.get("end_date", getattr(self.instance, "end_date", None))
        if end and start and end < start:
            raise serializers.ValidationError({"end_date": ["End date cannot be before the start date."]})
        return attrs


class DiscountSerializer(serializers.ModelSerializer):
    code = serializers.CharField(
        max_length=40, required=False, allow_blank=True, allow_null=True,
        validators=[UniqueValidator(queryset=Discount.objects.all(), lookup="iexact", message="This code is already in use.")],
    )

    value = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=0, required=False, allow_null=True)

    class Meta:
        model = Discount
        fields = [
            "id", "name", "kind", "value", "scope", "min_purchase", "min_quantity", "start_date", "end_date",
            "usage_limit", "times_used", "code", "reward", "perk_text", "products", "subscriptions", "is_active",
        ]
        read_only_fields = ["times_used"]

    def validate_code(self, value):
        return (value or "").strip().upper() or None

    def validate(self, attrs):
        def get(key):
            return attrs.get(key, getattr(self.instance, key, None))

        if get("end_date") and get("end_date") < get("start_date"):
            raise serializers.ValidationError({"end_date": ["End date cannot be before the start date."]})
        reward = get("reward") or Discount.Reward.DISCOUNT
        if reward != Discount.Reward.DISCOUNT and not get("code"):
            raise serializers.ValidationError({"code": ["This reward needs a promo code."]})
        if reward == Discount.Reward.PERK:
            attrs["value"] = 0
            if not (get("perk_text") or "").strip():
                raise serializers.ValidationError({"perk_text": ["Say what the customer gets."]})
        else:
            if not get("value") or get("value") <= 0:
                raise serializers.ValidationError({"value": ["Enter a value above zero."]})
            if reward == Discount.Reward.FREE_DAYS and (get("value") > 365 or get("value") != int(get("value"))):
                raise serializers.ValidationError({"value": ["Enter a whole number of days, up to 365."]})
            if reward == Discount.Reward.DISCOUNT and get("kind") == Discount.Kind.PERCENT and get("value") > 100:
                raise serializers.ValidationError({"value": ["A percentage cannot be over 100."]})
        products = attrs.get("products", self.instance.products.all() if self.instance else [])
        subscriptions = attrs.get("subscriptions", self.instance.subscriptions.all() if self.instance else [])
        if reward != Discount.Reward.DISCOUNT:
            attrs["scope"] = Discount.Scope.SUBSCRIPTIONS
        elif get("scope") == Discount.Scope.PRODUCTS and not len(products):
            raise serializers.ValidationError({"products": ["Choose at least one product."]})
        if reward == Discount.Reward.DISCOUNT and get("scope") == Discount.Scope.SUBSCRIPTIONS and not len(subscriptions) and not get("code"):
            raise serializers.ValidationError({"subscriptions": ["Choose at least one subscription."]})
        return attrs


class TemplateLineSerializer(serializers.ModelSerializer):
    class Meta:
        model = QuotationTemplateLine
        fields = ["product", "variant", "quantity"]

    def validate(self, attrs):
        variant = attrs.get("variant")
        if variant and variant.product_id != attrs["product"].pk:
            raise serializers.ValidationError({"variant": ["This variant belongs to another product."]})
        return attrs


class QuotationTemplateSerializer(serializers.ModelSerializer):
    lines = TemplateLineSerializer(many=True)

    class Meta:
        model = QuotationTemplate
        fields = ["id", "name", "plan", "validity_days", "is_active", "lines"]

    def validate_lines(self, value):
        if not value:
            raise serializers.ValidationError("Add at least one product line.")
        return value

    @transaction.atomic
    def create(self, validated_data):
        lines = validated_data.pop("lines")
        template = super().create(validated_data)
        QuotationTemplateLine.objects.bulk_create(QuotationTemplateLine(template=template, **row) for row in lines)
        return template

    @transaction.atomic
    def update(self, instance, validated_data):
        lines = validated_data.pop("lines", None)
        template = super().update(instance, validated_data)
        if lines is not None:
            template.lines.all().delete()
            QuotationTemplateLine.objects.bulk_create(QuotationTemplateLine(template=template, **row) for row in lines)
        return template
