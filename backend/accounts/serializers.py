from django.contrib.auth.password_validation import validate_password
from django.db import transaction
from rest_framework import serializers

from .identity import WORK_DOMAINS, classify, staff_email
from .models import Business, User

FORMATS = "Use name@gmail.com, or name + your business ID at sale.com, or name.businessID@support.com."


class BusinessSerializer(serializers.ModelSerializer):
    class Meta:
        model = Business
        fields = ["id", "code", "name", "is_platform"]


class MeSerializer(serializers.ModelSerializer):
    name = serializers.CharField(source="display_name", read_only=True)
    business = BusinessSerializer(read_only=True)
    role_label = serializers.CharField(read_only=True)
    is_root = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            "id", "email", "first_name", "last_name", "name", "role", "role_label", "department", "business", "is_root",
            "recovery_email", "company", "phone", "address",
        ]
        read_only_fields = ["id", "email", "role", "department"]

    def get_is_root(self, user):
        return bool(user.root_marker)

    def validate_recovery_email(self, value):
        value = value.strip().lower()
        if value.rpartition("@")[2] in WORK_DOMAINS:
            raise serializers.ValidationError("Use a real mailbox you can open, such as your personal Gmail.")
        if value == self.instance.email:
            raise serializers.ValidationError("Use a different address from the one you sign in with.")
        return value


class SignupSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True)
    business_name = serializers.CharField(required=False, allow_blank=True, write_only=True, max_length=150)
    business_id = serializers.CharField(required=False, allow_blank=True, write_only=True, max_length=20)
    pending = serializers.SerializerMethodField()
    role_label = serializers.CharField(read_only=True)

    class Meta:
        model = User
        fields = ["email", "password", "first_name", "last_name", "company", "phone", "business_name", "business_id", "pending", "role_label"]
        extra_kwargs = {"email": {"validators": []}}  # validate_email checks uniqueness in any letter case

    def get_pending(self, user):
        return not user.is_active

    def validate_email(self, value):
        value = value.strip().lower()
        if User.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError("An account with this email already exists.")
        kind = classify(value)["kind"]
        if kind in ("root", "platform_staff"):
            raise serializers.ValidationError("Brightloop staff accounts are created by the administrator.")
        if kind is None:
            raise serializers.ValidationError(FORMATS)
        return value

    def validate_password(self, value):
        validate_password(value)
        return value

    def validate(self, attrs):
        identity = classify(attrs["email"])
        code = identity["code"] or attrs.get("business_id", "").strip().lower()
        if code:
            business = Business.objects.filter(code=code, is_platform=False, is_active=True).first()
            if business is None:
                raise serializers.ValidationError({"business_id" if not identity["code"] else "email": ["No business has this ID. Ask the owner to share it."]})
            attrs["_business"] = business
        attrs["_identity"] = identity
        return attrs

    @transaction.atomic
    def create(self, validated_data):
        identity = validated_data.pop("_identity")
        business = validated_data.pop("_business", None)
        name = validated_data.pop("business_name", "").strip()
        validated_data.pop("business_id", None)
        email = validated_data.pop("email")
        password = validated_data.pop("password")
        if identity["kind"] == "business_staff":
            # Knowing the ID is not enough to see a business's records, so the owner approves each person.
            return User.objects.create_user(
                email, password, role=User.Role.STAFF, department=identity["department"], business=business, is_active=False, **validated_data
            )
        if business:
            return User.objects.create_user(email, password, role=User.Role.CUSTOMER, business=business, **validated_data)
        title = name or validated_data.get("company") or validated_data.get("first_name") or email.partition("@")[0]
        return User.objects.create_user(email, password, role=User.Role.ADMIN, business=Business.objects.create(name=title), **validated_data)


class PersonSerializer(serializers.ModelSerializer):
    """A customer of this business. The password is chosen through the Forgot password code."""

    name = serializers.CharField(source="display_name", read_only=True)

    class Meta:
        model = User
        fields = ["id", "email", "first_name", "last_name", "name", "department", "company", "phone", "address", "is_active", "date_joined"]
        read_only_fields = ["id", "date_joined", "department"]
        extra_kwargs = {"email": {"validators": []}}  # validate_email checks uniqueness in any letter case

    def validate_email(self, value):
        value = value.strip().lower()
        query = User.objects.filter(email__iexact=value)
        if self.instance:
            query = query.exclude(pk=self.instance.pk)
        if query.exists():
            raise serializers.ValidationError("An account with this email already exists.")
        if classify(value)["kind"] != "user":
            raise serializers.ValidationError("Customers use a name@gmail.com address.")
        return value


class StaffSerializer(serializers.ModelSerializer):
    """The owner gives a name and a role. The address follows from them, so it always matches the scheme."""

    name = serializers.CharField(source="display_name", read_only=True)
    password = serializers.CharField(write_only=True, required=False, allow_blank=True)
    department = serializers.ChoiceField(choices=User.Department.choices)
    department_label = serializers.CharField(source="get_department_display", read_only=True)
    first_name = serializers.CharField(max_length=150)

    class Meta:
        model = User
        fields = ["id", "email", "first_name", "last_name", "name", "department", "department_label", "password", "phone", "is_active", "date_joined"]
        read_only_fields = ["id", "email", "date_joined"]

    def validate_password(self, value):
        if value:
            validate_password(value)
        return value

    def validate(self, attrs):
        business = self.context["request"].user.business
        first = attrs.get("first_name", getattr(self.instance, "first_name", ""))
        department = attrs.get("department", getattr(self.instance, "department", ""))
        # Approving someone changes neither, and their address must stay as it is.
        if self.instance and first == self.instance.first_name and department == self.instance.department:
            return attrs
        email = staff_email(first, department, business)
        if email is None:
            raise serializers.ValidationError({"first_name": ["Use letters in the name, since it becomes the email address."]})
        query = User.objects.filter(email__iexact=email)
        if self.instance:
            query = query.exclude(pk=self.instance.pk)
        if query.exists():
            raise serializers.ValidationError({"first_name": [f"{email} is already taken. Add a letter to the name."]})
        if self.instance is None and not attrs.get("password"):
            raise serializers.ValidationError({"password": ["Choose a first password to give this person."]})
        attrs["email"] = email
        return attrs

    def create(self, validated_data):
        email, password = validated_data.pop("email"), validated_data.pop("password")
        business = self.context["request"].user.business
        return User.objects.create_user(email, password, role=User.Role.STAFF, business=business, **validated_data)

    def update(self, instance, validated_data):
        password = validated_data.pop("password", "")
        user = super().update(instance, validated_data)
        if password:
            user.set_password(password)
            user.save(update_fields=["password"])
        return user
