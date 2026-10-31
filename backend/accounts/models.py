import secrets
import string

from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.db import models


class Business(models.Model):
    """A company using Brightloop. Brightloop itself is one too, marked is_platform."""

    CODE_LENGTH = 6

    code = models.CharField(max_length=CODE_LENGTH, unique=True, editable=False)
    name = models.CharField(max_length=150)
    is_platform = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]
        verbose_name_plural = "businesses"

    def save(self, *args, **kwargs):
        while not self.code:
            candidate = "".join(secrets.choice(string.ascii_lowercase + string.digits) for _ in range(self.CODE_LENGTH))
            if not Business.objects.filter(code=candidate).exists():
                self.code = candidate
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


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
        platform = Business.objects.filter(is_platform=True).first() or Business.objects.create(name="Brightloop", is_platform=True)
        extra.update(is_staff=True, is_superuser=True, role=User.Role.ADMIN, root_marker=True, business=platform)
        return self._create(email, password, **extra)


class User(AbstractUser):
    class Role(models.TextChoices):
        ADMIN = "admin", "Admin"
        STAFF = "staff", "Staff"
        CUSTOMER = "customer", "Customer"

    class Department(models.TextChoices):
        SUPPORT = "support", "Customer care"
        SALES = "sales", "Sales"

    username = None
    email = models.EmailField(unique=True)
    business = models.ForeignKey(Business, on_delete=models.PROTECT, null=True, blank=True, related_name="users")
    # Where a password code is sent. Work addresses such as name@sale.com have no real mailbox.
    recovery_email = models.EmailField(blank=True)
    # True for the one administrator, NULL for everyone else. The unique index allows only one, in the database itself.
    root_marker = models.BooleanField(null=True, blank=True, unique=True, editable=False)
    role = models.CharField(max_length=10, choices=Role.choices, default=Role.CUSTOMER, db_index=True)
    # Narrows what a staff member sees. Empty means general staff.
    department = models.CharField(max_length=10, choices=Department.choices, blank=True)
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
        indexes = [models.Index(fields=["business", "role", "is_active"])]

    @property
    def is_platform(self):
        return bool(self.business_id and self.business.is_platform)

    @property
    def role_label(self):
        if self.root_marker:
            return "Administrator"
        if self.role == self.Role.ADMIN:
            return "Business owner"
        if self.role == self.Role.CUSTOMER:
            return "Customer"
        prefix = "Brightloop " if self.is_platform else ""
        return prefix + (self.get_department_display() or "Staff")

    @property
    def is_admin(self):
        return self.role == self.Role.ADMIN

    @property
    def is_team(self):
        return self.role in (self.Role.ADMIN, self.Role.STAFF)

    @property
    def is_sales(self):
        return self.role == self.Role.STAFF and self.department == self.Department.SALES

    @property
    def is_support(self):
        return self.role == self.Role.STAFF and self.department == self.Department.SUPPORT

    @property
    def is_back_office(self):
        return self.is_admin or (self.role == self.Role.STAFF and not self.department)

    @property
    def display_name(self):
        return self.get_full_name() or self.company or self.email

    def __str__(self):
        return self.display_name


class PasswordOTP(models.Model):
    """One live code per person. Only a hash is stored, so a database leak reveals no code."""

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="password_otp")
    code_hash = models.CharField(max_length=128)
    expires_at = models.DateTimeField()
    # Counted per account per hour, not per code, so asking for a new code never buys more guesses.
    window_start = models.DateTimeField()
    codes_sent = models.PositiveSmallIntegerField(default=0)
    attempts = models.PositiveSmallIntegerField(default=0)
