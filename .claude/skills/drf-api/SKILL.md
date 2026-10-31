---
name: drf-api
description: Conventions for REST APIs with Django REST Framework covering serializers, viewsets, workflow actions, JWT auth, role permissions, filtering, pagination, errors and API tests. Use when adding or changing endpoints, auth, permissions or serializers.
---

# Django REST Framework API

## Base configuration

```python
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": ["rest_framework_simplejwt.authentication.JWTAuthentication"],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 25,
    "DEFAULT_FILTER_BACKENDS": ["django_filters.rest_framework.DjangoFilterBackend"],
    "EXCEPTION_HANDLER": "config.exceptions.api_exception_handler",
}
```

Everything requires login by default. Make public endpoints opt in explicitly. Restrict CORS through `CORS_ALLOWED_ORIGINS`.

## URLs

Prefix everything with `/api/`, use plural nouns, and route with a `DefaultRouter`.

## Serializers

- List fields explicitly. Never use `fields = "__all__"`, because it exposes new fields by accident.
- Make `status`, `role`, owner and computed fields `read_only`, so they cannot be set through normal updates.
- Use separate read and write serializers when the shapes differ.

## Workflow actions

State changes get their own endpoint that calls the service layer. Do not allow them through `PATCH`.

```python
class RequestViewSet(viewsets.ModelViewSet):
    def get_queryset(self):
        qs = Request.objects.select_related("requester")
        if self.request.user.role == User.Role.EMPLOYEE:
            qs = qs.filter(requester=self.request.user)  # row-level scope
        return qs

    @action(detail=True, methods=["post"], permission_classes=[IsManager])
    def approve(self, request, pk=None):
        obj = self.get_object()  # applies queryset scope and object permissions
        result = services.approve_request(obj.pk, request.user)
        return Response(RequestSerializer(result).data)
```

## Permissions

Write one small `BasePermission` per role rule. Scope `get_queryset` by user, so another user's record returns 404.

## Errors

Use one format everywhere, handled by the custom exception handler:

```json
{"code": "invalid_transition", "message": "Only pending requests can be approved.", "fields": {}}
```

Status codes: 400 invalid input, 401 not logged in, 403 wrong role, 404 not found or out of scope, 409 invalid state or conflict.

## Performance

Use `select_related` and `prefetch_related` on lists. Compute dashboards with `aggregate` and `annotate` rather than Python loops.

## Tests

For each action, test with `APITestCase`: the allowed role succeeds, a wrong role gets 403, an invalid state gets 409, and the database row is correct afterwards.
