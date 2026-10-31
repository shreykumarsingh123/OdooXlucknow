from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.db import models


class UserManager(BaseUserManager):
    use_in_migrations = True

    def _create(self, email, password, **extra):
        if not email:
            raise ValueError("Email is required")
        user = self.model(email=self.normalize_email(email).lower(), **extra)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email, password=None, **extra):
        extra.setdefault("role", User.Role.CUSTOMER)
        return self._create(email, password, **extra)

    def create_superuser(self, email, password=None, **extra):
        extra.update(is_staff=True, is_superuser=True, role=User.Role.ADMIN)
        return self._create(email, password, **extra)


class User(AbstractUser):
    class Role(models.TextChoices):
        ADMIN = "admin", "Admin"
        STAFF = "staff", "Staff"
        CUSTOMER = "customer", "Customer"

    username = None
    email = models.EmailField(unique=True)
    role = models.CharField(max_length=10, choices=Role.choices, default=Role.CUSTOMER, db_index=True)
    company = models.CharField(max_length=150, blank=True)
    phone = models.CharField(max_length=30, blank=True)
    address = models.TextField(blank=True)
    # True once the owner has proved control of the mailbox, by a reset link or Google.
    email_verified = models.BooleanField(default=False)

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []
    objects = UserManager()

    class Meta:
        ordering = ["first_name", "email"]

    @property
    def is_admin(self):
        return self.role == self.Role.ADMIN

    @property
    def is_team(self):
        return self.role in (self.Role.ADMIN, self.Role.STAFF)

    @property
    def display_name(self):
        return self.get_full_name() or self.company or self.email

    def __str__(self):
        return self.display_name
