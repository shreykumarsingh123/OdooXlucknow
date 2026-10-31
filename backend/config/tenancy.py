"""Keeps every business's data apart. An id from another business is treated as if it does not exist."""
from rest_framework import serializers
from rest_framework.relations import ManyRelatedField, RelatedField


class TenantScoped:
    """Limits every writable relation on a serializer to the requesting user's business. With no user it allows nothing."""

    def get_fields(self):
        fields = super().get_fields()
        user = getattr(self.context.get("request"), "user", None)
        business_id = getattr(user, "business_id", None)
        for field in fields.values():
            relation = field.child_relation if isinstance(field, ManyRelatedField) else field
            if not isinstance(relation, RelatedField) or relation.read_only or relation.queryset is None:
                continue
            if getattr(relation, "tenant_safe", False):
                continue
            model = relation.queryset.model
            names = {f.name for f in model._meta.get_fields()}
            if "business" in names:
                relation.queryset = relation.queryset.filter(business_id=business_id)
            elif "product" in names:
                relation.queryset = relation.queryset.filter(product__business_id=business_id)
            else:
                relation.queryset = relation.queryset.none()
        return fields


class CustomerField(serializers.PrimaryKeyRelatedField):
    """Brightloop's customers belong to other businesses, so this one relation has its own rule."""

    tenant_safe = True

    def get_queryset(self):
        from accounts.identity import customers_of

        user = self.context["request"].user
        return customers_of(user.business_id, user.is_platform).filter(is_active=True)
