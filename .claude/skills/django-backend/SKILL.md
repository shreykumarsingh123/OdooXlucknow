---
name: django-backend
description: Conventions for the Django backend covering project setup, settings from environment, apps, models, service functions, admin, management commands and seed data. Use when creating or changing Django code, models, settings, or the admin, or scaffolding the backend.
---

# Django backend

Target: Django 5.2 LTS on Python 3.14, with MySQL 8. Machine setup is in `docs/SETUP.md`.

## Scaffolding

```
backend/
  manage.py
  requirements.txt
  config/          # settings, urls, wsgi, asgi
  accounts/        # custom user and roles
  <domain apps>/   # one per business area
```

```powershell
django-admin startproject config backend
```

**Create a custom user model before the first migration.** Changing it later is painful.

```python
class User(AbstractUser):
    class Role(models.TextChoices):
        ...  # roles from docs/ANALYSIS.md
    role = models.CharField(max_length=20, choices=Role.choices)
```

Set `AUTH_USER_MODEL = "accounts.User"`.

## Settings

Read everything from the environment with `python-dotenv`. Never hard-code secrets.

```python
DEBUG = os.environ.get("DEBUG", "false").lower() == "true"
SECRET_KEY = os.environ["SECRET_KEY"]
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.mysql",
        "NAME": os.environ["DB_NAME"],
        "USER": os.environ["DB_USER"],
        "PASSWORD": os.environ["DB_PASSWORD"],
        "HOST": os.environ.get("DB_HOST", "127.0.0.1"),
        "PORT": os.environ.get("DB_PORT", "3306"),
        "OPTIONS": {"charset": "utf8mb4"},
    }
}
TIME_ZONE = "Asia/Kolkata"  # change if the problem says otherwise
USE_TZ = True
```

## Models

- Use `TextChoices` for states, and `Meta.constraints` for invariants.
- Use `on_delete=PROTECT` for records with history. Use `CASCADE` only for true children.
- Use `DecimalField` for money, never `FloatField`.
- Add `created_at` and `updated_at` through an abstract base model.
- Index fields that are filtered often, such as status, foreign keys and dates.

## Business logic

Put workflows in `services.py`, not in views, serializers or `save()`. Each transition is one function that checks the state and uses a transaction:

```python
@transaction.atomic
def approve_request(request_id, actor):
    req = Request.objects.select_for_update().get(pk=request_id)
    if req.status != Request.Status.PENDING:
        raise InvalidTransition(req.status, Request.Status.APPROVED)
    req.status = Request.Status.APPROVED
    req.approved_by = actor
    req.save(update_fields=["status", "approved_by", "updated_at"])
    return req
```

## Admin

Register every model with `list_display` and `list_filter`. It is a free back office and a useful fallback during a demo.

## Seed data

Write an idempotent management command, `python manage.py seed_demo`, using `get_or_create`. It creates one account per role and covers every state the demo shows. Demo passwords stay in this command, and it must refuse to run when `DEBUG` is false.

## Check before finishing

- [ ] `python manage.py check` passes.
- [ ] `python manage.py makemigrations --check` reports no changes.
- [ ] Migrations are committed.
- [ ] `python manage.py test` passes.
