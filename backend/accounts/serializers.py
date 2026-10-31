from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers

from .models import User


class MeSerializer(serializers.ModelSerializer):
    name = serializers.CharField(source="display_name", read_only=True)

    class Meta:
        model = User
        fields = ["id", "email", "first_name", "last_name", "name", "role", "company", "phone", "address"]
        read_only_fields = ["id", "email", "role"]


class SignupSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True)

    class Meta:
        model = User
        fields = ["email", "password", "first_name", "last_name", "company", "phone"]
        extra_kwargs = {"email": {"validators": []}}  # validate_email checks uniqueness in any letter case

    def validate_email(self, value):
        value = value.strip().lower()
        if User.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError("An account with this email already exists.")
        return value

    def validate_password(self, value):
        validate_password(value)
        return value

    def create(self, validated_data):
        return User.objects.create_user(role=User.Role.CUSTOMER, **validated_data)


class PersonSerializer(serializers.ModelSerializer):
    """Team-managed customer or staff record. The password is set through an emailed link."""

    name = serializers.CharField(source="display_name", read_only=True)

    class Meta:
        model = User
        fields = ["id", "email", "first_name", "last_name", "name", "company", "phone", "address", "is_active", "date_joined"]
        read_only_fields = ["id", "date_joined"]
        extra_kwargs = {"email": {"validators": []}}  # validate_email checks uniqueness in any letter case

    def validate_email(self, value):
        value = value.strip().lower()
        query = User.objects.filter(email__iexact=value)
        if self.instance:
            query = query.exclude(pk=self.instance.pk)
        if query.exists():
            raise serializers.ValidationError("An account with this email already exists.")
        return value
